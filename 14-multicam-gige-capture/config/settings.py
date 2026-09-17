"""사용자 설정 모음.

값을 바꾸려면 이 파일만 고치면 된다. module/ 의 코드는 이 파일을 import 하지만,
이 파일은 module/ 을 import 하지 않는다 (의존 방향: module -> config).

현장마다 다른 값(저장 경로, 카메라 시리얼별 설치 방향)은 코드에 두지 않고
환경변수 또는 프로젝트 루트의 .env 파일에서 읽는다 (.env.example 참고).
"""
import os


def _load_dotenv(path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")):
    """프로젝트 루트의 .env 를 읽어 아직 없는 환경변수만 채운다. 외부 의존성 없이 KEY=VALUE 만 지원."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _rotate_table(raw):
    """CAMERA_ROTATE_180="25xxxxxx:1,25yyyyyy:0" -> {"25xxxxxx": True, "25yyyyyy": False}"""
    table = {}
    for item in filter(None, (x.strip() for x in raw.split(","))):
        sn, _, flag = item.partition(":")
        table[sn.strip()] = flag.strip() in ("1", "true", "True", "yes")
    return table


_load_dotenv()


class CameraConfig:
    """카메라 / 녹화 / 저장 관련 설정값 모음.

    인스턴스를 만들지 않고 ``CameraConfig.width`` 처럼 클래스 속성으로 바로 읽는다.
    필요에 따라 값들을 변경하면 `main.py` 실행 시 해당 설정이 적용됩니다.
    """

    # --- 이미지/해상도 ---
    width = 1280                     # 이미지 너비 (픽셀)
    height = 1024                    # 이미지 높이 (픽셀)

    # --- 네트워크 / GigE ---
    packet_size = 1500               # GigE 패킷 크기 (MTU)

    # --- 카메라 버퍼 ---
    max_buffer = 100                 # pylon 카메라 최대 버퍼 수

    # --- 녹화 설정 ---
    fps = 15                         # 녹화 프레임 레이트 (fps)
    bitrate = 8000000                # 비디오 비트레이트 (bps)
    segment_minutes = 10             # 저장 파일 분할 시간(분)
    segment_seconds = segment_minutes * 60

    # --- 저장 설정 ---
    save_video = True                 # 비디오 저장 사용 여부 (True/False)
    videos_dir = os.environ.get("VIDEOS_DIR", "item_videos")   # 비디오 저장 디렉터리 (.env: VIDEOS_DIR)

    # --- 카메라 설치 방향 (카메라별 개별 지정) ---
    # 시리얼 번호를 키로 쓴다. pylon 의 장치 열거 순서는 보장되지 않으므로
    # 인덱스로 묶으면 재부팅 때 설정이 다른 카메라에 붙을 수 있다.
    rotate_180_default = False        # 아래 표에 없는 카메라에 적용할 기본값

    # 시리얼 -> 180도 회전 여부. .env 의 CAMERA_ROTATE_180 에서 읽는다.
    #   예) CAMERA_ROTATE_180=25xxxxxx:0,25yyyyyy:1,25zzzzzz:1
    camera_rotate_180 = _rotate_table(os.environ.get("CAMERA_ROTATE_180", ""))

    # --- 디스크 용량 감시 ---
    disk_min_free_gb = 5.0           # 여유 공간이 이 값 미만이면 저장 중단 (GB)
    disk_warn_free_gb = 20.0         # 여유 공간이 이 값 미만이면 경고만 출력 (GB)
    disk_check_interval = 5.0        # 용량 확인 주기 (초). 매 프레임 확인할 필요는 없음

    # --- ACA(acA1300-75gc) 카메라 관련 설정 ---
    # 아래 값들은 a.py의 create_camera()에서 사용되던 기본값을 가져왔습니다.
    exposure_time = 6000                     # 노출 시간 (마이크로초)
    center_x = True                          # CenterX 사용 여부 (True/False)
    center_y = True                          # CenterY 사용 여부 (True/False)
    acquisition_frame_rate_enable = True     # AcquisitionFrameRate 사용 여부
    trigger_selector = "FrameStart"          # TriggerSelector 설정
    trigger_mode = "Off"                     # TriggerMode (On/Off) - 연속 스트리밍시 Off 권장
    trigger_source = "Software"              # TriggerSource (예: Software, Line1)

    # --- GigE 추가 설정 ---
    gev_scps_packet_size = 1500              # GevSCPSPacketSize
    gev_scpd = 1500                          # GevSCPD
    gev_scftd = 400                          # GevSCFTD
    gev_scbwr = 10                           # GevSCBWR
    gev_scbwra = 20                          # GevSCBWRA
    max_num_buffer = 10                      # 카메라 내부 MaxNumBuffer
