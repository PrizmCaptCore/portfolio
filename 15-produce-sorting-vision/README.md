# 농산물(감자) 선별기 비전 파이프라인 — 카메라 검증부터 NanoDet 판정까지

> 컨베이어 컵에 실려 지나가는 감자를 GigE 카메라로 보고 정상/불량을 판정해 라인 컨트롤러에 신호를 주는
> 엣지 비전 시스템의 소스. 모델 학습보다 **카메라가 몇 fps 를 실제로 낼 수 있는지, 10분 연속 스트리밍에
> 메모리가 새지 않는지, 라벨링 데이터를 NAS 에서 어떻게 디스크를 채우지 않고 뽑아내는지**가 프로젝트
> 시간의 대부분이었고, 그 흔적을 그대로 남겼다.

## 구성

```
.
├── main.py / potato.drawio          # 전체 루프 설계 메모 + 시스템 다이어그램
├── camera_part/                     # Basler GigE 프레임 소스 (Bayer -> BGR)
├── governor_part/sync.py            # 라인 컨트롤러와의 동기화 방식 (센서 타임스탬프 vs 신호 후 카운트)
├── common_part/logger_singleton.py  # 스레드 안전 싱글턴 로거 (rotating file + console)
├── ai_part/
│   ├── src/config/*.yml             # NanoDet-Plus-m 1.5x 416 설정 (1-class potato / 2-class normal·abnormal)
│   ├── src/detect_potato.py         # Stage 1: Detector 래퍼 + 이미지/폴더/비디오/웹캠 시각 확인
│   ├── src/pipeline.py              # 단일 스테이지 판정: 트랙별 MAX 집계, --min-hits 로 단일 프레임 오탐 억제
│   ├── src/export_tracks.py         # 트랙 단위 crop/메타 내보내기
│   ├── src/extract_label_frames.py  # 비디오 -> 라벨링 프레임(YOLO 프리라벨 + manifest.csv)
│   ├── src/extract_from_nas.py      # NAS 에서 비디오 한 개씩 복사-추출-삭제 (피크 디스크 = 비디오 1개), 재시작 안전
│   ├── src/prepare_nanodet_*.py     # 외부 데이터셋 병합 / 2-class 데이터셋 생성
│   ├── src/eval_vis.py, multihead_test.py   # 평가 시각화, 두 헤드 동시 비교
│   ├── src/tools/wheel_ghost_*.py   # 컵 캐리어 휠 포켓 오탐(ghost) 재검출·정리 (12,756 박스 제거)
│   └── runs/nanodet_potato/model_best/eval_results.txt   # 학습 곡선 (가중치는 제외)
├── backup/src/                      # 1차 반복(YOLO11): 데이터셋 병합, 리얼타임 하네스, Jetson 벤치마크
└── sketch_test/                     # GigE 카메라 검증 스크립트 (대역폭, 고정 버퍼, 소크, 타 대역 카메라 adoption)
```

## 판정 파이프라인 (`ai_part/src/pipeline.py`)

처음엔 "감자 검출 -> crop -> 불량 분류" 2-stage 였다. 검출기 자체가 normal/abnormal 을 답하도록 바꾸고
2-stage 를 버렸다. 남은 것은 분류기와 무관했던 부분, 즉 **한 감자는 여러 프레임에 걸쳐 보이고, 프레임별
판정은 결정이 아니라는 것**이다.

- IoU 기반 트랙에 프레임별 점수를 누적하되, 평균/EMA 가 아니라 **MAX** 로 줄인다. 한쪽 면에만 보이는 결함은
  몇 프레임에만 잡히고 평균은 그것을 지운다.
- 단일 프레임 오탐은 평균이 아니라 `--min-hits` 가 억제한다. 평균이 잘못 맡고 있던 일을 분리했다.
- `Detector` 는 `detect_potato.py` 한 곳에만 있고 `pipeline.py` 가 import 한다. 추론 경로가 둘로 갈라져
  서로 어긋나는 일을 막는다.

1-class potato 검출기(NanoDet-Plus-m 1.5x, 416) 학습 곡선 (`eval_results.txt`):

| epoch | mAP | AP50 | AP75 |
|---|---|---|---|
| 5 | 0.639 | 0.867 | 0.726 |
| 20 | 0.681 | 0.891 | 0.767 |
| 35 | 0.691 | 0.901 | 0.780 |

## 라벨링 데이터 추출 (`extract_from_nas.py`, `tools/`)

- 처음 "전부 복사하고 처리" 방식은 44GB 소스 비디오를 디스크에 올려놓고 아무도 쓰지 않았다. WSL 은 UNC 를
  직접 못 여니 PowerShell 로 **한 파일 복사 -> 로컬에서 추출 -> 삭제** 를 반복한다. 복사는 추론 시간의 몇 % 라
  총 시간은 같고, 누적되는 것이 없다.
- 레인별 `done.txt` 로 재시작 안전. 중단된 비디오의 manifest 행은 재시작 시 정리해(`prune_manifest`) 이미지 = 라벨 = manifest 를 유지한다.
- 웹 사진으로 학습한 1-class 검출기는 **빈 컵 캐리어 휠 포켓**을 감자로 잡는다(가로세로 ~2:1, conf 0.50~0.65).
  실제 감자는 ~1:1 이고 진짜 길쭉한 감자는 0.70 이상이라, `aspect >= 2.0 AND 재검출 conf < 0.65` 규칙으로
  12,756 박스를 제거하고 9,558 프레임을 격리했다. 삭제가 아니라 이동이라 되돌릴 수 있다.

## GigE 카메라 검증 (`sketch_test/`)

WSL2 mirrored 네트워킹에서 Basler acA1300-75gc 를 대상으로 한 실측. 상세는 `sketch_test/README.md`.

- 출고 설정에 GevSCPD=10059(패킷 간 ~80µs) + 30fps 캡이 있어 실효 10.8fps. 스로틀 해제 시 **81.3fps, 드랍 0 (~107MB/s)**.
  카메라 2대가 1GbE 하나를 공유하므로 동시 풀레이트는 불가능. 라인 설계에서 카메라당 대역 배분 또는 NIC 분리가 필요하다는 근거.
- 고정 버퍼 파이프라인은 10분 연속(6,481 프레임, crop 51,848개)에서 RSS 플랫, in-place 위반 0. naive 할당 + 보관 풀은 +3MB/10분씩 상승.
- 타 대역/무 IP 카메라는 pylon 열거에 안 잡힌다. `adopt_cameras.py` 가 0x11 discovery 를 raw UDP 로 쏘고,
  SN 에서 유도한 오프셋으로 링크 서브넷의 빈 주소를 persistent 로 써서 같은 카메라가 항상 같은 주소로 돌아오게 한다.
  Linux 에서는 소켓을 0.0.0.0 에 바인드하고 IP_PKTINFO 로 카메라 링크로 내보내야 브로드캐스트 ack 가 돌아온다 (Windows 는 이 문제를 숨긴다).

## 1차 반복 (`backup/src/`)

YOLO11 기반 초기 버전. 외부 Roboflow 데이터셋의 클래스명 난립('potato', 'Potatoes', '0')과 같은 원본 사진이
증강만 달리해 여러 데이터셋에 재수출되어 train/valid 로 새는 문제를 해시 기반으로 걸렀다. `realtime.py` 는
"큐는 버스트를 흡수한 뒤 영원히 회복하지 못한다"는 이유로 최신 프레임 한 슬롯만 유지하고 드랍 수와
capture->decision 지연을 함께 보고한다. `test_for_realtime.py` 는 Jetson 에 단일 파일로 던져 throughput 과
`--rate N` 두 모드로 "이 보드가 N fps 를 따라가는가, 판정이 얼마나 낡았는가"를 잰다.

## 환경

사이트별 경로(NAS UNC, WSL 접두어, 카메라 IP)는 `.env.example` 참고. 모델 가중치와 데이터셋은 포함하지 않는다.

- Python 3.10, PyTorch, [nanodet](https://github.com/RangiLyu/nanodet) (Stage 1), OpenCV, pypylon
- Jetson AGX Orin (현장), WSL2 + RTX (개발)
