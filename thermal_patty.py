"""Burgerpark — thermal patty flip detector (prototype).

Top-down thermal-camera view of a beef patty on a grill. The frame source
(`synth_frame`) is a physically-plausible synthetic generator so the rest of
the pipeline can be developed without hardware; swap it for a real camera
feed (FLIR Lepton, etc.) without touching the detector or the judge.

Run a live visualization:
    python thermal_patty.py

Run headless (no window, just prints the flip decision):
    python thermal_patty.py --headless
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import cv2
import numpy as np


FRAME_H, FRAME_W = 480, 480
PATTY_CY, PATTY_CX = 240, 240
PATTY_RADIUS = 110

AMBIENT_C = 24.0
GRILL_C = 220.0
SURFACE_ASYMPTOTE_C = 78.0
SURFACE_TAU_S = 95.0

FLIP_SURFACE_TEMP_C = 68.0
FLIP_DTDT_C_PER_S = 0.05
FLIP_MIN_COOK_S = 75.0

SIM_FPS = 30
SIM_SPEEDUP = 8.0


def synth_frame(t_seconds: float, rng: np.random.Generator) -> np.ndarray:
    """HxW float32 temperature field (°C) at cooking time `t_seconds`."""
    yy, xx = np.mgrid[0:FRAME_H, 0:FRAME_W].astype(np.float32)
    r = np.sqrt((yy - PATTY_CY) ** 2 + (xx - PATTY_CX) ** 2)

    surface_c = AMBIENT_C + (SURFACE_ASYMPTOTE_C - AMBIENT_C) * (
        1.0 - np.exp(-t_seconds / SURFACE_TAU_S)
    )

    inside = (r < PATTY_RADIUS).astype(np.float32)
    edge_profile = np.exp(-((r - PATTY_RADIUS) ** 2) / (12.0 ** 2)) * inside
    edge_gain_c = 6.0 * (1.0 - np.exp(-t_seconds / 60.0))

    temp = np.where(inside > 0.5, surface_c + edge_profile * edge_gain_c, GRILL_C)
    temp += rng.normal(0.0, 0.4, size=temp.shape).astype(np.float32)
    return temp.astype(np.float32)


def detect_patty(temp: np.ndarray) -> tuple[np.ndarray, dict]:
    """Return (mask, stats) for the patty region in a thermal frame."""
    mask = ((temp > AMBIENT_C + 8.0) & (temp < GRILL_C - 40.0)).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    n, labels, cc_stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return mask, {}
    largest = 1 + int(np.argmax(cc_stats[1:, cv2.CC_STAT_AREA]))
    mask = ((labels == largest).astype(np.uint8)) * 255

    pixels = temp[mask > 0]
    stats = {
        "area_px": int(pixels.size),
        "mean_c": float(pixels.mean()),
        "median_c": float(np.median(pixels)),
        "max_c": float(pixels.max()),
        "min_c": float(pixels.min()),
        "std_c": float(pixels.std()),
    }
    return mask, stats


@dataclass
class FlipJudge:
    """Decides when to flip from the patty's surface-temperature trace."""

    history: list[tuple[float, float]] = field(default_factory=list)
    flipped: bool = False
    flip_time_s: float | None = None

    def update(self, t_s: float, mean_c: float) -> bool:
        self.history.append((t_s, mean_c))
        if self.flipped:
            return False
        if t_s < FLIP_MIN_COOK_S:
            return False
        if mean_c < FLIP_SURFACE_TEMP_C:
            return False

        recent = [(tt, mm) for tt, mm in self.history if t_s - tt <= 10.0]
        if len(recent) < 2:
            return False
        (t0, m0), (t1, m1) = recent[0], recent[-1]
        if t1 - t0 < 1e-3:
            return False
        if (m1 - m0) / (t1 - t0) > FLIP_DTDT_C_PER_S:
            return False

        self.flipped = True
        self.flip_time_s = t_s
        return True


def colorize(temp: np.ndarray) -> np.ndarray:
    lo, hi = AMBIENT_C - 5.0, GRILL_C + 5.0
    norm = np.clip((temp - lo) / (hi - lo), 0.0, 1.0)
    return cv2.applyColorMap((norm * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)


def draw_hud(img: np.ndarray, t_s: float, stats: dict,
             flipped: bool, flip_t: float | None) -> None:
    H, W = img.shape[:2]
    band = img.copy()
    cv2.rectangle(band, (0, 0), (W, 92), (0, 0, 0), -1)
    cv2.addWeighted(band, 0.55, img, 0.45, 0, dst=img)

    lines = [
        f"cook time : {t_s:6.1f} s",
        f"mean temp : {stats.get('mean_c', 0):6.1f} C    area: {stats.get('area_px', 0)} px",
        f"max  temp : {stats.get('max_c', 0):6.1f} C    std : {stats.get('std_c', 0):4.2f}",
    ]
    for i, ln in enumerate(lines):
        cv2.putText(img, ln, (12, 24 + i * 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    if flipped and flip_t is not None:
        msg = f"FLIP NOW  (t={flip_t:.1f}s)"
        (tw, th), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_DUPLEX, 1.0, 2)
        x = (W - tw) // 2
        cv2.rectangle(img, (x - 16, H - 64), (x + tw + 16, H - 16), (0, 0, 0), -1)
        cv2.putText(img, msg, (x, H - 28),
                    cv2.FONT_HERSHEY_DUPLEX, 1.0, (0, 255, 255), 2, cv2.LINE_AA)


def run(headless: bool = False, max_sim_seconds: float = 240.0,
        seed: int = 0) -> FlipJudge:
    rng = np.random.default_rng(seed)
    judge = FlipJudge()
    t_sim = 0.0
    dt = SIM_SPEEDUP / SIM_FPS
    win = "burgerpark — thermal patty"
    if not headless:
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    while t_sim <= max_sim_seconds:
        temp = synth_frame(t_sim, rng)
        mask, stats = detect_patty(temp)
        if stats:
            judge.update(t_sim, stats["mean_c"])

        if not headless:
            bgr = colorize(temp)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(bgr, contours, -1, (255, 255, 255), 2)
            draw_hud(bgr, t_sim, stats, judge.flipped, judge.flip_time_s)
            cv2.imshow(win, bgr)
            key = cv2.waitKey(int(1000 / SIM_FPS)) & 0xFF
            if key in (27, ord("q")):
                break

        if judge.flipped and judge.flip_time_s is not None \
                and t_sim - judge.flip_time_s > 8.0:
            break

        t_sim += dt

    if not headless:
        cv2.destroyAllWindows()
    return judge


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--headless", action="store_true",
                   help="run without an OpenCV window (for CI / SSH)")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    judge = run(headless=args.headless, seed=args.seed)
    if judge.flipped and judge.flip_time_s is not None:
        print(f"flip @ t = {judge.flip_time_s:6.1f} s  "
              f"(criterion: mean ≥ {FLIP_SURFACE_TEMP_C} °C, "
              f"dT/dt ≤ {FLIP_DTDT_C_PER_S} °C/s, "
              f"after ≥ {FLIP_MIN_COOK_S:.0f} s)")
    else:
        print("no flip decision reached within simulation window")


if __name__ == "__main__":
    main()
