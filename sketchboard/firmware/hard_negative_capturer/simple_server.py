#!/usr/bin/env python3
"""
Simple Hard Negative Receiver - NO Flask needed.
Uses Python's built-in http.server.

Usage:  python simple_server.py
"""

import os
import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Dataset paths
DS_ROOT      = Path(__file__).resolve().parents[2] / "dataset"
HUMAN_DIR    = DS_ROOT / "Humans"
NONHUMAN_DIR = DS_ROOT / "NonHuman"
HUMAN_DIR.mkdir(parents=True, exist_ok=True)
NONHUMAN_DIR.mkdir(parents=True, exist_ok=True)


class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        print(f"[GET] {self.path}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Server is alive!")

    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        label = params.get("label", [""])[0].strip().lower()

        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length)

        print(f"[POST] {self.path}  label={label}  size={len(data)} bytes")

        if label not in ("human", "nonhuman"):
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Bad label")
            return

        if not data:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Empty body")
            return

        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        dest = HUMAN_DIR if label == "human" else NONHUMAN_DIR
        name = f"esp32_{label}_{ts}.jpg"
        path = dest / name
        path.write_bytes(data)

        print(f"[SAVED] {label.upper():>8s} -> {path.name}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"Saved {name}".encode())


if __name__ == "__main__":
    HOST, PORT = "0.0.0.0", 8000

    print("\n" + "=" * 52)
    print("   EagleEye  -  Simple Receiver (no Flask)")
    print("=" * 52)
    print(f"  Humans   -> {HUMAN_DIR}")
    print(f"  NonHuman -> {NONHUMAN_DIR}")
    print(f"\n  Listening on http://{HOST}:{PORT}")
    print("  Test in browser: http://127.0.0.1:8000/")
    print("  Waiting for ESP32 captures...\n")

    server = HTTPServer((HOST, PORT), Handler)
    server.serve_forever()
