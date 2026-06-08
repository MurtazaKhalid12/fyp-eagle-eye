#!/usr/bin/env python3
"""
Fast model swap for the Arduino EI library — avoids full SDK recompiles.

Instead of "Add .ZIP Library" (which replaces the whole final_inferencing folder
and forces Arduino to recompile the entire edge-impulse-sdk, ~minutes), this copies
ONLY the files that actually change between retrains:
    src/model-parameters/   (model_metadata.h, model_variables.h, ...)
    src/tflite-model/        (the quantized model)
    src/edge-impulse-sdk/classifier/ei_classifier_config.h  (ESP-NN flag, if changed)

The huge edge-impulse-sdk / tensorflow source files are left untouched (same mtime),
so Arduino's build cache reuses their compiled .o files -> recompile drops to seconds.

Usage (PowerShell):
  python tools/edge_impulse/swap_ei_model.py third_party/ei_arduino_library_rgb64_mobilenetv1_a2_eon_no_espnn.zip
  # optionally pass the installed library path as 2nd arg if auto-detect fails
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

# Folders/files that change per model (everything else is the unchanging SDK).
SWAP_PATHS = [
    "src/model-parameters",
    "src/tflite-model",
    "src/edge-impulse-sdk/classifier/ei_classifier_config.h",
]


def find_installed_lib() -> Path | None:
    import os
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    candidates = [
        home / "Documents" / "Arduino" / "libraries" / "final_inferencing",
        home / "OneDrive" / "Documents" / "Arduino" / "libraries" / "final_inferencing",
        home / "OneDrive - Higher Education Commission" / "Documents" / "Arduino" / "libraries" / "final_inferencing",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    # last resort: search a few levels under the profile
    for p in home.glob("**/Arduino/libraries/final_inferencing"):
        return p
    return None


def _force_copy(src: Path, dst: Path) -> None:
    """Copy a single file, clearing a read-only/locked dst first (OneDrive/Win)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        import os, stat
        try:
            os.chmod(dst, stat.S_IWRITE)
        except OSError:
            pass
    shutil.copy2(src, dst)


def copy_path(src_root: Path, dst_root: Path, rel: str) -> bool:
    src = src_root / rel
    dst = dst_root / rel
    if not src.exists():
        return False
    if src.is_dir():
        # Merge-copy file-by-file (overwrite in place) instead of rmtree+copytree.
        # rmtree fails with PermissionError when OneDrive / Arduino holds the dir.
        for f in src.rglob("*"):
            if f.is_file():
                _force_copy(f, dst / f.relative_to(src))
    else:
        _force_copy(src, dst)
    return True


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: python swap_ei_model.py <new_library.zip> [installed_lib_dir]")
    zip_path = Path(sys.argv[1])
    if not zip_path.is_file():
        sys.exit(f"Zip not found: {zip_path}")

    installed = Path(sys.argv[2]) if len(sys.argv) > 2 else find_installed_lib()
    if not installed or not installed.is_dir():
        sys.exit("Could not find installed final_inferencing library. Pass its path as 2nd arg.")
    print(f"Installed library: {installed}")

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        # the zip contains one top folder (final_inferencing)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if not roots:
            sys.exit("Zip has no library folder")
        src_root = roots[0]

        swapped = []
        for rel in SWAP_PATHS:
            if copy_path(src_root, installed, rel):
                swapped.append(rel)
        print("Swapped (only these — SDK left cached):")
        for s in swapped:
            print(f"  {s}")

    print("\nDone. In Arduino: just press Compile/Upload (do NOT re-Add the .ZIP).")
    print("The edge-impulse-sdk is unchanged, so only the model recompiles -> fast.")


if __name__ == "__main__":
    main()
