# EagleEye — Model Catalog (training method + measured ESP32-CAM inference)

This catalog documents every human/non-human detection model trained in the
v7.x optimization work for the **ESP32-CAM AI Thinker (ESP32-S1)**. For each model:
its training method, dataset, accuracy (validation + held-out test from Edge
Impulse project `1000575`), and the **actual on-device inference time** measured
on hardware where available.

> Notes
> - **Test accuracy** = held-out test set (327 real images: 112 human / 215 nonhuman) — the honest generalization number.
> - **Inference time** = `result.timing.classification` (the NN invoke), measured on the ESP32-CAM at 240 MHz. "measured" = read off the serial monitor on device; "estimated" = derived from MAC count, not yet flashed.
> - The S1 has **no vector unit**, so ESP-NN gives only modest gains vs the S3.
> - Dataset evolved across runs; "balanced" = human class augmented (geometric, color-preserving) to ~match nonhuman; "class-weighted" = `autoClassWeights` (human ≈ 2× loss weight).

---

## Quick comparison

| Model | Input | Color | Backbone | ESP-NN | Test acc | Human recall | **Inference (ESP32)** | Notes |
|---|---|---|---|---|---|---|---|---|
| v7.3 | 96×96 | RGB | MobileNetV1 0.2 (transfer) | off | **92.35%** | 92.0% | ~1300 ms (est) | most accurate |
| v7.4 | 64×64 | RGB | MobileNetV1 0.2 (transfer) | off | 91.13% | 92.0% | est ~570 ms* | *transfer=depthwise, off→likely slower |
| v7.6 | 64×64 | grey | MobileNetV1 0.2 (transfer) | off | 89.91% | 84.8% | not measured | |
| v7.7 | 96×96 | grey | MobileNetV1 0.2 (transfer) | off | 91.44% | 86.6% | not measured | |
| v7.10 | 96×96 | grey | MobileNetV1 0.1 (transfer) | off | 89.30% | 81.3% | **~1100 ms (measured)** | clean |
| v7.13 | 80×80 | grey | custom CNN 16-32-32 (std conv) | on | 85.63% | 75.9% | **~1145 ms (measured)** | clean (0.895) |
| v7.14 | 96×96 | grey | custom "depthwise"→std conv | on | 86.85% | 83.0% | not usable | **saturated → "always human"** |
| v7.15 | 80×80 | RGB | custom "depthwise"→std conv | off | 88.38% | 88.4% | **~3500 ms (measured)** | clean but very slow (ref kernels) |
| **v7.16** ⭐ | 96×96 | RGB | custom "depthwise"→std conv | **on** | **90.83%** | 87.5% | **872 ms (measured)** | **clean + >90% + fast** |

---

## Per-model briefs

### v7.3 — RGB MobileNetV1 0.2 @ 96×96 (transfer)
- **Training:** Edge Impulse transfer learning (ImageNet-pretrained MobileNetV1 0.2 backbone + 32-neuron head, dropout 0.25), 40+10 epochs, lr 0.00035, batch 16, augmentation all, class-weighted, cleaned dataset.
- **Accuracy:** val 92.45% INT8 · **test 92.35%** · human recall 92.0%.
- **Inference:** ~1300 ms estimated (96×96 RGB; on-device ESP-NN-off). Most accurate model.

### v7.4 — RGB MobileNetV1 0.2 @ 64×64 (transfer) + EON
- **Training:** same as v7.3 but 64×64 input, EON-compiled, ESP-NN off.
- **Accuracy:** val 92.81% · **test 91.13%** · human recall 92.0%.
- **Inference:** estimated ~570 ms, but **not device-verified** — note MobileNet is depthwise-separable, so ESP-NN-off may run slower than the estimate (reference depthwise kernels).

### v7.10 — greyscale MobileNetV1 0.1 @ 96×96 (transfer)
- **Training:** transfer MobileNetV1 0.1 (light), greyscale, full data + class weights, ESP-NN off.
- **Accuracy:** val 91.73% · **test 89.30%** · human recall 81.3%.
- **Inference:** **~1100 ms (measured on device)**, clean predictions.

### v7.13 — greyscale custom CNN @ 80×80 (standard conv, balanced)
- **Training:** EI visual mode, custom 3-conv CNN (16→32→32 standard Conv2D) + dropout 0.5, 40 epochs, **human class augmented to parity** (929/920), ESP-NN on.
- **Accuracy:** val 91.62% · **test 85.63%** · human recall 75.9%. Overfitting removed (train≈val).
- **Inference:** **~1145 ms (measured)**, clean (`human 0.895`). Standard conv + ESP-NN is clean on the S1.

### v7.14 — greyscale custom "depthwise" @ 96×96 (ESP-NN on)
- **Training:** EI expert mode, intended `SeparableConv2D`; balanced data, ESP-NN on.
- **Accuracy (cloud):** val 92.70% · **test 86.85%** · human recall 83.0% — balanced in the cloud.
- **On device:** ❌ **"always human" (saturated).** Cause = ESP-NN depthwise-kernel saturation on the S1 (cloud test was balanced, so it's a kernel bug, not the model). → led to the RGB + ESP-NN-off rebuild (v7.15).

### v7.15 — RGB custom "depthwise" @ 80×80 (ESP-NN off)
- **Training:** EI expert mode (SeparableConv2D), **RGB**, ESP-NN off, balanced data.
- **Accuracy:** val 95.41% · **test 88.38%** · human recall 88.4% — **bias fixed, balanced.**
- **Inference:** **~3500 ms (measured)** — very slow. Root cause: the expert `SeparableConv2D` **deployed as standard Conv2D** (op resolver has no DepthwiseConv2D), so it's a heavy ~23M-MAC standard conv, and **ESP-NN off** ran it on slow reference int8 kernels.

### v7.16 — RGB custom "depthwise" @ 96×96 (ESP-NN ON) ⭐ CURRENT
- **Training:** EI expert mode (SeparableConv2D → deployed as standard Conv2D 8→16→32), **RGB 96×96**, balanced data (929/920) + class weights, INT8.
- **Accuracy:** val 93.78% · **test 90.83%** (>90% ✅) · human recall 87.5%, nonhuman 92.6% — balanced.
- **ESP-NN:** **ON** — safe because the model is standard conv (the saturation bug was depthwise-only). Verified clean on device.
- **Inference:** **872 ms (measured)** — `DSP 8 ms | classification 872 ms | total 890 ms`, predictions correct (e.g. nonhuman scene → `Human 0.133 / NonHuman 0.867 → no human`).
- **Library:** `third_party/ei_arduino_library_rgb96_depthwise_espnn.zip` (ESP-NN on) / `..._no_espnn.zip` (off).

---

## Known issue: `cam_hal: EV-EOF-OVF`
Seen in serial during runs with ~870 ms+ inference (e.g. v7.16).
- **Cause:** the OV2640 free-runs via DMA; while one ~870 ms inference runs, the camera fills both frame buffers (`fb_count=2`) and overflows because the loop isn't recycling buffers during inference. **GRAB_LATEST means the next `esp_camera_fb_get()` still returns the freshest frame**, so it is **benign** (a warning, not a failure) — predictions are unaffected.
- **Fix (cosmetic):** silence it in `setup()` with
  `esp_log_level_set("cam_hal", ESP_LOG_NONE);` (needs `#include "esp_log.h"`).
- Optional: deinit/reinit camera around inference, or accept the warning.

## Key lessons (S1-specific)
1. **ESP-NN saturates *depthwise* kernels on the S1** (wrong "always human"), but is **clean for standard Conv2D**. Standard conv + ESP-NN is the reliable fast+correct combo.
2. **ESP-NN off → reference int8 kernels are ~3–5× slower** (v7.15: 3500 ms).
3. **EI expert `SeparableConv2D` deployed as standard Conv2D** here (no DepthwiseConv2D op) — the depthwise MAC savings never materialized; treat these as standard-conv models.
4. **Resolution drives accuracy:** 96×96 needed to cross 90%; 64×64 ≈ 88–91%; 48×48 collapses (~77% human recall).
5. **Color helps human recall** (+5–7 pts vs greyscale).
