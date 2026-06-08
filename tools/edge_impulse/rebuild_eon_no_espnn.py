#!/usr/bin/env python3
"""
Rebuild the CURRENT trained EI model as an EON-compiled Arduino library with
ESP-NN disabled. No retraining — same model/weights, just a different build:
  - engine = tflite-eon  (EON Compiler: compiled graph, no interpreter)
  - ESP-NN patched OFF    (ESP32-CAM S1 cannot use ESP-NN correctly)

EON lowers RAM/flash a lot and shaves a little off inference; predictions are
identical to the tflite build because the kernels are unchanged.

Usage (PowerShell):
  $env:EI_API_KEY = "ei_..."
  python tools/edge_impulse/rebuild_eon_no_espnn.py
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

import requests
from edgeimpulse_api import (
    ApiClient,
    BuildOnDeviceModelRequest,
    Configuration,
    DeploymentApi,
    JobsApi,
)

PROJECT_ID = 1000575
API_HOST = "https://studio.edgeimpulse.com/v1"
ENGINE = "tflite-eon"  # EON Compiler (speed-oriented). Use "tflite-eon-ram-optimized" for min RAM.

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "third_party"
RAW_ZIP = OUT / "ei_arduino_library_rgb96_mobilenetv1_a2_eon_raw.zip"
ZIP = OUT / "ei_arduino_library_rgb96_mobilenetv1_a2_eon_no_espnn.zip"
UNPACK = OUT / "ei_arduino_library_rgb96_mobilenetv1_a2_eon_no_espnn"


def need_key() -> str:
    k = os.environ.get("EI_API_KEY", "")
    return k or sys.exit("Set EI_API_KEY before running.")


def poll(jobs: JobsApi, jid: int, label: str, tmin: int = 25) -> None:
    start = time.time()
    while True:
        if time.time() - start > tmin * 60:
            sys.exit(f"[{label}] timeout")
        job = jobs.get_job_status(project_id=PROJECT_ID, job_id=jid).job
        if job.finished:
            ok = bool(job.finished_successful)
            print(f"[{label}] finished success={ok}", flush=True)
            if not ok:
                sys.exit(f"[{label}] failed")
            return
        print(f"[{label}] running ({int(time.time()-start)}s)...", flush=True)
        time.sleep(15)


def disable_esp_nn(lib_dir: Path) -> None:
    cfg = lib_dir / "src" / "edge-impulse-sdk" / "classifier" / "ei_classifier_config.h"
    text = cfg.read_text(encoding="utf-8")
    start = text.index("#ifndef EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN")
    end = text.index("#if EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN == 1", start)
    replacement = (
        "#ifndef EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN\n"
        "    // EagleEye: ESP32-CAM S1 cannot use ESP-NN (saturated output).\n"
        "    #define EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN      0\n"
        "#endif"
    )
    cfg.write_text(text[:start] + replacement + "\n\n" + text[end:], encoding="utf-8")


def zip_dir(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in src_dir.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(src_dir.parent))


def main() -> None:
    key = need_key()
    client = ApiClient(Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": key}))
    jobs = JobsApi(client)
    deploy = DeploymentApi(client)

    print(f"Building Arduino library with EON Compiler (engine={ENGINE}, int8)...", flush=True)
    req = BuildOnDeviceModelRequest.from_dict({"engine": ENGINE, "modelType": "int8"})
    resp = jobs.build_on_device_model_job(
        project_id=PROJECT_ID, type="arduino", build_on_device_model_request=req
    )
    poll(jobs, resp.id, "build-eon")

    hist = deploy.list_deployment_history(project_id=PROJECT_ID, limit=1)
    deployments = getattr(hist, "deployments", None) or []
    if not deployments:
        sys.exit("No deployment in history")
    ver = deployments[0].deployment_version
    url = f"{API_HOST}/api/{PROJECT_ID}/deployment/history/{ver}/download"
    r = requests.get(url, headers={"x-api-key": key}, timeout=600)
    r.raise_for_status()

    OUT.mkdir(parents=True, exist_ok=True)
    RAW_ZIP.write_bytes(r.content)
    print(f"  Raw EON zip: {RAW_ZIP} ({len(r.content):,} bytes)", flush=True)

    if UNPACK.exists():
        shutil.rmtree(UNPACK)
    UNPACK.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        zf.extractall(UNPACK)
    lib_dirs = [p for p in UNPACK.iterdir() if p.is_dir()]
    if not lib_dirs:
        sys.exit("Downloaded zip had no library folder")
    lib_dir = lib_dirs[0]
    disable_esp_nn(lib_dir)
    zip_dir(lib_dir, ZIP)

    print("=" * 64, flush=True)
    print(" EON + ESP-NN-disabled Arduino library ready", flush=True)
    print(f"   deploy version : {ver}", flush=True)
    print(f"   engine         : {ENGINE} (EON Compiler)", flush=True)
    print(f"   library zip    : {ZIP}", flush=True)
    print(f"   include        : #include <{lib_dir.name}.h>", flush=True)
    print("=" * 64, flush=True)


if __name__ == "__main__":
    main()
