#!/usr/bin/env python3
"""
EagleEye — Hard Negative Capturer (WiFi Mode)
Receives JPEG captures POSTed by the ESP32-CAM and saves them
into the correct dataset folder (Humans / NonHuman).

Usage:
    python collect_hard_negatives.py
"""

import os
import sys
import datetime
import logging
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("Missing flask!  Run:  pip install flask")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────
#  Dataset paths
# ──────────────────────────────────────────────────────────────
def find_dataset_dir() -> Path:
    # Sketchboard-only receiver: saved captures stay inside sketchboard/dataset.
    return Path(__file__).resolve().parents[2] / "dataset"

DS_ROOT     = find_dataset_dir()
HUMAN_DIR   = DS_ROOT / "Humans"
NONHUMAN_DIR = DS_ROOT / "NonHuman"
HUMAN_DIR.mkdir(parents=True, exist_ok=True)
NONHUMAN_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────
#  Flask app
# ──────────────────────────────────────────────────────────────
log = logging.getLogger("werkzeug")
log.setLevel(logging.WARNING)        # hide the per-request spam

app = Flask(__name__)

@app.route("/save", methods=["POST"])
def save():
    label = request.args.get("label", "").strip().lower()
    if label not in ("human", "nonhuman"):
        return jsonify(ok=False, error="label must be 'human' or 'nonhuman'"), 400

    data = request.data
    if not data:
        return jsonify(ok=False, error="empty body"), 400

    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    dest = HUMAN_DIR if label == "human" else NONHUMAN_DIR
    name = f"esp32_{label}_{ts}.jpg"
    path = dest / name
    path.write_bytes(data)

    print(f"[SAVED] {label.upper():>8s} → {path.name}")
    return f"Saved {name}", 200


if __name__ == "__main__":
    print("\n" + "=" * 52)
    print("   EagleEye  —  Hard Negative Capturer (WiFi)")
    print("=" * 52)
    print(f"  Humans   → {HUMAN_DIR}")
    print(f"  NonHuman → {NONHUMAN_DIR}")
    print("\n  Waiting for captures from the ESP32-CAM...")
    print("  (Flash hard_negative_capturer.ino, then open")
    print("   http://<ESP32-IP> in your browser)\n")
    app.run(host="0.0.0.0", port=8000, threaded=True, use_reloader=False)
