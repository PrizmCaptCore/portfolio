"""Live viewer: watch what both cameras are seeing, straight off the grab loop.

This is the eyeball check for the realtime path -- same grab (LatestImageOnly) and same
debayer (BayerRG2BGR) the inference loop will use, with a browser instead of a model. If
items look right here, the exact same numpy frame is what the detector gets.

    python live_view.py     # then open http://localhost:8081 in the Windows browser
                            # (/ shows both panes side by side; /stream/0, /stream/1)

The page always shows NUM_SLOTS panes; cameras hot-plug behind them. A manager thread
re-enumerates every RESCAN_S seconds and fills empty slots first-seen-first-bound: a
brand-new camera takes the first never-used slot, and once a serial number has lived in
a slot it returns to that same slot after a replug (session-sticky, zero config). A pane
whose camera drops shows a "disconnected" card instead of freezing on the last frame.
Expect the drop to register only after the GigE heartbeat expires (a few seconds), and
a PoE-powered camera to need ~10 s after replug -- the cable is also its power.

A spare camera can arrive on any IP band: the manager also runs adopt_cameras.py's
sweep every few ticks, rewriting stray-band Baslers onto the camera link subnet, after
which normal enumeration picks them up. See adopt_cameras.py for the how and why.

Per-pane controls: an exposure slider (5 ms up to the sensor max, log scale) and a
mode button toggling Bayer8@30fps (untouched mosaic -- the model pipeline) against
PGI@15fps (in-camera 5x5 debayer/denoise/sharpen shipped as YUV422). Both modes cost
the same ~39 MB/s per camera, so any mix of panes fits the shared link.

One grab thread per connected camera, each publishing JPEGs into its slot's Hub; the
HTTP handlers only ever read. Ctrl-C stops everything cleanly.

Bandwidth: the two cameras share one 1GbE link, so 30 fps each (~39 MB/s per camera)
plus GevSCPD=2500 to interleave their packet bursts. Much past 40 fps per camera the
link oversubscribes, and that shows up as failed grabs, not a polite error.

Run inside the item_test env. cv2's Qt plugin needs libSM/libICE, which live in the
conda env's lib dir but off the loader's search path -- the preload below covers that, so
no LD_LIBRARY_PATH is needed.
"""
import json
import os
import sys
import time
import ctypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_ENV_LIB = os.path.join(sys.prefix, "lib")
for _lib in ("libICE.so.6", "libSM.so.6"):
    _p = os.path.join(_ENV_LIB, _lib)
    if os.path.exists(_p):
        ctypes.CDLL(_p, mode=ctypes.RTLD_GLOBAL)
_FONTS = "/usr/share/fonts/truetype/dejavu"
if os.path.isdir(_FONTS):
    os.environ.setdefault("QT_QPA_FONTDIR", _FONTS)

import cv2
import numpy as np
from pypylon import pylon, genicam

try:
    from adopt_cameras import adopt_foreign   # pulls stray-band cameras into ours
except ImportError:
    adopt_foreign = None

NUM_SLOTS = 2         # panes on the page; fixed no matter what is plugged in
DURATION = 0          # seconds; 0 = run until ctrl-c
PORT = 8081
RESCAN_S = 1.5        # manager re-enumeration period (floor on hot-plug latency)
MIN_EXP_US = 5000.0   # slider floor; ceiling is the sensor max, read per camera

# Per-pane exposure slider: log scale from MIN_EXP_US to the sensor max, applied
# live between frames. Past ~33 ms the frame period stretches, so fps sinks
# below the 30 fps cap -- that is the camera being honest, not a bug.
SLIDER_JS = """
const MN = 5000;
for (let i = 0; i < __N__; i++) {
  const s = document.getElementById('s' + i), v = document.getElementById('v' + i);
  let mx = 1000000, t = null;
  const us = () => MN * Math.pow(mx / MN, s.value / 1000);
  const show = (x) => { v.textContent = (x / 1000).toFixed(1) + ' ms'; };
  fetch('/exposure/' + i).then(r => r.json()).then(j => {
    if (j.max) mx = j.max;
    if (j.cur) { s.value = Math.round(1000 * Math.log(j.cur / MN) / Math.log(mx / MN)); show(j.cur); }
  });
  s.oninput = () => {
    show(us());
    if (!t) t = setTimeout(() => { t = null; fetch('/exposure/' + i + '?us=' + Math.round(us())); }, 150);
  };
  s.onchange = () => fetch('/exposure/' + i + '?us=' + Math.round(us()));
  const mbtn = document.getElementById('m' + i);
  const mref = () => fetch('/mode/' + i).then(r => r.json()).then(j => {
    mbtn.textContent = (j.cur === 'pgi') ? 'PGI 15fps' : 'Bayer 30fps';
    mbtn.disabled = (j.want !== j.cur);       // greyed while the switch is in flight
  });
  mbtn.onclick = () => {
    const next = mbtn.textContent.startsWith('PGI') ? 'bayer' : 'pgi';
    fetch('/mode/' + i + '?m=' + next).then(() => setTimeout(mref, 500));
  };
  mref();
  setInterval(mref, 2000);
  const ab = document.getElementById('a' + i);
  const aref = () => fetch('/auto/' + i).then(r => r.json()).then(j => {
    ab.checked = !!j.cur;
    s.disabled = !!j.cur;                     // auto owns exposure while on
  });
  ab.onchange = () =>
    fetch('/auto/' + i + '?on=' + (ab.checked ? 1 : 0)).then(() => setTimeout(aref, 400));
  aref();
  setInterval(aref, 2000);
}
"""


class Hub:
    """Latest-JPEG mailbox; stream handlers wait for the next publish."""

    def __init__(self):
        self.cond = threading.Condition()
        self.jpg = None
        self.n = 0

    def publish(self, jpg):
        with self.cond:
            self.jpg, self.n = jpg, self.n + 1
            self.cond.notify_all()

    def next(self, seen):
        with self.cond:
            self.cond.wait_for(lambda: self.n != seen, timeout=2.0)
            return self.jpg, self.n


class Slot:
    """One fixed pane. bound_sn is session-sticky: the first camera assigned here
    keeps coming back here after a replug. Only the manager thread writes fields."""

    def __init__(self, idx):
        self.idx = idx
        self.hub = Hub()
        self.bound_sn = None
        self.thread = None
        self.exp_want = None     # slider request (us); grab thread applies it
        self.exp_cur = None      # last value actually on the camera
        self.exp_max = None      # sensor max, read at open
        self.mode_want = "bayer"  # pane button request: "bayer" | "pgi"
        self.mode_cur = None     # mode actually running on the camera
        self.auto_want = False   # pane checkbox: camera-side auto exp/gain/WB
        self.auto_cur = None     # auto state actually on the camera

    def busy(self):
        return self.thread is not None and self.thread.is_alive()


def status_jpg(idx, msg, color):
    """Full-size status card so the pane keeps its geometry with no camera behind it."""
    img = np.zeros((1024, 1280, 3), np.uint8)
    cv2.putText(img, f"cam{idx}: {msg}", (60, 512),
                cv2.FONT_HERSHEY_SIMPLEX, 1.4, color, 3)
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


def open_camera(dev_info):
    cam = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateDevice(dev_info))
    cam.Open()
    # Two cameras on one link: cap the average rate and spread the packet bursts.
    cam.AcquisitionFrameRateEnable.SetValue(True)
    cam.AcquisitionFrameRateAbs.SetValue(30.1)
    cam.GevSCPD.SetValue(2500)
    return cam


def apply_mode(cam, mode, base_fps):
    """Bayer = the sensor mosaic untouched, debayered on the host (model pipeline).
    PGI = in-camera 5x5 debayer + color anti-aliasing + denoise + sharpen, shipped
    as YUV422 (2 bytes/px), so the rate halves and the per-camera link budget stays
    ~39 MB/s either way. PixelFormat only moves while grabbing is stopped, and the
    PGI nodes only unlock once the format is YUV -- hence the ordering here."""
    if mode == "pgi":
        cam.PixelFormat.SetValue("YUV422Packed")
        cam.DemosaicingMode.SetValue("BaslerPGI")
        cam.NoiseReductionAbs.SetValue(0.0)      # camera defaults: PGI debayer only,
        cam.SharpnessEnhancementAbs.SetValue(1.0)  # no NR / no sharpening
        cam.AcquisitionFrameRateAbs.SetValue(15.0)
    else:
        try:
            cam.DemosaicingMode.SetValue("Simple")   # only writable while YUV
        except genicam.GenericException:
            pass
        cam.PixelFormat.SetValue("BayerBG8")
        cam.AcquisitionFrameRateAbs.SetValue(base_fps)


def set_auto(cam, on):
    """Camera-side full auto (exposure/gain/WB) -- the phone-like mode. These three
    functions are the only autos this model has (NR/sharpness are fixed values).
    Turning auto off keeps the last WB gains (auto-then-lock), drops gain back to
    the floor, and returns exposure to slider control."""
    if on:
        try:
            cam.AutoExposureTimeAbsUpperLimit.SetValue(30000.0)   # keep fps alive
        except genicam.GenericException:
            pass
        cam.ExposureAuto.SetValue("Continuous")
        cam.GainAuto.SetValue("Continuous")
        cam.BalanceWhiteAuto.SetValue("Continuous")
    else:
        cam.ExposureAuto.SetValue("Off")
        cam.GainAuto.SetValue("Off")
        cam.BalanceWhiteAuto.SetValue("Off")
        cam.GainRaw.SetValue(cam.GainRaw.GetMin())


def frames(cam, stop, cvt=cv2.COLOR_BayerRG2BGR):
    """Yield (image_number, bgr) frames until the camera drops or stop is set.

    Basler's BayerBG8 needs cv2.COLOR_BayerRG2BGR, not BayerBG2BGR: Basler names the
    pattern by the sensor's first two pixels (B,G -> BGGR), OpenCV by the 2x2 tile one
    pixel in from the corner -- the two conventions land on opposite names, and the
    matching-looking constant renders people corpse-blue (verified on this camera,
    2026-08-25). If a ROI with an odd x/y offset ever shifts the pattern, fix the
    offset, not this constant.
    """
    cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
    try:
        while not stop.is_set() and cam.IsGrabbing():
            try:
                res = cam.RetrieveResult(2000, pylon.TimeoutHandling_Return)
            except genicam.GenericException:
                break                    # device removed, or StopGrabbing raced us
            if res is None:
                if cam.IsCameraDeviceRemoved():
                    break                # unplugged: heartbeat expired mid-wait
                print("no frame within 2 s (stream stalled?)", flush=True)
                continue
            if not res.GrabSucceeded():
                print(f"grab failed: {res.GetErrorDescription()}", flush=True)
                res.Release()
                continue
            n = res.GetImageNumber()
            bgr = cv2.cvtColor(res.Array, cvt)
            res.Release()
            yield n, bgr
    finally:
        try:
            cam.StopGrabbing()
        except genicam.GenericException:
            pass


def run_slot(slot, dev_info, stop):
    """Own one camera for one plug-in: open, grab into the slot's hub, and on any exit
    publish the disconnected card so the pane can't freeze on a stale frame. The outer
    loop re-applies the capture mode whenever the pane's button asks for the other
    one -- PixelFormat only changes with grabbing stopped, so a switch means leaving
    frames() (which stops grabbing) and re-entering it (~0.5 s blink)."""
    sn = dev_info.GetSerialNumber()
    try:
        cam = open_camera(dev_info)
    except genicam.GenericException as e:
        # Enumerated but gone (or still booting) by the time we opened it; the
        # manager just retries next scan.
        print(f"slot{slot.idx}: open SN {sn} failed: {e}", flush=True)
        return
    print(f"slot{slot.idx}: {dev_info.GetModelName()} SN {sn} "
          f"@ {dev_info.GetIpAddress()} connected", flush=True)
    base_fps = cam.AcquisitionFrameRateAbs.GetValue()
    try:
        slot.exp_max = cam.ExposureTimeAbs.GetMax()
        if slot.exp_want:
            cam.ExposureTimeAbs.SetValue(slot.exp_want)   # slider survives replug
        slot.exp_cur = cam.ExposureTimeAbs.GetValue()
    except genicam.GenericException:
        pass
    shown, t0 = 0, time.perf_counter()
    try:
        while not stop.is_set():
            mode = slot.mode_want
            try:
                apply_mode(cam, mode, base_fps)
            except genicam.GenericException as e:
                print(f"slot{slot.idx}: mode '{mode}' failed: {e}", flush=True)
                break
            slot.mode_cur = mode
            print(f"slot{slot.idx}: mode {mode} "
                  f"({cam.PixelFormat.GetValue()})", flush=True)
            cvt = (cv2.COLOR_YUV2BGR_UYVY if mode == "pgi"
                   else cv2.COLOR_BayerRG2BGR)
            restart = False
            for n, bgr in frames(cam, stop, cvt):
                if slot.mode_want != slot.mode_cur:
                    restart = True
                    break                                 # re-apply with new mode
                if slot.auto_want != slot.auto_cur:
                    try:
                        set_auto(cam, slot.auto_want)
                        slot.auto_cur = slot.auto_want
                        print(f"slot{slot.idx}: auto "
                              f"{'on' if slot.auto_cur else 'off'}", flush=True)
                    except genicam.GenericException:
                        slot.auto_want = slot.auto_cur
                if slot.auto_cur:
                    try:                                  # show what auto chose
                        slot.exp_cur = cam.ExposureTimeAbs.GetValue()
                        slot.exp_want = slot.exp_cur      # slider follows auto
                    except genicam.GenericException:
                        pass
                else:
                    want = slot.exp_want
                    if want and slot.exp_cur and abs(want - slot.exp_cur) >= 1.0:
                        try:
                            cam.ExposureTimeAbs.SetValue(want)
                            slot.exp_cur = cam.ExposureTimeAbs.GetValue()
                        except genicam.GenericException:
                            slot.exp_want = slot.exp_cur  # refused: stop retrying
                shown += 1
                fps = shown / (time.perf_counter() - t0)
                ms = f"  {slot.exp_cur / 1000:.1f}ms" if slot.exp_cur else ""
                tag = ("  PGI" if mode == "pgi" else "") + \
                      ("  AUTO" if slot.auto_cur else "")
                cv2.putText(bgr, f"cam{slot.idx} SN {sn} #{n}  {fps:5.1f} fps{ms}{tag}",
                            (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    slot.hub.publish(buf.tobytes())
            if not restart:
                break                                     # stop, unplug, or error
    finally:
        try:
            cam.Close()
        except genicam.GenericException:
            pass
        slot.mode_cur = None
        slot.auto_cur = None                              # reconnect re-applies
        elapsed = time.perf_counter() - t0
        print(f"slot{slot.idx}: SN {sn} disconnected after {shown} frames "
              f"in {elapsed:.1f} s ({shown / max(elapsed, 1e-9):.1f} fps)", flush=True)
        if not stop.is_set():
            slot.hub.publish(status_jpg(slot.idx, "disconnected", (0, 0, 255)))


def manage_slots(slots, stop):
    """Re-enumerate every RESCAN_S and refill empty slots. Bound serials return to
    their own slot; brand-new serials go to never-bound slots first, then rebind the
    first empty one (camera-swap case). Every few ticks, also sweep for cameras
    sitting on a foreign IP band (a fresh spare, a stray) and adopt them into ours
    -- once adopted they enumerate normally and slot-binding takes over."""
    tlf = pylon.TlFactory.GetInstance()
    tick = 0
    while not stop.is_set():
        tick += 1
        if adopt_foreign and tick % 4 == 1:
            try:
                for ev in adopt_foreign(timeout=1.0):
                    print(f"adopt: {ev}", flush=True)
            except Exception as e:
                print(f"adopt scan failed: {e}", flush=True)
        try:
            present = {d.GetSerialNumber(): d for d in tlf.EnumerateDevices()
                       if d.GetDeviceClass() == "BaslerGigE"}
        except genicam.GenericException:
            present = {}                 # interface down; keep polling
        bound = {s.bound_sn for s in slots if s.bound_sn}
        fresh = [sn for sn in present if sn not in bound]

        empty = [s for s in slots if not s.busy()]
        for slot in empty[:]:            # pass 1: sticky reconnects
            if slot.bound_sn and slot.bound_sn in present:
                _spawn(slot, present[slot.bound_sn], stop)
                empty.remove(slot)
        empty.sort(key=lambda s: s.bound_sn is not None)
        for slot in empty:               # pass 2: new cameras
            if not fresh:
                break
            slot.bound_sn = fresh.pop(0)
            _spawn(slot, present[slot.bound_sn], stop)
        stop.wait(RESCAN_S)


def _spawn(slot, dev_info, stop):
    if stop.is_set():
        return                           # ctrl-c raced the manager's tick
    slot.thread = threading.Thread(target=run_slot, args=(slot, dev_info, stop),
                                   daemon=True)
    slot.thread.start()


def view_http(duration, port):
    """Stream MJPEG over HTTP instead of opening a window. Survives every WSLg failure
    mode because the pixels travel over a socket, not the RDP display channel -- with
    mirrored networking, http://localhost:<port> in the Windows browser lands here."""
    slots = [Slot(i) for i in range(NUM_SLOTS)]
    hubs = [s.hub for s in slots]
    for s in slots:
        s.hub.publish(status_jpg(s.idx, "waiting for camera", (160, 160, 160)))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass                         # keep the terminal to fps lines only

        def do_GET(self):
            if self.path == "/":
                panes = "".join(
                    f"<div style='flex:1;display:flex;flex-direction:column'>"
                    f"<img src='/stream/{i}' style='width:100%'>"
                    f"<div style='color:#ddd;font:13px sans-serif;padding:4px 8px'>"
                    f"exposure <input type='range' id='s{i}' min='0' max='1000' value='0'"
                    f" style='width:45%;vertical-align:middle'> <span id='v{i}'>-</span>"
                    f" <button id='m{i}' style='margin-left:14px'>...</button>"
                    f" <label style='margin-left:10px'>"
                    f"<input type='checkbox' id='a{i}'> auto</label>"
                    f"</div></div>"
                    for i in range(len(hubs)))
                script = SLIDER_JS.replace("__N__", str(len(hubs)))
                body = (f"<body style='margin:0;background:#111;display:flex'>{panes}"
                        f"<script>{script}</script></body>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/exposure/"):
                idx, _, query = self.path[len("/exposure/"):].partition("?")
                try:
                    slot = slots[int(idx)]
                except (ValueError, IndexError):
                    self.send_error(404)
                    return
                if query.startswith("us="):
                    try:
                        us = float(query[3:])
                    except ValueError:
                        self.send_error(400)
                        return
                    slot.exp_want = max(MIN_EXP_US,
                                        min(us, slot.exp_max or 1000000.0))
                body = json.dumps({"cur": slot.exp_cur, "max": slot.exp_max}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/mode/"):
                idx, _, query = self.path[len("/mode/"):].partition("?")
                try:
                    slot = slots[int(idx)]
                except (ValueError, IndexError):
                    self.send_error(404)
                    return
                if query.startswith("m="):
                    if query[2:] not in ("bayer", "pgi"):
                        self.send_error(400)
                        return
                    slot.mode_want = query[2:]
                body = json.dumps({"cur": slot.mode_cur,
                                   "want": slot.mode_want}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/auto/"):
                idx, _, query = self.path[len("/auto/"):].partition("?")
                try:
                    slot = slots[int(idx)]
                except (ValueError, IndexError):
                    self.send_error(404)
                    return
                if query.startswith("on="):
                    slot.auto_want = query[3:] == "1"
                body = json.dumps({"cur": bool(slot.auto_cur),
                                   "want": slot.auto_want}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/stream/"):
                try:
                    hub = hubs[int(self.path.rsplit("/", 1)[1])]
                except (ValueError, IndexError):
                    self.send_error(404)
                    return
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            seen = 0
            try:
                while True:
                    jpg, seen = hub.next(seen)
                    if jpg is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                     b"Content-Length: %d\r\n\r\n" % len(jpg))
                    self.wfile.write(jpg)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                return                   # viewer closed the tab

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"open http://localhost:{port} in the Windows browser (ctrl-c to stop)",
          flush=True)
    print("adopt sweep: " + ("enabled -- foreign-band cameras auto-migrate"
                             if adopt_foreign else
                             "DISABLED -- adopt_cameras.py not importable"),
          flush=True)

    stop = threading.Event()
    manager = threading.Thread(target=manage_slots, args=(slots, stop), daemon=True)
    manager.start()
    try:
        stop.wait(duration if duration else None)
    except KeyboardInterrupt:
        pass
    finally:
        # stop makes each frames() loop and the manager wind down on their own;
        # grab threads close their cameras in run_slot's finally.
        stop.set()
        manager.join(timeout=RESCAN_S + 1.0)
        for s in slots:
            if s.thread:
                s.thread.join(timeout=4.0)
        server.shutdown()


def main():
    view_http(DURATION, PORT)


if __name__ == "__main__":
    main()
