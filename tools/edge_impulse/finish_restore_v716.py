#!/usr/bin/env python3
"""
Finish the v7.16 (RGB96 depthwise) restore:
- attach to the already-running train job (or start one), wait for it,
- build the Arduino library,
- produce BOTH zips: ESP-NN ON (raw) and ESP-NN OFF (patched),
- save an Edge Impulse version snapshot so v7.16 is restorable next time.

Writes to third_party/ (root). Leaves third_party/current_model/ (the original
deployed v7.16) untouched.
"""
import io, os, re, sys, time, shutil, zipfile
from pathlib import Path
import requests

KEY = os.environ.get("EI_API_KEY") or sys.exit("Set EI_API_KEY")
PROJ = 1000575
LEARN_ID = 3
BASE = f"https://studio.edgeimpulse.com/v1/api/{PROJ}"
H = {"x-api-key": KEY}
HJ = {"x-api-key": KEY, "Content-Type": "application/json"}

TP = Path(r"C:\fyp-eagle-eye\third_party")
ZIP_ESPNN = TP / "ei_arduino_library_rgb96_depthwise_espnn.zip"
ZIP_NOESPNN = TP / "ei_arduino_library_rgb96_depthwise_no_espnn.zip"
UNPACK = TP / "_restore_v716_unpack"


def jget(path):
    r = requests.get(BASE + path, headers=H, timeout=120)
    r.raise_for_status()
    return r.json()


def jpost(path, body):
    r = requests.post(BASE + path, headers=HJ, json=body, timeout=120)
    try:
        return r.json()
    except Exception:
        raise RuntimeError(f"POST {path} -> {r.status_code} {r.text[:500]}")


def poll(job_id, label, timeout_min=75):
    start = time.time()
    while True:
        if time.time() - start > timeout_min * 60:
            print(f"[{label}] TIMEOUT", flush=True); return False
        job = jget(f"/jobs/{job_id}/status").get("job", {})
        if job.get("finished"):
            ok = bool(job.get("finishedSuccessful"))
            print(f"[{label}] finished success={ok}", flush=True); return ok
        print(f"[{label}] job {job_id} running ({int(time.time()-start)}s)...", flush=True)
        time.sleep(20)


def start_or_attach_train():
    resp = jpost(f"/jobs/train/keras/{LEARN_ID}", {"mode": "expert"})
    if resp.get("id"):
        print(f"started train job {resp['id']}", flush=True); return resp["id"]
    m = re.search(r"job ID: (\d+)", resp.get("error", ""))
    if m:
        print(f"attaching to running train job {m.group(1)}", flush=True); return int(m.group(1))
    sys.exit(f"train start failed: {resp}")


def zip_dir(src_dir: Path, zip_path: Path):
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in src_dir.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(src_dir.parent))


def patch_esp_nn_off(lib_dir: Path):
    cfg = lib_dir / "src" / "edge-impulse-sdk" / "classifier" / "ei_classifier_config.h"
    t = cfg.read_text(encoding="utf-8")
    s = t.index("#ifndef EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN")
    e = t.index("#if EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN == 1", s)
    repl = ("#ifndef EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN\n"
            "    #define EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN      0\n"
            "#endif")
    cfg.write_text(t[:s] + repl + "\n\n" + t[e:], encoding="utf-8")


def main():
    print("== 1) ensure depthwise model is trained ==", flush=True)
    if not poll(start_or_attach_train(), "train"):
        print("attached/started train did not succeed; starting a fresh one...", flush=True)
        r = jpost(f"/jobs/train/keras/{LEARN_ID}", {"mode": "expert"})
        jid = r.get("id")
        if not jid:
            sys.exit(f"fresh train start failed: {r}")
        if not poll(jid, "train2"):
            sys.exit("training failed")

    try:
        meta = jget(f"/training/keras/{LEARN_ID}/metadata")
        int8 = next((m for m in meta.get("modelValidationMetrics", []) if m.get("type") == "int8"), None)
        if int8:
            print(f"[metrics] INT8 val accuracy {int8.get('accuracy',0)*100:.2f}%  matrix {int8.get('confusionMatrix')}", flush=True)
    except Exception as ex:
        print("metrics unavailable:", ex, flush=True)

    print("== 2) build Arduino library ==", flush=True)
    b = jpost("/jobs/build-ondevice-model?type=arduino", {"engine": "tflite"})
    if not b.get("id"):
        sys.exit(f"build start failed: {b}")
    if not poll(b["id"], "build", 30):
        sys.exit("build failed")

    print("== 3) download library ==", flush=True)
    hist = jget("/deployment/history?limit=1")
    dep = hist["deployments"][0]
    ver = dep.get("deploymentVersion") or dep.get("deployment_version")
    r = requests.get(BASE + f"/deployment/history/{ver}/download", headers=H, timeout=600)
    r.raise_for_status()
    if UNPACK.exists():
        shutil.rmtree(UNPACK)
    UNPACK.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        zf.extractall(UNPACK)
    lib_dir = [p for p in UNPACK.iterdir() if p.is_dir()][0]

    print("== 4) write BOTH zips ==", flush=True)
    zip_dir(lib_dir, ZIP_ESPNN)        # raw EI build = ESP-NN ON
    print("   wrote", ZIP_ESPNN.name, "(ESP-NN ON)", flush=True)
    patch_esp_nn_off(lib_dir)
    zip_dir(lib_dir, ZIP_NOESPNN)      # patched = ESP-NN OFF
    print("   wrote", ZIP_NOESPNN.name, "(ESP-NN OFF)", flush=True)
    shutil.rmtree(UNPACK, ignore_errors=True)

    print("== 5) save Edge Impulse version snapshot ==", flush=True)
    try:
        v = jpost("/versions", {
            "description": "v7.16 RGB96 depthwise CNN (restored): Conv2D(8)+BN -> SeparableConv2D(16)+BN -> SeparableConv2D(32)+BN -> Flatten -> Dropout(0.5) -> Dense, 96x96 RGB INT8",
            "makePublic": False,
            "bumpType": "patch",
        })
        if v.get("id"):
            poll(v["id"], "save-version", 20)
        print("   version snapshot saved:", v.get("success"), flush=True)
    except Exception as ex:
        print("   save-version skipped:", ex, flush=True)

    print("=" * 64, flush=True)
    print(f" RESTORED v7.16 depthwise (deploy version {ver})", flush=True)
    print(f"   ESP-NN ON : {ZIP_ESPNN}", flush=True)
    print(f"   ESP-NN OFF: {ZIP_NOESPNN}", flush=True)
    print("=" * 64, flush=True)


if __name__ == "__main__":
    main()
