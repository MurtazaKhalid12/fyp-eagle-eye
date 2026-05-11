#!/usr/bin/env python3
"""
Web UI to capture hard examples while the same TFLite model runs on the PC.

Fetches JPEG frames from ESP32-CAM (GET /capture), preprocesses like firmware
(center square crop, 48x48 greyscale, int8 = gray - 128), runs inference, then
lets you save the *original* JPEG into Humans/ or NonHuman/ for retraining.

Usage (defaults point at this repo’s dataset + tiny_human_model.tflite):
  cd firmware/tools/ai_assisted_capturer
  pip install -r requirements.txt
  python web_hard_capturer.py --camera http://<ESP32_IP>

Open http://127.0.0.1:8765 in a browser.
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
from flask import Flask, Response, jsonify, request
from PIL import Image

try:
    import tensorflow as tf
except ImportError as e:
    print("Install TensorFlow: pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1) from e

# --- Match firmware/eagleeye-main.ino ---
IMG_W = 48
IMG_H = 48


def center_square_crop_rgb(arr: np.ndarray) -> np.ndarray:
    """RGB uint8 HxWx3 -> center square crop (uses full height as square side)."""
    h, w = arr.shape[0], arr.shape[1]
    side = min(h, w)
    ox = (w - side) // 2
    oy = (h - side) // 2
    return arr[oy : oy + side, ox : ox + side, :]


def rgb_to_model_input(rgb: np.ndarray) -> np.ndarray:
    """48x48 RGB -> int8 NHWC matching ESP32 resize_rgb565_to_greyscale."""
    pil = Image.fromarray(rgb).resize((IMG_W, IMG_H), Image.BILINEAR)
    x = np.asarray(pil, dtype=np.uint8)
    r = x[:, :, 0].astype(np.int32)
    g = x[:, :, 1].astype(np.int32)
    b = x[:, :, 2].astype(np.int32)
    gray = ((r * 77 + g * 150 + b * 29) >> 8).astype(np.int8)
    inp = (gray.astype(np.int32) - 128).astype(np.int8)
    return inp.reshape(1, IMG_H, IMG_W, 1)


def jpeg_bytes_to_model_input(jpeg: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    arr = np.asarray(img, dtype=np.uint8)
    crop = center_square_crop_rgb(arr)
    return rgb_to_model_input(crop)


class TfliteHumanDetector:
    def __init__(self, model_path: Path):
        self.interpreter = tf.lite.Interpreter(model_path=str(model_path))
        self.interpreter.allocate_tensors()
        self.in_det = self.interpreter.get_input_details()[0]
        self.out_det = self.interpreter.get_output_details()[0]

    def predict_int8(self, x_int8: np.ndarray) -> tuple[int, int]:
        self.interpreter.set_tensor(self.in_det["index"], x_int8)
        self.interpreter.invoke()
        out = self.interpreter.get_tensor(self.out_det["index"]).astype(np.int32).flatten()
        if out.size != 2:
            raise RuntimeError(f"Expected 2 output logits, got shape {out.shape}")
        return int(out[0]), int(out[1])


app = Flask(__name__)
_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "last_jpeg": None,
    "last_human": 0,
    "last_nonhuman": 0,
    "last_predicted_human": False,
    "last_error": None,
    "last_fetch_ms": 0.0,
}

_detector: TfliteHumanDetector | None = None
_camera_url: str = ""
_human_dir: Path = Path(".")
_nonhuman_dir: Path = Path(".")


def fetch_capture_jpeg() -> bytes:
    url = _camera_url.rstrip("/") + "/capture"
    req = Request(url, headers={"User-Agent": "EagleEye-hard-capturer/1.0"})
    with urlopen(req, timeout=10) as resp:
        return resp.read()


def run_inference_on_jpeg(jpeg: bytes) -> tuple[int, int, bool]:
    assert _detector is not None
    x = jpeg_bytes_to_model_input(jpeg)
    h, n = _detector.predict_int8(x)
    predicted = h > n and h > 10
    return h, n, predicted


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>EagleEye — hard example capturer</title>
  <style>
    :root { font-family: system-ui, sans-serif; background: #111; color: #eee; }
    body { max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-size: 1.25rem; }
    .row { display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-start; }
    img { max-width: 100%; background: #222; border-radius: 8px; }
    .panel { background: #1e1e1e; padding: 1rem; border-radius: 8px; flex: 1; min-width: 260px; }
    .scores { font-family: ui-monospace, monospace; font-size: 1.1rem; margin: 0.5rem 0; }
    .human { color: #7fdbff; }
    .non { color: #ff9f7a; }
    button {
      padding: 0.75rem 1rem; margin: 0.35rem 0.35rem 0 0; border: none; border-radius: 6px;
      cursor: pointer; font-weight: 600; font-size: 0.95rem;
    }
    .btn-human { background: #2a7d4a; color: #fff; }
    .btn-human:hover { background: #359658; }
    .btn-non { background: #8b3a3a; color: #fff; }
    .btn-non:hover { background: #a84848; }
    .btn-refresh { background: #444; color: #fff; }
    .hint { font-size: 0.85rem; color: #aaa; margin-top: 0.75rem; line-height: 1.4; }
    .err { color: #f66; margin-top: 0.5rem; }
    .ok { color: #8d8; margin-top: 0.5rem; }
    #status { min-height: 1.5rem; }
  </style>
</head>
<body>
  <h1>EagleEye — web hard-data capturer</h1>
  <p class="hint">Live frame from your camera; model output matches firmware (int8 scores). Use the buttons when the model is wrong.</p>
  <div class="row">
    <div class="panel">
      <img id="frame" alt="latest frame" />
      <p class="hint">Auto-refresh every 600 ms (pause if your camera struggles).</p>
      <label><input type="checkbox" id="auto"/> Auto refresh</label>
      <button type="button" class="btn-refresh" id="btnRefresh">Refresh now</button>
    </div>
    <div class="panel">
      <div class="scores">
        <span class="human">Human</span> score: <span id="hScore">—</span><br/>
        <span class="non">NonHuman</span> score: <span id="nScore">—</span><br/>
        Model says: <strong id="pred">—</strong><br/>
        Fetch: <span id="fetchMs">—</span> ms
      </div>
      <button type="button" class="btn-human" id="btnHuman">Save as HUMAN</button>
      <button type="button" class="btn-non" id="btnNon">Save as NON-HUMAN</button>
      <p class="hint"><strong>Save as HUMAN</strong> — scene really has a person but the model missed (false negative / empty prediction).<br/>
      <strong>Save as NON-HUMAN</strong> — model fired “human” but it’s wrong (false positive).</p>
      <div id="status"></div>
    </div>
  </div>
<script>
const frameEl = document.getElementById('frame');
const hEl = document.getElementById('hScore');
const nEl = document.getElementById('nScore');
const predEl = document.getElementById('pred');
const fetchEl = document.getElementById('fetchMs');
const statusEl = document.getElementById('status');
const autoEl = document.getElementById('auto');
let timer = null;

function setStatus(msg, ok) {
  statusEl.textContent = msg || '';
  statusEl.className = ok ? 'ok' : 'err';
}

async function refresh() {
  statusEl.textContent = '';
  statusEl.className = '';
  try {
    const r = await fetch('/api/frame');
    const j = await r.json();
    if (!j.ok) {
      setStatus(j.error || 'Request failed', false);
      return;
    }
    frameEl.src = 'data:image/jpeg;base64,' + j.image_b64;
    hEl.textContent = j.human;
    nEl.textContent = j.non_human;
    predEl.textContent = j.predicted_human ? 'HUMAN' : 'not human';
    predEl.style.color = j.predicted_human ? '#7fdbff' : '#aaa';
    fetchEl.textContent = j.fetch_ms != null ? Math.round(j.fetch_ms) : '—';
  } catch (e) {
    setStatus(String(e), false);
  }
}

async function saveLabel(label) {
  try {
    const r = await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label }),
    });
    const j = await r.json();
    if (!j.ok) {
      setStatus(j.error || 'Save failed', false);
      return;
    }
    setStatus('Saved ' + j.path, true);
  } catch (e) {
    setStatus(String(e), false);
  }
}

document.getElementById('btnRefresh').onclick = refresh;
document.getElementById('btnHuman').onclick = () => saveLabel('human');
document.getElementById('btnNon').onclick = () => saveLabel('nonhuman');
autoEl.checked = true;
autoEl.onchange = () => {
  if (timer) { clearInterval(timer); timer = null; }
  if (autoEl.checked) timer = setInterval(refresh, 600);
};
refresh();
if (autoEl.checked) timer = setInterval(refresh, 600);
</script>
</body>
</html>
"""


@app.route("/")
def index() -> Response:
    return Response(INDEX_HTML, mimetype="text/html")


@app.route("/api/frame", methods=["GET"])
def api_frame():
    t0 = time.perf_counter()
    try:
        jpeg = fetch_capture_jpeg()
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        with _state_lock:
            _state["last_error"] = str(e)
        return jsonify({"ok": False, "error": f"Camera fetch failed: {e}"})
    fetch_ms = (time.perf_counter() - t0) * 1000.0
    try:
        h, n, predicted = run_inference_on_jpeg(jpeg)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Inference failed: {e}"})
    with _state_lock:
        _state["last_jpeg"] = jpeg
        _state["last_human"] = h
        _state["last_nonhuman"] = n
        _state["last_predicted_human"] = predicted
        _state["last_fetch_ms"] = fetch_ms
        _state["last_error"] = None
    b64 = base64.standard_b64encode(jpeg).decode("ascii")
    return jsonify(
        {
            "ok": True,
            "image_b64": b64,
            "human": h,
            "non_human": n,
            "predicted_human": predicted,
            "fetch_ms": fetch_ms,
        }
    )


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json(force=True, silent=True) or {}
    label = (data.get("label") or "").strip().lower()
    if label not in ("human", "nonhuman"):
        return jsonify({"ok": False, "error": 'label must be "human" or "nonhuman"'})
    with _state_lock:
        jpeg = _state["last_jpeg"]
    if not jpeg:
        return jsonify({"ok": False, "error": "No frame yet — wait for a successful refresh."})
    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond // 1000:03d}"
    if label == "human":
        dest_dir = _human_dir
        prefix = "esp32_human"
    else:
        dest_dir = _nonhuman_dir
        prefix = "esp32_nonhuman"
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{prefix}_{ts}.jpg"
    path = dest_dir / fname
    path.write_bytes(jpeg)
    return jsonify({"ok": True, "path": str(path)})


def main() -> None:
    global _detector, _camera_url, _human_dir, _nonhuman_dir
    here = Path(__file__).resolve().parent
    # .../firmware/tools/ai_assisted_capturer -> repo root is four levels up
    repo_root = here.parent.parent.parent.parent
    ds_base = (
        repo_root
        / "datasets"
        / "Human_Detection_Dataset"
        / "Human_Detection_Dataset_2"
        / "Human_Detection_Dataset"
    )
    parser = argparse.ArgumentParser(description="Web hard-example capturer for EagleEye")
    parser.add_argument(
        "--camera",
        default="http://192.168.4.1",
        help="ESP32 base URL (no trailing /capture)",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=repo_root
        / "model-training"
        / "exported-models"
        / "tiny_human_model.tflite",
        help="Same .tflite you deploy on the ESP32",
    )
    parser.add_argument("--human-dir", type=Path, default=ds_base / "Humans")
    parser.add_argument("--nonhuman-dir", type=Path, default=ds_base / "NonHuman")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not args.model.is_file():
        print(f"Model not found: {args.model}", file=sys.stderr)
        sys.exit(1)

    _detector = TfliteHumanDetector(args.model)
    _camera_url = args.camera.rstrip("/")
    _human_dir = args.human_dir.resolve()
    _nonhuman_dir = args.nonhuman_dir.resolve()

    print(f"Model: {args.model}")
    print(f"Camera: {_camera_url}/capture")
    print(f"Humans -> {_human_dir}")
    print(f"NonHuman -> {_nonhuman_dir}")
    print(f"Open http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
