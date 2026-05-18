#!/usr/bin/env python3
"""Download latest Edge Impulse INT8 build into sketchboard + models (grayscale)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "edge_impulse" / "retrain_grayscale_and_deploy.py"


def main() -> None:
    if not __import__("os").environ.get("EI_API_KEY"):
        print("Set EI_API_KEY (admin key for project 1000575)", file=sys.stderr)
        sys.exit(1)
    print("Running full grayscale pipeline (DSP config, features, train, build, deploy)...")
    print(f"  {SCRIPT}\n")
    subprocess.run([sys.executable, str(SCRIPT)], check=True)


if __name__ == "__main__":
    main()
