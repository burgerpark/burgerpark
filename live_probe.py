"""Sanity check: can we open the TC001 Max as a UVC camera in Python?

Usage on the Windows PC:
    1. Close TopView first (only one process can hold the camera at a time).
    2. Plug the camera directly into the PC (no extender).
    3. Run:    python live_probe.py
    4. A window will pop up showing whatever the camera streams.
       Press 'q' to quit, 's' to save a frame to ./data/probe/.

What we're looking for in the output:
    - Which device index works (0, 1, 2, ...)
    - Resolution: 256x192 means visual only,
                  256x384 means dual stream (visual + raw temperature data)
    - FPS, format (FOURCC)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

OUT = Path(__file__).resolve().parent / "data" / "probe"
OUT.mkdir(parents=True, exist_ok=True)


def try_open(idx: int, backend: int) -> cv2.VideoCapture | None:
    cap = cv2.VideoCapture(idx, backend)
    if not cap.isOpened():
        cap.release()
        return None
    ok, _ = cap.read()
    if not ok:
        cap.release()
        return None
    return cap


def find_camera() -> tuple[cv2.VideoCapture, int, str] | None:
    backends = [
        (cv2.CAP_DSHOW,  "DirectShow"),
        (cv2.CAP_MSMF,   "Media Foundation"),
        (cv2.CAP_ANY,    "Auto"),
    ]
    for backend, name in backends:
        for idx in range(6):
            cap = try_open(idx, backend)
            if cap is not None:
                return cap, idx, name
    return None


def main() -> int:
    print("scanning device indices 0..5 on DirectShow / MSMF / Auto ...")
    found = find_camera()
    if found is None:
        print("\n❌ no camera opened.")
        print("   - is TopView still running? close it and try again")
        print("   - is the camera plugged directly into the PC (no extender)?")
        return 1

    cap, idx, backend = found
    w  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    fcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fcc_s = "".join(chr((fcc >> 8 * i) & 0xFF) for i in range(4))
    print(f"\n✅ opened: index={idx}  backend={backend}")
    print(f"   resolution = {w} x {h}")
    print(f"   fps        = {fps:.2f}")
    print(f"   fourcc     = {fcc_s!r}  (raw={fcc})")
    print()
    if h == 192:
        print("   shape suggests: VISUAL ONLY stream")
    elif h == 384:
        print("   shape suggests: DUAL stream (top: visual, bottom: 16-bit temperature)")
        print("   → this is the good case, we can recover per-pixel °C")
    else:
        print(f"   unusual height {h} — will inspect content")
    print("\npress 'q' to quit  /  's' to save current frame to ./data/probe/")

    win = "TC001 Max — live probe"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    saved = 0
    t0, n = time.time(), 0
    while True:
        ok, frame = cap.read()
        if not ok:
            print("frame read failed, retrying ...")
            continue
        n += 1
        cv2.imshow(win, frame)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord("s"):
            saved += 1
            out = OUT / f"probe_{int(time.time())}_{saved:02d}.png"
            cv2.imwrite(str(out), frame)
            print(f"   saved {out}  shape={frame.shape}  dtype={frame.dtype}")
    cap.release()
    cv2.destroyAllWindows()
    dt = time.time() - t0
    if dt > 0:
        print(f"\nstreamed {n} frames in {dt:.1f}s  ({n / dt:.1f} fps measured)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
