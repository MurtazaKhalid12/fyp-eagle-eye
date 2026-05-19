#!/usr/bin/env python3
"""
Evaluate the trained int8 TFLite model on samples downloaded directly from
the Edge Impulse project. Tries several preprocessing pipelines so we know
exactly what the model "sees".

Pipelines tested:
  - bilinear-fitshort + [0,1] norm  (matches what the deployed runtime does)
  - bilinear-resize  + [0,1] norm   (no center crop, just resize-to-square)
  - bilinear-fitshort + [-1,1] norm (MobileNetV2 stock)

If the model is good, the first pipeline (which mimics what `extract_image_features_quantized`
does on device) should match the reported 88% validation accuracy.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

import numpy as np
import requests
from PIL import Image
from ai_edge_litert.interpreter import Interpreter

PROJECT_ID = 1000575
LEARN_ID = 3
HOST = "https://studio.edgeimpulse.com/v1"
CLASS_NAMES = ["human", "nonhuman"]

REPO = pathlib.Path(__file__).resolve().parents[2]
MODEL = REPO / "models" / "model_v3_mobilenetv2_96_rgb_int8.tflite"
CACHE = REPO / "models" / "eval_cache"


def get_session(api_key: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"x-api-key": api_key})
    return s


def list_samples(session: requests.Session, label: str, want: int) -> list[dict]:
    """Paginate raw-data until we have at least `want` of `label`."""
    out: list[dict] = []
    offset = 0
    while len(out) < want and offset < 5000:
        r = session.get(f"{HOST}/api/{PROJECT_ID}/raw-data",
                        params={"category": "training", "limit": 200, "offset": offset},
                        timeout=30)
        r.raise_for_status()
        samples = r.json().get("samples", [])
        if not samples:
            break
        out.extend(s for s in samples if s["label"] == label)
        offset += 200
    return out[:want]


def download_image(session: requests.Session, sample_id: int, label: str) -> pathlib.Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    fp = CACHE / f"{label}_{sample_id}.png"
    if fp.exists() and fp.stat().st_size > 0:
        return fp
    r = session.get(f"{HOST}/api/{PROJECT_ID}/raw-data/{sample_id}/image", timeout=30)
    if r.status_code == 200:
        fp.write_bytes(r.content)
    return fp


def resize_fitshort_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    sw, sh = img.size
    ratio = max(w / sw, h / sh)
    nw, nh = int(round(sw * ratio)), int(round(sh * ratio))
    img2 = img.resize((nw, nh), Image.BILINEAR)
    x0 = (nw - w) // 2
    y0 = (nh - h) // 2
    return img2.crop((x0, y0, x0 + w, y0 + h))


def predict(interp: Interpreter, inp, out, arr_u8: np.ndarray, norm: str) -> np.ndarray:
    if norm == "0to1":
        x = arr_u8.astype(np.float32) / 255.0
    elif norm == "m1to1":
        x = arr_u8.astype(np.float32) / 127.5 - 1.0
    elif norm == "raw":
        x = arr_u8.astype(np.float32)
    else:
        raise ValueError(norm)
    in_scale, in_zp = inp["quantization"]
    out_scale, out_zp = out["quantization"]
    q = np.clip(np.round(x / in_scale + in_zp), -128, 127).astype(np.int8)
    interp.set_tensor(inp["index"], q[np.newaxis, ...])
    interp.invoke()
    raw = interp.get_tensor(out["index"])[0]
    return (raw.astype(np.float32) - out_zp) * out_scale


def evaluate(n_per_class: int = 60) -> None:
    api_key = os.environ.get("EI_API_KEY", "")
    if not api_key:
        sys.exit("Set EI_API_KEY first")
    session = get_session(api_key)

    print(f"Downloading {n_per_class} samples per class from project {PROJECT_ID}...")
    samples = []
    for label in ("human", "nonhuman"):
        sub = list_samples(session, label, n_per_class)
        print(f"  {label}: {len(sub)} samples")
        for s in sub:
            samples.append((s["id"], label))

    interp = Interpreter(model_path=str(MODEL))
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]

    print("\nDownloading + running inference...")
    results: dict[str, dict] = {
        "fitshort_0to1": {"correct": 0, "by_class": {"human": [0, 0], "nonhuman": [0, 0]},
                          "scores": {"human": [], "nonhuman": []}},
        "resize_0to1":   {"correct": 0, "by_class": {"human": [0, 0], "nonhuman": [0, 0]},
                          "scores": {"human": [], "nonhuman": []}},
        "fitshort_m1to1": {"correct": 0, "by_class": {"human": [0, 0], "nonhuman": [0, 0]},
                           "scores": {"human": [], "nonhuman": []}},
    }
    total = 0

    for sample_id, label in samples:
        fp = download_image(session, sample_id, label)
        if not fp.exists() or fp.stat().st_size == 0:
            continue
        img = Image.open(fp).convert("RGB")
        total += 1

        for pipeline in results:
            if pipeline.startswith("fitshort"):
                arr = np.array(resize_fitshort_crop(img, 96, 96))
            else:
                arr = np.array(img.resize((96, 96), Image.BILINEAR))
            norm = pipeline.split("_")[1]
            probs = predict(interp, inp, out, arr, norm)
            pred_idx = int(np.argmax(probs))
            pred = CLASS_NAMES[pred_idx]
            r = results[pipeline]
            r["scores"][label].append(float(probs[CLASS_NAMES.index(label)]))
            if pred == label:
                r["correct"] += 1
                r["by_class"][label][0] += 1
            r["by_class"][label][1] += 1

    if total == 0:
        sys.exit("No samples downloaded")

    print(f"\nTotal evaluated: {total}\n")
    for pipeline, r in results.items():
        acc = 100 * r["correct"] / total
        h_correct, h_total = r["by_class"]["human"]
        n_correct, n_total = r["by_class"]["nonhuman"]
        h_acc = 100 * h_correct / h_total if h_total else 0
        n_acc = 100 * n_correct / n_total if n_total else 0
        h_mean = np.mean(r["scores"]["human"]) if r["scores"]["human"] else 0
        n_mean = np.mean(r["scores"]["nonhuman"]) if r["scores"]["nonhuman"] else 0
        print(f"== {pipeline} ==")
        print(f"   overall acc: {r['correct']}/{total} = {acc:.1f}%")
        print(f"   human   recall: {h_correct}/{h_total} = {h_acc:.1f}%  | mean confidence on true human: {h_mean:.3f}")
        print(f"   nonhuman recall: {n_correct}/{n_total} = {n_acc:.1f}%  | mean confidence on true nonhuman: {n_mean:.3f}")
        print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    args = ap.parse_args()
    evaluate(args.n)
