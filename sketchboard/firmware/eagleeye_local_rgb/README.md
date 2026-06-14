# EagleEye — Local model firmware (PlatformIO, self-contained)

ESP32-CAM (AI Thinker) firmware that runs a **locally-trained** 96×96 RGB
human/non-human detector on **TFLite-Micro + ESP-NN**, with **everything in this
one folder** — nothing installed into Arduino's `libraries/`, no `Add .ZIP`.

## Layout

```
eagleeye_local/
  platformio.ini            board + build config (PSRAM, Huge-APP, 240 MHz)
  src/main.cpp              the firmware
  src/model_data.h          OUR trained int8 weights (g_model[]) — written by training
  lib/final_inferencing/    the TFLM + ESP-NN engine (ESP-NN enabled)
```

PlatformIO automatically adds `lib/final_inferencing/` to the include path and
compiles it — that's why this works in-folder with no system install (the thing
Arduino IDE can't do for a library with rooted includes).

## What's local vs. what's the engine

- **Model** = `src/model_data.h` (≈15 KB). 100% ours, trained by
  `sketchboard/train_ei_local.py` (a faithful local replica of the EI "final"
  project). Edge Impulse trained nothing.
- **Engine** = `lib/final_inferencing/`. Edge Impulse's Arduino SDK, used **only**
  as the int8 runtime because it bundles **ESP-NN** (hardware-accelerated int8
  kernels). `EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN = 1`. We load *our* model into it
  via `MicroInterpreter` — we do **not** use EI's bundled model.

Verified in the build: `esp_nn_conv_s8_opt`, `esp_nn_fully_connected_s8_ansi`,
`esp_nn_max_pool_s8_ansi` are linked into `firmware.elf`.

## Build / flash / monitor

Requires the PlatformIO extension (VS Code) or the `pio` CLI — already installed.

```bash
pio run                 # compile  (first run downloads the toolchain, ~minutes)
pio run -t upload       # flash the ESP32-CAM
pio device monitor -b 115200
```

Board is pinned to `espressif32@6.5.0` = **arduino-esp32 2.0.14** (matches the
Arduino IDE setup). Last build: RAM 17.0%, Flash 14.4% of the 3 MB Huge-APP
partition.

## Updating the model

Retrain, which rewrites `src/model_data.h` in place, then re-flash:

```bash
python ../../train_ei_local.py    # from sketchboard/, writes src/model_data.h
pio run -t upload
```

## I/O convention (must match training)

- Input: RGB888 0..255 → normalise `/255` → quantise with the model's own input
  scale/zero-point (`1/255`, `-128`). Centre-square crop + resize to 96×96.
- Output softmax order: `[0] = human`, `[1] = nonhuman`. Threshold `0.65`
  (matches the EI project); lower it to trade precision for recall.

## Expected serial output

```
=== EagleEye LOCAL (PlatformIO · TFLM + ESP-NN) ===
[build] ESP-NN: ENABLED
[OK] input 96x96x3 scale=0.003922 zp=-128 | arena used ...
HUMAN     | Human 0.94  NonHuman 0.06 | Inference 8x ms
no human  | Human 0.11  NonHuman 0.89 | Inference 8x ms
```
