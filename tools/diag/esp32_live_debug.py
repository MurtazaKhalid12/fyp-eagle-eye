#!/usr/bin/env python3
"""
Live debug an ESP32-CAM running eagleeye_ei_runtime_rgb.ino.

Connects to the board over serial, sends the `d` command, captures the
base64 dump, decodes it to a PNG, runs the int8 TFLite model on the same
pixels with the same preprocessing the deployed runtime uses, and prints
side-by-side scores. Also reads back the on-device prediction lines so we
can verify whether PC and device agree.

Examples (PowerShell):
    python tools\\diag\\esp32_live_debug.py --port COM3
    python tools\\diag\\esp32_live_debug.py --port COM3 --every 5
    python tools\\diag\\esp32_live_debug.py --list

Install once:
    pip install pyserial
"""

from __future__ import annotations

import argparse
import base64
import pathlib
import re
import sys
import time
from typing import Optional

import numpy as np
from PIL import Image
from ai_edge_litert.interpreter import Interpreter

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.exit("pyserial not installed — run: pip install pyserial")

REPO = pathlib.Path(__file__).resolve().parents[2]
MODEL_PATH = REPO / "models" / "model_v3_mobilenetv2_96_rgb_int8.tflite"
WIDTH = 96
HEIGHT = 96
CLASS_NAMES = ["human", "nonhuman"]


def list_ports() -> None:
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("No serial ports detected.")
        return
    print("Available ports:")
    for p in ports:
        print(f"  {p.device:8s}  {p.description}")


def open_port(name: str, boot_wait_s: float) -> serial.Serial:
    s = serial.Serial(name, baudrate=115200, timeout=1)
    # Avoid holding ESP32 in reset/bootloader on some CH340 boards.
    s.dtr = False
    s.rts = False
    time.sleep(boot_wait_s)
    return s


def capture_dump(port: serial.Serial, timeout_s: float = 30.0) -> tuple[bytes, list[str], Optional[dict]]:
    """Send 'd' and read until DUMP_END. Returns (raw_rgb_bytes, log_lines, last_prediction_dict)."""
    start = time.time()
    next_request_at = start
    state = "wait_begin"
    log: list[str] = []
    payload = ""
    last_pred: Optional[dict] = None
    pred_buf: dict = {}

    while time.time() - start < timeout_s:
        # Send the command repeatedly. This handles the common case where opening
        # the serial port reset the ESP32 and the first command arrived too early.
        now = time.time()
        if state == "wait_begin" and now >= next_request_at:
            port.write(b"d\n")
            port.flush()
            next_request_at = now + 3.0

        line = port.readline().decode("ascii", errors="ignore").strip()
        if not line:
            continue
        log.append(line)
        print(f"[serial] {line}")

        if state == "wait_begin":
            if line.startswith("DUMP_BEGIN"):
                state = "in_dump"
            elif m := re.match(r"\s*(human|nonhuman):\s*([\d.]+)", line):
                pred_buf[m.group(1)] = float(m.group(2))
                if "human" in pred_buf and "nonhuman" in pred_buf:
                    last_pred = pred_buf.copy()
                    pred_buf = {}
        elif state == "in_dump":
            if line == "DUMP_END":
                break
            payload += line

    if state != "in_dump" and not payload:
        print("\nNever saw DUMP_BEGIN. Last serial lines:")
        for line in log[-25:]:
            print("  " + line)
        print("\nLikely causes:")
        print("  1. The updated sketch with the 'd' dump command is not flashed.")
        print("  2. Arduino Serial Monitor is still open on the same COM port.")
        print("  3. The board reset on serial open and needs a longer --boot-wait.")
        print("  4. Wrong COM port.")
        raise RuntimeError("Never saw DUMP_BEGIN")

    raw = base64.b64decode("".join(payload.split()))
    return raw, log, last_pred


def run_model(rgb: np.ndarray) -> dict:
    interp = Interpreter(model_path=str(MODEL_PATH))
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]
    in_scale, in_zp = inp["quantization"]
    out_scale, out_zp = out["quantization"]
    x = rgb.astype(np.float32) / 255.0
    q = np.clip(np.round(x / in_scale + in_zp), -128, 127).astype(np.int8)
    interp.set_tensor(inp["index"], q[np.newaxis, ...])
    interp.invoke()
    raw_out = interp.get_tensor(out["index"])[0]
    probs = (raw_out.astype(np.float32) - out_zp) * out_scale
    return {CLASS_NAMES[i]: float(probs[i]) for i in range(len(CLASS_NAMES))}


def channel_stats(rgb: np.ndarray) -> None:
    for ci, ch in enumerate("RGB"):
        c = rgb[..., ci]
        print(f"   {ch}: mean={c.mean():6.2f}  min={int(c.min()):3d}  max={int(c.max()):3d}  std={c.std():5.2f}")
    r, g, b = rgb[..., 0].mean(), rgb[..., 1].mean(), rgb[..., 2].mean()
    print(f"   G/R={g/max(r,1e-3):.2f}   G/B={g/max(b,1e-3):.2f}  "
          f"(training: G/R~0.98, G/B~1.01 — values further from 1.0 = colour cast)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--every", type=int, default=0,
                    help="Repeat every N seconds (0 = single shot)")
    ap.add_argument("--png", type=pathlib.Path,
                    default=REPO / "tools" / "diag" / "last_esp32_frame.png")
    ap.add_argument("--open", action="store_true",
                    help="Open the saved PNG with the default OS viewer")
    ap.add_argument("--boot-wait", type=float, default=5.0,
                    help="Seconds to wait after opening serial before requesting a frame")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="Seconds to wait for DUMP_BEGIN/DUMP_END")
    args = ap.parse_args()

    if args.list:
        list_ports()
        return 0
    if not args.port:
        list_ports()
        ap.error("--port is required (use --list to see options)")

    print(f"Opening {args.port} @ 115200...")
    port = open_port(args.port, args.boot_wait)

    def one_shot() -> None:
        print("\n[..] Requesting frame dump...")
        raw, log, device_pred = capture_dump(port, args.timeout)
        expected = WIDTH * HEIGHT * 3
        if len(raw) < expected:
            raw = raw + bytes(expected - len(raw))
        rgb = np.frombuffer(raw[:expected], dtype=np.uint8).reshape((HEIGHT, WIDTH, 3))
        Image.fromarray(rgb, mode="RGB").save(args.png)

        print(f"[OK] Saved frame: {args.png}")
        print("Frame channel statistics:")
        channel_stats(rgb)

        print("\nPC inference (same int8 model, same preprocessing as runtime):")
        probs = run_model(rgb)
        for k, v in probs.items():
            print(f"   {k}: {v:.3f}")
        pred = max(probs, key=probs.get)
        print(f"   -> predicted: {pred}")

        if device_pred:
            print("\nOn-device last prediction (from serial log):")
            for k, v in device_pred.items():
                print(f"   {k}: {v:.3f}")
            dev = max(device_pred, key=device_pred.get)
            print(f"   -> predicted: {dev}")
            agree = (dev == pred)
            print(f"\nAgreement: {'YES' if agree else 'NO'}")
            if agree and pred == "nonhuman":
                print("Both agree the captured frame doesn't look like a human to the model.")
                print("Look at the PNG — is the subject framed/lit similarly to training samples?")
            elif not agree:
                print("PC and device disagree. The bug is in how the device feeds pixels to the model")
                print("(unlikely given our cb is straightforward), or quantization differs.")
        if args.open:
            import os, platform, subprocess
            if platform.system() == "Windows":
                os.startfile(str(args.png))
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(args.png)])
            else:
                subprocess.run(["xdg-open", str(args.png)])

    one_shot()
    while args.every > 0:
        try:
            time.sleep(args.every)
            one_shot()
        except KeyboardInterrupt:
            print("\nbye")
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
