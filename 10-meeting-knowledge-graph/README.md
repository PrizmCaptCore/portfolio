# 회의·업무 스트림 지식그래프 엔진 (Firehose Ontology)

> AI 회의 인텔리전스 제품 **Relay**(제품명 가명화)의 추론 계층. 시간순으로 흘러오는 팀 채팅/회의 스트림을
> **한 번만 지나가며(single pass)** 결정·액션·이슈의 그래프로 쌓고, 새 결정이 과거 결정을 **뒤집거나 다듬는**
> 순간을 잡아낸다. 원칙은 **"LLM 은 좁은 판단만, 구조는 결정론적 코드"** 다. 그래프 전체를 LLM 에 맡기면
> 비용·환각·재현성이 무너지므로, LLM 호출은 분류와 매칭으로 제한하고 어디에 붙일지·언제 새 가지를 낼지는 코드가 정한다.

## 구성

```text
.
├── firehose.py               # v1 모놀리스: 윈도우 단위 추출 + 그래프 (첫 실험)
├── models.py                 # v2: Node / link / struct / grounding / conflict 를 한 파일에 (구 boolean reversal 설계)
├── module/                   # v3 모듈 리팩터 (현재 설계)
│   ├── struct/pipeline.py    # WHAT: 메시지 -> decision|action|issue|noise + title/actor/why_hint/ref_hint
│   ├── ground/surface.py     # 토큰 겹침으로 top-k 후보 (activity 는 이름 + 최근 3개 멤버만 대표 — 토큰 자석 방지)
│   ├── ground/match.py       # 단일 LLM 호출: "같은 구체적 사안을 공유하는 후보 or null" (추측보다 null 선호)
│   ├── ground/dependency.py  # why/ref 힌트를 앞선 노드로 기계적으로 해석 — 인과는 절대 추론하지 않음
│   ├── ground/grounding.py   # EXTEND / BIRTH(parked peer 에서 탄생) / PARK(pending) 라우팅 + reclaim()
│   ├── conflict/conflict.py  # 결정 diff 랭커: {ref, rel: reversal|refinement|unrelated, changed}
│   ├── asker/llm.py          # LLM 클라이언트 (BACKEND=small|claude)
│   ├── node_arch/node.py     # {uuid, pre[], post[], value{}, date} — pre 는 belongs-to + caused-by 혼합 인접 리스트
│   ├── tester_stream/        # 채팅 로그 -> 메시지 스트림
│   └── pipeline.py, __main__.py
├── viz.py                    # vis-network 타임라인 (x = 시간 순위, y = activity 레인, parked 는 하단 회색)
├── test_legacy/              # 이전 ablation: replay(분류 recall) / dedup(결정 변수 병합) / thread(병렬 스레드) / ground(LLM 올인 baseline) / compare
└── later.md                  # 다음 단계 메모
```

## 세 단계

1. **struct (WHAT)** — 메시지당 bounded LLM 호출 1회. `decision | action | issue | noise` 분류와 `title`, `actor`,
   그리고 **명시적 증거 필드** 둘: `why_hint`(발화에 적힌 원인: "because", "so", "때문에")와 `ref_hint`(역참조: "that", "그거", "again").
   noise 는 그래프에 들어오지 않는다.
2. **ground (WHERE)** — 엔진의 핵심.
   - `surface.py` 가 토큰 겹침으로 싸게 후보를 자른다. 문서화된 "embedding seam" 이라 나중에 임베딩으로 교체 가능.
     큰 activity 가 모든 메시지를 빨아들이지 않도록 **이름 + 최근 3개 멤버**만으로 대표한다. 겹침 0 이면 fallback 없이 후보 없음.
   - `match.py` 가 LLM 에 딱 하나만 묻는다: 같은 **구체적** 사안을 공유하는 후보가 있는가, 없으면 null.
     "공유 스탠드업은 매치가 아니다" 를 프롬프트에 박았다.
   - `dependency.py` 는 why/ref 힌트를 앞선 노드에 기계적으로 연결한다. 힌트가 없으면 엣지도 없다.
   - `grounding.py` 가 **EXTEND**(기존 가지 연장) / **BIRTH**(parked peer 에서 새 가지 탄생) / **PARK**(pending 보류) 로 라우팅하고,
     frontier 가 바뀔 때마다 `reclaim()` 이 보류 항목을 다시 검사한다.
3. **conflict** — 모순 판정기가 아니라 **diff 랭커**. 새 결정마다 과거 결정을 토픽으로 잘라 가장 가까운 k 개에
   `{rel: reversal|refinement|unrelated, changed: "<무엇이 달라졌나>"}` 를 붙인다. 임계값은 UI 가 정한다.
   (`models.py` 의 v2 는 boolean `reversal` 판정이었고, 그 한계 때문에 이렇게 바뀌었다.)

**용어**: *activity* 는 구체적 사안을 이름으로 갖는 워크스트림(가지), "daily sync" 같은 의식(ritual)은 activity 가 아니다.
*grounding* 은 노드를 올바른 activity 아래에 놓는 일, *frontier* 는 현재 열린 activity + parked 항목의 집합으로 새 메시지가 매칭되는 대상이다.

## 실행

```bash
export ANTHROPIC_API_KEY=...            # BACKEND=claude
export SMALL_LLM_URL=http://localhost:8000/v1/chat/completions   # BACKEND=small (OpenAI 호환, X-Internal-Key)
export SMALL_LLM_KEY=...
export CHAT_LOG=chat_log.txt            # 카카오톡 내보내기 형식의 채팅 로그

BACKEND=small  python -m module
BACKEND=claude python -m module
python viz.py frontier_small.json graph_small.html
```

작은 모델(자체 서빙 Gemma)과 Claude(`claude-sonnet-4-6`) 두 백엔드로 같은 스트림을 돌려 `test_legacy/compare.py` 로 합의율을 본다.
실제 팀 채팅으로 만든 결과물(`frontier_*.json`, `graph_*.html`)은 실명·내부 정보가 포함되어 포함하지 않는다.

**Technologies**: Python, Anthropic Messages API, OpenAI-compatible self-hosted LLM, vis-network
