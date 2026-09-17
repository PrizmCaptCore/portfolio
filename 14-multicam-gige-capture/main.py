"""농산물 영상 수집 프로그램 (Basler GigE 카메라 여러 대).

설정값은 config/settings.py 의 CameraConfig 에서 바꾼다.
실행 흐름은 module/runtime/ 아래에 있다: startup(시작) -> run_loop(수집) -> shutdown(종료)
"""
from module.runtime.startup import (discover_cameras, select_serials, open_cameras,
                                    make_converter, start_grabbing, prepare_recording)
from module.runtime.run_loop import run_loop
from module.runtime.shutdown import shutdown, print_summary


def main():
    found = discover_cameras()
    serials = select_serials(found)
    cameras = open_cameras(serials, found)
    converter = make_converter()
    start_grabbing(cameras)
    prepare_recording(cameras)

    try:
        record_time = run_loop(cameras, converter)
    finally:
        shutdown(cameras)

    print_summary(cameras, record_time)


if __name__ == "__main__":
    main()
