"""프로그램 시작 루틴: 카메라 탐색 -> SN 선택 -> 열기 -> 그랩 시작 -> 저장 준비"""
import os
import datetime
from pypylon import pylon

from module.camera.camera import Camera, enumerate_by_serial
from config.settings import CameraConfig
from module.disk_management.disk_state import DiskState
from module.disk_management.disk_logic import check_disk_space, stop_saving_on_full_disk


# ==================================================
# 카메라 선택 / 열기
# ==================================================
def discover_cameras():
    """연결된 카메라를 열거해 {시리얼: DeviceInfo} 로 돌려준다. 한 대도 없으면 종료한다."""
    found = enumerate_by_serial()
    print("Camera Count:", len(found))
    if not found:
        raise SystemExit("Camera not found")
    return found


def select_serials(found):
    """연결된 카메라 목록을 보여주고 사용할 SN 을 입력받는다.

    쉼표로 구분해 입력한 순서가 CAM 0, 1, ... 이 된다.
    그냥 Enter 를 누르면 (또는 입력을 받을 수 없는 환경이면) 연결된 카메라 전부를 SN 순으로 쓴다.
    """
    print("연결된 카메라:")
    for sn in sorted(found):
        d = found[sn]
        rotate = CameraConfig.camera_rotate_180.get(sn, CameraConfig.rotate_180_default)
        print(f"  SN {sn}  {d.GetModelName()}  {d.GetIpAddress()}  rotate_180={rotate}")

    while True:
        try:
            raw = input("사용할 카메라 SN 을 쉼표로 구분해 입력 (Enter = 전부): ").strip()
        except EOFError:
            raw = ""
        if not raw:
            return sorted(found)

        serials = [s.strip() for s in raw.split(",") if s.strip()]
        unknown = [s for s in serials if s not in found]
        duplicated = sorted({s for s in serials if serials.count(s) > 1})
        if unknown:
            print(f"  연결되지 않은 SN: {unknown}. 다시 입력하세요.")
            continue
        if duplicated:
            print(f"  중복 입력된 SN: {duplicated}. 다시 입력하세요.")
            continue
        return serials


def open_cameras(serials, found):
    """입력 순서대로 CAM 0, 1, ... 을 만들고 연다."""
    # 저장 파일명에 들어가는 실행 시각. 카메라 생성 전에 만들어 모든 카메라가 같은 값을 쓰게 한다
    record_prefix = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    cameras = []
    for i, sn in enumerate(serials):
        if sn not in CameraConfig.camera_rotate_180:
            print(f"[WARN] CameraConfig.camera_rotate_180 에 없는 카메라 {sn} "
                  f"-> 기본값 {CameraConfig.rotate_180_default} 적용")
        rotate = CameraConfig.camera_rotate_180.get(sn, CameraConfig.rotate_180_default)
        cameras.append(Camera(i, found[sn], rotate_180=rotate, record_prefix=record_prefix).open())

    print("\nConnected Cameras:", len(cameras), "EA")
    return cameras


def make_converter():
    converter = pylon.ImageFormatConverter()
    converter.OutputPixelFormat = pylon.PixelType_BGR8packed
    converter.OutputBitAlignment.Value = pylon.OutputBitAlignment_MsbAligned
    return converter


def start_grabbing(cameras):
    for cam in cameras:
        cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)


# ==================================================
# 저장 준비
# ==================================================
def prepare_recording(cameras):
    """저장 디렉터리를 만들고 용량을 확인한 뒤, 저장 가능하면 카메라마다 writer 를 연다."""
    if not CameraConfig.save_video:
        print("[SAVE] save_video=False. 미리보기만 실행합니다.")
        return

    try:
        os.makedirs(CameraConfig.videos_dir, exist_ok=True)
    except OSError as e:
        print(f"[SAVE] 저장 디렉터리 생성 실패 ({CameraConfig.videos_dir}): {e}")

    # 녹화 시작 전 용량 확인 - 이미 부족하면 저장 없이 미리보기만 실행한다
    status, free_gb = check_disk_space(CameraConfig.videos_dir)
    DiskState.free_gb = free_gb
    if status == "full":
        stop_saving_on_full_disk(free_gb, cameras)
        return
    if status == "warn":
        DiskState.warned = True
        print(f"[DISK] 경고: 남은 공간 {free_gb:.1f}GB. "
              f"{CameraConfig.disk_min_free_gb:.1f}GB 미만이 되면 저장을 자동 중단합니다.")
    elif status == "ok":
        print(f"[DISK] 저장 경로 여유 공간: {free_gb:.1f}GB")

    for cam in cameras:
        cam.open_writer()
