from config.settings import CameraConfig
from module.disk_management.disk_state import DiskState
from module.disk_management.disk_logic import check_disk_space, stop_saving_on_full_disk
from module.disk_management.disk_writer import create_writer
from pypylon import pylon, genicam
import time
import datetime
import cv2
import os

class Camera:
    """카메라 1대. 장치 핸들, 녹화 writer, 프레임 통계를 함께 보유한다.

    rotate_180 은 카메라마다 독립적으로 지정한다. 4대의 설치 방향이
    서로 다를 수 있으므로 전역 플래그로는 표현할 수 없다.
    """

    def __init__(self, index, device, rotate_180=False, record_prefix=None):
        self.index = index
        self.device = device
        self.serial = device.GetSerialNumber()
        self.model = device.GetModelName()
        self.ip = device.GetIpAddress()
        self.rotate_180 = rotate_180
        # 저장 파일명에 들어가는 실행 시각. 모든 카메라가 같은 값을 쓰도록 main.py 에서 넘겨준다
        self.record_prefix = record_prefix or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        self.cam = pylon.InstantCamera(
            pylon.TlFactory.GetInstance().CreateDevice(device)
        )

        # 녹화 상태
        self.writer = None
        self.segment_index = 0
        self.segment_start = time.monotonic()

        # 통계
        self.frame_count = 0
        self.fps_count = 0
        self.fps_value = 0

    # ---------- 장치 ----------
    def open(self):
        """카메라를 열고 설정을 적용한 뒤, 실제 적용된 값을 확인한다."""
        self.cam.Open()
        self.print_device_info()
        self.apply_settings()
        self.setting_check()
        return self

    def print_device_info(self):
        print("\n====================")
        print("Model:", self.model)
        print("Serial:", self.serial)
        print("IP:", self.ip)

    # ---------- 설정 적용 ----------
    def apply_settings(self):
        """CameraConfig 값을 카메라에 적용한다. 항목별 메서드를 순서대로 호출한다."""
        self.apply_image_settings()
        self.apply_exposure_settings()
        self.apply_gige_settings()
        self.apply_frame_rate_settings()
        self.apply_trigger_settings()
        self.apply_buffer_settings()

    def apply_image_settings(self):
        self._set_node("Width", CameraConfig.width)
        self._set_node("Height", CameraConfig.height)
        self._set_node("CenterX", CameraConfig.center_x)
        self._set_node("CenterY", CameraConfig.center_y)

    def apply_exposure_settings(self):
        self._set_node("ExposureTimeAbs", CameraConfig.exposure_time)

    def apply_gige_settings(self):
        self._set_node("GevSCPSPacketSize", CameraConfig.packet_size)
        self._set_node("GevSCPD", CameraConfig.gev_scpd)
        self._set_node("GevSCFTD", CameraConfig.gev_scftd)
        self._set_node("GevSCBWR", CameraConfig.gev_scbwr)
        self._set_node("GevSCBWRA", CameraConfig.gev_scbwra)

    def apply_frame_rate_settings(self):
        self._set_node("AcquisitionFrameRateEnable", CameraConfig.acquisition_frame_rate_enable)
        self._set_node("AcquisitionFrameRateAbs", CameraConfig.fps)

    def apply_trigger_settings(self):
        # TriggerSelector 를 먼저 골라야 Mode/Source 가 그 트리거에 적용된다
        self._set_node("TriggerSelector", CameraConfig.trigger_selector)
        self._set_node("TriggerMode", CameraConfig.trigger_mode)
        self._set_node("TriggerSource", CameraConfig.trigger_source)

    def apply_buffer_settings(self):
        # MaxNumBuffer 는 카메라 노드가 아니라 pylon 그랩 엔진 설정이라 노드맵을 거치지 않는다
        self.cam.MaxNumBuffer.Value = CameraConfig.max_buffer

    # ---------- 설정 확인 ----------
    def setting_check(self):
        """카메라에서 실제 값을 다시 읽어 출력하고, 설정값과 다르면 경고한다. 전부 일치하면 True."""
        checks = (
            ("Width",        "Width",                   CameraConfig.width),
            ("Height",       "Height",                  CameraConfig.height),
            ("Packet Size",  "GevSCPSPacketSize",       CameraConfig.packet_size),
            ("Exposure(us)", "ExposureTimeAbs",         CameraConfig.exposure_time),
            ("Frame Rate",   "AcquisitionFrameRateAbs", CameraConfig.fps),
            ("Trigger Mode", "TriggerMode",             CameraConfig.trigger_mode),
        )
        all_ok = True
        for label, node_name, expected in checks:
            actual = self._get_node(node_name)
            if actual is None:
                print(f"{label}: (읽기 불가)")
                continue
            if self._matches(actual, expected):
                print(f"{label}: {actual}")
            else:
                print(f"{label}: {actual}   [WARN] 설정값 {expected} 과 다름")
                all_ok = False
        print("MaxNumBuffer:", self.cam.MaxNumBuffer.Value)
        print("Rotate 180:", self.rotate_180)
        return all_ok

    @staticmethod
    def _matches(actual, expected):
        # 실수 노드는 카메라가 값을 양자화할 수 있으므로 1% 오차까지 같은 값으로 본다
        if isinstance(actual, float):
            return abs(actual - expected) <= 0.01 * abs(expected)
        return actual == expected

    # ---------- 노드 접근 헬퍼 ----------
    def _find_node(self, name):
        """장치 노드맵에서 노드를 찾는다. 없으면 None."""
        try:
            return self.cam.GetNodeMap().GetNode(name)  # pypylon 버전에 따라 None 을 주거나 예외를 던진다
        except genicam.GenericException:
            return None

    def _get_node(self, name):
        """노드 값을 읽는다. 없거나 읽을 수 없으면 None."""
        node = self._find_node(name)
        if node is None or not genicam.IsReadable(node):
            return None
        return node.Value

    def _set_node(self, name, value):
        """노드에 값을 쓴다. 없거나 쓸 수 없으면 건너뛰고, 실패하면 경고를 출력한다. 성공 여부를 돌려준다."""
        node = self._find_node(name)
        if node is None:
            print(f"  [SKIP] {name}: 이 카메라에 없는 노드")
            return False
        if not genicam.IsWritable(node):
            print(f"  [SKIP] {name}: 지금 상태에서는 쓸 수 없는 노드")
            return False
        try:
            node.Value = value
        except genicam.GenericException as e:
            print(f"  [WARN] {name} = {value!r} 적용 실패: {e}")
            return False
        return True

    # pylon InstantCamera 위임 (메인 루프를 그대로 쓰기 위함)
    def IsGrabbing(self):
        return self.cam.IsGrabbing()

    def StartGrabbing(self, *args, **kwargs):
        return self.cam.StartGrabbing(*args, **kwargs)

    def RetrieveResult(self, *args, **kwargs):
        return self.cam.RetrieveResult(*args, **kwargs)

    def close(self):
        if self.cam.IsGrabbing():
            self.cam.StopGrabbing()
        self.cam.Close()

    # ---------- 영상 ----------
    def apply_rotation(self, frame):
        """이 카메라의 설치 방향 보정을 적용한다. 저장/표시 영상 모두에 반영된다."""
        if self.rotate_180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        return frame

    # ---------- 녹화 ----------
    def segment_filename(self):
        return f"cam{self.index}_{self.record_prefix}_{self.segment_index:03d}.mp4"

    def open_writer(self):
        filepath = os.path.join(CameraConfig.videos_dir, self.segment_filename())
        self.writer = create_writer(filepath)
        # 세그먼트 길이는 파일이 열린 시점부터 센다
        self.segment_start = time.monotonic()

    def release_writer(self):
        if self.writer is not None:
            self.writer.release()
            self.writer = None

    def rotate_writer_if_needed(self, cameras):
        # cameras: 용량 부족 시 모든 카메라의 writer 를 닫아야 하므로 전체 목록을 받는다
        if not CameraConfig.save_video or DiskState.full or self.writer is None:
            return

        if time.monotonic() - self.segment_start < CameraConfig.segment_seconds:
            return

        print(f"Rotating video segment for camera {self.index} "
              f"at {CameraConfig.segment_minutes} minute interval")
        self.release_writer()
        self.segment_index += 1
        self.segment_start = time.monotonic()

        # 새 세그먼트를 열기 전에 용량을 확인한다 (부족하면 여기서 저장 종료)
        status, free_gb = check_disk_space(CameraConfig.videos_dir)
        if status == "full":
            stop_saving_on_full_disk(free_gb, cameras)
            return

        self.open_writer()


def enumerate_by_serial():
    """연결된 카메라를 한 번 열거해 {시리얼: DeviceInfo} 로 돌려준다."""
    devices = pylon.TlFactory.GetInstance().EnumerateDevices()
    return {d.GetSerialNumber(): d for d in devices}