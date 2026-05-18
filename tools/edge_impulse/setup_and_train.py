#!/usr/bin/env python3
"""Create 48x48 grayscale image impulse and start EI training."""

import os
import sys
import time

from edgeimpulse_api import (
    ApiClient,
    Configuration,
    GenerateFeaturesRequest,
    Impulse,
    ImpulseApi,
    JobsApi,
    SetKerasParameterRequest,
)

API_HOST = "https://studio.edgeimpulse.com/v1"
DEFAULT_PROJECT_ID = 1000575


def poll_job(jobs_api: JobsApi, project_id: int, job_id: int, label: str) -> bool:
    while True:
        resp = jobs_api.get_job_status(project_id=project_id, job_id=job_id)
        job = getattr(resp, "job", None)
        if job and getattr(job, "finished", False):
            ok = getattr(job, "finished_successful", False)
            print(f"[{label}] done success={ok}")
            return bool(ok)
        print(f"[{label}] job {job_id} running...")
        time.sleep(5)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=DEFAULT_PROJECT_ID)
    args = parser.parse_args()
    project_id = args.project_id

    api_key = os.environ.get("EI_API_KEY", "")
    if not api_key:
        print("Set EI_API_KEY", file=sys.stderr)
        sys.exit(1)

    config = Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": api_key})
    client = ApiClient(config)
    impulse_api = ImpulseApi(client)
    jobs_api = JobsApi(client)

    impulse = Impulse.from_dict(
        {
            "name": "EagleEye 48x48 human",
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

    print(f"Project {project_id}: creating impulse (48x48, Keras classifier)...")
    resp = impulse_api.create_impulse(project_id=project_id, impulse=impulse)
    if not getattr(resp, "success", True):
        raise RuntimeError(f"create_impulse failed: {resp}")
    print("Impulse saved.")

    from edgeimpulse_api import DSPApi, DSPConfigRequest

    dsp_api = DSPApi(client)
    print("Setting Image DSP to Grayscale...")
    dsp_api.set_dsp_config(
        project_id=project_id,
        dsp_id=2,
        dsp_config_request=DSPConfigRequest.from_dict({"config": {"channels": "Grayscale"}}),
    )

    print("Generating features...")
    gen = GenerateFeaturesRequest.from_dict(
        {
            "dspId": 2,
            "calculate_feature_importance": False,
            "skip_feature_explorer": True,
        }
    )
    resp = jobs_api.generate_features_job(project_id=project_id, generate_features_request=gen)
    if not poll_job(jobs_api, project_id, resp.id, "features"):
        sys.exit(1)

    print("Training (30 epochs, no EI image augmentation)...")
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
        project_id=project_id, learn_id=3, set_keras_parameter_request=train
    )
    if not poll_job(jobs_api, project_id, resp.id, "train"):
        sys.exit(1)

    print(f"Done: https://studio.edgeimpulse.com/studio/{project_id}")


if __name__ == "__main__":
    main()
