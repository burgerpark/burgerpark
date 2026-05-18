"""Live analysis via TopView window capture, with multi-patty tracking.

TC001 Max isn't a standard UVC camera so OpenCV can't open it directly.
Instead we let TopView own the camera, capture its window, and run our
colour-bar LUT pipeline on the captured pixels.

Unlike TopView (which only supports 3 measurement dots), this script
detects an arbitrary number of patties per frame, assigns each one a
stable ID, and tracks its mean surface temperature and elapsed time.

Two capture modes:
  --visible     (default) cheap GDI screen grab via mss; fast but the
                TopView window must be unobstructed and on-screen.
  --background  PrintWindow API; works even when TopView is covered by
                other windows or sits on a different virtual desktop.
                Requires pywin32. Some GPU-accelerated apps render as
                solid black under this method; if so, fall back to
                --visible.

Run on the Windows PC (TopView open + showing the live feed):
    pip install mss pygetwindow opencv-python numpy pywin32
    python live_screen.py                     # foreground
    python live_screen.py --background        # capture-when-hidden

Keys in the live window:
    q : quit
    r : re-detect the colour bar (use after resizing TopView)
    b : draw the camera-image ROI by hand (mouse drag, ENTER to accept)
    s : save the current ROI to ./data/probe/
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from dataclasses import dataclass, field
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

TRACK_MAX_DIST_PX = 60        # centroid match radius between frames
TRACK_MAX_MISSED = 6          # keep a track alive this many frames after last seen


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


def capture_visible(sct, win):
    """GDI screen grab — fast but only works if the window is on top / visible."""
    bbox = {"left": int(win.left), "top": int(win.top),
            "width": int(win.width), "height": int(win.height)}
    raw = np.array(sct.grab(bbox))
    return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)


# lazily imported so non-Windows / no-pywin32 setups still load the file
_win32gui = None
_win32ui = None


def _ensure_win32():
    global _win32gui, _win32ui
    if _win32gui is None:
        import win32gui as _g, win32ui as _u   # type: ignore
        _win32gui, _win32ui = _g, _u
    return _win32gui, _win32ui


def capture_background(hwnd):
    """PrintWindow capture — works even when the window is hidden behind others.

    Uses PW_RENDERFULLCONTENT (flag 0x2) so Chromium/DirectComposition-style
    apps render their actual contents instead of a black rect.
    """
    win32gui, win32ui = _ensure_win32()
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        raise RuntimeError("window has zero size (minimised?)")

    hdc_window = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hdc_window)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bmp)

    ok = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 0x2)
    info = bmp.GetInfo()
    bits = bmp.GetBitmapBits(True)
    img = np.frombuffer(bits, dtype=np.uint8).reshape(info["bmHeight"], info["bmWidth"], 4)
    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR).copy()  # detach from C buffer

    # cleanup
    win32gui.DeleteObject(bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc_window)

    if not ok:
        raise RuntimeError("PrintWindow returned 0 (unsupported window?)")
    return img


def pick_roi_with_mouse(frame, title="drag camera region — ENTER to accept, ESC to cancel"):
    """Let the user drag a rectangle on the current capture.
    Returns (x0, x1, y0, y1) or None if cancelled."""
    r = cv2.selectROI(title, frame, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow(title)
    x, y, w, h = [int(v) for v in r]
    if w <= 4 or h <= 4:
        return None
    return x, x + w, y, y + h


def find_colorbar(frame_bgr):
    H, W, _ = frame_bgr.shape
    rx0 = int(W * 0.65)                              # search wider right strip
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
    ys = np.flatnonzero(col_sat > 25)                # lower saturation gate
    if ys.size < 30:
        return None
    y0, y1 = int(ys[0]), int(ys[-1])

    lut_bgr = frame_bgr[y0:y1, x0:x1].mean(axis=1).astype(np.float32)
    lut_norm = np.linspace(1.0, 0.0, lut_bgr.shape[0], dtype=np.float32)
    return ColorBar(x0, x1, y0, y1, lut_bgr, lut_norm)


def colorbar_from_rect(frame_bgr, x0, y0, w, h):
    """Build a ColorBar from a user-drawn rectangle (assumes top=hot, bottom=cold)."""
    if w < 3 or h < 20:
        return None
    x1, y1 = x0 + w, y0 + h
    lut_bgr = frame_bgr[y0:y1, x0:x1].mean(axis=1).astype(np.float32)
    lut_norm = np.linspace(1.0, 0.0, lut_bgr.shape[0], dtype=np.float32)
    return ColorBar(x0, x1, y0, y1, lut_bgr, lut_norm)


def pick_colorbar_with_mouse(frame):
    """Let the user drag a rectangle around the colour bar (top=hot, bottom=cold)."""
    title = "drag the colour bar (TOP = hottest, BOTTOM = coldest)  —  ENTER ok / ESC cancel"
    r = cv2.selectROI(title, frame, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow(title)
    x, y, w, h = [int(v) for v in r]
    return colorbar_from_rect(frame, x, y, w, h)


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


@dataclass
class Detection:
    """One patty-like blob found in a single frame."""
    cx: float
    cy: float
    area: int
    mean_t: float            # normalised temperature 0..1
    mask: np.ndarray         # boolean mask, same shape as the ROI


def find_patty_blobs(norm_t, hot_q=0.55, cold_q=0.45,
                     min_area_frac=0.003) -> list[Detection]:
    """Return a list of detections, one per patty-like cool blob."""
    H, W = norm_t.shape
    min_area = max(int(H * W * min_area_frac), 200)
    hot = norm_t > hot_q
    if hot.mean() < 0.05:
        return []

    cool = (norm_t < cold_q).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cool = cv2.morphologyEx(cool, cv2.MORPH_OPEN, k)
    cool = cv2.morphologyEx(cool, cv2.MORPH_CLOSE, k)

    n, labels, stats, centroids = cv2.connectedComponentsWithStats(cool, connectivity=8)
    out: list[Detection] = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area:
            continue
        if x <= 2 or y <= 2 or x + w >= W - 2 or y + h >= H - 2:
            continue
        m = (labels == i)
        out.append(Detection(
            cx=float(centroids[i][0]),
            cy=float(centroids[i][1]),
            area=int(area),
            mean_t=float(norm_t[m].mean()),
            mask=m,
        ))
    return out


@dataclass
class Track:
    """A patty followed across frames."""
    id: int
    cx: float
    cy: float
    area: int
    mean_t: float
    first_seen: float        # wall-clock seconds
    last_seen: float
    missed: int = 0
    mean_t_history: list[float] = field(default_factory=list)


class PattyTracker:
    """Greedy nearest-centroid tracker; good enough for ~12 mostly-static patties."""

    def __init__(self):
        self.next_id = 1
        self.tracks: dict[int, Track] = {}

    def update(self, dets: list[Detection], now: float) -> list[Track]:
        # build distance matrix detections × existing tracks
        if self.tracks and dets:
            ids = list(self.tracks.keys())
            tx = np.array([self.tracks[i].cx for i in ids])
            ty = np.array([self.tracks[i].cy for i in ids])
            dx = np.array([d.cx for d in dets])
            dy = np.array([d.cy for d in dets])
            dist = np.sqrt((dx[:, None] - tx[None, :]) ** 2
                           + (dy[:, None] - ty[None, :]) ** 2)
            matched_det: set[int] = set()
            matched_trk: set[int] = set()
            # greedy: repeatedly take the smallest pair under threshold
            while True:
                if dist.size == 0:
                    break
                idx = np.argmin(dist)
                di, ti = divmod(int(idx), dist.shape[1])
                if dist[di, ti] > TRACK_MAX_DIST_PX:
                    break
                tid = ids[ti]
                d = dets[di]
                tr = self.tracks[tid]
                tr.cx, tr.cy = d.cx, d.cy
                tr.area = d.area
                tr.mean_t = d.mean_t
                tr.last_seen = now
                tr.missed = 0
                tr.mean_t_history.append(d.mean_t)
                if len(tr.mean_t_history) > 600:
                    tr.mean_t_history.pop(0)
                matched_det.add(di)
                matched_trk.add(ti)
                dist[di, :] = np.inf
                dist[:, ti] = np.inf
            unmatched_dets = [i for i in range(len(dets)) if i not in matched_det]
            unmatched_trks = [ids[i] for i in range(len(ids)) if i not in matched_trk]
        else:
            unmatched_dets = list(range(len(dets)))
            unmatched_trks = list(self.tracks.keys())

        # new tracks for unmatched detections
        for di in unmatched_dets:
            d = dets[di]
            tid = self.next_id
            self.next_id += 1
            self.tracks[tid] = Track(
                id=tid, cx=d.cx, cy=d.cy, area=d.area,
                mean_t=d.mean_t, first_seen=now, last_seen=now,
                mean_t_history=[d.mean_t],
            )

        # age out unmatched tracks
        for tid in unmatched_trks:
            self.tracks[tid].missed += 1
        to_drop = [tid for tid, tr in self.tracks.items()
                   if tr.missed > TRACK_MAX_MISSED]
        for tid in to_drop:
            del self.tracks[tid]

        return list(self.tracks.values())


def colour_for_id(tid: int) -> tuple[int, int, int]:
    """Stable BGR colour for a given track id (golden-ratio hue spacing)."""
    h = int((tid * 47) % 180)
    hsv = np.uint8([[[h, 200, 240]]])
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--background", action="store_true",
                    help="capture via PrintWindow API (works while hidden)")
    args = ap.parse_args()

    print(f"looking for window containing '{WINDOW_TITLE_SUBSTRING}' ...")
    win = find_window()
    if win is None:
        print(f"❌ no window with title containing '{WINDOW_TITLE_SUBSTRING}'.")
        print("   open TopView first, show the live camera feed, then re-run.")
        return 1
    print(f"✅ {win.title}  pos=({win.left},{win.top})  size={win.width}x{win.height}")

    hwnd = None
    if args.background:
        try:
            _ensure_win32()
            hwnd = win._hWnd  # pygetwindow keeps the HWND here on Windows
            print("capture mode: BACKGROUND (PrintWindow)  — works when hidden")
        except ImportError:
            print("❌ pywin32 not installed; falling back to visible mode")
            print("   install with: pip install pywin32")
            args.background = False
    if not args.background:
        print("capture mode: VISIBLE (mss)  — TopView must be on-screen")

    sct = mss.MSS()
    cb = None
    qlut = None
    roi = None
    manual_roi = False
    tracker = PattyTracker()

    print("\nkeys: q=quit  r=redetect bar  c=draw colour bar  b=draw camera ROI  s=save")
    out_win = "burgerpark — live (via TopView capture)"
    cv2.namedWindow(out_win, cv2.WINDOW_NORMAL)

    n_frames = 0
    last_fps_t = time.time()
    saved = 0

    while True:
        try:
            if args.background:
                frame = capture_background(hwnd)
            else:
                frame = capture_visible(sct, win)
        except Exception as e:
            print(f"capture error: {e}")
            time.sleep(0.5)
            continue

        if cb is None:
            cb = find_colorbar(frame)
            if cb is None:
                hint = frame.copy()
                cv2.rectangle(hint, (0, 0), (hint.shape[1], 56), (0, 0, 0), -1)
                cv2.putText(hint,
                            "colour bar not detected.  c = draw it by hand   q = quit",
                            (16, 36),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2, cv2.LINE_AA)
                cv2.imshow(out_win, hint)
                k = cv2.waitKey(200) & 0xFF
                if k == ord("q"):
                    break
                if k == ord("c"):
                    cb = pick_colorbar_with_mouse(frame)
                    if cb is not None:
                        print(f"colour bar (manual): x={cb.x0}-{cb.x1}  y={cb.y0}-{cb.y1}")
                        qlut = build_qlut(cb)
                        if not manual_roi:
                            roi = detect_camera_roi(frame, cb)
                            print(f"camera ROI (auto): x={roi[0]}-{roi[1]}  y={roi[2]}-{roi[3]}")
                            print("press 'b' to draw the camera ROI by hand")
                    else:
                        print("colour bar selection cancelled")
                if k == ord("b"):
                    new_roi = pick_roi_with_mouse(frame)
                    if new_roi is not None:
                        roi = new_roi
                        manual_roi = True
                        print(f"camera ROI (manual): x={roi[0]}-{roi[1]}  y={roi[2]}-{roi[3]}")
                continue
            print(f"colour bar (auto): x={cb.x0}-{cb.x1}  y={cb.y0}-{cb.y1}  L={len(cb.lut_norm)}")
            qlut = build_qlut(cb)
            if not manual_roi:
                roi = detect_camera_roi(frame, cb)
                print(f"camera ROI (auto): x={roi[0]}-{roi[1]}  y={roi[2]}-{roi[3]}")
                print("press 'b' if you want to draw the ROI by hand instead")

        x0, x1, y0, y1 = roi
        sub = frame[y0:y1, x0:x1]
        if sub.size == 0:
            cb = None
            continue
        norm = lut_apply(sub, qlut)
        dets = find_patty_blobs(norm)

        now = time.time()
        tracks = tracker.update(dets, now)

        vis = sub.copy()
        for tr in tracks:
            # find the detection for this track this frame, if any, for mask drawing
            d = next((d for d in dets
                      if abs(d.cx - tr.cx) < 1 and abs(d.cy - tr.cy) < 1), None)
            col = colour_for_id(tr.id)
            if d is not None:
                overlay = vis.copy()
                overlay[d.mask] = col
                vis = cv2.addWeighted(vis, 0.6, overlay, 0.4, 0)
                # contour for clarity
                cnts, _ = cv2.findContours(d.mask.astype(np.uint8) * 255,
                                           cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(vis, cnts, -1, col, 2)
            elapsed = now - tr.first_seen
            txt = f"#{tr.id}  t={elapsed:5.1f}s  T={tr.mean_t:.2f}"
            org = (int(tr.cx) - 50, int(tr.cy) - 8)
            cv2.rectangle(vis,
                          (org[0] - 4, org[1] - 16),
                          (org[0] + 130, org[1] + 4),
                          (0, 0, 0), -1)
            cv2.putText(vis, txt, org,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)

        n_frames += 1
        fps = n_frames / (now - last_fps_t + 1e-6) if now - last_fps_t > 0.1 else 0
        n_active = sum(1 for t in tracks if t.missed == 0)
        header = f"patties: {n_active} active / {len(tracks)} total      {fps:4.1f} fps"
        cv2.rectangle(vis, (0, 0), (vis.shape[1], 32), (0, 0, 0), -1)
        cv2.putText(vis, header, (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        if now - last_fps_t > 2.0:
            last_fps_t, n_frames = now, 0

        cv2.imshow(out_win, vis)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord("r"):
            cb = None
            print("re-detecting colour bar...")
        if k == ord("c"):
            new_cb = pick_colorbar_with_mouse(frame)
            if new_cb is not None:
                cb = new_cb
                qlut = build_qlut(cb)
                print(f"colour bar (manual): x={cb.x0}-{cb.x1}  y={cb.y0}-{cb.y1}")
            else:
                print("colour bar selection cancelled")
        if k == ord("b"):
            new_roi = pick_roi_with_mouse(frame)
            if new_roi is not None:
                roi = new_roi
                manual_roi = True
                tracker = PattyTracker()       # ids are stale after ROI change
                print(f"camera ROI (manual): x={roi[0]}-{roi[1]}  y={roi[2]}-{roi[3]}")
            else:
                print("ROI selection cancelled")
        if k == ord("s"):
            saved += 1
            p = OUT / f"live_{int(time.time())}_{saved:02d}.png"
            cv2.imwrite(str(p), vis)
            print(f"saved {p}")

    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
