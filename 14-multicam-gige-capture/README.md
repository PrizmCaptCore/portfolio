# Basler GigE 멀티카메라 영상 수집기 (Jetson AGX Orin)

> 농산물 선별 라인의 학습 데이터 확보용 수집기. 컨베이어 위 카메라 여러 대의 영상을 장시간
> 끊김 없이 녹화해야 하고, 현장 PC(Jetson)는 사람이 상주하지 않는다. 설계의 핵심은 "녹화가 되느냐"가
> 아니라 **재부팅 후에도 카메라-설정 매핑이 어긋나지 않고, 디스크가 차도 파일이 깨지지 않는 것**이었다.

멀티 카메라 GigE 영상 수집 및 저장용 Python 프로젝트입니다. Basler 카메라를 `pypylon`으로 제어하고, OpenCV + GStreamer 기반으로 실시간 영상을 출력하며, 장시간 녹화 시 10분 단위로 자동 세그먼트 분할 저장을 지원합니다.

## Overview

이 프로젝트는 Jetson AGX Orin 환경에서 동작하도록 설계되었으며, 여러 대의 Basler 카메라를 연결하여 동시에 영상 스트림을 수집하고 화면에 표시합니다.  
(현재 코드는 Balser ACA1300-75gc * 2EA 기준으로 테스트 하였습니다.)

주요 기능은 다음과 같습니다.

- Basler GigE 카메라 자동 탐지 및 연결
- 카메라 해상도, 프레임레이트, 패킷 크기 설정
- 실시간 화면 표시 (`cv2.imshow`)
- GStreamer 기반 MP4 저장
- 장시간 녹화 시 10분 단위 세그먼트 자동 분할
- 메모리 사용량 표시 및 FPS 모니터링

## Project Structure

```text
.
├── main.py                  # 진입점: startup -> run_loop -> shutdown
├── README.md
├── requirements.txt
├── .env.example             # 현장별 값(저장 경로, 카메라 시리얼 표) 템플릿
├── config/
|   └── settings.py          # CameraConfig: 해상도/GigE/노출/트리거/디스크 임계값
└── module/
    ├── camera/camera.py           # Camera: 노드맵 설정 적용·검증, 세그먼트 writer 관리
    ├── runtime/startup.py         # 탐색 -> SN 선택 -> open -> grab -> 저장 준비
    ├── runtime/run_loop.py        # 프레임 수신/표시/저장, FPS·RAM·디스크 오버레이
    ├── runtime/shutdown.py        # 세그먼트 finalize, 요약 출력
    └── disk_management/           # 여유 공간 감시, 임계값 미만 시 저장 자동 중단
```

## 설계 포인트

- **시리얼 기준 설정 바인딩**: pylon 의 장치 열거 순서는 보장되지 않는다. 카메라별 설치 방향(180도 회전)을
  인덱스가 아니라 시리얼 번호에 묶어, 재부팅 후 카메라 순서가 바뀌어도 설정이 다른 카메라에 붙지 않는다.
  시리얼 표는 코드가 아니라 `.env` 의 `CAMERA_ROTATE_180` 에 둔다.
- **설정 적용 후 재검증**: `Camera.setting_check()` 가 노드맵에서 실제 값을 다시 읽어 설정값과 비교한다.
  카메라가 값을 양자화하는 실수 노드는 1% 오차를 허용한다. 없는 노드/쓸 수 없는 노드는 건너뛰고 경고만 남긴다.
- **디스크 감시와 안전한 중단**: `disk_check_interval` 주기로 여유 공간을 확인하고, 임계값 미만이면
  모든 카메라의 writer 를 `release()` 해 진행 중 세그먼트를 재생 가능한 mp4 로 마무리한 뒤 저장만 중단한다
  (미리보기는 계속). 저장 디렉터리가 아직 없어도 상위 경로로 올라가며 용량을 확인한다.
- **하드웨어 인코딩 파이프라인**: `appsrc -> nvvidconv -> nvv4l2h264enc -> qtmux(faststart)` GStreamer
  파이프라인으로 Jetson 의 HW 인코더를 쓴다. 10분 세그먼트에서 실측 길이 9:59 로 프레임 드랍이 가장 적었다.
- **의존 방향 고정**: `module -> config` 만 허용. 설정 파일은 모듈을 import 하지 않는다.

## Main Functionality

`main.py`는 다음 흐름으로 동작합니다.

1. 연결된 카메라 장치를 탐색합니다.
2. 각 카메라에 대해 해상도, 프레임율, 네트워크 파라미터를 설정합니다.
3. 카메라를 `StartGrabbing()`으로 실행합니다.
4. 프레임을 받아 BGR 형식으로 변환합니다.
5. 화면에 `CAM n`, `FPS`, `RAM` 정보를 오버레이합니다.
6. `SAVE_VIDEO=True`일 경우 GStreamer 파이프라인으로 MP4 파일에 저장합니다.
7. 설정된 10분 단위 기준으로 새 세그먼트 파일을 생성합니다.

## Recording Configuration

현재 기본 설정은 아래와 같습니다.

```python
width = 1280
height = 1024
fps = 15
bitrate = 8000000
segment_minutes = 10
save_video = True
videos_dir = os.environ.get("VIDEOS_DIR", "potato_videos")
camera_rotate_180 = _rotate_table(os.environ.get("CAMERA_ROTATE_180", ""))
```

현장마다 달라지는 값은 코드가 아니라 `.env` 에 둡니다.

```bash
cp .env.example .env
# VIDEOS_DIR=/mnt/ssd/potato_videos
# CAMERA_ROTATE_180=<시리얼>:0,<시리얼>:1     # 카메라별 180도 설치 보정
```

이 설정은 다음 의미를 가집니다.

- 해상도: 1280x1024
- 프레임 속도: 15 FPS (카메라 2대가 1GbE 링크 하나를 공유하므로 대역 배분 후 고정)
- 인코딩 비트레이트: 8 Mbps
- 세그먼트 분할: 10분마다 새 파일 생성
- 저장 위치: `potato_videos/`

## How to Run

1. 필요한 패키지를 설치합니다.

```bash
pip install -r requirements.txt
```

2. 카메라가 연결되어 있는지 확인합니다.

```bash
python main.py
```

3. 녹화 중 `q` 키를 누르면 종료됩니다.

## Video Output

녹화 파일은 다음 형식으로 생성됩니다.

카메라번호_년월일_시분초_10분단위저장순서.mp4

```text
potato_videos/
├── cam0_20260825_123456_000.mp4
├── cam0_20260825_123456_001.mp4
├── cam1_20260825_123456_000.mp4
└── ...
```

각 파일은 카메라 번호, 시작 시간, 세그먼트 번호로 구분됩니다.

## System Environment

| 항목 | 값 |
|---|---|
| Date | 2026. 08. 24. (월) 10:44:35 KST |
| Device | Jetson AGX Orin Developer Kit |
| Architecture | aarch64 |
| Ubuntu | 20.04.6 LTS |
| Python | 3.10.20 |
| JetPack / L4T | R35 (release), REVISION: 4.1 |
| Board | t186ref |
| CUDA | 11.4 |
| GPU | Orin |
| OpenCV | 4.8.0 |
| Pylon SDK | 9.0.3 |
| pypylon | 26.7 |
| cuDNN | 8.6.0 |
| PyTorch | 2.1.0a0+git7bcf7da |

## Requirements

### Hardware

- Jetson AGX Orin Developer Kit
- Basler GigE 카메라 (ACA1300-75gc * 2EA)

### Software

- Python 3.10+
- OpenCV 4.8+
- pypylon 26.7+
- GStreamer
- CUDA-enabled environment

OpenCV 빌드 버전 필요 (apt 등등 원격 레포지토리 버전 불가)

## Notes

- 현재 프로젝트는 영상 수집과 저장에 초점을 두고 있습니다.
- `main.py`는 실시간 감시/모니터링용으로 설계되어 있으며, 영상 처리 알고리즘이나 AI 추론은 별도의 단계에서 확장하는 구조입니다.
- 장시간 녹화 시 디스크 용량과 프레임 처리 속도를 함께 고려해야 하며, 필요 시 저장 세그먼트 길이와 인코딩 설정을 조정할 수 있습니다.

---

프로젝트 관련 개선 사항이나 커스텀 설정 변경이 필요한 경우, `main.py`의 파라미터를 조정해 실행 환경에 맞게 사용하면 됩니다.

10분 단위 저장 시 동영상길이 9:59로 프레임 드랍이 적음을 확인하였습니다. 더 긴 단위로 저장하면 프레임드랍이 누적되어 다소 차이가 발생 할 수 있습니다.
