"""Thermal video analysis pipeline (TOPDON TC001 Max footage).

Stages:
  1. locate the vertical colour bar in a reference frame
  2. build a quantised 3D LUT (BGR → normalised temperature 0..1)
  3. for every sampled frame, look up per-pixel relative temperature
  4. segment patty pixels (cool blobs bordered by hot grill)
  5. plot mean patty relative-temperature vs time and overlay the
     operator-confirmed flip moments
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "raw"
OUT = ROOT / "data" / "out"
OUT.mkdir(parents=True, exist_ok=True)

VIDEOS = [
    {"name": "20260512013505983_100.mp4", "flip_s": 61.0, "label": "video 1"},
    {"name": "20260512014522124_100.mp4", "flip_s": 32.0, "label": "video 2"},
]

LUT_BITS = 5                 # 32 levels per channel → 32³ = 32 768 bins
DOWNSAMPLE = 0.5             # process frames at half resolution
SAMPLE_EVERY_S = 0.5


@dataclass
class ColorBar:
    x0: int
    x1: int
    y0: int
    y1: int
    lut_bgr: np.ndarray       # (L, 3) top→bottom (hot→cold)
    lut_norm: np.ndarray      # (L,)   1.0→0.0


def find_colorbar(frame_bgr: np.ndarray) -> ColorBar:
    H, W, _ = frame_bgr.shape
    rx0 = int(W * 0.80)
    search = frame_bgr[:, rx0:W]
    sat = cv2.cvtColor(search, cv2.COLOR_BGR2HSV)[:, :, 1].astype(np.float32)
    bar_xc = int(np.argmax(sat.mean(axis=0) * sat.std(axis=0))) + rx0

    half = 14
    x0, x1 = max(bar_xc - half, 0), min(bar_xc + half, W)
    column = frame_bgr[:, x0:x1].mean(axis=1)
    col_sat = cv2.cvtColor(column.astype(np.uint8)[None, :, :], cv2.COLOR_BGR2HSV)[0, :, 1]
    ys = np.flatnonzero(col_sat > 40)
    if ys.size < 50:
        raise RuntimeError("colour bar not detected")
    y0, y1 = int(ys[0]), int(ys[-1])

    lut_bgr = frame_bgr[y0:y1, x0:x1].mean(axis=1).astype(np.float32)
    lut_norm = np.linspace(1.0, 0.0, lut_bgr.shape[0], dtype=np.float32)
    return ColorBar(x0, x1, y0, y1, lut_bgr, lut_norm)


def build_qlut(cb: ColorBar, bits: int = LUT_BITS) -> np.ndarray:
    """3D array (levels, levels, levels) → norm-temp at each quantised BGR cell."""
    levels = 1 << bits
    step = 256 // levels
    # bin centre values, [0, step, 2*step, ...]
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


def lut_apply(frame_bgr: np.ndarray, qlut: np.ndarray,
              bits: int = LUT_BITS) -> np.ndarray:
    shift = 8 - bits
    b = frame_bgr[..., 0] >> shift
    g = frame_bgr[..., 1] >> shift
    r = frame_bgr[..., 2] >> shift
    return qlut[b, g, r]


def segment_patties(norm_t: np.ndarray, hot_q: float = 0.55,
                    cold_q: float = 0.45, min_area_frac: float = 0.003) -> np.ndarray:
    H, W = norm_t.shape
    min_area = int(H * W * min_area_frac)
    hot = norm_t > hot_q
    if hot.mean() < 0.1:
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
        pad = 6
        rx0, ry0 = max(x - pad, 0), max(y - pad, 0)
        rx1, ry1 = min(x + w + pad, W), min(y + h + pad, H)
        region = (labels[ry0:ry1, rx0:rx1] == i)
        hot_region = hot[ry0:ry1, rx0:rx1]
        if hot_region.sum() < region.sum() * 0.4:
            continue
        keep |= (labels == i)
    return keep


def analyze(video_path: Path) -> dict:
    t_start = time.time()
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    stride = max(int(round(fps * SAMPLE_EVERY_S)), 1)

    # reference frame from late in the video (grill is hot, patty is clear)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(0.5 * n))
    ok, ref = cap.read()
    if not ok:
        raise RuntimeError(f"cannot read reference frame from {video_path}")
    cb = find_colorbar(ref)
    print(f"  colour bar:  x={cb.x0}-{cb.x1}  y={cb.y0}-{cb.y1}  L={len(cb.lut_norm)}")
    qlut = build_qlut(cb)
    print(f"  built {qlut.size}-entry quantised LUT in {time.time()-t_start:.2f}s")

    times, mean_t, area = [], [], []
    sample_overlay = None
    sample_t_label = None

    bar_x_orig = cb.x0
    bar_x_ds = int(bar_x_orig * DOWNSAMPLE)

    for idx in range(0, n, stride):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        small = cv2.resize(frame, None, fx=DOWNSAMPLE, fy=DOWNSAMPLE,
                           interpolation=cv2.INTER_AREA)
        small[:, max(bar_x_ds - 4, 0):] = 0          # blank the bar + side UI
        norm = lut_apply(small, qlut)
        mask = segment_patties(norm)
        t_s = idx / fps
        if mask.any():
            mean_t.append(float(norm[mask].mean()))
            area.append(int(mask.sum()))
        else:
            mean_t.append(np.nan)
            area.append(0)
        times.append(t_s)

        if sample_overlay is None and mask.any() and 0.3 * n <= idx <= 0.55 * n:
            ov = small.copy()
            ov[mask] = (0, 255, 0)
            sample_overlay = cv2.addWeighted(small, 0.55, ov, 0.45, 0)
            sample_t_label = t_s

    cap.release()
    print(f"  {len(times)} samples in {time.time()-t_start:.1f}s total")

    return {
        "fps": fps,
        "n_frames": n,
        "times": np.asarray(times),
        "mean_t": np.asarray(mean_t),
        "area": np.asarray(area),
        "colorbar": cb,
        "sample_overlay": sample_overlay,
        "sample_t_label": sample_t_label,
    }


def main() -> None:
    fig, axes = plt.subplots(2, 1, figsize=(10, 7))
    for ax, cfg in zip(axes, VIDEOS):
        path = DATA / cfg["name"]
        print(f"\n=== {cfg['name']}  (flip @ {cfg['flip_s']:.1f}s) ===")
        r = analyze(path)
        ax.plot(r["times"], r["mean_t"], lw=1.6, label="patty mean (norm)")
        ax.axvline(cfg["flip_s"], color="red", ls="--", lw=1.2,
                   label=f"operator flip @ {cfg['flip_s']:.0f}s")
        ax.set_title(f"{cfg['label']}  —  {cfg['name']}")
        ax.set_xlabel("time (s)")
        ax.set_ylabel("relative surface temp (0=cold, 1=hot)")
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right", fontsize=9)

        if r["sample_overlay"] is not None:
            ov_path = OUT / f"{Path(cfg['name']).stem}_segmentation.png"
            cv2.imwrite(str(ov_path), r["sample_overlay"])
            print(f"  segmentation sample @ t={r['sample_t_label']:.1f}s → {ov_path.name}")

    fig.tight_layout()
    out = OUT / "patty_curves.png"
    fig.savefig(out, dpi=130)
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
