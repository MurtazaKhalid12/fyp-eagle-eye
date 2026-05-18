#!/usr/bin/env python3
"""
Retrain Edge Impulse project 1000575 with Grayscale (48x48x1), build INT8,
and install to sketchboard + models/.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
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
    Impulse,
    ImpulseApi,
    JobsApi,
    ProjectsApi,
    SetKerasParameterRequest,
    UpdateProjectRequest,
)

API_HOST = "https://studio.edgeimpulse.com/v1"
PROJECT_ID = 1000575
DSP_ID = 2
LEARN_ID = 3
DEPLOY_FORMAT = "arduino"

REPO = Path(__file__).resolve().parents[2]
SKETCH_HDR = REPO / "sketchboard" / "firmware" / "hard_negative_capturer" / "human_detect_model_data.h"
MODELS_TFLITE = REPO / "models" / "model_v6.1_edge_impulse_grayscale.tflite"
EXPORTED_TFLITE = REPO / "model-training" / "exported-models" / "model_v6.1_edge_impulse_grayscale.tflite"


def poll_job(jobs_api: JobsApi, job_id: int, label: str) -> bool:
    while True:
        job = jobs_api.get_job_status(project_id=PROJECT_ID, job_id=job_id).job
        if job.finished:
            ok = bool(job.finished_successful)
            print(f"[{label}] finished success={ok}")
            if not ok:
                r = requests.get(
                    f"{API_HOST}/api/{PROJECT_ID}/jobs/{job_id}/stdout",
                    headers={"x-api-key": os.environ["EI_API_KEY"]},
                )
                for line in reversed(r.json().get("stdout", [])):
                    d = (line.get("data") or "").strip()
                    if d and "spinner" not in d.lower():
                        print(f"  {d[:600]}")
                        break
            return ok
        print(f"[{label}] job {job_id} running...")
        time.sleep(8)


def extract_tflite(zip_bytes: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".tflite")]
        if names:
            names.sort(
                key=lambda n: (0 if "int8" in n.lower() else 1, 0 if "trained" in n.lower() else 1, len(n))
            )
            return zf.read(names[0])
    import re as _re

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        headers = [n for n in zf.namelist() if "/tflite-model/tflite_learn_" in n and n.endswith(".h")]
        if not headers:
            raise RuntimeError("No .tflite in deployment zip")
        text = zf.read(headers[0]).decode("utf-8", errors="replace")
    start, end = text.find("{"), text.rfind("}")
    return bytes(int(x, 16) for x in _re.findall(r"0x([0-9a-fA-F]{2})", text[start + 1 : end]))


def write_header(tflite: bytes, out_path: Path) -> None:
    var = "g_human_detect_model_data"
    guard = f"{var.upper()}_H"
    lines = [
        f"// Edge Impulse INT8 grayscale — project {PROJECT_ID}",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        f"extern const unsigned char {var}[];",
        f"extern const unsigned int {var}_len;",
        "",
        f"const unsigned char {var}[] = {{",
    ]
    for i in range(0, len(tflite), 12):
        chunk = ", ".join(f"0x{b:02x}" for b in tflite[i : i + 12])
        lines.append(f"  {chunk},")
    lines.extend([f"}};", f"const unsigned int {var}_len = {len(tflite)};", f"#endif  // {guard}", ""])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    api_key = os.environ.get("EI_API_KEY", "")
    if not api_key:
        print("Set EI_API_KEY (admin key for project 1000575)", file=sys.stderr)
        sys.exit(1)

    config = Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": api_key})
    client = ApiClient(config)
    projects_api = ProjectsApi(client)
    impulse_api = ImpulseApi(client)
    dsp_api = DSPApi(client)
    jobs_api = JobsApi(client)
    deploy_api = DeploymentApi(client)

    print("1) single_label + impulse 48x48...")
    projects_api.update_project(
        project_id=PROJECT_ID,
        update_project_request=UpdateProjectRequest.from_dict({"labelingMethod": "single_label"}),
    )
    impulse = Impulse.from_dict(
        {
            "name": "EagleEye 48x48 human grayscale",
            "inputBlocks": [
                {
                    "id": 1,
                    "type": "image",
                    "name": "Image",
                    "title": "Image",
                    "imageWidth": 48,
                    "imageHeight": 48,
                    "resizeMode": "fit-short",
                }
            ],
            "dspBlocks": [
                {
                    "id": 2,
                    "type": "image",
                    "name": "Image",
                    "title": "Image",
                    "axes": ["image"],
                    "input": 1,
                    "implementationVersion": 3,
                }
            ],
            "learnBlocks": [
                {
                    "id": 3,
                    "type": "keras",
                    "name": "Classifier",
                    "title": "Classifier (Keras)",
                    "dsp": [2],
                }
            ],
        }
    )
    impulse_api.create_impulse(project_id=PROJECT_ID, impulse=impulse)

    print("2) DSP color depth -> Grayscale...")
    dsp_api.set_dsp_config(
        project_id=PROJECT_ID,
        dsp_id=DSP_ID,
        dsp_config_request=DSPConfigRequest.from_dict({"config": {"channels": "Grayscale"}}),
    )
    cfg = dsp_api.get_dsp_config(project_id=PROJECT_ID, dsp_id=DSP_ID)
    for item in getattr(cfg, "config", []) or []:
        for sub in getattr(item, "items", []) or []:
            if getattr(sub, "name", "") == "Color depth":
                print(f"   Color depth now: {getattr(sub, 'value', '?')}")

    print("3) Generate features...")
    gen = GenerateFeaturesRequest.from_dict(
        {"dspId": DSP_ID, "calculate_feature_importance": False, "skip_feature_explorer": True}
    )
    resp = jobs_api.generate_features_job(project_id=PROJECT_ID, generate_features_request=gen)
    if not poll_job(jobs_api, resp.id, "features"):
        sys.exit(1)

    feat = dsp_api.get_dsp_config(project_id=PROJECT_ID, dsp_id=DSP_ID)
    count = feat.dsp.features.count if feat.dsp and feat.dsp.features else 0
    print(f"   Feature count: {count} (expect 2304 for 48x48 grayscale)")
    if count and count != 2304:
        print("   WARNING: feature count is not 2304; grayscale may not be active.", file=sys.stderr)

    print("4) Train Keras (30 epochs)...")
    train = SetKerasParameterRequest.from_dict(
        {
            "mode": "visual",
            "training_cycles": 30,
            "learning_rate": 0.001,
            "train_test_split": 0.8,
            "augmentationPolicyImage": "none",
            "skip_embeddings_and_memory": True,
            "visualLayers": [
                {"type": "conv2d", "neurons": 16, "kernelSize": 3, "stack": 1, "enabled": True},
                {"type": "dropout", "dropoutRate": 0.2, "enabled": True},
                {"type": "conv2d", "neurons": 32, "kernelSize": 3, "stack": 1, "enabled": True},
                {"type": "flatten", "enabled": True},
            ],
        }
    )
    resp = jobs_api.train_keras_job(
        project_id=PROJECT_ID, learn_id=LEARN_ID, set_keras_parameter_request=train
    )
    if not poll_job(jobs_api, resp.id, "train"):
        sys.exit(1)

    print(f"5) Build {DEPLOY_FORMAT}...")
    req = BuildOnDeviceModelRequest.from_dict({"eonCompiler": False, "engine": "tflite"})
    resp = jobs_api.build_on_device_model_job(
        project_id=PROJECT_ID, type=DEPLOY_FORMAT, build_on_device_model_request=req
    )
    if not poll_job(jobs_api, resp.id, "build"):
        sys.exit(1)

    print("6) Download...")
    hist = deploy_api.list_deployment_history(project_id=PROJECT_ID, limit=1)
    deployments = getattr(hist, "deployments", None) or []
    if not deployments:
        sys.exit("No deployment in history")
    ver = deployments[0].deployment_version
    url = f"{API_HOST}/api/{PROJECT_ID}/deployment/history/{ver}/download"
    r = requests.get(url, headers={"x-api-key": api_key}, timeout=180)
    r.raise_for_status()
    tflite = extract_tflite(r.content)
    print(f"   TFLite size: {len(tflite)} bytes")

    MODELS_TFLITE.write_bytes(tflite)
    EXPORTED_TFLITE.parent.mkdir(parents=True, exist_ok=True)
    EXPORTED_TFLITE.write_bytes(tflite)
    write_header(tflite, SKETCH_HDR)

    hdr_tool = REPO / "models" / "tflite_to_cpp_header.py"
    subprocess.run(
        [
            sys.executable,
            str(hdr_tool),
            str(MODELS_TFLITE),
            "-o",
            str(REPO / "models" / "model_v6.1_edge_impulse_grayscale.h"),
            "--var",
            "g_model_v6_1_edge_impulse_grayscale",
            "--label",
            "Edge Impulse 1000575 INT8 48x48 grayscale",
        ],
        check=True,
    )

    print(f"\nDone.")
    print(f"  Studio: https://studio.edgeimpulse.com/studio/{PROJECT_ID}")
    print(f"  {MODELS_TFLITE}")
    print(f"  {SKETCH_HDR}")
    print("  Reflash sketchboard/firmware/hard_negative_capturer/hard_negative_capturer.ino (grayscale)")


if __name__ == "__main__":
    main()
