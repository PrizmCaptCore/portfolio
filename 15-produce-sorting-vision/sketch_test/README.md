# sketch_test — Basler GigE 카메라 검증 스크립트

WSL2(mirrored 모드)에서 Basler acA1300-75gc를 대상으로
메모리 거동과 전송 성능을 검증한 스크립트 모음. 2026-08-12 세션에서 작성.

## 사전 조건

- WSL2 mirrored 네트워킹 + Hyper-V 방화벽 규칙 `GigEVision-GVSP-WSL` (없으면 GVSP 스트림 차단)
- 카메라 전용 링크 서브넷(호스트 NIC 에 정적 IP). 카메라 IP 는 첫 인자 또는 `CAMERA_IP`
  환경변수로 넘긴다. 신규·타 대역 카메라는 `adopt_cameras.py`가 링크 서브넷의 빈 주소로
  자동 배정(SN 에서 유도하므로 같은 카메라는 항상 같은 주소). 방화벽 규칙은 link-local
  구 대역(169.254.0.0/16)도 함께 허용하고, 타 대역 카메라의 discovery 응답은 별도 규칙
  `GigEVision-GVCP-Adopt-WSL`(UDP 원격포트 3956)로 통과.
- Python 3.10 (pypylon 휠 제약)

```bash
python3.10 -m venv .venv
.venv/bin/pip install pypylon numpy opencv-python-headless
```

모든 스크립트는 첫 인자로 카메라 IP를 받음 (생략 시 `CAMERA_IP` 환경변수, 기본 192.168.0.2).

## 스크립트

| 파일 | 용도 |
|---|---|
| `gvcp_unicast.py` | pylon 없이 GVCP 유니캐스트로 카메라 도달성 확인 (네트워크 1차 진단) |
| `adopt_cameras.py` | 0x11 discovery로 타 대역/무IP 카메라까지 탐지 → 카메라 링크(기본 라우트 없는 NIC) 서브넷의 빈 주소로 persistent 이전. 단독 실행 또는 live_view가 주기 호출 |
| `capture_stills.py` | 연결된 카메라마다 N장(기본 10) JPEG 저장 — `captures/<타임스탬프>/`. `--every`로 저장 간격(기본 5프레임마다). `--nice`는 폰 스타일 보정 스냅샷(12장 평균+WB+감마+VNG, 사람 눈용 — 모델 입력 금지) |
| `grab_test.py` | 디스커버리 / 직접 IP 오픈 / 3프레임 grab 스모크 테스트 |
| `camera_diag.py` | fps 저하 원인 분리: 노출·fps캡·GevSCPD 등 노드 덤프 + 무처리 수신 fps 측정 |
| `bandwidth_ab_test.py` | GevSCPD 스로틀 유/무 A/B로 달성 가능 fps 확정 (원래 설정 자동 복원) |
| `fixed_buffer_proof.py` | 고정 버퍼 vs naive 비교: 포인터 고정·in-place 검증 + churn 측정 |
| `trend_test.py` | 고정 버퍼 3,000프레임 추세 (정착 vs 선형 누수 구분) |
| `naive_trend.py` | naive 할당의 RSS 추이: 즉시 버림(A) vs 불규칙 보관 풀(B) |
| `continuous_soak.py` | 연속 스트리밍 소크: `fixed\|naive <초> [IP]`, 15초 간격 RSS/fps/드랍 기록 |

## 주요 결과 (2026-08-12, WSL2)

- 고정 버퍼 파이프라인: 10분 연속(6,481프레임, crop 51,848개)에서 RSS 플랫
  (1.3MB 계단 1회 제외), in-place 위반 0.
- naive+보관 풀: 진동 밴드가 +3MB/10분씩 상승 (할당자 고수위 creep 초입)
- 카메라 출고 시점 설정에 GevSCPD=10059(패킷 간 ~80µs) + 30fps 캡이 있어
  실효 10.8fps였음. 스로틀 해제 시 81.3fps, 드랍 0 (~107MB/s) 확인.
  단, 카메라 2대가 1GbE 링크 하나를 공유하므로 동시 풀레이트(2×107MB/s)는
  불가능 — 라인 설계 시 카메라당 대역 배분(GevSCPD) 또는 NIC 분리 필요.
