#!/usr/bin/env python3
"""
Train a stronger Edge Impulse RGB 96x96 model for the classic ESP32-CAM.

This is the "smart best guess" after the MobileNetV1 0.1 INT8 model showed a
large quantization accuracy drop. The architecture uses MobileNetV1 0.2 to add
capacity without jumping to the slowest 0.25 variant, then packages the Arduino
library with ESP-NN disabled because ESP-NN produced saturated wrong predictions
on the AI Thinker ESP32-CAM in earlier testing.
"""

from __future__ import annotations

import io
import os
import re
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
    ProjectVersionRequest,
    UpdateProjectRequest,
)

PROJECT_ID = 1000575
API_HOST = "https://studio.edgeimpulse.com/v1"
DSP_ID = 2
LEARN_ID = 3

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "third_party"
RAW_ZIP_PATH = OUT_DIR / "ei_arduino_library_rgb64_mobilenetv1_a2_eon_raw.zip"
ZIP_PATH = OUT_DIR / "ei_arduino_library_rgb64_mobilenetv1_a2_eon_no_espnn.zip"
UNPACK_DIR = OUT_DIR / "ei_arduino_library_rgb64_mobilenetv1_a2_eon_no_espnn"

# Best-guess architecture for ESP32-CAM S1/classic ESP32:
# - 96x96 RGB preserves enough detail for "human" shape.
# - MobileNetV1 0.2 is materially stronger than 0.1 but should be less painful
#   than 0.25 when ESP-NN is disabled.
# - 32-neuron head gives the quantized classifier more separation than 16.
TL_MODEL = "transfer_mobilenetv1_a2_d100"
NEURONS = 32
DROPOUT = 0.25

# Hyperparameters: conservative LR for transfer learning, enough epochs for a
# small dataset, batch 16 for stabler updates and lower training memory.
TRAINING_CYCLES = 40
LEARNING_RATE = 0.00035
BATCH_SIZE = 16
TRAIN_TEST_SPLIT = 0.2
AUGMENTATION = "all"
MIN_CONFIDENCE = 0.65


def need_api_key() -> str:
    key = os.environ.get("EI_API_KEY", "")
    if not key:
        sys.exit("Set EI_API_KEY before running.")
    return key


def poll_job(jobs_api: JobsApi, job_id: int, label: str, timeout_min: int = 75) -> bool:
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
        time.sleep(20)


def rest_post(path: str, body: dict, api_key: str) -> dict:
    r = requests.post(
        f"{API_HOST}/api/{PROJECT_ID}/{path}",
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json=body,
        timeout=120,
    )
    if not r.ok:
        raise RuntimeError(f"POST {path} failed: {r.status_code} {r.text[:1000]}")
    return r.json()


def disable_esp_nn(lib_dir: Path) -> None:
    cfg = lib_dir / "src" / "edge-impulse-sdk" / "classifier" / "ei_classifier_config.h"
    text = cfg.read_text(encoding="utf-8")
    start = text.index("#ifndef EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN")
    end = text.index("#if EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN == 1", start)
    replacement = """#ifndef EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN
    // EagleEye: disabled because ESP-NN produced saturated wrong output on
    // AI Thinker ESP32-CAM for 96x96 RGB MobileNet transfer models.
    #define EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN      0
#endif"""
    cfg.write_text(text[:start] + replacement + "\n\n" + text[end:], encoding="utf-8")


def zip_dir(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in src_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src_dir.parent))


def get_int8_metrics(api_key: str) -> dict | None:
    r = requests.get(
        f"{API_HOST}/api/{PROJECT_ID}/training/keras/{LEARN_ID}/metadata",
        headers={"x-api-key": api_key},
        timeout=60,
    )
    if not r.ok:
        print(f"[metrics] unavailable: {r.status_code} {r.text[:300]}", flush=True)
        return None
    d = r.json()
    return next((m for m in d.get("modelValidationMetrics", []) if m.get("type") == "int8"), None)


def print_metrics(api_key: str) -> None:
    int8 = get_int8_metrics(api_key)
    if not int8:
        print("[metrics] no int8 metrics found", flush=True)
        return

    print("[metrics] INT8 validation", flush=True)
    print(f"  accuracy: {int8.get('accuracy', 0) * 100:.2f}%", flush=True)
    print(f"  loss:     {int8.get('loss', 0):.4f}", flush=True)
    print(f"  matrix:   {int8.get('confusionMatrix')}", flush=True)
    for key in ("auc", "precision", "recall", "f1"):
        if key in int8:
            print(f"  {key}:      {int8[key]:.4f}", flush=True)


def main() -> None:
    api_key = need_api_key()
    client = ApiClient(Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": api_key}))
    projects_api = ProjectsApi(client)
    dsp_api = DSPApi(client)
    jobs_api = JobsApi(client)
    deploy_api = DeploymentApi(client)

    print("Step 1) Ensure single_label project layout...", flush=True)
    projects_api.update_project(
        project_id=PROJECT_ID,
        update_project_request=UpdateProjectRequest.from_dict({"labelingMethod": "single_label"}),
    )

    print("Step 2) Set impulse: 96x96 RGB + MobileNetV1 0.2 transfer image...", flush=True)
    rest_post("impulse", {
        "name": "EagleEye 64x64 RGB MobileNetV1 0.2 smart human",
        "inputBlocks": [{
            "id": 1, "type": "image", "name": "Image", "title": "Image",
            "imageWidth": 64, "imageHeight": 64,
            "resizeMode": "fit-short",
        }],
        "dspBlocks": [{
            "id": DSP_ID, "type": "image", "name": "Image", "title": "Image",
            "axes": ["image"], "input": 1, "implementationVersion": 3,
        }],
        "learnBlocks": [{
            "id": LEARN_ID, "type": "keras-transfer-image",
            "name": "Transfer learning", "dsp": [DSP_ID],
            "title": "Transfer learning",
        }],
    }, api_key)

    print("Step 3) DSP color depth -> RGB...", flush=True)
    dsp_api.set_dsp_config(
        project_id=PROJECT_ID, dsp_id=DSP_ID,
        dsp_config_request=DSPConfigRequest.from_dict({"config": {"channels": "RGB"}}),
    )

    print("Step 4) Apply smart architecture and hyperparameters...", flush=True)
    rest_post(f"training/keras/{LEARN_ID}", {
        "mode": "visual",
        "selectedModelType": "int8",
        "augmentationPolicyImage": AUGMENTATION,
        "trainingCycles": TRAINING_CYCLES,
        "learningRate": LEARNING_RATE,
        "batchSize": BATCH_SIZE,
        "minimumConfidenceRating": MIN_CONFIDENCE,
        "autoClassWeights": True,
        "trainTestSplit": TRAIN_TEST_SPLIT,
        "skipEmbeddingsAndMemory": False,
        "profileInt8": True,
        "visualLayers": [
            {"type": TL_MODEL, "neurons": NEURONS, "dropoutRate": DROPOUT, "enabled": True}
        ],
    }, api_key)

    print("Step 5) Generate 96x96 RGB features...", flush=True)
    gen = GenerateFeaturesRequest.from_dict({
        "dspId": DSP_ID,
        "calculate_feature_importance": False,
        "skip_feature_explorer": True,
    })
    resp = jobs_api.generate_features_job(project_id=PROJECT_ID, generate_features_request=gen)
    if not poll_job(jobs_api, resp.id, "features", timeout_min=20):
        sys.exit("Feature generation failed")

    print("Step 6) Train MobileNetV1 0.2 smart transfer model...", flush=True)
    r = requests.post(
        f"{API_HOST}/api/{PROJECT_ID}/jobs/train/keras/{LEARN_ID}",
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json={"mode": "visual"},
        timeout=120,
    )
    if not r.ok:
        sys.exit(f"Could not start training: {r.status_code} {r.text[:1000]}")
    train_job_id = r.json().get("id")
    if not train_job_id:
        sys.exit(f"Could not start training: {r.text}")
    if not poll_job(jobs_api, train_job_id, "train", timeout_min=75):
        sys.exit("Training failed")
    print_metrics(api_key)

    print("Step 7) Save private Edge Impulse version snapshot...", flush=True)
    desc = (
        "Smart RGB64 MobileNetV1 0.2 INT8 (EON), 32-neuron head, dropout 0.25, "
        "ESP-NN disabled Arduino package"
    )
    try:
        version_req = ProjectVersionRequest.from_dict({
            "description": desc,
            "makePublic": False,
            "runModelTestingWhileVersioning": False,
        })
        vjob = jobs_api.start_version_job(project_id=PROJECT_ID, project_version_request=version_req)
        poll_job(jobs_api, vjob.id, "version", timeout_min=20)
    except Exception as exc:
        print(f"[version] skipped/failed: {exc}", flush=True)

    print("Step 8) Build Arduino library...", flush=True)
    build_req = BuildOnDeviceModelRequest.from_dict({"eonCompiler": True, "engine": "tflite-eon"})
    resp = jobs_api.build_on_device_model_job(
        project_id=PROJECT_ID, type="arduino", build_on_device_model_request=build_req
    )
    if not poll_job(jobs_api, resp.id, "build-arduino", timeout_min=25):
        sys.exit("Build failed")

    print("Step 9) Download and patch Arduino library zip...", flush=True)
    hist = deploy_api.list_deployment_history(project_id=PROJECT_ID, limit=1)
    deployments = getattr(hist, "deployments", None) or []
    if not deployments:
        sys.exit("No deployment in history")
    ver = deployments[0].deployment_version
    url = f"{API_HOST}/api/{PROJECT_ID}/deployment/history/{ver}/download"
    r = requests.get(url, headers={"x-api-key": api_key}, timeout=600)
    r.raise_for_status()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_ZIP_PATH.write_bytes(r.content)
    print(f"  Raw EI zip: {RAW_ZIP_PATH} ({len(r.content):,} bytes)", flush=True)

    if UNPACK_DIR.exists():
        shutil.rmtree(UNPACK_DIR)
    UNPACK_DIR.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        zf.extractall(UNPACK_DIR)

    lib_dirs = [p for p in UNPACK_DIR.iterdir() if p.is_dir()]
    if not lib_dirs:
        sys.exit("Downloaded zip did not contain a library folder")
    lib_dir = lib_dirs[0]
    disable_esp_nn(lib_dir)
    zip_dir(lib_dir, ZIP_PATH)

    print()
    print("=" * 70, flush=True)
    print(" RGB 96x96 MobileNetV1 0.2 smart Arduino library is ready", flush=True)
    print("=" * 70, flush=True)
    print(f" Deployment version: {ver}", flush=True)
    print(f" Transfer model:     {TL_MODEL}", flush=True)
    print(f" Head:               Dense({NEURONS}) + Dropout({DROPOUT})", flush=True)
    print(f" Hyperparameters:    epochs={TRAINING_CYCLES}, lr={LEARNING_RATE}, batch={BATCH_SIZE}", flush=True)
    print(f" ESP-NN:             DISABLED in packaged zip", flush=True)
    print(f" Library zip:        {ZIP_PATH}", flush=True)
    print(f" Unpacked folder:    {lib_dir}", flush=True)
    print(f" Include:            #include <{lib_dir.name}.h>", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
