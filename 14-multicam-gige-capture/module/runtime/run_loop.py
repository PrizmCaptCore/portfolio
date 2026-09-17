"""수집 루틴: 'q' 를 누를 때까지 프레임을 받아 표시하고 저장한다."""
import time
import cv2
import psutil  # RAM 사용량 출력
from pypylon import pylon

from config.settings import CameraConfig
from module.disk_management.disk_state import DiskState
from module.disk_management.disk_logic import monitor_disk_space

# 화면 표시 색 (BGR)
GREEN = (0, 255, 0)
YELLOW = (0, 255, 255)
ORANGE = (0, 165, 255)
RED = (0, 0, 255)


# ==================================================
# 상태 / 화면 표시
# ==================================================
def saving():
    """지금 저장 중인지. 설정이 켜져 있고 용량 부족으로 중단되지 않았을 때만 True."""
    return CameraConfig.save_video and not DiskState.full


def disk_overlay():
    """화면에 표시할 디스크 상태 (문구, 색)."""
    if DiskState.full:
        return "DISK FULL - SAVING STOPPED", RED
    if DiskState.free_gb is None:
        return "DISK --", YELLOW
    return f"DISK {DiskState.free_gb:.1f}GB free", (ORANGE if DiskState.warned else YELLOW)


def draw_overlay(display, lines):
    """왼쪽 위에 상태 문구를 한 줄씩 그린다. lines: [(문구, 색), ...]"""
    for row, (text, color) in enumerate(lines):
        cv2.putText(display, text, (20, 40 + 40 * row), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)


# ==================================================
# 메인 루프
# ==================================================
def run_loop(cameras, converter):
    """'q' 를 누를 때까지 프레임을 받아 표시하고 저장한다. 돌아간 시간(초)을 돌려준다."""
    record_start = time.time()
    fps_time = record_start

    while True:
        # 용량 감시와 RAM 확인은 프레임마다가 아니라 루프마다 한 번이면 충분하다
        monitor_disk_space(cameras)
        mem = psutil.virtual_memory()
        ram_text = f"RAM {mem.used / (1024 ** 3):.1f}/{mem.total / (1024 ** 3):.1f}GB"
        disk_text, disk_color = disk_overlay()

        for cam in cameras:
            if not cam.IsGrabbing():
                continue

            result = cam.RetrieveResult(1000, pylon.TimeoutHandling_ThrowException)
            if result.GrabSucceeded():
                # 카메라 설치 방향 보정 (저장/표시 영상 모두 적용)
                frame = cam.apply_rotation(converter.Convert(result).GetArray())
                cam.frame_count += 1
                cam.fps_count += 1

                if saving() and cam.writer is not None:
                    cam.writer.write(frame)
                    cam.rotate_writer_if_needed(cameras)

                # 화면 표시용 복사본에만 문구를 얹는다 (저장 영상은 깨끗하게)
                display = frame.copy()
                draw_overlay(display, [
                    (f"CAM {cam.index}", GREEN),
                    (f"FPS {cam.fps_value:.1f}", GREEN),
                    (ram_text, YELLOW),
                    (disk_text, disk_color),
                ])
                cv2.imshow(f"Camera {cam.index}", display)

            result.Release()

        # 1초마다 FPS 갱신
        if time.time() - fps_time >= 1.0:
            for cam in cameras:
                cam.fps_value = cam.fps_count
                cam.fps_count = 0
            fps_time = time.time()

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    return time.time() - record_start
