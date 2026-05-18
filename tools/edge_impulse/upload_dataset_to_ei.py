#!/usr/bin/env python3
"""
Upload Humans / NonHuman image folders to Edge Impulse with labels from folder names.

No labeling in Studio required: each folder is uploaded with x-label set via the
Ingestion API (https://docs.edgeimpulse.com/apis/ingestion).

Setup:
  1. Create an Edge Impulse project (Image classification).
  2. Dashboard → Keys → copy API key.
  3. pip install -r tools/edge_impulse/requirements.txt
  4. set EI_API_KEY=ei_...   (Windows)  or  export EI_API_KEY=ei_...

Usage:
  python tools/edge_impulse/upload_dataset_to_ei.py
  python tools/edge_impulse/upload_dataset_to_ei.py --dataset sketchboard/dataset
  python tools/edge_impulse/upload_dataset_to_ei.py --dry-run
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install requests: pip install -r tools/edge_impulse/requirements.txt", file=sys.stderr)
    sys.exit(1)

INGESTION_URL = "https://ingestion.edgeimpulse.com"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}

# Folder name on disk -> Edge Impulse label (change if your EI project uses other names)
DEFAULT_LABEL_MAP = {
    "Humans": "human",
    "NonHuman": "nonhuman",
    "humans": "human",
    "nonhuman": "nonhuman",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_dataset() -> Path:
    candidates = [
        repo_root() / "sketchboard" / "dataset",
        repo_root()
        / "datasets"
        / "Human_Detection_Dataset"
        / "Human_Detection_Dataset_2"
        / "Human_Detection_Dataset",
        repo_root() / "datasets" / "Human_Detection_Dataset" / "Human_Detection_Dataset",
    ]
    for path in candidates:
        if path.is_dir() and any((path / name).is_dir() for name in DEFAULT_LABEL_MAP):
            return path
    return candidates[0]


def collect_images(class_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in class_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            files.append(path)
    return sorted(files)


def chunk_list(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def upload_batch(
    paths: list[Path],
    label: str,
    api_key: str,
    endpoint: str,
    session: requests.Session,
    disallow_duplicates: bool,
) -> tuple[int, int]:
    """Returns (ok_count, fail_count)."""
    url = f"{INGESTION_URL}/api/{endpoint}/files"
    headers = {
        "x-api-key": api_key,
        "x-label": label,
    }
    if disallow_duplicates:
        headers["x-disallow-duplicates"] = "1"

    files = []
    opened = []
    try:
        for path in paths:
            mime, _ = mimetypes.guess_type(str(path))
            if not mime or not mime.startswith("image/"):
                mime = "image/jpeg"
            fh = open(path, "rb")
            opened.append(fh)
            files.append(("data", (path.name, fh, mime)))

        resp = session.post(url, headers=headers, files=files, timeout=300)
        if resp.status_code == 200:
            return len(paths), 0
        print(f"  [FAIL] HTTP {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
        return 0, len(paths)
    except requests.RequestException as e:
        print(f"  [FAIL] {e}", file=sys.stderr)
        return 0, len(paths)
    finally:
        for fh in opened:
            fh.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload Humans/NonHuman folders to Edge Impulse (labels from folders)."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Root with Humans/ and NonHuman/ subfolders",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("EI_API_KEY", ""),
        help="Edge Impulse API key (or set EI_API_KEY)",
    )
    parser.add_argument(
        "--humans-folder",
        default="Humans",
        help="Subfolder name for human class",
    )
    parser.add_argument(
        "--nonhuman-folder",
        default="NonHuman",
        help="Subfolder name for non-human class",
    )
    parser.add_argument(
        "--humans-label",
        default=None,
        help="Edge Impulse label for humans (default: human)",
    )
    parser.add_argument(
        "--nonhuman-label",
        default=None,
        help="Edge Impulse label for non-humans (default: nonhuman)",
    )
    parser.add_argument(
        "--endpoint",
        choices=("training", "testing"),
        default="training",
        help="training or testing dataset in EI",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Images per HTTP request (max 1000)",
    )
    parser.add_argument(
        "--disallow-duplicates",
        action="store_true",
        help="Skip files already in the EI dataset (hash check)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files only; do not upload",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max images per class (0 = all)",
    )
    args = parser.parse_args()

    dataset = (args.dataset or default_dataset()).resolve()
    if not dataset.is_dir():
        print(f"Dataset not found: {dataset}", file=sys.stderr)
        sys.exit(1)

    humans_dir = dataset / args.humans_folder
    nonhuman_dir = dataset / args.nonhuman_folder
    if not humans_dir.is_dir() or not nonhuman_dir.is_dir():
        print(
            f"Expected folders:\n  {humans_dir}\n  {nonhuman_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    humans_label = args.humans_label or DEFAULT_LABEL_MAP.get(args.humans_folder, "human")
    nonhuman_label = args.nonhuman_label or DEFAULT_LABEL_MAP.get(
        args.nonhuman_folder, "nonhuman"
    )

    classes = [
        (humans_dir, humans_label),
        (nonhuman_dir, nonhuman_label),
    ]

    if not args.dry_run and not args.api_key:
        print(
            "Missing API key. Set EI_API_KEY or pass --api-key ei_...",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.batch_size < 1 or args.batch_size > 1000:
        print("--batch-size must be between 1 and 1000", file=sys.stderr)
        sys.exit(1)

    print(f"Dataset root: {dataset}")
    print(f"Endpoint: /api/{args.endpoint}/files")
    print(f"Labels: {humans_label!r}, {nonhuman_label!r}")
    print()

    session = requests.Session()
    total_ok = total_fail = 0

    for class_dir, label in classes:
        images = collect_images(class_dir)
        if args.limit > 0:
            images = images[: args.limit]
        print(f"=== {class_dir.name} -> EI label {label!r} ({len(images)} images) ===")
        if not images:
            continue

        if args.dry_run:
            for p in images[:5]:
                print(f"  would upload: {p.name}")
            if len(images) > 5:
                print(f"  ... and {len(images) - 5} more")
            continue

        for batch_idx, batch in enumerate(chunk_list(images, args.batch_size), start=1):
            ok, fail = upload_batch(
                batch,
                label,
                args.api_key,
                args.endpoint,
                session,
                args.disallow_duplicates,
            )
            total_ok += ok
            total_fail += fail
            print(f"  batch {batch_idx}: uploaded {ok}/{len(batch)}")
            time.sleep(0.3)

    if args.dry_run:
        print("\nDry run only — no uploads sent.")
        return

    print(f"\nDone. Uploaded: {total_ok}, failed: {total_fail}")
    if total_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
