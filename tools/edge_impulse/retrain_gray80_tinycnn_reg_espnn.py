#!/usr/bin/env python3
"""
Train a CUSTOM TINY CNN (not MobileNet transfer) on Edge Impulse project 1000575.

Goal: much lower inference latency on the ESP32-CAM S1 by using a small 2-conv
network instead of a ~28-layer MobileNet, at 96x96 GREYSCALE, and building the
Arduino library WITH ESP-NN ENABLED (left on — the saturation bug was specific
to the MobileNet RGB path; plain Conv2D ops may run fine accelerated).

Architecture (visual mode):
  Conv2D(32, 3x3) + pool -> Conv2D(16, 3x3) + pool -> Flatten -> Dropout(0.25) -> Dense(classes)

Full dataset with autoClassWeights (human is the minority class).

Usage (PowerShell):
  $env:EI_API_KEY = "ei_..."
  python tools/edge_impulse/retrain_gray96_tinycnn_espnn.py
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
ZIP_PATH = OUT_DIR / "ei_arduino_library_gray80_tinycnn_reg_espnn.zip"
UNPACK_DIR = OUT_DIR / "ei_arduino_library_gray80_tinycnn_reg_espnn"

# Tiny conv net (NOT transfer learning).
VISUAL_LAYERS = [
    {"type": "conv2d", "neurons": 16, "kernelSize": 3, "stack": 1, "enabled": True},
    {"type": "conv2d", "neurons": 32, "kernelSize": 3, "stack": 1, "enabled": True},
    {"type": "conv2d", "neurons": 32, "kernelSize": 3, "stack": 1, "enabled": True},
    {"type": "flatten", "enabled": True},
    {"type": "dropout", "dropoutRate": 0.5, "enabled": True},
]
TRAINING_CYCLES = 40      # fewer epochs to curb overfitting (best-val weights kept)
LEARNING_RATE = 0.0005
BATCH_SIZE = 32
AUGMENTATION = "all"


def need_api_key() -> str:
    key = os.environ.get("EI_API_KEY", "")
    return key or sys.exit("Set EI_API_KEY before running.")


def poll_job(jobs_api: JobsApi, job_id: int, label: str, timeout_min: int = 75) -> bool:
    start = time.time()
    while True:
        if time.time() - start > timeout_min * 60:
            print(f"[{label}] timeout", flush=True); return False
        job = jobs_api.get_job_status(project_id=PROJECT_ID, job_id=job_id).job
        if job.finished:
            ok = bool(job.finished_successful)
            print(f"[{label}] finished success={ok}", flush=True); return ok
        print(f"[{label}] job {job_id} running ({int(time.time()-start)}s)...", flush=True)
        time.sleep(20)


def rest_post(path: str, body: dict, api_key: str) -> dict:
    r = requests.post(f"{API_HOST}/api/{PROJECT_ID}/{path}",
                      headers={"x-api-key": api_key, "Content-Type": "application/json"},
                      json=body, timeout=120)
    if not r.ok:
        raise RuntimeError(f"POST {path} failed: {r.status_code} {r.text[:1000]}")
    return r.json()


def zip_dir(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in src_dir.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(src_dir.parent))


def get_int8_metrics(api_key: str):
    r = requests.get(f"{API_HOST}/api/{PROJECT_ID}/training/keras/{LEARN_ID}/metadata",
                     headers={"x-api-key": api_key}, timeout=60)
    if not r.ok:
        return None
    return next((m for m in r.json().get("modelValidationMetrics", []) if m.get("type") == "int8"), None)


def main() -> None:
    api_key = need_api_key()
    client = ApiClient(Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": api_key}))
    projects_api = ProjectsApi(client)
    dsp_api = DSPApi(client)
    jobs_api = JobsApi(client)
    deploy_api = DeploymentApi(client)

    print("Step 1) single_label layout...", flush=True)
    projects_api.update_project(project_id=PROJECT_ID,
        update_project_request=UpdateProjectRequest.from_dict({"labelingMethod": "single_label"}))

    print("Step 2) Set impulse: 80x80 + custom Keras (tiny CNN) block...", flush=True)
    rest_post("impulse", {
        "name": "EagleEye 80x80 Grayscale Tiny CNN regularized human",
        "inputBlocks": [{
            "id": 1, "type": "image", "name": "Image", "title": "Image",
            "imageWidth": 80, "imageHeight": 80, "resizeMode": "fit-short",
        }],
        "dspBlocks": [{
            "id": DSP_ID, "type": "image", "name": "Image", "title": "Image",
            "axes": ["image"], "input": 1, "implementationVersion": 3,
        }],
        "learnBlocks": [{
            "id": LEARN_ID, "type": "keras",
            "name": "Classifier", "dsp": [DSP_ID], "title": "Classification",
        }],
    }, api_key)

    print("Step 3) DSP color depth -> Grayscale...", flush=True)
    dsp_api.set_dsp_config(project_id=PROJECT_ID, dsp_id=DSP_ID,
        dsp_config_request=DSPConfigRequest.from_dict({"config": {"channels": "Grayscale"}}))

    print("Step 4) Apply tiny-CNN architecture + hyperparameters...", flush=True)
    rest_post(f"training/keras/{LEARN_ID}", {
        "mode": "visual",
        "selectedModelType": "int8",
        "augmentationPolicyImage": AUGMENTATION,
        "trainingCycles": TRAINING_CYCLES,
        "learningRate": LEARNING_RATE,
        "batchSize": BATCH_SIZE,
        "autoClassWeights": True,
        "trainTestSplit": 0.2,
        "skipEmbeddingsAndMemory": False,
        "profileInt8": True,
        "visualLayers": VISUAL_LAYERS,
    }, api_key)

    print("Step 5) Generate 80x80 grayscale features...", flush=True)
    gen = GenerateFeaturesRequest.from_dict({"dspId": DSP_ID, "calculate_feature_importance": False, "skip_feature_explorer": True})
    resp = jobs_api.generate_features_job(project_id=PROJECT_ID, generate_features_request=gen)
    if not poll_job(jobs_api, resp.id, "features", 20):
        sys.exit("feature gen failed")

    print("Step 6) Train tiny CNN...", flush=True)
    r = requests.post(f"{API_HOST}/api/{PROJECT_ID}/jobs/train/keras/{LEARN_ID}",
                      headers={"x-api-key": api_key, "Content-Type": "application/json"},
                      json={"mode": "visual"}, timeout=120)
    if not r.ok:
        sys.exit(f"train start failed: {r.status_code} {r.text[:800]}")
    if not poll_job(jobs_api, r.json().get("id"), "train", 75):
        sys.exit("train failed")

    int8 = get_int8_metrics(api_key)
    if int8:
        print(f"[metrics] INT8 val accuracy: {int8.get('accuracy',0)*100:.2f}%  matrix: {int8.get('confusionMatrix')}", flush=True)

    print("Step 7) Build Arduino library (ESP-NN LEFT ENABLED)...", flush=True)
    build_req = BuildOnDeviceModelRequest.from_dict({"engine": "tflite"})
    resp = jobs_api.build_on_device_model_job(project_id=PROJECT_ID, type="arduino", build_on_device_model_request=build_req)
    if not poll_job(jobs_api, resp.id, "build", 25):
        sys.exit("build failed")

    print("Step 8) Download library (no ESP-NN patch)...", flush=True)
    hist = deploy_api.list_deployment_history(project_id=PROJECT_ID, limit=1)
    ver = (getattr(hist, "deployments", None) or [])[0].deployment_version
    r = requests.get(f"{API_HOST}/api/{PROJECT_ID}/deployment/history/{ver}/download",
                     headers={"x-api-key": api_key}, timeout=600)
    r.raise_for_status()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if UNPACK_DIR.exists():
        shutil.rmtree(UNPACK_DIR)
    UNPACK_DIR.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        zf.extractall(UNPACK_DIR)
    lib_dir = [p for p in UNPACK_DIR.iterdir() if p.is_dir()][0]
    zip_dir(lib_dir, ZIP_PATH)

    print("=" * 64, flush=True)
    print(" Tiny CNN regularized (greyscale 80x80) Arduino library — ESP-NN ENABLED", flush=True)
    print(f"   deploy version : {ver}", flush=True)
    print(f"   library zip    : {ZIP_PATH}", flush=True)
    print(f"   include        : #include <{lib_dir.name}.h>", flush=True)
    print("   NOTE: verify predictions are NOT saturated (ESP-NN is on).", flush=True)
    print("=" * 64, flush=True)


if __name__ == "__main__":
    main()
