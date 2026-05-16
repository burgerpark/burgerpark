"""Pygame tycoon-style overlay for the thermal patty flipper.

Pipeline:
  1. wait until the grill becomes visibly hot
  2. for a short "locking" window, accumulate detected patty centres
  3. KMeans(k=2) over those centres → two permanent patty ROIs
  4. afterwards, each ROI is sampled every frame for mean surface temp
     and a per-patty state machine decides FLIP / DONE

Reuses LUT + detection from analyze_videos.py.
"""
from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from analyze_videos import (
    build_qlut,
    find_colorbar,
    lut_apply,
    DOWNSAMPLE,
)

PANEL_W = 320
N_PATTIES = 2                        # fixed at 2 for now (video 1 layout)
LOCK_WINDOW_S = 5.0                  # accumulate detections this long
LOCK_MIN_SAMPLES = 16                # need at least this many detections to lock
GRILL_HOT_THRESHOLD = 0.55
GRILL_HOT_PIXEL_FRAC = 0.15

ROI_RADIUS_SCALE = 0.95              # multiplier on median detected radius

FLIP_NORM = 0.27                     # mean surface norm trigger
COOK1_MIN_S = 30.0
FLIP_AUTO_AFTER_S = 8.0
DONE_NORM = 0.30
DONE_HOLD_S = 6.0
COOK2_MIN_S = 25.0

STATE_COLORS = {
    "COOKING":        (250, 200,  80),
    "READY_TO_FLIP":  (255,  80,  80),
    "COOKING_2":      (250, 200,  80),
    "DONE":           ( 80, 230, 120),
}
STATE_LABELS = {
    "COOKING":       "COOKING",
    "READY_TO_FLIP": "FLIP NOW",
    "COOKING_2":     "COOKING B",
    "DONE":          "DONE!",
}


@dataclass
class Patty:
    pid: int
    cx: float
    cy: float
    radius: float
    state: str = "COOKING"
    norm: float = 0.0
    started_s: float = 0.0
    flip_t_s: float | None = None
    done_t_s: float | None = None
    progress: float = 0.0
    flash_phase: float = 0.0

    def step(self, norm: float, t: float) -> None:
        # exponential smoothing on the measurement
        a = 0.25
        self.norm = a * norm + (1 - a) * self.norm if self.norm > 0 else norm
        cook_age = t - self.started_s

        if self.state == "COOKING":
            self.progress = min(cook_age / COOK1_MIN_S, 1.0) * 0.5
            if self.norm >= FLIP_NORM and cook_age >= COOK1_MIN_S:
                self.state = "READY_TO_FLIP"
        elif self.state == "READY_TO_FLIP":
            self.progress = 0.5
            if self.flip_t_s is None:
                self.flip_t_s = t
            elif t - self.flip_t_s > FLIP_AUTO_AFTER_S:
                self.state = "COOKING_2"
        elif self.state == "COOKING_2":
            elapsed = t - (self.flip_t_s or t)
            self.progress = 0.5 + min(elapsed / COOK2_MIN_S, 0.5)
            if self.norm >= DONE_NORM and elapsed > DONE_HOLD_S:
                self.state = "DONE"
                self.done_t_s = t
        else:
            self.progress = 1.0


def detect_candidates(norm: np.ndarray) -> list[dict]:
    """Return candidate cool blobs for the locking window."""
    H, W = norm.shape
    if (norm > GRILL_HOT_THRESHOLD).mean() < GRILL_HOT_PIXEL_FRAC:
        return []
    hot = norm > GRILL_HOT_THRESHOLD
    cool = (norm < 0.45).astype(np.uint8) * 255
    cool = cv2.morphologyEx(cool, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(cool, connectivity=8)
    out = []
    min_area = int(0.010 * H * W)
    max_area = int(0.05 * H * W)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area or area > max_area:
            continue
        if x <= 2 or y <= 2 or x + w >= W - 2 or y + h >= H - 2:
            continue
        pad = 6
        rx0, ry0 = max(x - pad, 0), max(y - pad, 0)
        rx1, ry1 = min(x + w + pad, W), min(y + h + pad, H)
        region = labels[ry0:ry1, rx0:rx1] == i
        hot_region = hot[ry0:ry1, rx0:rx1]
        if hot_region.sum() < region.sum() * 0.4:
            continue
        out.append({
            "center": (float(cents[i][0]), float(cents[i][1])),
            "radius": float((w + h) / 4),
            "area": int(area),
        })
    out.sort(key=lambda d: -d["area"])
    return out[:4]


def attempt_lock(state: dict, t: float, scale: float) -> bool:
    """Try to lock the patty ROIs from accumulated detections."""
    samples = state.get("lock_samples", [])
    if t - state["lock_start_s"] < LOCK_WINDOW_S:
        return False
    pts = np.array([s["center"] for s in samples], dtype=np.float32)
    radii = np.array([s["radius"] for s in samples], dtype=np.float32)
    if len(pts) < LOCK_MIN_SAMPLES:
        return False

    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, labels, centers = cv2.kmeans(pts, N_PATTIES, None, crit, 5,
                                     cv2.KMEANS_PP_CENTERS)
    labels = labels.flatten()

    patties: list[Patty] = []
    for k in range(N_PATTIES):
        mask = labels == k
        if mask.sum() < 3:
            return False
        cx = float(centers[k, 0]) / scale
        cy = float(centers[k, 1]) / scale
        r = float(np.median(radii[mask])) / scale * ROI_RADIUS_SCALE
        patties.append(Patty(pid=k + 1, cx=cx, cy=cy, radius=max(r, 20.0),
                              started_s=state["lock_start_s"]))
    # sort by (y, x) so #1 is the upper-left patty
    patties.sort(key=lambda p: (p.cy, p.cx))
    for i, p in enumerate(patties, 1):
        p.pid = i
    state["patties"] = {p.pid: p for p in patties}
    state["phase"] = "RUNNING"
    return True


def sample_roi(norm: np.ndarray, cx: float, cy: float, r: float,
               scale: float) -> float | None:
    """Mean of cool (patty) pixels in a circular ROI."""
    H, W = norm.shape
    cx_s, cy_s = cx * scale, cy * scale
    r_s = r * scale
    x0, y0 = max(int(cx_s - r_s), 0), max(int(cy_s - r_s), 0)
    x1, y1 = min(int(cx_s + r_s), W), min(int(cy_s + r_s), H)
    if x1 <= x0 or y1 <= y0:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    inside = (xx - cx_s) ** 2 + (yy - cy_s) ** 2 <= r_s * r_s
    roi = norm[y0:y1, x0:x1][inside]
    cool = roi[roi < 0.55]
    if cool.size < 30:
        return None
    return float(cool.mean())


def draw_overlay(screen, font_small, font_big, frame_bgr: np.ndarray,
                 state: dict, t_s: float, panel_w: int) -> None:
    import pygame

    H, W = frame_bgr.shape[:2]
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    surf = pygame.image.frombuffer(rgb.tobytes(), (W, H), "RGB")
    screen.fill((22, 24, 32))
    screen.blit(surf, (0, 0))

    phase = state["phase"]
    if phase == "RUNNING":
        for p in state["patties"].values():
            color = STATE_COLORS[p.state]
            cx, cy, r = int(p.cx), int(p.cy), int(p.radius)
            pygame.draw.circle(screen, color, (cx, cy), r, 4)

            # doneness arc around the ring
            rect = pygame.Rect(cx - r - 10, cy - r - 10, (r + 10) * 2, (r + 10) * 2)
            end = -math.pi / 2 + 2 * math.pi * p.progress
            pygame.draw.arc(screen, color, rect, -math.pi / 2, end, 6)

            label = font_small.render(
                f"P{p.pid}  {STATE_LABELS[p.state]}", True, color)
            screen.blit(label, (cx - label.get_width() // 2, cy + r + 14))

            if p.state == "READY_TO_FLIP":
                p.flash_phase = (p.flash_phase + 0.25) % (2 * math.pi)
                if math.sin(p.flash_phase) > 0:
                    ax, ay = cx, cy - r - 38
                    pts = [(ax, ay - 18), (ax - 14, ay + 6), (ax + 14, ay + 6)]
                    pygame.draw.polygon(screen, (255, 80, 80), pts)
                    t2 = font_big.render("FLIP!", True, (255, 240, 240))
                    screen.blit(t2, (ax - t2.get_width() // 2, ay - 52))
    elif phase == "LOCKING":
        msg = font_big.render("DETECTING PATTIES...", True, (240, 220, 120))
        screen.blit(msg, (16, 16))
    else:  # WAITING
        msg = font_big.render("WAITING FOR GRILL...", True, (200, 200, 220))
        screen.blit(msg, (16, 16))

    # side panel
    px = W
    import pygame
    pygame.draw.rect(screen, (32, 36, 48), (px, 0, panel_w, H))
    title = font_big.render("BURGERPARK", True, (250, 220, 100))
    screen.blit(title, (px + 16, 14))
    sub = font_small.render(f"t = {t_s:5.1f} s    phase = {phase}",
                            True, (200, 200, 220))
    screen.blit(sub, (px + 16, 50))

    if phase == "RUNNING":
        y = 92
        for p in sorted(state["patties"].values(), key=lambda p: p.pid):
            color = STATE_COLORS[p.state]
            pygame.draw.rect(screen, (44, 48, 64), (px + 12, y, panel_w - 24, 96),
                             border_radius=10)
            pygame.draw.circle(screen, color, (px + 36, y + 32), 16)
            name = font_small.render(f"Patty #{p.pid}", True, (240, 240, 250))
            screen.blit(name, (px + 60, y + 8))
            st = font_small.render(STATE_LABELS[p.state], True, color)
            screen.blit(st, (px + 60, y + 30))
            normtxt = font_small.render(f"surface norm: {p.norm:.2f}",
                                         True, (180, 180, 200))
            screen.blit(normtxt, (px + 60, y + 52))
            gx, gy = px + 16, y + 76
            gw, gh = panel_w - 32, 12
            pygame.draw.rect(screen, (60, 64, 80), (gx, gy, gw, gh),
                             border_radius=6)
            pygame.draw.rect(screen, color,
                             (gx + 2, gy + 2, int((gw - 4) * p.progress), gh - 4),
                             border_radius=5)
            y += 108


def run(video_path: Path, headless: bool, capture_every: int,
        capture_dir: Path | None) -> None:
    if headless:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    pygame.init()

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"cannot open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    cap.set(cv2.CAP_PROP_POS_FRAMES, int(0.5 * n))
    ok, ref = cap.read()
    if not ok:
        raise SystemExit("cannot read reference frame for LUT")
    cb = find_colorbar(ref)
    qlut = build_qlut(cb)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    win_w = W + PANEL_W
    screen = pygame.display.set_mode((win_w, H))
    pygame.display.set_caption("burgerpark — flip tycoon")
    font_small = pygame.font.SysFont("dejavusans", 18)
    font_big = pygame.font.SysFont("dejavusans", 28, bold=True)
    clock = pygame.time.Clock()

    state: dict = {
        "phase": "WAITING",
        "patties": {},
        "lock_samples": [],
        "lock_start_s": None,
    }

    if capture_dir is not None:
        capture_dir.mkdir(parents=True, exist_ok=True)

    frame_i = 0
    running = True
    while running:
        ok, frame = cap.read()
        if not ok:
            break
        t_s = frame_i / fps

        small = cv2.resize(frame, None, fx=DOWNSAMPLE, fy=DOWNSAMPLE,
                           interpolation=cv2.INTER_AREA)
        small[:, max(int(cb.x0 * DOWNSAMPLE) - 4, 0):] = 0
        norm = lut_apply(small, qlut)

        if state["phase"] == "WAITING":
            if (norm > GRILL_HOT_THRESHOLD).mean() >= GRILL_HOT_PIXEL_FRAC:
                state["phase"] = "LOCKING"
                state["lock_start_s"] = t_s
        if state["phase"] == "LOCKING":
            cands = detect_candidates(norm)
            state["lock_samples"].extend(cands)
            attempt_lock(state, t_s, scale=DOWNSAMPLE)
        elif state["phase"] == "RUNNING":
            for p in state["patties"].values():
                m = sample_roi(norm, p.cx, p.cy, p.radius, DOWNSAMPLE)
                if m is not None:
                    p.step(m, t_s)

        draw_overlay(screen, font_small, font_big, frame, state, t_s, PANEL_W)
        pygame.display.flip()

        if capture_dir is not None and capture_every > 0 and frame_i % capture_every == 0:
            out_path = capture_dir / f"frame_{frame_i:05d}_t{int(t_s*10):04d}.png"
            pygame.image.save(screen, str(out_path))

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False

        if not headless:
            clock.tick(int(fps))
        frame_i += 1

    cap.release()
    pygame.quit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--capture-every", type=int, default=0)
    ap.add_argument("--capture-dir", type=Path, default=None)
    args = ap.parse_args()
    run(args.video, args.headless, args.capture_every, args.capture_dir)


if __name__ == "__main__":
    main()
