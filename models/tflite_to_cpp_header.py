#!/usr/bin/env python3
"""Convert a .tflite file to an ESP32/TFLite Micro C header."""

from __future__ import annotations

import argparse
from pathlib import Path


def tflite_to_header(tflite_path: Path, out_path: Path, var_name: str, model_label: str) -> None:
    data = tflite_path.read_bytes()
    guard = f"{var_name.upper()}_H"

    lines = [
        f"// Auto-generated from {tflite_path.name}",
        f"// {model_label}",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        f"extern const unsigned char {var_name}[];",
        f"extern const unsigned int {var_name}_len;",
        "",
        f"const unsigned char {var_name}[] = {{",
    ]
    for i in range(0, len(data), 12):
        chunk = ", ".join(f"0x{b:02x}" for b in data[i : i + 12])
        lines.append(f"  {chunk},")
    lines.extend(
        [
            "};",
            f"const unsigned int {var_name}_len = {len(data)};",
            f"#endif  // {guard}",
            "",
        ]
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path} ({len(data)} bytes, var={var_name})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tflite", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--var",
        default="g_human_detect_model_data",
        help="C array symbol name",
    )
    parser.add_argument("--label", default="", help="Comment label for the model")
    args = parser.parse_args()
    tflite_to_header(args.tflite, args.output, args.var, args.label or args.tflite.name)


if __name__ == "__main__":
    main()
