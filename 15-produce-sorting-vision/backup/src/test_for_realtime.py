"""Standalone realtime benchmark. Copy this single file to the Orin and run it there.

Deliberately depends on nothing else in this repo so it can be dropped onto the target
box on its own.

Two modes, and the difference matters:

  throughput (default)  -- pull frames as fast as they decode. Answers "how many frames
                           per second can this box do at all".
  --rate N              -- feed frames on a wall clock from a separate thread and keep
                           only the newest one. Answers "at N fps from the cameras, does
                           it keep up, and how stale is a decision when it lands". This
                           is the number that decides whether the rig works.

Timing notes that change the answer on Jetson:
  * CUDA is asynchronous, so wall-clock around a predict call measures the launch unless
    you synchronize. Every stage below synchronizes explicitly.
  * The first inferences build kernels and are several seconds slow. Those are warmup and
    are excluded, not averaged in.
  * Latency is reported per stage, because on Orin video decode often costs more than the
    model does, and a single fused number hides that.
  * Results are also split into quarters. A box that is fine for ten seconds and throttles
    after two minutes looks identical to a healthy one unless you compare start to end.

    python test_for_realtime.py --source test.mp4
    python test_for_realtime.py --source test.mp4 --rate 60 --duration 300
    python test_for_realtime.py --source 0 --camera --display
    python test_for_realtime.py --weights best.engine --half        # TensorRT on Orin
"""
import os
import csv
import glob
import time
import queue
import argparse
import platform
import threading

import cv2
import numpy as np

try:
    import torch
except ImportError:                       # ultralytics pulls torch in; guard anyway
    torch = None

from ultralytics import YOLO

EXTS = (".png", ".jpg", ".jpeg", ".bmp")


# --------------------------------------------------------------------------- platform

def describe_host():
    """Report what we are actually measuring on -- Jetson model, power mode, device."""
    lines = [f"python   {platform.python_version()}  {platform.machine()}"]

    model_path = "/proc/device-tree/model"
    if os.path.exists(model_path):
        with open(model_path, "rb") as f:
            lines.append(f"board    {f.read().decode(errors='ignore').strip(chr(0))}")

    # Power mode caps clocks hard on Jetson; a benchmark taken in 15W mode says nothing
    # about 60W mode. Worth printing rather than silently varying between runs.
    for cmd in ("nvpmodel -q 2>/dev/null | tr '\\n' ' '",):
        out = os.popen(cmd).read().strip()
        if out:
            lines.append(f"power    {out}")

    if torch is not None:
        lines.append(f"torch    {torch.__version__}  cuda={torch.cuda.is_available()}")
        if torch.cuda.is_available():
            lines.append(f"device   {torch.cuda.get_device_name(0)}")
    return "\n".join(lines)


def sync():
    if torch is not None and torch.cuda.is_available():
        torch.cuda.synchronize()


def pct(xs, q):
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(int(len(s) * q), len(s) - 1)]


# ----------------------------------------------------------------------------- source

class LatestSlot:
    """One-frame mailbox: a new frame replaces an unread one rather than queueing.

    Under overload this bounds latency at roughly one inference and loses frames instead.
    A Queue would keep every frame and let staleness grow without limit, which for a
    conveyor means acting on a potato that has already gone past.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._item = None
        self._ready = threading.Event()
        self.dropped = 0

    def put(self, item):
        with self._lock:
            if self._item is not None:
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


def frame_reader(source, camera=False, loop=False):
    """Yield BGR frames from a capture device, a video file, or a directory of stills."""
    if camera:
        cap = cv2.VideoCapture(int(source) if str(source).isdigit() else source)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            raise SystemExit(f"cannot open capture device {source}")
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame
        cap.release()
        return

    while True:
        if os.path.isdir(source):
            for p in sorted(p for p in glob.glob(os.path.join(source, "*"))
                            if p.lower().endswith(EXTS)):
                frame = cv2.imread(p)
                if frame is not None:
                    yield frame
        else:
            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                raise SystemExit(f"cannot open {source}")
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                yield frame
            cap.release()
        if not loop:
            return


class PacedProducer(threading.Thread):
    """Emit frames on a wall clock, mimicking cameras that will not wait for us.

    Decoding runs one step ahead of the pacing so that decode cost does not distort the
    arrival times -- otherwise a slow PNG decoder makes the model look slow.
    """

    def __init__(self, source, slot, rate, camera=False, loop=True):
        super().__init__(daemon=True)
        self.slot, self.rate = slot, rate
        self.stop_flag = threading.Event()
        self.emitted = 0
        self.late = 0
        self._buffer = queue.Queue(maxsize=8)
        self._src = (source, camera, loop)

    def _decode_loop(self):
        try:
            for frame in frame_reader(*self._src):
                if self.stop_flag.is_set():
                    break
                self._buffer.put(frame)
        finally:
            self._buffer.put(None)

    def run(self):
        self._decoder = threading.Thread(target=self._decode_loop, daemon=True)
        self._decoder.start()
        interval = 1.0 / self.rate
        start = time.perf_counter()
        while not self.stop_flag.is_set():
            frame = self._buffer.get()
            if frame is None:
                break
            target = start + self.emitted * interval
            now = time.perf_counter()
            if now < target:
                time.sleep(target - now)
            elif now - target > interval:
                self.late += 1
            self.slot.put((time.perf_counter(), frame))
            self.emitted += 1

    def stop(self):
        self.stop_flag.set()
        while not self._buffer.empty():
            try:
                self._buffer.get_nowait()
            except queue.Empty:
                break
        d = getattr(self, "_decoder", None)
        if d is not None:
            d.join(timeout=2.0)


# -------------------------------------------------------------------------- benchmark

def predict_kwargs(args):
    """Only pass half when it is on -- passing half=False still trips a deprecation warning
    on every single call, which floods the log during a long run."""
    kw = {"imgsz": args.imgsz, "conf": args.conf, "verbose": False}
    if args.half:
        kw["half"] = True
    return kw


def warmup(model, kw, shape, n=10):
    """Build kernels before the clock starts. On Orin the first call can take seconds."""
    blank = np.zeros(shape, dtype=np.uint8)
    t0 = time.perf_counter()
    for _ in range(n):
        model.predict(blank, **kw)
    sync()
    return time.perf_counter() - t0


def run(args):
    print(describe_host())
    print()

    model = YOLO(args.weights)

    # Probe one frame for the real resolution so warmup uses the right shape.
    probe = next(frame_reader(args.source, args.camera, loop=False), None)
    if probe is None:
        raise SystemExit(f"no frames from {args.source}")
    print(f"source   {args.source}  {probe.shape[1]}x{probe.shape[0]}")
    print(f"weights  {args.weights}   imgsz={args.imgsz} half={args.half}")

    kw = predict_kwargs(args)
    took = warmup(model, kw, probe.shape, args.warmup)
    print(f"warmup   {args.warmup} iters in {took:.2f} s  "
          f"({took/args.warmup*1000:.0f} ms/iter, excluded from results)\n")

    decode_ms, infer_ms, post_ms, render_ms, e2e_ms = [], [], [], [], []
    rows = []
    n = hits = 0
    writer = None
    slot = producer = None
    t_start = time.perf_counter()

    if args.rate:
        slot = LatestSlot()
        producer = PacedProducer(args.source, slot, args.rate, args.camera, loop=True)
        producer.start()
        print(f"paced at {args.rate} fps (latest-frame-wins)\n")
        source_iter = None
    else:
        source_iter = frame_reader(args.source, args.camera, args.loop)
        print("throughput mode (no pacing)\n")

    try:
        while True:
            if args.duration and time.perf_counter() - t_start > args.duration:
                break
            if args.max_frames and n >= args.max_frames:
                break

            if args.rate:
                item = slot.get(timeout=2.0)
                if item is None:
                    if not producer.is_alive():
                        break
                    continue
                captured, frame = item
                decode_ms.append(0.0)          # decode happened in the producer thread
            else:
                t = time.perf_counter()
                frame = next(source_iter, None)
                if frame is None:
                    break
                sync()
                decode_ms.append((time.perf_counter() - t) * 1000)
                captured = time.perf_counter()

            t0 = time.perf_counter()
            results = model.predict(frame, **kw)
            sync()
            t1 = time.perf_counter()

            r = results[0]
            n_box = len(r.boxes)
            confs = [float(c) for c in r.boxes.conf]
            sync()
            t2 = time.perf_counter()

            if args.display or args.out:
                vis = r.plot()
                cv2.putText(vis, f"{(t1-t0)*1000:.1f} ms  potato {n_box}",
                            (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                if args.out and writer is None:
                    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
                    h, w = vis.shape[:2]
                    writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"),
                                             args.rate or 30, (w, h))
                if writer:
                    writer.write(vis)
                if args.display:
                    cv2.imshow("realtime", vis)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
            t3 = time.perf_counter()

            infer_ms.append((t1 - t0) * 1000)
            post_ms.append((t2 - t1) * 1000)
            render_ms.append((t3 - t2) * 1000)
            e2e_ms.append((t3 - captured) * 1000)
            hits += n_box > 0
            n += 1
            rows.append([n - 1, int(n_box > 0), n_box,
                         round(max(confs), 3) if confs else 0.0,
                         round(decode_ms[-1], 2), round(infer_ms[-1], 2),
                         round(post_ms[-1], 2), round(e2e_ms[-1], 2)])

            if n % 100 == 0:
                print(f"  {n} frames  infer p50 {pct(infer_ms, 0.5):.1f} ms", end="\r")
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        if producer:
            producer.stop()
            producer.join(timeout=3.0)
        if writer:
            writer.release()
        if args.display:
            cv2.destroyAllWindows()

    elapsed = time.perf_counter() - t_start
    report(args, n, hits, elapsed, decode_ms, infer_ms, post_ms, render_ms, e2e_ms,
           slot, producer, rows)


def report(args, n, hits, elapsed, decode_ms, infer_ms, post_ms, render_ms, e2e_ms,
           slot, producer, rows):
    if not n:
        print("no frames processed")
        return

    print(" " * 60)
    print(f"elapsed          {elapsed:.1f} s")
    print(f"frames processed {n}")
    if producer:
        emitted = producer.emitted or 1
        print(f"frames emitted   {emitted}")
        print(f"frames dropped   {slot.dropped}  ({slot.dropped/emitted*100:.1f}%)")
        print(f"producer late    {producer.late}  (decoder could not hit the target rate)")
    print(f"achieved rate    {n/elapsed:.2f} fps")
    print(f"gpu duty cycle   {sum(infer_ms)/1000/elapsed*100:.1f}%")
    print()

    header = f"{'stage':<10}{'p50':>9}{'p90':>9}{'p95':>9}{'p99':>9}{'max':>9}   (ms)"
    print(header)
    print("-" * len(header))
    for label, xs in (("decode", decode_ms), ("inference", infer_ms),
                      ("postproc", post_ms), ("render", render_ms), ("end2end", e2e_ms)):
        if not any(xs):
            continue
        print(f"{label:<10}{pct(xs,0.5):>9.1f}{pct(xs,0.9):>9.1f}{pct(xs,0.95):>9.1f}"
              f"{pct(xs,0.99):>9.1f}{max(xs):>9.1f}")

    # Thermal / clock drift: a box that throttles looks healthy in a short run.
    if n >= 40:
        q = n // 4
        print("\nquarters (inference p50, ms) -- a rising trend means throttling")
        parts = [pct(infer_ms[i*q:(i+1)*q], 0.5) for i in range(4)]
        print("  " + "  ".join(f"Q{i+1} {v:6.1f}" for i, v in enumerate(parts)))
        if parts[0] > 0:
            drift = (parts[-1] - parts[0]) / parts[0] * 100
            print(f"  drift Q1->Q4: {drift:+.1f}%"
                  + ("   <- investigate" if drift > 15 else ""))

    budget = 1000.0 / args.rate if args.rate else None
    if budget:
        print(f"\nframe budget at {args.rate} fps: {budget:.1f} ms")
        print(f"  inference p95 {pct(infer_ms,0.95):.1f} ms "
              f"({pct(infer_ms,0.95)/budget*100:.0f}% of budget)")
        headroom = budget / pct(infer_ms, 0.95) if pct(infer_ms, 0.95) else 0
        print(f"  headroom {headroom:.2f}x"
              + ("   <- tight" if headroom < 1.5 else ""))

    print(f"\npotato in {hits}/{n} frames")

    if args.csv:
        os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["i", "has_potato", "n_boxes", "max_conf",
                        "decode_ms", "infer_ms", "post_ms", "e2e_ms"])
            w.writerows(rows)
        print(f"wrote {args.csv}")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weights", default=os.path.join(here, "runs", "detect", "potato",
                                                          "weights", "best.pt"),
                        help=".pt, or a .engine built with TensorRT on the Orin itself")
    parser.add_argument("--source", default="test.mp4",
                        help="video file, directory of stills, or device index with --camera")
    parser.add_argument("--camera", action="store_true")
    parser.add_argument("--rate", type=float, default=None,
                        help="feed at N fps with latest-frame-wins; omit for a throughput run")
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--conf", type=float, default=0.05)
    parser.add_argument("--half", action="store_true", help="fp16 -- usually a win on Orin")
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--duration", type=float, default=None, help="stop after N seconds")
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--display", action="store_true", help="needs a GUI; off by default")
    parser.add_argument("--out", default=None, help="write an annotated mp4 here")
    parser.add_argument("--csv", default=None, help="write per-frame timings here")
    args = parser.parse_args()

    run(args)
