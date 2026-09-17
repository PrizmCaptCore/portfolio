import time

from config.settings import CameraConfig
from module.disk_management.disk_state import DiskState
from module.disk_management.disk_writer import get_disk_free_gb


def check_disk_space(path):
    """디스크 여유 상태를 (status, free_gb) 튜플로 반환.

    status
        "ok"      : 충분함
        "warn"    : CameraConfig.disk_warn_free_gb 미만 (저장은 계속)
        "full"    : CameraConfig.disk_min_free_gb 미만 (저장 중단 대상)
        "unknown" : 확인 실패 (free_gb 는 None)
    """
    free_gb = get_disk_free_gb(path)

    if free_gb is None:
        return "unknown", None
    if free_gb < CameraConfig.disk_min_free_gb:
        return "full", free_gb
    if free_gb < CameraConfig.disk_warn_free_gb:
        return "warn", free_gb
    return "ok", free_gb

def stop_saving_on_full_disk(free_gb, cameras):
    """저장을 중단하고 안내 메시지를 출력. 이미 중단된 상태면 아무 동작도 하지 않는다.

    cameras : 진행 중인 세그먼트를 닫아야 하므로 카메라 전체 목록을 받는다.
    저장 중단은 DiskState.full 로 표시한다. 설정값 CameraConfig.save_video 는 바꾸지 않는다.
    """
    if DiskState.full:
        return
    DiskState.full = True

    # 진행 중이던 세그먼트는 release() 로 마무리해야 재생 가능한 mp4 가 된다
    released = 0
    for c in cameras:
        if c.writer is not None:
            c.release_writer()
            released += 1

def monitor_disk_space(cameras):
    """주기적으로 디스크 용량을 확인하고, 부족하면 저장을 중단한다.

    메인 루프에서 매 프레임 호출해도 되도록 CameraConfig.disk_check_interval 간격으로만
    실제 확인(statvfs)을 수행한다.
    """
    if not CameraConfig.save_video or DiskState.full:
        return

    now = time.monotonic()
    if now - DiskState.last_check < CameraConfig.disk_check_interval:
        return
    DiskState.last_check = now

    status, free_gb = check_disk_space(CameraConfig.videos_dir)
    DiskState.free_gb = free_gb

    if status == "full":
        stop_saving_on_full_disk(free_gb, cameras)
    elif status == "warn":
        if not DiskState.warned:
            DiskState.warned = True
            print(f"[DISK] 경고: 남은 공간 {free_gb:.1f}GB. "
                  f"{CameraConfig.disk_min_free_gb:.1f}GB 미만이 되면 저장을 자동 중단합니다.")
    elif status == "ok":
        DiskState.warned = False