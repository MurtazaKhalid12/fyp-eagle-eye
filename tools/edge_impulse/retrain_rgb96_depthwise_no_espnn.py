#!/usr/bin/env python3
"""
DEPTHWISE-SEPARABLE tiny CNN via Edge Impulse EXPERT mode (project 1000575).

EI visual mode only offers standard Conv2D. Expert mode lets us use
SeparableConv2D (depthwise + 1x1 pointwise) — MobileNet's trick — which cuts
conv MACs ~8-10x vs standard conv, and ESP-NN accelerates depthwise/pointwise
well on the ESP32-S1. Greyscale 80x80, ESP-NN left ENABLED. Balanced data.

Usage (PowerShell):
  $env:EI_API_KEY = "ei_..."
  python tools/edge_impulse/retrain_gray80_depthwise_espnn.py
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
    ApiClient, BuildOnDeviceModelRequest, Configuration, DSPApi, DSPConfigRequest,
    DeploymentApi, GenerateFeaturesRequest, JobsApi, ProjectsApi, UpdateProjectRequest,
)

PROJECT_ID = 1000575
API_HOST = "https://studio.edgeimpulse.com/v1"
DSP_ID = 2
LEARN_ID = 3
TRAINING_CYCLES = 50
LEARNING_RATE = 0.0005
BATCH_SIZE = 32

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "third_party"
ZIP_PATH = OUT_DIR / "ei_arduino_library_rgb96_depthwise_no_espnn.zip"
UNPACK_DIR = OUT_DIR / "ei_arduino_library_rgb96_depthwise_no_espnn"

# Expert-mode Keras script: first conv standard (1->8 is cheap), then
# depthwise-separable convs for the channel-heavy layers. Keeps EI's harness
# interface (train_dataset, callbacks, classes, Y_train, BatchLoggerCallback).
EXPERT_SCRIPT = r'''import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout, Conv2D, SeparableConv2D, Flatten, MaxPooling2D, BatchNormalization
from tensorflow.keras.optimizers.legacy import Adam

EPOCHS = args.epochs or 50
LEARNING_RATE = args.learning_rate or 0.0005
ENSURE_DETERMINISM = args.ensure_determinism
BATCH_SIZE = args.batch_size or 32
if not ENSURE_DETERMINISM:
    train_dataset = train_dataset.shuffle(buffer_size=BATCH_SIZE*4)
train_dataset = train_dataset.batch(BATCH_SIZE, drop_remainder=False)
validation_dataset = validation_dataset.batch(BATCH_SIZE, drop_remainder=False)

# Depthwise-separable tiny CNN (MobileNet-style). ~8-10x fewer conv MACs than
# standard Conv2D at the same filter counts -> much faster on ESP32-S1.
model = Sequential()
model.add(Conv2D(8, kernel_size=3, padding='same', activation='relu'))
model.add(BatchNormalization())
model.add(MaxPooling2D(pool_size=2, strides=2, padding='same'))
model.add(SeparableConv2D(16, kernel_size=3, padding='same', activation='relu'))
model.add(BatchNormalization())
model.add(MaxPooling2D(pool_size=2, strides=2, padding='same'))
model.add(SeparableConv2D(32, kernel_size=3, padding='same', activation='relu'))
model.add(BatchNormalization())
model.add(MaxPooling2D(pool_size=2, strides=2, padding='same'))
model.add(Flatten())
model.add(Dropout(0.5))
model.add(Dense(classes, name='y_pred', activation='softmax'))

opt = Adam(learning_rate=LEARNING_RATE, beta_1=0.9, beta_2=0.999)
callbacks.append(BatchLoggerCallback(BATCH_SIZE, train_sample_count, epochs=EPOCHS, ensure_determinism=ENSURE_DETERMINISM))
model.compile(loss='categorical_crossentropy', optimizer=opt, metrics=["accuracy"])
model.fit(train_dataset, epochs=EPOCHS, validation_data=validation_dataset, verbose=2, callbacks=callbacks, class_weight=ei_tensorflow.training.get_class_weights(Y_train))
disable_per_channel_quantization = False
'''


def need_api_key() -> str:
    return os.environ.get("EI_API_KEY", "") or sys.exit("Set EI_API_KEY before running.")


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



def disable_esp_nn(lib_dir: Path) -> None:
    cfg = lib_dir / "src" / "edge-impulse-sdk" / "classifier" / "ei_classifier_config.h"
    text = cfg.read_text(encoding="utf-8")
    start = text.index("#ifndef EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN")
    end = text.index("#if EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN == 1", start)
    repl = (
        "#ifndef EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN\n"
        "    #define EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN      0\n"
        "#endif"
    )
    cfg.write_text(text[:start] + repl + "\n\n" + text[end:], encoding="utf-8")

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

    print("Step 2) Set impulse: 96x96 + custom Keras block...", flush=True)
    rest_post("impulse", {
        "name": "EagleEye 96x96 RGB Depthwise CNN human",
        "inputBlocks": [{"id": 1, "type": "image", "name": "Image", "title": "Image",
                         "imageWidth": 96, "imageHeight": 96, "resizeMode": "fit-short"}],
        "dspBlocks": [{"id": DSP_ID, "type": "image", "name": "Image", "title": "Image",
                       "axes": ["image"], "input": 1, "implementationVersion": 3}],
        "learnBlocks": [{"id": LEARN_ID, "type": "keras", "name": "Classifier",
                         "dsp": [DSP_ID], "title": "Classification"}],
    }, api_key)

    print("Step 3) DSP color depth -> RGB...", flush=True)
    dsp_api.set_dsp_config(project_id=PROJECT_ID, dsp_id=DSP_ID,
        dsp_config_request=DSPConfigRequest.from_dict({"config": {"channels": "RGB"}}))

    print("Step 4) Apply EXPERT-mode depthwise script...", flush=True)
    rest_post(f"training/keras/{LEARN_ID}", {
        "mode": "expert",
        "script": EXPERT_SCRIPT,
        "selectedModelType": "int8",
        "augmentationPolicyImage": "all",
        "trainingCycles": TRAINING_CYCLES,
        "learningRate": LEARNING_RATE,
        "batchSize": BATCH_SIZE,
        "autoClassWeights": True,
        "trainTestSplit": 0.2,
        "profileInt8": True,
    }, api_key)

    print("Step 5) Generate 96x96 RGB features...", flush=True)
    gen = GenerateFeaturesRequest.from_dict({"dspId": DSP_ID, "calculate_feature_importance": False, "skip_feature_explorer": True})
    resp = jobs_api.generate_features_job(project_id=PROJECT_ID, generate_features_request=gen)
    if not poll_job(jobs_api, resp.id, "features", 20):
        sys.exit("feature gen failed")

    print("Step 6) Train depthwise CNN (expert)...", flush=True)
    r = requests.post(f"{API_HOST}/api/{PROJECT_ID}/jobs/train/keras/{LEARN_ID}",
                      headers={"x-api-key": api_key, "Content-Type": "application/json"},
                      json={"mode": "expert"}, timeout=120)
    if not r.ok:
        sys.exit(f"train start failed: {r.status_code} {r.text[:800]}")
    if not poll_job(jobs_api, r.json().get("id"), "train", 75):
        sys.exit("train failed")

    int8 = get_int8_metrics(api_key)
    if int8:
        print(f"[metrics] INT8 val accuracy: {int8.get('accuracy',0)*100:.2f}%  matrix: {int8.get('confusionMatrix')}", flush=True)

    print("Step 7) Build Arduino library (ESP-NN DISABLED)...", flush=True)
    resp = jobs_api.build_on_device_model_job(project_id=PROJECT_ID, type="arduino",
        build_on_device_model_request=BuildOnDeviceModelRequest.from_dict({"engine": "tflite"}))
    if not poll_job(jobs_api, resp.id, "build", 25):
        sys.exit("build failed")

    print("Step 8) Download library...", flush=True)
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
    disable_esp_nn(lib_dir)
    zip_dir(lib_dir, ZIP_PATH)

    print("=" * 64, flush=True)
    print(" Depthwise-separable tiny CNN (RGB 96x96) — ESP-NN DISABLED", flush=True)
    print(f"   deploy version : {ver}", flush=True)
    print(f"   library zip    : {ZIP_PATH}", flush=True)
    print("=" * 64, flush=True)


if __name__ == "__main__":
    main()
