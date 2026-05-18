#!/usr/bin/env python3
"""
Train an Edge Impulse image-classification project from the command line.

Prerequisites (one-time in Studio):
  1. Project type: Image classification.
  2. Data already uploaded (upload_dataset_to_ei.py).
  3. Impulse created: Image input -> Image DSP (set 48x48, grayscale if you
     match EagleEye) -> Classifier (Keras) or Transfer learning block.

Then:
  set EI_API_KEY=ei_...
  python tools/edge_impulse/train_on_ei.py --project-id YOUR_ID

This script: generate features -> train Keras -> wait for completion.
Training runs on Edge Impulse servers, not on your PC GPU (unless EI enables GPU).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

try:
    from edgeimpulse_api import (
        ApiClient,
        Configuration,
        GenerateFeaturesRequest,
        ImpulseApi,
        JobsApi,
        ProjectsApi,
        SetKerasParameterRequest,
    )
except ImportError:
    print(
        "Install Edge Impulse API bindings:\n"
        "  pip install edgeimpulse-api\n",
        file=sys.stderr,
    )
    sys.exit(1)

API_HOST = "https://studio.edgeimpulse.com/v1"


def poll_job(jobs_api: JobsApi, project_id: int, job_id: int, label: str) -> bool:
    while True:
        resp = jobs_api.get_job_status(project_id=project_id, job_id=job_id)
        if not getattr(resp, "success", True):
            print(f"[{label}] Could not get job status: {resp}", file=sys.stderr)
            return False
        job = getattr(resp, "job", None)
        if job and getattr(job, "finished", False):
            ok = getattr(job, "finished_successful", False)
            print(f"[{label}] finished success={ok}")
            return bool(ok)
        print(f"[{label}] waiting for job {job_id}...")
        time.sleep(3.0)


def pick_block_ids(impulse_api: ImpulseApi, project_id: int) -> tuple[int, int]:
    """Return (dsp_id, learn_id) from current impulse."""
    resp = impulse_api.get_impulse(project_id=project_id)
    if not getattr(resp, "success", True):
        raise RuntimeError(f"get_impulse failed: {resp}")

    impulse = getattr(resp, "impulse", None) or resp
    dsp_blocks = getattr(impulse, "dsp_blocks", None) or getattr(impulse, "dspBlocks", [])
    learn_blocks = getattr(impulse, "learn_blocks", None) or getattr(impulse, "learnBlocks", [])

    if not dsp_blocks or not learn_blocks:
        raise RuntimeError(
            "No impulse blocks found. Open Studio -> Impulse design and add:\n"
            "  Image -> Image processing -> Image / Keras classifier\n"
            "Then run this script again."
        )

    dsp_id = dsp_blocks[0].id if hasattr(dsp_blocks[0], "id") else dsp_blocks[0]["id"]
    learn_id = learn_blocks[0].id if hasattr(learn_blocks[0], "id") else learn_blocks[0]["id"]
    return int(dsp_id), int(learn_id)


def list_projects(projects_api: ProjectsApi) -> None:
    resp = projects_api.list_projects()
    projects = getattr(resp, "projects", None) or []
    if not projects:
        print("No projects on this API key.")
        return
    print("Projects:")
    for p in projects:
        pid = getattr(p, "id", None) or p.get("id")
        name = getattr(p, "name", None) or p.get("name")
        print(f"  id={pid}  name={name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Edge Impulse project via Studio API")
    parser.add_argument("--api-key", default=os.environ.get("EI_API_KEY", ""))
    parser.add_argument("--project-id", type=int, default=0, help="Edge Impulse project ID")
    parser.add_argument("--list-projects", action="store_true")
    parser.add_argument("--epochs", type=int, default=30, help="Training cycles")
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument(
        "--augmentation",
        choices=("none", "all"),
        default="none",
        help="EI image augmentation policy (none = no EI aug; all = default aug pack)",
    )
    parser.add_argument("--skip-features", action="store_true", help="Only retrain (features already built)")
    args = parser.parse_args()

    if not args.api_key:
        print("Set EI_API_KEY or pass --api-key", file=sys.stderr)
        sys.exit(1)

    config = Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": args.api_key})
    client = ApiClient(config)
    projects_api = ProjectsApi(client)
    impulse_api = ImpulseApi(client)
    jobs_api = JobsApi(client)

    if args.list_projects:
        list_projects(projects_api)
        return

    project_id = args.project_id
    if not project_id:
        resp = projects_api.list_projects()
        projects = getattr(resp, "projects", None) or []
        if not projects:
            print("No projects. Create one at https://studio.edgeimpulse.com", file=sys.stderr)
            sys.exit(1)
        project_id = getattr(projects[0], "id", None) or projects[0]["id"]
        name = getattr(projects[0], "name", None) or projects[0].get("name")
        print(f"Using first project: id={project_id} name={name!r}")

    dsp_id, learn_id = pick_block_ids(impulse_api, project_id)
    print(f"Project {project_id}: dsp_id={dsp_id}, learn_id={learn_id}")
    print(f"Studio: https://studio.edgeimpulse.com/studio/{project_id}")

    if not args.skip_features:
        print("\n--- Generate features ---")
        gen_req = GenerateFeaturesRequest.from_dict(
            {
                "dspId": dsp_id,
                "calculate_feature_importance": False,
                "skip_feature_explorer": True,
            }
        )
        resp = jobs_api.generate_features_job(
            project_id=project_id, generate_features_request=gen_req
        )
        if not getattr(resp, "success", True):
            raise RuntimeError(f"generate_features failed: {resp}")
        if not poll_job(jobs_api, project_id, resp.id, "features"):
            sys.exit(1)

    print("\n--- Train Keras model ---")
    train_req = SetKerasParameterRequest.from_dict(
        {
            "mode": "visual",
            "training_cycles": args.epochs,
            "learning_rate": args.learning_rate,
            "train_test_split": 0.8,
            "augmentationPolicyImage": args.augmentation,
            "skip_embeddings_and_memory": True,
        }
    )
    resp = jobs_api.train_keras_job(
        project_id=project_id,
        learn_id=learn_id,
        set_keras_parameter_request=train_req,
    )
    if not getattr(resp, "success", True):
        raise RuntimeError(f"train failed: {resp}")
    if not poll_job(jobs_api, project_id, resp.id, "train"):
        sys.exit(1)

    print("\nDone. Open Model testing / Deployment in Studio to download INT8 / Arduino library.")


if __name__ == "__main__":
    main()
