#!/usr/bin/env python3
"""
Geometric-only augmentation of the human class to balance EI project 1000575.

WHY: the training set is imbalanced (~519 human vs ~926 nonhuman). Plain
duplication (inject_and_oversample.py) just gets deduplicated by Edge Impulse
and teaches memorization. This script instead creates genuinely different human
images using GEOMETRIC transforms only — NO color/brightness/contrast/hue
changes — so the RGB content is preserved exactly while the model still learns
pose/position invariance, and the new files survive EI's hash dedup.

Transforms (all border-free, composed randomly per output):
  - horizontal flip
  - small rotation (reflect-padded, then center-cropped — no black corners)
  - crop-zoom (random sub-crop resized back — gives zoom + translation)

Train/test leakage guard: human images that are in the EI *test* set are
excluded as augmentation sources (list in _test_human_names.json), so no
augmented variant of a test image ever lands in training.

Usage (PowerShell):
  $env:EI_API_KEY = "ei_..."
  python tools/edge_impulse/augment_humans_geometric.py --target-count 420
  python tools/edge_impulse/augment_humans_geometric.py --target-count 420 --no-upload
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

REPO = Path(__file__).resolve().parents[2]
SRC_HUMANS = (
    REPO / "datasets" / "Human_Detection_Dataset"
    / "Human_Detection_Dataset_4" / "Human_Detection_Dataset" / "Humans"
)
OUT_DIR = REPO / "datasets" / "augmented_humans_geometric"
EXCLUDE_JSON = Path(__file__).resolve().parent / "_test_human_names.json"

PROJECT_ID = 1000575
INGESTION_URL = "https://ingestion.edgeimpulse.com"
SEED = 42


def hflip(im: Image.Image) -> Image.Image:
    return im.transpose(Image.FLIP_LEFT_RIGHT)


def rotate_reflect(im: Image.Image, angle: float) -> Image.Image:
    """Rotate without introducing black borders (reflect-pad -> rotate -> center crop)."""
    w, h = im.size
    pad = int(max(w, h) * 0.3)
    arr = np.asarray(im)
    arr = np.pad(arr, ((pad, pad), (pad, pad), (0, 0)), mode="reflect")
    pim = Image.fromarray(arr).rotate(angle, resample=Image.BICUBIC, expand=False)
    W, H = pim.size
    left, top = (W - w) // 2, (H - h) // 2
    return pim.crop((left, top, left + w, top + h))


def crop_zoom(im: Image.Image, scale_min: float, scale_max: float) -> Image.Image:
    """Random sub-crop resized back to original size (zoom-in + translation, no borders)."""
    w, h = im.size
    s = random.uniform(scale_min, scale_max)
    cw, ch = max(8, int(w * s)), max(8, int(h * s))
    x = random.randint(0, w - cw)
    y = random.randint(0, h - ch)
    return im.crop((x, y, x + cw, y + ch)).resize((w, h), Image.BICUBIC)


def augment_once(im: Image.Image) -> Image.Image:
    """Apply a random non-empty composition of geometric ops (no color changes)."""
    out = im
    applied = False
    if random.random() < 0.5:
        out = hflip(out); applied = True
    if random.random() < 0.7:
        out = rotate_reflect(out, random.uniform(-12, 12)); applied = True
    if random.random() < 0.8:
        out = crop_zoom(out, 0.80, 0.97); applied = True
    if not applied:  # guarantee at least one transform
        out = crop_zoom(out, 0.80, 0.97)
    return out


def load_sources() -> list[Path]:
    exclude = set()
    if EXCLUDE_JSON.exists():
        exclude = {n.lower() for n in json.loads(EXCLUDE_JSON.read_text())}
    srcs = []
    for p in sorted(SRC_HUMANS.glob("*.jpg")):
        name = p.name.lower()
        if "esp32_injected_v" in name:      # skip exact-duplicate copies
            continue
        if p.stem.lower() in exclude:       # skip EI test-set humans (no leakage)
            continue
        srcs.append(p)
    return srcs


def upload(paths: list[Path], api_key: str) -> tuple[int, int]:
    url = f"{INGESTION_URL}/api/training/files"
    headers = {"x-api-key": api_key, "x-label": "human", "x-disallow-duplicates": "1"}
    ok = fail = 0
    BATCH = 40
    sess = requests.Session()
    for i in range(0, len(paths), BATCH):
        batch = paths[i : i + BATCH]
        files, fhs = [], []
        try:
            for p in batch:
                fh = open(p, "rb"); fhs.append(fh)
                files.append(("data", (p.name, fh, "image/jpeg")))
            r = sess.post(url, headers=headers, files=files, timeout=300)
            if r.status_code == 200:
                ok += len(batch)
            else:
                fail += len(batch)
                print(f"  [FAIL] {r.status_code}: {r.text[:300]}")
        finally:
            for fh in fhs:
                fh.close()
        print(f"  uploaded {ok}/{len(paths)}")
        time.sleep(0.3)
    return ok, fail


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-count", type=int, default=420,
                    help="Number of augmented human images to generate")
    ap.add_argument("--no-upload", action="store_true", help="Generate only; don't upload")
    ap.add_argument("--api-key", default=os.environ.get("EI_API_KEY", ""))
    args = ap.parse_args()

    random.seed(SEED)
    if not SRC_HUMANS.is_dir():
        sys.exit(f"Source humans not found: {SRC_HUMANS}")

    sources = load_sources()
    print(f"Augmentation sources (training-only base humans): {len(sources)}")
    if not sources:
        sys.exit("No source images after exclusions.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.jpg"):
        old.unlink()

    # Sample distinct sources for max diversity; cycle if target > pool.
    order = sources[:]
    random.shuffle(order)
    made: list[Path] = []
    for i in range(args.target_count):
        src = order[i % len(order)]
        im = Image.open(src).convert("RGB")
        aug = augment_once(im)
        out = OUT_DIR / f"aug_geom_{i:04d}_{src.stem}.jpg"
        aug.save(out, "JPEG", quality=92)
        made.append(out)
    print(f"Generated {len(made)} augmented human images -> {OUT_DIR}")

    if args.no_upload:
        print("--no-upload set; skipping upload.")
        return
    if not args.api_key:
        sys.exit("Set EI_API_KEY to upload (or pass --no-upload).")

    print("Uploading augmented humans to EI training set (label=human, dedup on)...")
    ok, fail = upload(made, args.api_key)
    print(f"\nDone. Uploaded {ok}, failed {fail}.")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
