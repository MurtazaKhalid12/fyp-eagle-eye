#!/usr/bin/env python3
"""
Clean and balance the Edge Impulse dataset for project 1000575.

Steps:
  1. Relabel samples whose filename clearly contradicts the label
     (`human` label but filename contains `nonhuman`).
  2. Remove duplicate samples by sha256Hash (keep the oldest in each group).
  3. Down-sample the majority class so the two classes match in size.
  4. Print before/after counts.

Usage (PowerShell):
  $env:EI_API_KEY = "ei_..."
  python tools/edge_impulse/clean_and_balance_dataset.py

Add --dry-run to preview without modifying Studio.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict

from edgeimpulse_api import (
    ApiClient,
    Configuration,
    EditSampleLabelRequest,
    RawDataApi,
)
from edgeimpulse_api.models.raw_data_filter_category import RawDataFilterCategory


PROJECT_ID = 1000575
API_HOST = "https://studio.edgeimpulse.com/v1"
SEED = 42
CHUNK = 100  # ids per batch API call


def to_dict(obj):
    return obj.to_dict() if hasattr(obj, "to_dict") else obj


def list_all_training(raw: RawDataApi):
    out = []
    offset = 0
    limit = 250
    while True:
        resp = raw.list_samples(
            project_id=PROJECT_ID,
            category=RawDataFilterCategory.TRAINING,
            limit=limit,
            offset=offset,
            exclude_sensors=True,
        )
        samples = to_dict(resp).get("samples") or []
        out.extend(samples)
        if len(samples) < limit:
            break
        offset += limit
    return out


def chunked(items, n):
    for i in range(0, len(items), n):
        yield items[i : i + n]


def batch_relabel(raw: RawDataApi, ids, new_label, dry_run):
    if not ids:
        return
    print(f"  Relabel -> {new_label}: {len(ids)} samples")
    if dry_run:
        return
    for batch in chunked(list(ids), CHUNK):
        raw.batch_edit_labels(
            project_id=PROJECT_ID,
            category=RawDataFilterCategory.TRAINING,
            edit_sample_label_request=EditSampleLabelRequest(label=new_label),
            ids=json.dumps(batch),
        )


def batch_remove(raw: RawDataApi, ids, dry_run, label):
    if not ids:
        return
    print(f"  Delete: {len(ids)} samples ({label})")
    if dry_run:
        return
    for batch in chunked(list(ids), CHUNK):
        raw.batch_delete(
            project_id=PROJECT_ID,
            category=RawDataFilterCategory.TRAINING,
            ids=json.dumps(batch),
        )
        time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("EI_API_KEY")
    if not api_key:
        sys.exit("EI_API_KEY env var is missing")

    client = ApiClient(
        Configuration(host=API_HOST, api_key={"ApiKeyAuthentication": api_key})
    )
    raw = RawDataApi(client)

    print("Pulling training samples...")
    samples = list_all_training(raw)
    print(f"Loaded {len(samples)} samples")

    # ---- 1) Filename/label mismatch ----
    relabel_ids = []
    for s in samples:
        label = (s.get("label") or "").lower()
        fn = (s.get("filename") or "").lower()
        if label == "human" and "nonhuman" in fn:
            relabel_ids.append(s["id"])
            s["label"] = "nonhuman"
        elif label == "nonhuman" and "human" in fn and "nonhuman" not in fn:
            relabel_ids.append(s["id"])
            s["label"] = "human"

    print("\n[1/3] Relabel mismatched filenames")
    batch_relabel(raw, relabel_ids, "nonhuman", args.dry_run)

    # ---- 2) Deduplicate by sha256Hash ----
    by_hash = defaultdict(list)
    no_hash = 0
    for s in samples:
        h = s.get("sha256Hash")
        if not h:
            no_hash += 1
            continue
        by_hash[h].append(s)
    dup_delete = []
    for h, group in by_hash.items():
        if len(group) > 1:
            group_sorted = sorted(group, key=lambda x: x.get("id") or 0)
            for extra in group_sorted[1:]:
                dup_delete.append(extra["id"])
    print(f"\n[2/3] Deduplicate by sha256Hash")
    print(f"  Groups with duplicates: {sum(1 for g in by_hash.values() if len(g) > 1)}")
    print(f"  Samples missing hash:   {no_hash}")
    batch_remove(raw, dup_delete, args.dry_run, "duplicates")

    drop = set(dup_delete)
    survivors = [s for s in samples if s["id"] not in drop]

    # ---- 3) Balance classes ----
    counts = Counter((s.get("label") or "").lower() for s in survivors)
    print(f"\n[3/3] Balance classes (current: {dict(counts)})")
    if not counts:
        print("  No samples left, aborting balance")
        return
    min_count = min(counts.values())
    rng = random.Random(SEED)
    balance_delete = []
    for label, count in counts.items():
        extra = count - min_count
        if extra <= 0:
            continue
        pool = [s["id"] for s in survivors if (s.get("label") or "").lower() == label]
        rng.shuffle(pool)
        balance_delete.extend(pool[:extra])
    print(f"  Target per class: {min_count}")
    batch_remove(raw, balance_delete, args.dry_run, "majority-downsample")

    if args.dry_run:
        print("\n(dry-run) Skipping verification.")
        return

    print("\nVerifying counts after cleanup...")
    after = list_all_training(raw)
    final = Counter((s.get("label") or "").lower() for s in after)
    print(f"Total training samples now: {len(after)}")
    print(f"Label counts: {dict(final)}")


if __name__ == "__main__":
    main()
