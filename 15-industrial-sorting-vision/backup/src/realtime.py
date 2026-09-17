"""Realtime harness: a frame source that does not wait, and a detector that must keep up.

The offline scripts pull frames one at a time, so the pipeline can never fall behind --
cap.read() simply blocks. A camera does not block. If inference is slower than the
capture rate, something has to give, and the choice of what to drop is the whole design:

  * a Queue absorbs the burst, then never recovers -- latency grows without bound and
    you end up making decisions about a item that left the frame seconds ago
  * a single slot holding only the newest frame keeps latency bounded at roughly one
    inference, and the frames you skip are simply never looked at

This uses the single slot, counts what it drops, and reports end-to-end latency
(capture -> decision), not just model time.

    python realtime.py --source ../item_img/raw/25.11.05/normal/SB
    python realtime.py --source ../runs/video/SB/SB_burst03.mp4 --rate 30
    python realtime.py --source 0 --camera          # webcam / capture device
"""
import os
import re
import csv
import glob
import time
import queue
import argparse
import threading
from datetime import datetime

import cv2
from ultralytics import YOLO

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTS = (".png", ".jpg", ".jpeg", ".bmp")
STAMP = re.compile(r"_(\d{8})_(\d{6})_(\d{6})")


def timestamp(path):
    m = STAMP.search(os.path.basename(path))
    if not m:
        return None
    base = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").timestamp()
    return base + int(m.group(3)) / 1e6


class LatestSlot:
    """One-frame mailbox. A new frame overwrites an unread one instead of queueing."""

    def __init__(self):
        self._lock = threading.Lock()
        self._item = None
        self._ready = threading.Event()
        self.dropped = 0

    def put(self, item):
        with self._lock:
            if self._item is not None:      # consumer never got to the previous frame
                self.dropped += 1
            self._item = item
            self._ready.set()

    def get(self, timeout=1.0):
        if not self._ready.wait(timeout):
            return None
        with self._lock:
            item, self._item = self._item, None
            self._ready.clear()
            return item


class ReplaySource(threading.Thread):
    """Replays stills or a video at wall-clock rate, dropping nothing on its own side.

    Decoding happens here, one step ahead of the pacing, because PNG decode costs more
    than inference does -- doing it inline would measure the harness, not the model.
    """

    def __init__(self, source, slot, rate=None, loop=False):
        super().__init__(daemon=True)
        self.slot = slot
        self.rate = rate
        self.loop = loop
        self.stop_flag = threading.Event()
        self.emitted = 0
        self.late = 0                        # producer could not hit its own schedule
        self.items, self.native_rate = self._plan(source)

    def _plan(self, source):
        if os.path.isdir(source):
            paths = sorted((p for p in glob.glob(os.path.join(source, "*"))
                            if p.lower().endswith(EXTS)), key=lambda p: timestamp(p) or 0)
            times = [timestamp(p) for p in paths]
            if len(times) > 2 and all(t is not None for t in times):
                deltas = sorted(b - a for a, b in zip(times, times[1:]))
                native = 1.0 / deltas[len(deltas) // 2]
            else:
                native = 10.0
            return paths, native
        cap = cv2.VideoCapture(source)
        native = cap.get(cv2.CAP_PROP_FPS) or 10.0
        cap.release()
        return source, native

    def _frames(self):
        """Yield decoded frames, from a directory of stills or a video file."""
        if isinstance(self.items, list):
            for p in self.items:
                frame = cv2.imread(p)
                if frame is not None:
                    yield frame
        else:
            cap = cv2.VideoCapture(self.items)
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                yield frame
            cap.release()

    def run(self):
        rate = self.rate or self.native_rate
        interval = 1.0 / rate

        # Decode ahead of the clock so pacing is not distorted by decode cost.
        buffer = queue.Queue(maxsize=8)

        def decoder():
            while not self.stop_flag.is_set():
                for frame in self._frames():
                    if self.stop_flag.is_set():
                        return
                    buffer.put(frame)
                if not self.loop:
                    break
            buffer.put(None)

        self._decoder = threading.Thread(target=decoder, daemon=True)
        self._decoder.start()
        self._buffer = buffer

        start = time.perf_counter()
        while not self.stop_flag.is_set():
            frame = buffer.get()
            if frame is None:
                break
            target = start + self.emitted * interval
            now = time.perf_counter()
            if now < target:
                time.sleep(target - now)
            elif now - target > interval:
                self.late += 1               # decoder fell behind the requested rate
            self.slot.put((time.perf_counter(), frame))
            self.emitted += 1

    def stop(self):
        self.stop_flag.set()
        # Unblock the decoder if it is parked on a full buffer, or it never sees the flag.
        buffer = getattr(self, "_buffer", None)
        if buffer is not None:
            while not buffer.empty():
                try:
                    buffer.get_nowait()
                except queue.Empty:
                    break
        # Let the decoder finish its current imread; killing it mid-decode at interpreter
        # shutdown aborts the process.
        decoder = getattr(self, "_decoder", None)
        if decoder is not None:
            decoder.join(timeout=2.0)


class CameraSource(threading.Thread):
    """Live capture. Grabs as fast as the device allows and always publishes the newest.

    For the Basler rig, swap cv2.VideoCapture for pypylon and keep the rest -- the
    contract is just 'put (capture_time, frame) into the slot, never block on the consumer'.
    """

    def __init__(self, index, slot, width=None, height=None):
        super().__init__(daemon=True)
        self.slot = slot
        self.stop_flag = threading.Event()
        self.emitted = 0
        self.cap = cv2.VideoCapture(int(index) if str(index).isdigit() else index)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)     # keep the driver from queueing too
        if width:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not self.cap.isOpened():
            raise SystemExit(f"cannot open capture device {index}")
        self.native_rate = self.cap.get(cv2.CAP_PROP_FPS) or 0.0
        self.late = 0

    def run(self):
        while not self.stop_flag.is_set():
            ok, frame = self.cap.read()
            if not ok:
                break
            self.slot.put((time.perf_counter(), frame))
            self.emitted += 1
        self.cap.release()

    def stop(self):
        self.stop_flag.set()


def run(source, weights, rate=None, conf=0.05, imgsz=1280, camera=False, loop=False,
        duration=None, out_dir=None, display=False):
    slot = LatestSlot()
    producer = (CameraSource(source, slot) if camera
                else ReplaySource(source, slot, rate=rate, loop=loop))

    model = YOLO(weights)

    # Warm up before the producer starts. Loading weights and building CUDA kernels takes
    # ~2 s; doing it inside the loop stalls the first frame and makes the producer look
    # like it overran, when nothing was actually late.
    import numpy as np
    warm = np.zeros((1024, 1280, 3), dtype=np.uint8)
    for _ in range(3):
        model.predict(warm, imgsz=imgsz, conf=conf, verbose=False)

    writer = None
    rows = []
    e2e, infer = [], []
    consumed = hits = 0
    idle_timeouts = 0

    producer.start()
    print(f"source rate: {producer.native_rate:.2f} fps"
          f"{'' if rate is None else f' (replaying at {rate:.2f} fps)'}")
    print("running... ctrl-c to stop\n")

    t_start = time.perf_counter()
    try:
        while True:
            if duration and time.perf_counter() - t_start > duration:
                break
            item = slot.get(timeout=1.0)
            if item is None:
                idle_timeouts += 1
                if not producer.is_alive():
                    break
                continue
            captured, frame = item

            t0 = time.perf_counter()
            result = model.predict(frame, imgsz=imgsz, conf=conf, verbose=False)[0]
            t1 = time.perf_counter()

            n = len(result.boxes)
            confs = [float(c) for c in result.boxes.conf]
            hits += n > 0
            consumed += 1
            infer.append((t1 - t0) * 1000)
            e2e.append((t1 - captured) * 1000)
            rows.append([consumed - 1, round(captured - t_start, 4), int(n > 0), n,
                         round(max(confs), 3) if confs else 0.0,
                         round(infer[-1], 2), round(e2e[-1], 2)])

            if out_dir or display:
                vis = result.plot()
                cv2.putText(vis, f"e2e {e2e[-1]:5.1f} ms | drop {slot.dropped} | item {n}",
                            (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                if out_dir and writer is None:
                    os.makedirs(out_dir, exist_ok=True)
                    h, w = vis.shape[:2]
                    writer = cv2.VideoWriter(os.path.join(out_dir, "realtime.mp4"),
                                             cv2.VideoWriter_fourcc(*"mp4v"),
                                             rate or producer.native_rate or 10.0, (w, h))
                if writer:
                    writer.write(vis)
                if display:
                    cv2.imshow("realtime", vis)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        producer.stop()
        producer.join(timeout=3.0)
        if writer:
            writer.release()
        if display:
            cv2.destroyAllWindows()

    elapsed = time.perf_counter() - t_start
    emitted = producer.emitted

    def pct(xs, q):
        return sorted(xs)[min(int(len(xs) * q), len(xs) - 1)] if xs else 0.0

    print(f"\nelapsed            {elapsed:.1f} s")
    print(f"frames emitted     {emitted}")
    print(f"frames processed   {consumed}"
          f"  ({consumed/emitted*100:.1f}%)" if emitted else "")
    print(f"frames dropped     {slot.dropped}"
          f"  ({slot.dropped/emitted*100:.1f}%)" if emitted else "")
    print(f"producer late      {producer.late}   (decoder could not hit target rate)")
    print(f"achieved rate      {consumed/elapsed:.2f} fps")
    print(f"inference   p50 {pct(infer,0.5):6.1f}  p95 {pct(infer,0.95):6.1f}  "
          f"max {max(infer) if infer else 0:6.1f} ms")
    print(f"end-to-end  p50 {pct(e2e,0.5):6.1f}  p95 {pct(e2e,0.95):6.1f}  "
          f"max {max(e2e) if e2e else 0:6.1f} ms")
    print(f"gpu duty cycle     {sum(infer)/1000/elapsed*100:.1f}%")
    print(f"item in          {hits}/{consumed} processed frames")

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        csv_path = os.path.join(out_dir, "realtime.csv")
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["i", "t_capture", "has_item", "n_boxes", "max_conf",
                        "infer_ms", "e2e_ms"])
            w.writerows(rows)
        print(f"\nwrote {csv_path}")
    return consumed, slot.dropped, e2e


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True,
                        help="frames dir, video file, or capture index with --camera")
    parser.add_argument("--weights", default=os.path.join(REPO, "src", "runs", "detect",
                                                          "item", "weights", "best.pt"))
    parser.add_argument("--camera", action="store_true", help="treat source as a live device")
    parser.add_argument("--rate", type=float, default=None,
                        help="replay fps; omit to use the captured rate, raise it to stress test")
    parser.add_argument("--conf", type=float, default=0.05)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--loop", action="store_true", help="repeat the source")
    parser.add_argument("--duration", type=float, default=None, help="stop after N seconds")
    parser.add_argument("--out", default=None, help="write annotated mp4 + csv here")
    parser.add_argument("--display", action="store_true", help="live window (needs a GUI)")
    args = parser.parse_args()

    run(args.source, args.weights, args.rate, args.conf, args.imgsz,
        args.camera, args.loop, args.duration, args.out, args.display)
