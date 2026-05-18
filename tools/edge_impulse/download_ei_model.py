#!/usr/bin/env python3
"""Build and download INT8 TFLite from Edge Impulse, convert to ESP32 header."""

from __future__ import annotations

import io
import os
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
    KerasModelTypeEnum,
    DeploymentTargetEngine,
)

API_HOST = "https://studio.edgeimpulse.com/v1"
PROJECT_ID = 1000575
REPO = Path(__file__).resolve().parents[2]
DEPLOY_FORMAT = "arduino"
MODEL_OUT = REPO / "models" / "model_v6.1_edge_impulse_grayscale.tflite"


def poll_job(jobs_api: JobsApi, job_id: int) -> bool:
    while True:
        st = jobs_api.get_job_status(project_id=PROJECT_ID, job_id=job_id)
        job = st.job
        if job.finished:
            print(f"Build job finished success={job.finished_successful}")
            if not job.finished_successful:
                r = requests.get(
                    f"{API_HOST}/api/{PROJECT_ID}/jobs/{job_id}/stdout",
                    headers={"x-api-key": os.environ["EI_API_KEY"]},
                )
                for line in reversed(r.json().get("stdout", [])):
                    d = (line.get("data") or "").strip()
                    if d and "spinner" not in d:
                        print(" ", d[:500])
                        break
            return bool(job.finished_successful)
        print(f"Build running (job {job_id})...")
        time.sleep(8)


def extract_tflite(zip_bytes: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        candidates = [n for n in zf.namelist() if n.endswith(".tflite")]
        if not candidates:
            raise RuntimeError(f"No .tflite in zip. Files: {zf.namelist()[:20]}")
        # Prefer int8 / trained model names
        candidates.sort(
            key=lambda n: (
                0 if "int8" in n.lower() else 1,
                0 if "trained" in n.lower() else 1,
                len(n),
            )
        )
        name = candidates[0]
        print(f"Extracting {name}")
        return zf.read(name)


def write_header(tflite: bytes, out_path: Path) -> None:
    var = "g_human_detect_model_data"
    guard = f"{var.upper()}_H"
    lines = [
        "// Auto-generated from Edge Impulse project (INT8 TFLite)",
        f"// Project {PROJECT_ID} — EagleEye hard negative live testing",
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
    print(f"Wrote header {out_path} ({len(tflite)} bytes)")


def main() -> None:
    api_key = os.environ.get("EI_API_KEY", "")
    if not api_key:
        print("Set EI_API_KEY", file=sys.stderr)
        sys.exit(1)

    sketch_fw = REPO / "sketchboard" / "firmware" / "hard_negative_capturer"
    tflite_out = REPO / "sketchboard" / "ei_grayscale_int8.tflite"

    config = Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": api_key})
    client = ApiClient(config)
    jobs_api = JobsApi(client)
    deploy_api = DeploymentApi(client)

    print(f"Building deployment '{DEPLOY_FORMAT}' (int8, tflite engine)...")
    req = BuildOnDeviceModelRequest.from_dict({"eonCompiler": False, "engine": "tflite"})
    resp = jobs_api.build_on_device_model_job(
        project_id=PROJECT_ID,
        type=DEPLOY_FORMAT,
        build_on_device_model_request=req,
    )
    if not poll_job(jobs_api, resp.id):
        sys.exit(1)

    print("Downloading build zip...")
    zip_data = deploy_api.download_build(
        project_id=PROJECT_ID,
        type=DEPLOY_FORMAT,
        model_type=KerasModelTypeEnum("int8"),
        engine=DeploymentTargetEngine("tflite"),
    )
    if isinstance(zip_data, str):
        zip_bytes = zip_data.encode("latin-1")
    else:
        zip_bytes = zip_data

    tflite = extract_tflite(zip_bytes)
    tflite_out.write_bytes(tflite)
    MODEL_OUT.write_bytes(tflite)
    print(f"Saved {tflite_out} and {MODEL_OUT}")

    header_path = sketch_fw / "human_detect_model_data.h"
    write_header(tflite_out.read_bytes(), header_path)
    print(f"Ready to flash: {sketch_fw / 'hard_negative_capturer.ino'}")


if __name__ == "__main__":
    main()
