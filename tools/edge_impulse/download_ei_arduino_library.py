#!/usr/bin/env python3
"""
Download the full Edge Impulse Arduino library (with ESP-NN) for EagleEye
project 1000575 and unpack it next to the firmware sketch.

This is Option A: use Edge Impulse's official runtime + ESP-NN kernels via
`run_classifier()` instead of dropping the raw .tflite into TensorFlowLite_ESP32.

Usage (PowerShell):
  $env:EI_API_KEY = "ei_..."           # admin/api key for project 1000575
  python tools/edge_impulse/download_ei_arduino_library.py

Outputs:
  third_party/ei_arduino_library_v6_1.zip            (downloaded zip, kept for reference)
  third_party/ei_arduino_library_v6_1/<LibraryName>/ (unpacked library; copy this to ~/Documents/Arduino/libraries/)

The script prints the exact library include name and the next manual step.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
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

API_HOST = "https://studio.edgeimpulse.com/v1"
PROJECT_ID = 1000575
DEPLOY_TYPE = "arduino"

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "third_party"
ZIP_PATH = OUT_DIR / "ei_arduino_library_v6_1.zip"
UNPACK_DIR = OUT_DIR / "ei_arduino_library_v6_1"


def poll_job(jobs_api: JobsApi, job_id: int, label: str) -> bool:
    import time
    while True:
        job = jobs_api.get_job_status(project_id=PROJECT_ID, job_id=job_id).job
        if job.finished:
            ok = bool(job.finished_successful)
            print(f"[{label}] finished success={ok}")
            return ok
        print(f"[{label}] job {job_id} running...")
        time.sleep(8)


def main() -> None:
    api_key = os.environ.get("EI_API_KEY", "")
    if not api_key:
        print("Set EI_API_KEY first:  $env:EI_API_KEY = 'ei_...'", file=sys.stderr)
        sys.exit(1)

    cfg = Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": api_key})
    client = ApiClient(cfg)
    jobs_api = JobsApi(client)
    deploy_api = DeploymentApi(client)

    print(f"1) Build Arduino library for project {PROJECT_ID} (EON off, tflite engine + ESP-NN)...")
    req = BuildOnDeviceModelRequest.from_dict({"eonCompiler": False, "engine": "tflite"})
    resp = jobs_api.build_on_device_model_job(
        project_id=PROJECT_ID, type=DEPLOY_TYPE, build_on_device_model_request=req
    )
    if not poll_job(jobs_api, resp.id, "build-arduino"):
        sys.exit("Build failed in Studio")

    print("2) Download deployment zip...")
    hist = deploy_api.list_deployment_history(project_id=PROJECT_ID, limit=1)
    deployments = getattr(hist, "deployments", None) or []
    if not deployments:
        sys.exit("No deployment in history")
    ver = deployments[0].deployment_version
    url = f"{API_HOST}/api/{PROJECT_ID}/deployment/history/{ver}/download"
    r = requests.get(url, headers={"x-api-key": api_key}, timeout=300)
    r.raise_for_status()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ZIP_PATH.write_bytes(r.content)
    print(f"   Saved {ZIP_PATH} ({len(r.content):,} bytes)")

    print("3) Unpack...")
    if UNPACK_DIR.exists():
        shutil.rmtree(UNPACK_DIR)
    UNPACK_DIR.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        zf.extractall(UNPACK_DIR)

    library_dirs = [p for p in UNPACK_DIR.iterdir() if p.is_dir()]
    if not library_dirs:
        sys.exit("Unzip produced no library folder")
    lib_dir = library_dirs[0]
    include_name = f"{lib_dir.name}.h"

    print()
    print("============================================================")
    print(" Edge Impulse Arduino library is ready")
    print("============================================================")
    print(f" Library folder: {lib_dir}")
    print(f" Sketch include: #include <{include_name}>")
    print()
    print(" Next manual steps:")
    print("   1. In Arduino IDE: Sketch -> Include Library -> Add .ZIP Library...")
    print(f"      Pick:  {ZIP_PATH}")
    print("   2. Open sketchboard/firmware/eagleeye_ei_runtime/eagleeye_ei_runtime.ino")
    print(f"   3. Make sure the #include at the top matches:  <{include_name}>")
    print("   4. Board: 'AI Thinker ESP32-CAM', PSRAM: Enabled, Partition Scheme: Huge APP")
    print("   5. Flash. Watch Serial @115200 for:")
    print("        Predictions (DSP: X ms., Classification: Y ms., Anomaly: Z ms.)")
    print("============================================================")


if __name__ == "__main__":
    main()
