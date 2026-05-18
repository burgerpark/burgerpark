"""Live analysis via TopView window capture.

TC001 Max isn't a standard UVC camera so OpenCV can't open it directly.
Instead we let TopView own the camera, capture its window, and run our
colour-bar LUT pipeline on the captured pixels.

Run on the Windows PC (TopView open + showing the live feed):
    pip install mss pygetwindow opencv-python numpy
    python live_screen.py

Keys in the live window:
    q : quit
    r : re-detect the colour bar (use after resizing TopView)
    s : save the current ROI to ./data/probe/
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

try:
    import mss
    import pygetwindow as gw
except ImportError as e:
    print(f"missing dependency: {e}")
    print("install with: pip install mss pygetwindow")
    sys.exit(1)


WINDOW_TITLE_SUBSTRING = "TopView"
LUT_BITS = 5
OUT = Path(__file__).resolve().parent / "data" / "probe"
OUT.mkdir(parents=True, exist_ok=True)


@dataclass
class ColorBar:
    x0: int
    x1: int
    y0: int
    y1: int
    lut_bgr: np.ndarray
    lut_norm: np.ndarray


def find_window():
    for w in gw.getAllWindows():
        if WINDOW_TITLE_SUBSTRING.lower() in w.title.lower() and w.width > 200:
            return w
    return None


def capture(sct, win):
    bbox = {"left": int(win.left), "top": int(win.top),
            "width": int(win.width), "height": int(win.height)}
    raw = np.array(sct.grab(bbox))
    return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)


def find_colorbar(frame_bgr):
    H, W, _ = frame_bgr.shape
    rx0 = int(W * 0.75)
    search = frame_bgr[:, rx0:W]
    sat = cv2.cvtColor(search, cv2.COLOR_BGR2HSV)[:, :, 1].astype(np.float32)
    score = sat.mean(axis=0) * sat.std(axis=0)
    if score.max() < 1.0:
        return None
    bar_xc = int(np.argmax(score)) + rx0

    half = 14
    x0, x1 = max(bar_xc - half, 0), min(bar_xc + half, W)
    column = frame_bgr[:, x0:x1].mean(axis=1)
    col_sat = cv2.cvtColor(column.astype(np.uint8)[None, :, :], cv2.COLOR_BGR2HSV)[0, :, 1]
    ys = np.flatnonzero(col_sat > 40)
    if ys.size < 50:
        return None
    y0, y1 = int(ys[0]), int(ys[-1])

    lut_bgr = frame_bgr[y0:y1, x0:x1].mean(axis=1).astype(np.float32)
    lut_norm = np.linspace(1.0, 0.0, lut_bgr.shape[0], dtype=np.float32)
    return ColorBar(x0, x1, y0, y1, lut_bgr, lut_norm)


def build_qlut(cb, bits=LUT_BITS):
    levels = 1 << bits
    step = 256 // levels
    centres = (np.arange(levels) * step + step // 2).astype(np.float32)
    bb, gg, rr = np.meshgrid(centres, centres, centres, indexing="ij")
    all_bgr = np.stack([bb, gg, rr], axis=-1).reshape(-1, 3)

    out = np.empty(all_bgr.shape[0], dtype=np.float32)
    chunk = 8192
    for i in range(0, all_bgr.shape[0], chunk):
        d = all_bgr[i : i + chunk, None, :] - cb.lut_bgr[None, :, :]
        d2 = (d * d).sum(axis=2)
        out[i : i + chunk] = cb.lut_norm[np.argmin(d2, axis=1)]
    return out.reshape(levels, levels, levels)


def lut_apply(frame_bgr, qlut, bits=LUT_BITS):
    shift = 8 - bits
    b = frame_bgr[..., 0] >> shift
    g = frame_bgr[..., 1] >> shift
    r = frame_bgr[..., 2] >> shift
    return qlut[b, g, r]


def detect_camera_roi(frame_bgr, cb):
    """Pick the rectangle to the left of the colour bar that holds the camera feed."""
    H, W, _ = frame_bgr.shape
    x1 = max(cb.x0 - 8, 1)
    x0 = int(W * 0.18)
    y0 = int(H * 0.08)
    y1 = int(H * 0.92)
    if x1 <= x0:
        x0 = max(int(W * 0.05), 0)
    return x0, x1, y0, y1


def segment_patties(norm_t, hot_q=0.55, cold_q=0.45, min_area_frac=0.003):
    H, W = norm_t.shape
    min_area = max(int(H * W * min_area_frac), 200)
    hot = norm_t > hot_q
    if hot.mean() < 0.05:
        return np.zeros_like(norm_t, dtype=bool)

    cool = (norm_t < cold_q).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cool = cv2.morphologyEx(cool, cv2.MORPH_OPEN, k)
    cool = cv2.morphologyEx(cool, cv2.MORPH_CLOSE, k)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(cool, connectivity=8)
    keep = np.zeros_like(cool, dtype=bool)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area:
            continue
        if x <= 2 or y <= 2 or x + w >= W - 2 or y + h >= H - 2:
            continue
        keep |= (labels == i)
    return keep


def main():
    print(f"looking for window containing '{WINDOW_TITLE_SUBSTRING}' ...")
    win = find_window()
    if win is None:
        print(f"❌ no window with title containing '{WINDOW_TITLE_SUBSTRING}'.")
        print("   open TopView first, show the live camera feed, then re-run.")
        return 1
    print(f"✅ {win.title}  pos=({win.left},{win.top})  size={win.width}x{win.height}")

    sct = mss.mss()
    cb = None
    qlut = None
    roi = None

    print("\nstarting capture. q=quit, r=re-detect colour bar, s=save frame")
    out_win = "burgerpark — live (via TopView capture)"
    cv2.namedWindow(out_win, cv2.WINDOW_NORMAL)

    n_frames = 0
    last_fps_t = time.time()
    saved = 0

    while True:
        try:
            frame = capture(sct, win)
        except Exception as e:
            print(f"capture error: {e}")
            time.sleep(0.5)
            continue

        if cb is None:
            cb = find_colorbar(frame)
            if cb is None:
                cv2.putText(frame, "colour bar not detected, retrying...",
                            (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                cv2.imshow(out_win, frame)
                if (cv2.waitKey(200) & 0xFF) == ord("q"):
                    break
                continue
            print(f"colour bar: x={cb.x0}-{cb.x1}  y={cb.y0}-{cb.y1}  L={len(cb.lut_norm)}")
            qlut = build_qlut(cb)
            roi = detect_camera_roi(frame, cb)
            print(f"camera ROI: x={roi[0]}-{roi[1]}  y={roi[2]}-{roi[3]}")

        x0, x1, y0, y1 = roi
        sub = frame[y0:y1, x0:x1]
        if sub.size == 0:
            cb = None
            continue
        norm = lut_apply(sub, qlut)
        mask = segment_patties(norm)

        vis = sub.copy()
        if mask.any():
            overlay = vis.copy()
            overlay[mask] = (0, 255, 0)
            vis = cv2.addWeighted(vis, 0.55, overlay, 0.45, 0)
            mean_t = float(norm[mask].mean())
            area = int(mask.sum())
            label = f"patty mean(norm)={mean_t:.2f}  area={area}px  n={int(mask.sum() > 0)}"
        else:
            label = "no patty detected"

        n_frames += 1
        now = time.time()
        fps = n_frames / (now - last_fps_t + 1e-6) if now - last_fps_t > 0.1 else 0
        cv2.rectangle(vis, (0, 0), (vis.shape[1], 32), (0, 0, 0), -1)
        cv2.putText(vis, label, (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(vis, f"{fps:4.1f} fps",
                    (vis.shape[1] - 90, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)
        if now - last_fps_t > 2.0:
            last_fps_t, n_frames = now, 0

        cv2.imshow(out_win, vis)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord("r"):
            cb = None
            print("re-detecting colour bar...")
        if k == ord("s"):
            saved += 1
            p = OUT / f"live_{int(time.time())}_{saved:02d}.png"
            cv2.imwrite(str(p), vis)
            print(f"saved {p}")

    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
