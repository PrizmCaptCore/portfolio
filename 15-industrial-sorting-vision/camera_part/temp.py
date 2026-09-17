import pypylon.pylon as pylon
import cv2


info = pylon.DeviceInfo()
info.SetDeviceClass("BaslerGigE")
cam = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice(info))
if not cam.GetDeviceInfo().GetModelName().startswith("acA"):
    raise RuntimeError("Camera is not a Basler acA camera")
cam.Open()
cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
while cam.IsGrabbing():
    res = cam.RetrieveResult(1000, pylon.TimeoutHandling_ThrowException)
    if not res.GrabSucceeded():
        res.Release()
        continue
    raw = res.Array                                  # numpy (1024,1280) uint8, Bayer
    frame = cv2.cvtColor(raw, cv2.COLOR_BayerBG2BGR) # numpy (1024,1280,3) uint8, BGR
    res.Release()
