class DiskState:
    """디스크 용량 감시 상태값 모음.

    인스턴스를 만들지 않고 ``DiskState.full`` 처럼 클래스 속성으로 읽는다.
    갱신할 때는 ``global`` 대신 ``DiskState.full = True`` 처럼 클래스에 직접 대입한다.
    monitor_disk_space() / stop_saving_on_full_disk() 에서 갱신된다.
    """

    full = False          # 용량 부족으로 저장을 중단했는지 여부
    warned = False        # 경고 메시지를 이미 출력했는지 여부
    last_check = 0.0      # 마지막 확인 시각 (time.monotonic 기준)
    free_gb = None        # 최근 확인된 여유 공간 (GB), 화면 표시용
