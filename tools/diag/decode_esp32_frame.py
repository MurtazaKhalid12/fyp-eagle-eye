#!/usr/bin/env python3
"""
Decode a base64-encoded 96x96x3 RGB888 frame dumped by the ESP32-CAM sketch
(`d` command) and run it through the int8 TFLite model. Reports prediction
and also saves the frame as PNG for visual sanity-checking.

Usage:
    1. In Arduino's Serial Monitor (line ending = NL+CR), send `d`.
    2. Copy the block between DUMP_BEGIN/DUMP_END (the single long base64 line
       is what you need; copy just that line).
    3. Save the base64 line to a file, e.g. C:\\tmp\\frame.b64
    4. python tools/diag/decode_esp32_frame.py C:\\tmp\\frame.b64

Or pass the base64 string directly:
    python tools/diag/decode_esp32_frame.py --b64 "AAA..."
"""

from __future__ import annotations

import argparse
import base64
import pathlib
import sys

import numpy as np
from PIL import Image
from ai_edge_litert.interpreter import Interpreter

REPO = pathlib.Path(__file__).resolve().parents[2]
MODEL_PATH = REPO / "models" / "model_v3_mobilenetv2_96_rgb_int8.tflite"
WIDTH = 96
HEIGHT = 96

CLASS_NAMES = ["human", "nonhuman"]  # alphabetic from EI


def decode_b64_payload(path: pathlib.Path | None, raw: str | None) -> bytes:
    if path:
        text = path.read_text(encoding="ascii", errors="ignore").strip()
    else:
        text = (raw or "").strip()
    text = "".join(text.split())
    return base64.b64decode(text)


def run_model(rgb: np.ndarray) -> dict:
    """rgb: (H, W, 3) uint8."""
    interp = Interpreter(model_path=str(MODEL_PATH))
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]

    in_scale, in_zp = inp["quantization"]
    out_scale, out_zp = out["quantization"]

    results = {}

    def predict(arr_u8: np.ndarray, tag: str):
        # EI's deployed fast-path: q = pixel - 128 (i.e. expects [0,1] floats)
        x_float = arr_u8.astype(np.float32) / 255.0
        q = np.clip(np.round(x_float / in_scale + in_zp), -128, 127).astype(np.int8)
        interp.set_tensor(inp["index"], q[np.newaxis, ...])
        interp.invoke()
        raw_out = interp.get_tensor(out["index"])[0]
        probs = (raw_out.astype(np.float32) - out_zp) * out_scale
        results[tag] = {CLASS_NAMES[i]: float(probs[i]) for i in range(len(CLASS_NAMES))}

    predict(rgb, "as_dumped")
    swapped = rgb[..., ::-1].copy()
    predict(swapped, "rb_swap")
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", type=pathlib.Path, help="file containing base64 payload")
    ap.add_argument("--b64", help="base64 payload directly")
    ap.add_argument("--out-png", type=pathlib.Path,
                    default=REPO / "tools" / "diag" / "last_esp32_frame.png")
    args = ap.parse_args()
    if not args.path and not args.b64:
        ap.error("Provide a path or --b64")

    raw = decode_b64_payload(args.path, args.b64)
    expected = WIDTH * HEIGHT * 3
    if len(raw) != expected:
        print(f"WARNING: payload size {len(raw)} != expected {expected}")
        if len(raw) > expected:
            raw = raw[:expected]
        else:
            raw = raw + bytes(expected - len(raw))

    rgb = np.frombuffer(raw, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3))

    Image.fromarray(rgb, mode="RGB").save(args.out_png)
    print(f"Saved decoded frame: {args.out_png}")

    print("\nFrame statistics:")
    for ci, ch in enumerate("RGB"):
        c = rgb[..., ci]
        print(f"  {ch}: mean={c.mean():6.2f}  min={c.min():3d}  max={c.max():3d}  std={c.std():5.2f}")

    print("\nTFLite prediction with [0,1] normalization (matches EI deployed path):")
    results = run_model(rgb)
    for tag, probs in results.items():
        print(f"  {tag:10s}: " + ", ".join(f"{k}={v:.3f}" for k, v in probs.items()))

    print("\nInterpretation:")
    print("  - If on-device prediction matches `as_dumped`: preprocessing is consistent,")
    print("    the model itself just doesn't generalize to this live scene.")
    print("  - If on-device says nonhuman but `rb_swap` predicts correctly: R<->B is swapped")
    print("    in the on-device pack; try the 'b' command on the sketch to confirm.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
