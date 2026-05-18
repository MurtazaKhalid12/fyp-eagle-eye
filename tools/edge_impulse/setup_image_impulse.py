#!/usr/bin/env python3
"""Create a default image-classification impulse if none exists."""

import json
import os
import sys

from edgeimpulse_api import ApiClient, Configuration, Impulse, ImpulseApi

API_HOST = "https://studio.edgeimpulse.com/v1"
PROJECT_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1000567
API_KEY = os.environ.get("EI_API_KEY", "")

if not API_KEY:
    print("Set EI_API_KEY", file=sys.stderr)
    sys.exit(1)

config = Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": API_KEY})
client = ApiClient(config)
impulse_api = ImpulseApi(client)

resp = impulse_api.get_impulse_blocks(project_id=PROJECT_ID)
data = json.loads(resp.to_json()) if hasattr(resp, "to_json") else resp

print("=== inputBlocks (image) ===")
for b in data.get("inputBlocks", []):
    if "image" in str(b.get("type", "")).lower() or "image" in str(b.get("name", "")).lower():
        print(json.dumps(b, indent=2))

print("\n=== dspBlocks (image) ===")
for b in data.get("dspBlocks", []):
    t = str(b.get("type", "")).lower()
    n = str(b.get("name", "")).lower()
    if "image" in t or "image" in n:
        print(json.dumps(b, indent=2))

print("\n=== learnBlocks (classification) ===")
for b in data.get("learnBlocks", []):
    t = str(b.get("type", "")).lower()
    if "keras" in t or "transfer" in t or "classif" in str(b.get("name", "")).lower():
        print(json.dumps(b, indent=2))
