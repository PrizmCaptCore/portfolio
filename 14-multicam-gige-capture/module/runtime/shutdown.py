"""종료 루틴: 카메라 닫기, 진행 중인 세그먼트 마무리, 결과 요약"""
import cv2

from config.settings import CameraConfig
from module.disk_management.disk_state import DiskState


def shutdown(cameras):
    print("\nStopping...")
    for cam in cameras:
        cam.close()

    # 진행 중이던 세그먼트는 release() 로 마무리해야 재생 가능한 mp4 가 된다
    for cam in cameras:
        if cam.writer is not None:
            print(f"Finalizing video segment for camera {cam.index}")
            cam.release_writer()
    cv2.destroyAllWindows()

    if DiskState.full:
        print(f"\n[DISK] 용량 부족으로 저장이 중단된 상태였습니다. "
              f"공간 확보 후 다시 실행하세요. ({CameraConfig.videos_dir})")


def print_summary(cameras, record_time):
    print("\nDone")
    print(f"Recording Time: {record_time:.2f} sec")
    for cam in cameras:
        print(f"Camera {cam.index} (SN {cam.serial}) Frames:", cam.frame_count)
        print(f"Camera {cam.index} (SN {cam.serial}) FPS:",
              f"{cam.frame_count / record_time:.2f}")
