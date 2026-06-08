# EagleEye — Models to Consider (shortlist to evaluate)

A curated shortlist of the candidate models worth checking on the ESP32-CAM,
distilled from the full catalog ([EAGLEEYE_MODEL_CATALOG.md](EAGLEEYE_MODEL_CATALOG.md)).
Use this to decide what to flash and benchmark next. All target the ESP32-CAM
AI Thinker (S1, 240 MHz).

## Decision at a glance

| Priority | Pick | Test acc | Human recall | Inference (ESP32) | Why |
|---|---|---|---|---|---|
| **Balanced (recommended)** ⭐ | **v7.16** RGB 96×96, ESP-NN on | **90.83%** | 87.5% | **872 ms (measured)** | only model that is >90% AND clean AND <1 s on device |
| Max accuracy | v7.3 RGB 96×96 transfer | 92.35% | 92.0% | ~1300 ms (est) | best accuracy; slower; verify ESP-NN behavior |
| Faster, slightly less accurate | v7.15 RGB 80×80, ESP-NN **on**¹ | 88.38% | 88.4% | ~600–900 ms (est)¹ | drop to 80×80 if you need margin under 1 s |
| Highest human recall | v7.4 RGB 64×64 transfer | 91.13% | **92.0%** | needs device check² | transfer model; ESP-NN behavior unverified |

¹ v7.15 was measured at 3500 ms with ESP-NN **off**; re-enable ESP-NN (it's standard conv → clean) to get the ~600–900 ms range. Verify on device.
² transfer models are depthwise-separable; with ESP-NN off they may be slow, with ESP-NN on they previously saturated. Must be verified on the S1 before trusting.

## Recommendation
**Deploy v7.16.** It's the only candidate that satisfies all the hard requirements at once:
- ✅ **>90% accuracy** (90.83% held-out test)
- ✅ **Balanced / no "always human" bias** (87.5% human / 92.6% nonhuman)
- ✅ **Clean on device** (ESP-NN safe — standard conv)
- ✅ **<1 s inference** (872 ms measured)
- ✅ **Trained from scratch** on your data (custom expert-mode CNN)

Library: `third_party/ei_arduino_library_rgb96_depthwise_espnn.zip` · Firmware: any **RGB** sketch (`eagleeye_latency_test` or `hard_negative_capturer`) — **not** the greyscale runtime sketch.

## What to check when evaluating any candidate
1. **Predictions clean?** Point at a non-human scene → must read `no human` with high nonhuman score. (ESP-NN on a *depthwise* model saturates to "always human" on the S1 — reject those.)
2. **Inference time** = the `classification` ms on serial (not total). Target < ~1 s for a responsive PIR-triggered shot.
3. **Human recall** matters most for intruder detection — prefer models that miss the fewest people, even at some false-alarm cost. Threshold tuning (lower the human threshold) trades nonhuman precision for human recall with no retrain.
4. **ESP-NN rule of thumb (S1):** ON is fine for **standard Conv2D** models (fast + clean); ON **saturates depthwise** models (MobileNet/SeparableConv2D); OFF is always correct but ~3–5× slower.

## Not recommended
- **v7.14** (greyscale depthwise, ESP-NN on) — saturates on device ("always human").
- **v7.5 / v7.8 / 48×48 variants** — human recall ≤ 77%, too low for reliable detection.
- **Any depthwise model with ESP-NN off at 96×96** — correct but ~3.5–5 s (e.g. v7.15-off).

## If you need >90% AND faster than ~870 ms
The S1 is near its ceiling for a >90% RGB model. Realistic options:
- Accept **v7.16 @ 872 ms** on a **PIR-triggered single-shot** flow (sleep between events → latency is a non-issue).
- Or move to an **ESP32-S3** (vector unit) — ESP-NN flies, MobileNet/depthwise run ~100–200 ms and don't saturate.
