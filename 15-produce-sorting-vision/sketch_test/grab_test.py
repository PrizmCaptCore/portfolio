"""Smoke test: broadcast discovery, direct-IP open, and a 3-frame grab."""
from pypylon import pylon
import os
import sys

IP = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CAMERA_IP", "192.168.0.2")

tlf = pylon.TlFactory.GetInstance()

print("--- enumeration test (broadcast discovery) ---")
devs = tlf.EnumerateDevices()
print(f"discovered {len(devs)} device(s)")
for d in devs:
    print(" ", d.GetModelName(), d.GetIpAddress())

print(f"--- direct-IP open test ({IP}) ---")
di = pylon.DeviceInfo()
di.SetDeviceClass("BaslerGigE")
di.SetIpAddress(IP)
try:
    cam = pylon.InstantCamera(tlf.CreateDevice(di))
    cam.Open()
    info = cam.GetDeviceInfo()
    print("OPEN OK:", info.GetModelName(), "SN", info.GetSerialNumber())
except Exception as e:
    print("OPEN FAILED:", e)
    sys.exit(1)

print("--- grab test (GVSP stream) ---")
try:
    cam.StartGrabbingMax(3)
    n = 0
    while cam.IsGrabbing():
        res = cam.RetrieveResult(5000, pylon.TimeoutHandling_Return)
        if res and res.GrabSucceeded():
            n += 1
            print(f"GRAB OK #{n}: {res.Width}x{res.Height}")
            res.Release()
        elif res:
            print(f"GRAB FAILED: code={res.GetErrorCode():#x} {res.GetErrorDescription()}")
            break
        else:
            print("GRAB FAILED: no result within 5 s (stream packets never arrived)")
            break
except Exception as e:
    print("GRAB FAILED (exception):", e)
finally:
    cam.Close()
