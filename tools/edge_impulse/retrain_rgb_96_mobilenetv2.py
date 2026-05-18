#!/usr/bin/env python3
"""
Retrain EagleEye (Edge Impulse project 1000575) using the recommended human-detection pipeline:

  - Input: 96x96 RGB (fit-short + center crop)
  - DSP:   image RGB
  - Learn: keras-transfer-image with MobileNetV2 96x96 0.1 (transfer_mobilenetv2_a1)
  - Augmentation: enabled (rotation/flip/zoom)
  - Training: 20 cycles, learning rate 0.0005, INT8 quantization

After training, builds an Arduino library (with ESP-NN) and saves the zip.

Usage (PowerShell):
  $env:EI_API_KEY = "ei_..."
  python tools/edge_impulse/retrain_rgb_96_mobilenetv2.py
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
    DSPApi,
    DSPConfigRequest,
    DeploymentApi,
    GenerateFeaturesRequest,
    JobsApi,
    ProjectsApi,
    UpdateProjectRequest,
)

PROJECT_ID = 1000575
API_HOST = "https://studio.edgeimpulse.com/v1"
DSP_ID = 2
LEARN_ID = 3

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "third_party"
ZIP_PATH = OUT_DIR / "ei_arduino_library_v7_rgb96_mobilenetv2.zip"
UNPACK_DIR = OUT_DIR / "ei_arduino_library_v7_rgb96_mobilenetv2"

# Transfer learning model: MobileNetV2 96x96 0.1
TL_MODEL = "transfer_mobilenetv2_a1"

TRAINING_CYCLES = 20
LEARNING_RATE = 0.0005
NEURONS = 16
DROPOUT = 0.1
AUGMENTATION = "all"  # rotation/flip/zoom
MIN_CONFIDENCE = 0.6


def need_api_key() -> str:
    key = os.environ.get("EI_API_KEY", "")
    if not key:
        sys.exit("Set EI_API_KEY before running.")
    return key


def poll_job(jobs_api: JobsApi, job_id: int, label: str, timeout_min: int = 30) -> bool:
    start = time.time()
    while True:
        if time.time() - start > timeout_min * 60:
            print(f"[{label}] timeout after {timeout_min} minutes")
            return False
        job = jobs_api.get_job_status(project_id=PROJECT_ID, job_id=job_id).job
        if job.finished:
            ok = bool(job.finished_successful)
            print(f"[{label}] finished success={ok}")
            return ok
        elapsed = int(time.time() - start)
        print(f"[{label}] job {job_id} running ({elapsed}s)...")
        time.sleep(10)


def rest_post(path: str, body: dict, api_key: str) -> dict:
    r = requests.post(f"{API_HOST}/api/{PROJECT_ID}/{path}",
                      headers={"x-api-key": api_key, "Content-Type": "application/json"},
                      json=body, timeout=60)
    r.raise_for_status()
    return r.json()


def main() -> None:
    api_key = need_api_key()
    client = ApiClient(Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": api_key}))
    projects_api = ProjectsApi(client)
    dsp_api = DSPApi(client)
    jobs_api = JobsApi(client)
    deploy_api = DeploymentApi(client)

    print("Step 1) Ensure single_label project layout...")
    projects_api.update_project(
        project_id=PROJECT_ID,
        update_project_request=UpdateProjectRequest.from_dict({"labelingMethod": "single_label"}),
    )

    print("Step 2) Set impulse: 96x96 RGB + keras-transfer-image...")
    rest_post("impulse", {
        "name": "EagleEye 96x96 RGB human",
        "inputBlocks": [{
            "id": 1, "type": "image", "name": "Image", "title": "Image",
            "imageWidth": 96, "imageHeight": 96,
            "resizeMode": "fit-short",
        }],
        "dspBlocks": [{
            "id": DSP_ID, "type": "image", "name": "Image", "title": "Image",
            "axes": ["image"], "input": 1, "implementationVersion": 3,
        }],
        "learnBlocks": [{
            "id": LEARN_ID, "type": "keras-transfer-image", "name": "Transfer learning",
            "dsp": [DSP_ID], "title": "Transfer learning",
        }],
    }, api_key)

    print("Step 3) DSP color depth -> RGB...")
    dsp_api.set_dsp_config(
        project_id=PROJECT_ID, dsp_id=DSP_ID,
        dsp_config_request=DSPConfigRequest.from_dict({"config": {"channels": "RGB"}}),
    )

    print("Step 4) Select transfer learning model:", TL_MODEL)
    rest_post(f"training/keras/{LEARN_ID}", {
        "mode": "visual",
        "selectedModelType": "int8",
        "augmentationPolicyImage": AUGMENTATION,
        "trainingCycles": TRAINING_CYCLES,
        "learningRate": LEARNING_RATE,
        "minimumConfidenceRating": MIN_CONFIDENCE,
        "autoClassWeights": True,
        "trainTestSplit": 0.2,
        "skipEmbeddingsAndMemory": False,
        "profileInt8": True,
        "visualLayers": [
            {"type": TL_MODEL, "neurons": NEURONS, "dropoutRate": DROPOUT, "enabled": True}
        ],
    }, api_key)

    print("Step 5) Generate features for 96x96 RGB...")
    gen = GenerateFeaturesRequest.from_dict({
        "dspId": DSP_ID,
        "calculate_feature_importance": False,
        "skip_feature_explorer": True,
    })
    resp = jobs_api.generate_features_job(project_id=PROJECT_ID, generate_features_request=gen)
    if not poll_job(jobs_api, resp.id, "features"):
        sys.exit("Feature generation failed")
    print("   Expected feature count for 96x96 RGB: 27648")

    print("Step 6) Train transfer learning (this takes a few minutes)...")
    # Trigger training via direct REST so we don't need SetKerasParameterRequest re-config
    body = {"mode": "visual"}
    r = requests.post(f"{API_HOST}/api/{PROJECT_ID}/jobs/train/keras/{LEARN_ID}",
                      headers={"x-api-key": api_key, "Content-Type": "application/json"},
                      json=body, timeout=120)
    r.raise_for_status()
    train_job_id = r.json().get("id")
    if not train_job_id:
        sys.exit(f"Could not start training: {r.text}")
    if not poll_job(jobs_api, train_job_id, "train", timeout_min=45):
        sys.exit("Training failed")

    print("Step 7) Build Arduino library (with ESP-NN)...")
    build_req = BuildOnDeviceModelRequest.from_dict({"eonCompiler": False, "engine": "tflite"})
    resp = jobs_api.build_on_device_model_job(
        project_id=PROJECT_ID, type="arduino", build_on_device_model_request=build_req
    )
    if not poll_job(jobs_api, resp.id, "build-arduino"):
        sys.exit("Build failed")

    print("Step 8) Download deployment zip...")
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
    print(f"   Saved {ZIP_PATH} ({len(r.content):,} bytes)")

    if UNPACK_DIR.exists():
        shutil.rmtree(UNPACK_DIR)
    UNPACK_DIR.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        zf.extractall(UNPACK_DIR)

    lib_dirs = [p for p in UNPACK_DIR.iterdir() if p.is_dir()]
    lib_dir = lib_dirs[0] if lib_dirs else None
    include_name = f"{lib_dir.name}.h" if lib_dir else "<unknown>.h"

    print()
    print("=" * 60)
    print(" RGB 96x96 MobileNetV2 model is ready")
    print("=" * 60)
    print(f" Deployment version: {ver}")
    print(f" Library zip:       {ZIP_PATH}")
    print(f" Library folder:    {lib_dir}")
    print(f" Sketch include:    #include <{include_name}>")
    print()
    print(" Next steps (manual):")
    print("   1. Arduino IDE > Sketch > Include Library > Add .ZIP Library...")
    print(f"      Pick:  {ZIP_PATH}")
    print("   2. Create a new sketch that wires ESP32-CAM RGB565 capture into run_classifier()")
    print("      (same shape as eagleeye_ei_runtime_rgb but with 96x96 input).")
    print("=" * 60)


if __name__ == "__main__":
    main()
