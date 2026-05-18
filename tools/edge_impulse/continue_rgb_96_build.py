#!/usr/bin/env python3
"""Continue retrain pipeline: wait for the in-flight training job, then build Arduino lib."""

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
LEARN_ID = 3
TRAIN_JOB_ID = 48773592

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "third_party"
ZIP_PATH = OUT_DIR / "ei_arduino_library_v7_rgb96_mobilenetv2.zip"
UNPACK_DIR = OUT_DIR / "ei_arduino_library_v7_rgb96_mobilenetv2"


def poll(jobs_api: JobsApi, job_id: int, label: str, timeout_min: int = 60) -> bool:
    start = time.time()
    while True:
        if time.time() - start > timeout_min * 60:
            print(f"[{label}] timeout after {timeout_min} minutes", flush=True)
            return False
        job = jobs_api.get_job_status(project_id=PROJECT_ID, job_id=job_id).job
        if job.finished:
            ok = bool(job.finished_successful)
            print(f"[{label}] finished success={ok}", flush=True)
            return ok
        elapsed = int(time.time() - start)
        print(f"[{label}] job {job_id} running ({elapsed}s)...", flush=True)
        time.sleep(15)


def main() -> None:
    api_key = os.environ.get("EI_API_KEY", "")
    if not api_key:
        sys.exit("EI_API_KEY not set")
    client = ApiClient(Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": api_key}))
    jobs_api = JobsApi(client)
    deploy_api = DeploymentApi(client)

    print(f"Step A) Waiting for in-flight training job {TRAIN_JOB_ID}...", flush=True)
    if not poll(jobs_api, TRAIN_JOB_ID, "train", timeout_min=60):
        sys.exit("Training failed")

    print("Step B) Fetch metrics from completed model...", flush=True)
    r = requests.get(f"{API_HOST}/api/{PROJECT_ID}/training/keras/{LEARN_ID}/metadata",
                     headers={"x-api-key": api_key}, timeout=60)
    if r.ok:
        m = r.json()
        last = (m.get("metrics") or {}).get("validation") or {}
        print("   validation:", last, flush=True)

    print("Step C) Build Arduino library (with ESP-NN)...", flush=True)
    build_req = BuildOnDeviceModelRequest.from_dict({"eonCompiler": False, "engine": "tflite"})
    resp = jobs_api.build_on_device_model_job(
        project_id=PROJECT_ID, type="arduino", build_on_device_model_request=build_req
    )
    if not poll(jobs_api, resp.id, "build-arduino", timeout_min=20):
        sys.exit("Build failed")

    print("Step D) Download deployment zip...", flush=True)
    hist = deploy_api.list_deployment_history(project_id=PROJECT_ID, limit=1)
    deployments = getattr(hist, "deployments", None) or []
    if not deployments:
        sys.exit("No deployment in history")
    ver = deployments[0].deployment_version
    url = f"{API_HOST}/api/{PROJECT_ID}/deployment/history/{ver}/download"
    r = requests.get(url, headers={"x-api-key": api_key}, timeout=600)
    r.raise_for_status()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ZIP_PATH.write_bytes(r.content)
    print(f"   Saved {ZIP_PATH} ({len(r.content):,} bytes)", flush=True)

    if UNPACK_DIR.exists():
        shutil.rmtree(UNPACK_DIR)
    UNPACK_DIR.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        zf.extractall(UNPACK_DIR)

    lib_dirs = [p for p in UNPACK_DIR.iterdir() if p.is_dir()]
    lib_dir = lib_dirs[0] if lib_dirs else None
    include_name = f"{lib_dir.name}.h" if lib_dir else "<unknown>.h"

    print()
    print("=" * 60, flush=True)
    print(" RGB 96x96 MobileNetV2 model is ready", flush=True)
    print("=" * 60, flush=True)
    print(f" Deployment version: {ver}", flush=True)
    print(f" Library zip:       {ZIP_PATH}", flush=True)
    print(f" Library folder:    {lib_dir}", flush=True)
    print(f" Sketch include:    #include <{include_name}>", flush=True)


if __name__ == "__main__":
    main()
