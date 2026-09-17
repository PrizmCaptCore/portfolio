import os
import shutil
import cv2

from config.settings import CameraConfig

# ==================================================
# GStreamer Writer
# ==================================================
def create_writer(filename):
    pipeline = (
        "appsrc "
        "is-live=true "
        "format=time "
        "do-timestamp=true "
        "caps=video/x-raw,"
        f"format=BGR,"
        f"width={CameraConfig.width},"
        f"height={CameraConfig.height},"
        f"framerate={CameraConfig.fps}/1 ! "
        "videoconvert ! "
        "video/x-raw,format=BGRx ! "
        "nvvidconv ! "
        "video/x-raw(memory:NVMM),format=NV12 ! "
        f"nvv4l2h264enc bitrate={CameraConfig.bitrate} "
        "iframeinterval=30 ! "
        "h264parse ! "
        "qtmux faststart=true ! "
        f"filesink location={filename} sync=false"
    )
    print("\nPipeline:")
    print(pipeline)

    writer = cv2.VideoWriter(
        pipeline,
        cv2.CAP_GSTREAMER,
        0,
        CameraConfig.fps,
        (CameraConfig.width, CameraConfig.height),
        True
    )

    if not writer.isOpened():
        raise Exception("VideoWriter open failed")

    return writer

def get_disk_free_gb(path):
    """path가 속한 파일시스템의 여유 공간을 GB 단위로 반환. 확인 실패 시 None."""
    # 저장 디렉터리가 아직 없을 수 있으므로 존재하는 상위 경로까지 거슬러 올라간다
    target = os.path.abspath(path)
    while not os.path.exists(target):
        parent = os.path.dirname(target)
        if parent == target:
            break
        target = parent

    try:
        return shutil.disk_usage(target).free / (1024 ** 3)
    except OSError as e:
        print(f"[DISK] 용량 확인 실패 ({path}): {e}")
        return None