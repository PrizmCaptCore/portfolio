# 회의 지식그래프 엔진 (Meeting Knowledge-Graph Engine)

> AI 회의 인텔리전스 제품 **Relay**(제품명 익명화)의 추론 계층. 회의 전사(transcript)가
> 스트리밍되는 동안 **사건(activity)·결정(decision)·액션(action)·이슈(issue)** 의 증분
> 그래프를 만들고, 새 결정이 **과거 결정을 뒤집는(reversal)** 순간을 자동으로 잡아낸다.

핵심 설계 원칙은 **"LLM 은 좁은 판단만, 구조는 결정론적 규칙"** 이다.
LLM 에 그래프 전체를 맡기면 비용·환각·재현성 문제가 생기므로, LLM 호출은 *분류/매칭* 같은
좁은 판단으로 제한하고 그래프의 골격(언제 새 사건으로 끊을지, 어떤 인과 엣지를 그을지)은
코드가 결정한다.

## 파이프라인

```
스트리밍 발화 (transcript utterance)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. STRUCTURE  (WHAT)   — LLM: 좁은 분류                       │
│    발화 → {type: decision|action|issue|noise, title, actor,  │
│            why_hint, ref_hint}                                │
│    · noise 는 즉시 폐기 (그래프에 넣지 않음)                  │
└───────────────┬─────────────────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. GROUNDING  (WHERE)  — 기계적 prune → LLM match → 규칙      │
│    a) surface(): 토큰 겹침으로 열린 activity top-k 만 추림    │
│       (임베딩 seam — 히스토리가 커져도 LLM 비용 상한 유지)    │
│    b) match():  후보 중 소속 activity 를 LLM 이 선택 (or none)│
│    c) THE CUT:  none 이면 → 새 activity 생성 (규칙, 추측 X)   │
│    d) causal(): why/ref 단서가 명시됐을 때만 caused-by 엣지   │
└───────────────┬─────────────────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. CONFLICT  (vs 과거)  — LLM: reversal 판정                  │
│    새 decision 을 과거 decision 들과 비교                     │
│    reversal(반대/양립불가) 이면 conflicts_with 에 기록         │
│    → "우리 아까 결정 뒤집었네" 를 자동 표면화                 │
└─────────────────────────────────────────────────────────────┘
```

## 왜 이렇게 설계했나 (Engineering decisions)

- **LLM 은 좁은 판단, 코드가 구조 결정** — 모델은 메시지를 분류하고 열린 activity 에 매칭만
  한다. *새 activity 로 끊을지* 는 매칭 실패 시 발동하는 **결정론적 cut 규칙**이지 모델의
  추측이 아니다. 재현성과 신뢰성을 확보하는 핵심.
- **값싼 기계적 prewhere** — LLM 을 부르기 전에 토큰 겹침으로 후보를 top-k 로 줄인다.
  히스토리가 길어져도 매 발화당 LLM 비용이 선형으로 폭증하지 않도록 상한을 건다.
  (임베딩 유사도로 교체 가능한 "seam" 으로 설계)
- **근거 있는 인과만** — `caused-by` 엣지는 발화에 **명시된** why/ref 단서에서만 그린다.
  모델이 그럴듯하게 지어낸 인과 링크(환각)를 원천 차단.
- **reversal 자동 감지** — 새 결정을 과거 결정과 대조해 직접적 모순을 찾아, 회의에서
  자주 놓치는 "말 바꾼 지점"을 자동으로 드러낸다.

## 구현

- [`graph_engine.py`](./graph_engine.py) — 위 3단계 전체를 담은 자족적(self-contained) 구현.
  `python graph_engine.py` 로 샘플 스트림에 대한 그래프 빌드를 확인할 수 있다.
- Node 스키마: `{uuid, pre[], post[], value{}, date}` — `pre[]` 가 belongs-to/caused-by
  엣지를 담는 인접 리스트.

## 기술 스택

**Technologies**: Python, LLM orchestration (vLLM / Claude 백엔드 스위칭), 그래프 모델링,
결정론적 규칙 엔진, 스트리밍 파이프라인

> 이 디렉토리의 코드는 포트폴리오용으로 sanitize 되었습니다 — 내부 endpoint/키/제품 특정
> 샘플은 환경변수·일반 예시로 대체했습니다.
