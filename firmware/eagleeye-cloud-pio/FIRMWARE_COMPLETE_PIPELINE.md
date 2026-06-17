# EagleEye Firmware — Complete Pipeline (Evaluation Reference)

Everything connected, from power-on to phone notification, with all the math.

---

## PART 1: THE HARDWARE

**Board**: AI-Thinker ESP32-CAM

| Spec | Value | Why It Matters |
|:---|:---|:---|
| CPU | Dual-core Xtensa LX6, **240 MHz** | Core 0 = servos, Core 1 = everything else |
| Internal SRAM | **~520 KB** | Tight — tensor arena (126 KB) + TLS (40 KB) + system (~150 KB) eat most of it |
| PSRAM | **4 MB** (external, SPI) | Camera frame buffers go here (300 KB). ~3× slower than internal SRAM |
| Flash | **4 MB** | Stores firmware code + the 13 KB model weights. Partition = `huge_app.csv` |
| Camera | **OV2640** | Supports RGB565 (raw) and hardware JPEG. Captures at QVGA (320×240) |
| Wi-Fi | 802.11 b/g/n, **2.4 GHz** | TX power lowered to 8.5 dBm to prevent brownout |

**Pin assignments**: Pan servo = GPIO 15, Tilt servo = GPIO 14, Flash LED = GPIO 4, Camera uses 13 pins (data bus + control)

---

## PART 2: BOOT SEQUENCE (setup)

The ESP32 boots and executes these steps once:

```
Step 1:  Disable brownout detector (cheap USB supplies droop during Wi-Fi TX)
Step 2:  Serial.begin(115200) — debug output
Step 3:  config_load() — read Wi-Fi/MQTT/Cloudinary settings from NVS flash
Step 4:  Allocate snapshot_buf — 96×96×3 = 27,648 bytes in internal SRAM
Step 5:  Initialize camera — RGB565, QVGA (320×240), 2 frame buffers in PSRAM
Step 6:  Initialize servos — Pan GPIO15, Tilt GPIO14, both centered at 90°, LEDC timers 1-3
Step 7:  Connect Wi-Fi → sync clock via SNTP → connect MQTT broker (TLS port 8883)
Step 8:  Start LAN WebSocket server on port 81
Step 9:  Pin servo stepper task to Core 0: xTaskCreatePinnedToCore(..., 4096 stack, priority 2, core 0)
Step 10: Print heap stats → enter loop()
```

---

## PART 3: THE THREE DEVICE MODES

The firmware runs in exactly ONE mode at a time:

| Mode | Camera Format | What Runs | AI Active? |
|:---|:---|:---|:---:|
| **MODE_AI** | RGB565 QVGA | Capture → Resize → Classify → Decide | ✅ |
| **MODE_UPLOADING** | RGB565 QVGA | Flash LED → Grab JPEG → Upload to cloud | ❌ |
| **MODE_RELAY** | RGB565 QVGA (software JPEG) | Grab → JPEG encode → Send via WebSocket | ❌ |

> **Critical design rule**: Only one mode at a time because the ESP32 doesn't have enough RAM for AI + TLS upload or AI + video streaming simultaneously.

---

## PART 4: THE AI INFERENCE PIPELINE (The Core)

This is the main loop when in MODE_AI. Each cycle takes ~800 ms.

### Step 1: Camera Captures a Raw Frame

```
esp_camera_fb_get() → DMA fills a frame buffer in PSRAM

Frame format: RGB565 (2 bytes per pixel)
Frame size:   320 × 240 × 2 = 153,600 bytes
Location:     PSRAM (external memory)
```

**RGB565** packs each pixel into 16 bits: 5 bits Red, 6 bits Green, 5 bits Blue. Green gets 6 bits because the human eye is most sensitive to green.

### Step 2: Resize — Crop + Shrink + Convert

The function `resize_rgb565_to_rgb888()` does three things in ONE pass:

**2a. Center-crop 320×240 → 240×240 (make it square)**
```
Offset = (320 - 240) / 2 = 40 pixels
Cut 40 pixels from left, 40 from right
The model needs a square input
```

**2b. Nearest-neighbor downscale 240×240 → 96×96**
```
For each output pixel (x, y):
  source_x = 40 + (x × 240 / 96)    ← pick every ~2.5th pixel
  source_y = y × 240 / 96
  Copy the pixel at (source_x, source_y)

No interpolation — just pick and copy. Fastest possible method.
```

**2c. Convert RGB565 (2 bytes) → RGB888 (3 bytes)**
```
Read 2-byte pixel: uint16_t p = (byte1 << 8) | byte2

Extract channels:
  R = (p >> 11) & 0x1F     → 5 bits (0-31)
  G = (p >> 5)  & 0x3F     → 6 bits (0-63)
  B =  p        & 0x1F     → 5 bits (0-31)

Scale to full 8-bit range:
  R_out = (R << 3) | (R >> 2)    → 0-31 becomes 0-255
  G_out = (G << 2) | (G >> 4)    → 0-63 becomes 0-255
  B_out = (B << 3) | (B >> 2)    → 0-31 becomes 0-255
```

**Result**: `snapshot_buf` = 96 × 96 × 3 = **27,648 bytes** of RGB888 in internal SRAM.

### Step 3: Build the Signal (Callback System)

```c
ei::signal_t signal;
signal.total_length = 96 * 96;        // 9,216 pixels
signal.get_data = &ei_get_data_cb;    // "call this function to get pixel data"
```

Edge Impulse uses a PULL model — it doesn't want the whole buffer copied. Instead, it calls YOUR callback function to request pixels on demand.

**The callback** packs R, G, B bytes into a single float as `0xRRGGBB`:
```
out = (R << 16) + (G << 8) + B
Example: R=173, G=215, B=98 → 11,392,866
```

### Step 4: run_classifier() — THE BLACK BOX

```c
ei_impulse_result_t result = { 0 };
run_classifier(&signal, &result, false);
```

This ONE function call enters the Edge Impulse library and does everything below.

---

## PART 5: INSIDE run_classifier() — THE EDGE IMPULSE PIPELINE

### What Is Edge Impulse in This Project?

Edge Impulse is **NOT** a cloud service the ESP32 calls. It's a **pre-generated C++ library** sitting in `lib/eagleeye_vision/`. It was generated once on the Edge Impulse website and downloaded. No internet needed at runtime.

### The Library Structure

```
lib/eagleeye_vision/src/
├── eagleeye_vision.h              ← The ONE header your code includes
├── edge-impulse-sdk/              ← THE ENGINE (TFLite Micro + ESP-NN)
├── model-parameters/              ← THE RECIPE (input 96×96 RGB, 2 classes)
│   ├── model_metadata.h              Constants: input size, arena size, labels
│   └── model_variables.h            Wires model to engine, defines categories
└── tflite-model/                  ← THE BRAIN (architecture + weights)
    └── tflite_learn_1000575_3.h      13,272 bytes = the complete neural network
```

### Your Code Touches Edge Impulse at Exactly TWO Points

1. `#include <eagleeye_vision.h>` — pulls in the library
2. `run_classifier(&signal, &result, false)` — calls the one function

Everything else (camera, servos, MQTT, uploads) has ZERO connection to Edge Impulse.

### What Happens Inside run_classifier()

**Phase A — DSP Block** (`extract_image_features`):
- Calls YOUR callback to fetch all 9,216 pixels
- Unpacks 0xRRGGBB → separate R, G, B
- Normalizes to INT8 range using quantization parameters

**Phase B — Neural Network** (`run_nn_inference`):
- Allocates 126 KB tensor arena in internal SRAM
- Loads model from the 13 KB weight array in flash
- Executes each layer (Conv2D → MaxPool → SepConv → MaxPool → SepConv → MaxPool → Dense → Softmax)
- ESP-NN accelerates Conv2D, DepthwiseConv2D, FullyConnected, MaxPool
- Takes ~800 ms

**Phase C — Post-Processing** (`process_classification_i8`):
- Dequantizes INT8 output → float probabilities
- Formula: `float = (int8_value + 128) × 0.00390625`
- Fills `result.classification[]` with label + value pairs

---

## PART 6: THE MODEL ARCHITECTURE

```
Input:         96 × 96 × 3  (RGB image)
                    │
Conv2D(8):     3×3 kernel, 8 filters → 96×96×8    then MaxPool → 48×48×8
                    │
SepConv2D(16): Depthwise 3×3 + Pointwise 1×1 → 48×48×16    then MaxPool → 24×24×16
                    │
SepConv2D(32): Depthwise 3×3 + Pointwise 1×1 → 24×24×32    then MaxPool → 12×12×32
                    │
Flatten:       12×12×32 = 4,608 values (1D vector)
                    │
Dropout(0.5):  Skipped during inference (does nothing on ESP32)
                    │
Dense(2):      4,608 inputs → 2 outputs
                    │
Softmax:       Raw scores → probabilities that sum to 1.0
                    │
Output:        [human: 0.87, nonhuman: 0.13]
```

---

## PART 7: WEIGHT CALCULATIONS PER LAYER

### Formulas:
- **Conv2D**: weights = `kernel_w × kernel_h × input_channels × output_channels`
- **Depthwise**: weights = `kernel_w × kernel_h × input_channels` (NO × output_channels)
- **Pointwise (1×1)**: weights = `1 × 1 × input_channels × output_channels`
- **Dense**: weights = `input_size × output_size`
- **MaxPool, Flatten, Dropout, Softmax, BatchNorm**: weights = 0 (BatchNorm folded into conv)
- **Biases**: `output_channels × 4 bytes` (stored as INT32)
- **MaxPool effect**: spatial dimensions ÷ 2, channels unchanged

### Layer-by-Layer Calculation:

```
LAYER                 SHAPE CHANGE                 WEIGHTS              BIASES        TOTAL
─────                 ────────────                 ───────              ──────        ─────

Conv2D(8)             96×96×3 → 96×96×8      3×3×3×8    = 216     8×4  = 32        248 B
MaxPool               96×96×8 → 48×48×8            0                  0              0

SepConv2D(16):
  Depthwise           48×48×8 → 48×48×8      3×3×8      =  72     8×4  = 32        104 B
  Pointwise           48×48×8 → 48×48×16     1×1×8×16   = 128    16×4  = 64        192 B
MaxPool               48×48×16 → 24×24×16          0                  0              0

SepConv2D(32):
  Depthwise           24×24×16 → 24×24×16    3×3×16     = 144    16×4  = 64        208 B
  Pointwise           24×24×16 → 24×24×32    1×1×16×32  = 512    32×4  = 128       640 B
MaxPool               24×24×32 → 12×12×32          0                  0              0

Flatten               12×12×32 → 4608              0                  0              0
Dense(2)              4608 → 2               4608×2     = 9,216    2×4  = 8       9,224 B
Softmax               2 → 2                        0                  0              0
                                             ═══════════════════════════════    ══════════
                                             WEIGHTS + BIASES:                  10,616 B
                                             Architecture metadata:             ~2,656 B
                                             ════════════════════════════════════════════
                                             TOTAL IN tflite ARRAY:             13,272 B ✓
```

**Key insight**: The Dense layer alone (9,224 B) = 69% of the entire model. Depthwise separable conv layers are tiny because they share weights.

---

## PART 8: STANDARD vs DEPTHWISE SEPARABLE CONVOLUTIONS

### Standard Convolution

One filter looks at ALL input channels simultaneously. Filter is 3D: `kernel × kernel × all_input_channels`.

```
Cost per output position = kernel_w × kernel_h × input_channels
Total cost = cost_per_position × output_positions × output_channels

Example: 96×96, 3→8 channels, 3×3 kernel
  Per position: 3 × 3 × 3 = 27 multiplications
  Total: 27 × 9,216 × 8 = 1,990,656 multiplications
  Weights: 3 × 3 × 3 × 8 = 216
```

### Depthwise Separable (Two Cheap Steps)

**Step 1 — Depthwise**: Each channel gets its OWN 3×3 filter, processed INDEPENDENTLY.
- Output has SAME number of channels as input
- Cost: `kernel_w × kernel_h × input_channels × output_positions`
- 3×3×3×9,216 = 248,832 multiplications. Weights: 3×3×3 = 27

**Step 2 — Pointwise (1×1)**: Mix the channels with tiny 1×1 filters.
- At each pixel: take all depthwise outputs, multiply by weights, sum → one output per channel
- Cost: `input_channels × output_channels × output_positions`
- 3×8×9,216 = 221,184 multiplications. Weights: 1×1×3×8 = 24

**Combined**: 248,832 + 221,184 = **470,016** vs standard's **1,990,656** = **4.2× fewer operations**

### Why It's Cheaper — The Core Insight

Standard conv does the expensive 3×3 spatial work SEPARATELY for each output channel — nothing shared.

Depthwise separable does the 3×3 spatial work ONCE, then cheaply remixes the results into multiple output channels via 1×1 weighted sums. The depthwise result is SHARED by all output channels.

### General Ratio Formula

```
                    1           1
Savings ratio = ────────── + ──────
                output_ch     K²

For K=3, output_channels=32:  1/32 + 1/9 = 0.142 → uses only 14.2% of the compute = ~7× reduction
```

---

## PART 9: THE 13 KB TFLite FILE — ARCHITECTURE + WEIGHTS TOGETHER

The `tflite_learn_1000575_3[]` array is NOT just weights. It's a **TFLite FlatBuffer** containing:

```
┌─────────────────────────────┐
│ HEADER: "TFL3" + version    │  ← "I am a TFLite model file"
├─────────────────────────────┤
│ GRAPH: operator list        │  ← Architecture: "Layer 1 is Conv2D 3×3,
│   operator types            │     Layer 2 is MaxPool 2×2, Layer 3 is
│   input/output connections  │     DepthwiseConv2D 3×3, ..."
│   kernel sizes, strides     │
├─────────────────────────────┤
│ TENSORS: shape descriptions │  ← "Tensor 0 is [1,96,96,3] INT8,
│                             │     Tensor 1 is [1,96,96,8] INT8, ..."
├─────────────────────────────┤
│ BUFFERS: weight values      │  ← The actual learned numbers
│   filter weights (INT8)     │     (10,288 bytes of weights)
│   bias values (INT32)       │     (328 bytes of biases)
├─────────────────────────────┤
│ QUANTIZATION: scale/offset  │  ← Per-tensor: scale + zero_point
│   per tensor                │     for INT8 ↔ float conversion
└─────────────────────────────┘
Total: 13,272 bytes
```

The TFLite Micro interpreter reads this ONE array to learn:
- **What layers** to execute (architecture)
- **In what order** (graph connections)
- **With what numbers** (weights)
- **How to convert** INT8 ↔ float (quantization params)

---

## PART 10: INT8 QUANTIZATION

### What It Is

Original training uses 32-bit floats (4 bytes per weight). Quantization compresses each to 8-bit integers (1 byte).

```
FP32 weight: 0.3724859356880188    → 4 bytes
INT8 weight: 95                    → 1 byte    (4× smaller!)
```

### How It Converts

```
float_value = (int8_value - zero_point) × scale

Your model's output layer:
  zero_point = -128
  scale = 0.00390625

Example:
  human output   INT8 = 95  → (95 - (-128)) × 0.00390625 = 223 × 0.00390625 = 0.871
  nonhuman output INT8 = -95 → (-95 - (-128)) × 0.00390625 = 33 × 0.00390625 = 0.129
```

### Why It Matters for ESP32

- **4× smaller model**: 13 KB instead of ~52 KB
- **3-4× faster math**: ESP32 has no float hardware. INT8 multiply-add is done in integer ALU = much faster
- **ESP-NN exploits it**: Can process multiple INT8 values per instruction

---

## PART 11: ESP-NN ACCELERATION

### What Is ESP-NN

Espressif's optimized C functions that replace generic TFLite C implementations for convolution, pooling, etc.

### Status in Your Build

```
EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN = 1    (enabled, default in ei_classifier_config.h)
platformio.ini does NOT override it       → ESP-NN IS ACTIVE
```

### Which Operators Are Accelerated

Your model registers 5 operators (in tflite-resolver.h):

| Operator | ESP-NN Accelerated? | Implementation |
|:---|:---:|:---|
| Conv2D | ✅ | `esp_nn_conv_opt.c` (optimized C) |
| DepthwiseConv2D | ✅ | `esp_nn_depthwise_conv_opt.c` |
| FullyConnected | ✅ | `esp_nn_fully_connected_ansi.c` |
| MaxPool2D | ✅ | `esp_nn_max_pool_ansi.c` |
| Reshape | ❌ | No math needed, just memory reorder |
| Softmax | ❌ | Simple e^x / sum(e^x) |

### ESP32 vs ESP32-S3

Your board is a **regular ESP32** (not S3). The S3 has special SIMD assembly files (`_esp32s3.S`) that are even faster. Your board uses the `_opt.c` and `_ansi.c` versions — still faster than generic TFLite C, just not S3-level fast.

### Impact

Without ESP-NN: ~2.5 seconds per inference. With ESP-NN: **~800 ms per inference**.

---

## PART 12: AFTER CLASSIFICATION — THE DECISION

```c
float human = result.classification[0].value;      // e.g. 0.87
float nonhuman = result.classification[1].value;    // e.g. 0.13

bool detected = (human >= 0.60) && (human > nonhuman);
```

**Detection requires**: human score ≥ 60% AND human > nonhuman.

**Re-arming logic**: After detection, `image_sent_this_event = true`. The system won't trigger again until 20 consecutive non-human frames pass. This prevents rapid-fire false alerts.

---

## PART 13: INTRUSION RESPONSE CHAIN

When a human IS detected for the first time in an event:

```
Step 1:  g_mode = MODE_UPLOADING (pause AI)
Step 2:  Flash LED ON (GPIO 4 HIGH)
Step 3:  Wait 300ms (let sensor adjust exposure)
Step 4:  Flush one frame (overexposed — discard it)
Step 5:  Wait 80ms
Step 6:  Grab fresh frame (properly exposed under flash)
Step 7:  Flash LED OFF
Step 8:  fmt2jpg() — encode RGB565 frame to JPEG quality 85
Step 9:  HTTPS POST to Cloudinary (multipart/form-data, 1024-byte chunks)
         → Returns: secure_url + public_id
Step 10: HTTPS POST to Firebase RTDB /alerts.json
         → {timestamp, image_url, public_id, score, type: "Human Detected"}
Step 11: HTTPS POST to Cloud Function ingest endpoint (optional)
Step 12: MQTT publish to eagleeye/cam-01/alert
         → {ts, image_url, public_id, score, type}
Step 13: Free JPEG buffer
Step 14: g_mode = MODE_AI (resume detection)
```

---

## PART 14: MEMORY MANAGEMENT

### The Memory Budget

| Consumer | MODE_AI | MODE_UPLOADING | MODE_RELAY |
|:---|---:|---:|---:|
| FreeRTOS + WiFi + System | ~150 KB | ~150 KB | ~150 KB |
| MQTT TLS session (permanent) | ~40 KB | ~40 KB | ~40 KB |
| TFLite tensor arena | **~126 KB** | ❌ freed | ❌ freed |
| AI snapshot buffer | 27 KB | 27 KB | 27 KB |
| Upload TLS session | ❌ | **~40 KB** | ❌ |
| Relay WSS TLS session | ❌ | ❌ | **~40 KB** |
| JPEG temp buffer | ❌ | ~20-40 KB | ~5-15 KB |
| MQTT buffer | 1 KB | 1 KB | 1 KB |
| Servo task stack | 4 KB | 4 KB | 4 KB |
| Camera buffers (PSRAM) | 300 KB | 300 KB | 300 KB |

### Seven Memory Strategies

1. **PSRAM for camera**: `config.fb_location = CAMERA_FB_IN_PSRAM` — 300 KB stays out of internal SRAM
2. **One-shot TLS**: Upload functions create `WiFiClientSecure` on stack, `tls.stop()` immediately after → 40 KB freed
3. **Mutual exclusion**: Modes are exclusive — tensor arena (126 KB) freed when uploading/streaming
4. **Small MQTT buffer**: `client.setBufferSize(1024)` — images go to Cloudinary, not MQTT
5. **Chunked uploads**: JPEG sent in 1024-byte pieces, no giant String buffer
6. **Stack-allocated JSON**: `StaticJsonDocument<256>` on stack, auto-freed when function returns
7. **Tiny servo stack**: 4 KB — only reads 2 integers and writes PWM registers

---

## PART 15: DUAL-CORE CPU SCHEDULING

| Core | Task | Priority | What Runs | Frequency |
|:---:|:---|:---:|:---|:---:|
| **0** | `servoCtl` | 2 | `servos_service()` — LEDC PWM writes only | ~330 Hz |
| **0** | (system) | — | Wi-Fi driver, TCP/IP stack | System |
| **1** | `loopTask` | 1 | `loop()` — MQTT, camera, AI, uploads, relay | As fast as possible |

### Why Split?

AI inference blocks Core 1 for ~800 ms. Without the split, servos would freeze during every inference cycle. With Core 0 running the servo stepper independently at 330 Hz, servos stay smooth regardless of what Core 1 is doing.

### Thread Safety

Core 1 writes `panTgt`/`tiltTgt` (plain integers). Core 0 reads them. On ESP32, 32-bit integer read/write is naturally atomic — no mutex needed.

All WebSocket/network code stays on Core 1 only. Core 0 never touches network — only LEDC PWM hardware registers.

### Servo Motion

Smooth micro-stepping: 1° every 5ms = ~200°/sec slew rate. Non-blocking — never uses `delay()`.

---

## PART 16: FOUR COMMUNICATION PLANES

| Plane | Protocol | Port | Direction | Purpose |
|:---|:---|:---:|:---|:---|
| **1. MQTT** | MQTT over TLS | 8883 | Bidirectional | Commands, status, alerts |
| **2. Relay** | WSS (WebSocket Secure) | 443 | ESP→Relay→App | Live video streaming |
| **3. HTTPS** | HTTPS POST | 443 | ESP→Cloud | Image upload + alert write |
| **4. LAN** | WS (WebSocket) | 81 | App↔ESP (local) | Low-latency servo control (<50ms) |

### MQTT Topics

| Topic | Direction | Retained | Content |
|:---|:---:|:---:|:---|
| `eagleeye/cam-01/status` | Device→Cloud | ✅ | online, armed, rssi, ip, fw |
| `eagleeye/cam-01/cmd` | Cloud→Device | ❌ | arm, servo, stream, ota, factory_reset |
| `eagleeye/cam-01/alert` | Device→Cloud | ❌ | ts, image_url, public_id, score |
| `eagleeye/cam-01/stream` | Device→Cloud | ❌ | {"ready": true} |

### Streaming Details

- Frame rate cap: ~12 FPS (80ms interval)
- Camera stays in RGB565 (NOT hardware JPEG) — software-encoded via `frame2jpg()` quality 25
- Auto-stops after 5 minutes or when no viewers remain
- AI is paused during streaming

---

## PART 17: THE COMPLETE PIPELINE — ONE FLOW

```
POWER ON
   │
   ▼
SETUP: disable brownout → load NVS config → alloc 27KB snapshot buffer
       → init camera (RGB565 QVGA 320×240, 2 buffers in PSRAM)
       → init servos (GPIO14/15, timers 1-3, centered 90°)
       → connect WiFi → sync SNTP → connect MQTT (TLS 8883)
       → start LAN WebSocket server (port 81)
       → pin servo task to Core 0 (4KB stack, priority 2, 330Hz)
   │
   ▼
MAIN LOOP (Core 1, repeating):
   │
   ├── mqtt_service() — pump MQTT, non-blocking reconnect every 5s
   ├── lanctrl_service() — check for direct-LAN servo commands
   ├── publish_status() every 15 seconds
   ├── Process any pending commands (servo/stream/ota/factory_reset)
   │
   ├── IF MODE_RELAY → relay_loop() (grab frame → software JPEG → sendBIN via WSS)
   ├── IF MODE_UPLOADING → idle (upload is synchronous)
   ├── IF user panning (< 2.5s since last cmd) → delay(5), skip AI
   │
   └── IF MODE_AI + no panning → run_ai_step():
       │
       ├── esp_camera_fb_get() → 320×240 RGB565 frame in PSRAM (153 KB)
       │
       ├── resize_rgb565_to_rgb888():
       │     Center-crop 320→240 (cut 40px each side)
       │     Nearest-neighbor shrink 240→96
       │     Convert RGB565→RGB888
       │     → snapshot_buf: 96×96×3 = 27,648 bytes in internal SRAM
       │
       ├── Build signal (callback that packs RGB→0xRRGGBB float)
       │
       ├── run_classifier(&signal, &result):    ← ENTERS EDGE IMPULSE
       │     │
       │     ├── DSP: fetch pixels via callback → normalize to INT8
       │     │
       │     ├── TFLite Micro Interpreter:
       │     │     Allocate 126 KB tensor arena
       │     │     Read 13 KB model (architecture + weights) from flash
       │     │     Execute layers:
       │     │       Conv2D(8) + MaxPool → 48×48×8
       │     │       DepthwiseConv(8) + PointwiseConv(16) + MaxPool → 24×24×16
       │     │       DepthwiseConv(16) + PointwiseConv(32) + MaxPool → 12×12×32
       │     │       Flatten → 4608
       │     │       Dense(2) → 2 values
       │     │       Softmax → probabilities
       │     │     ESP-NN accelerates Conv2D, DepthwiseConv, FC, MaxPool
       │     │     ~800 ms total
       │     │
       │     └── Post-process: dequantize INT8→float
       │           float = (int8 + 128) × 0.00390625
       │           → [human: 0.87, nonhuman: 0.13]
       │
       ├── Decision: human ≥ 0.60 AND human > nonhuman?
       │
       ├── IF YES and first time in event:
       │     MODE_UPLOADING:
       │       Flash LED ON → flush frame → wait 80ms → grab frame → LED OFF
       │       → fmt2jpg (RGB565→JPEG quality 85)
       │       → HTTPS POST to Cloudinary (1024-byte chunks) → get secure_url
       │       → HTTPS POST to Firebase RTDB /alerts.json
       │       → HTTPS POST to Cloud Function (optional)
       │       → MQTT publish alert {ts, image_url, score}
       │       → free JPEG → MODE_AI
       │
       └── IF NO for 20 consecutive frames → re-arm (allow next detection)


MEANWHILE ON CORE 0 (independent, never stops):
   └── servo_core0_task: every 3ms
         Read panTgt/tiltTgt (set by MQTT or LAN commands on Core 1)
         Step panCur toward panTgt by 1° (if different)
         Step tiltCur toward tiltTgt by 1° (if different)
         Write LEDC PWM registers
         → Servos move smoothly at ~200°/sec regardless of Core 1 load
```

---

## QUICK REFERENCE: KEY NUMBERS

| Metric | Value |
|:---|:---|
| CPU cores used | **2 of 2** |
| Model file size (flash) | **13,272 bytes (13 KB)** |
| Model = architecture + weights | **Yes, both in one TFLite FlatBuffer** |
| Model weights only | **10,616 bytes** |
| Dense layer alone | **9,224 bytes (69% of model)** |
| Tensor arena (RAM) | **126,361 bytes (123 KB)** |
| Input resolution | **96 × 96 × 3 RGB** |
| Quantization | **INT8** (4× smaller than FP32) |
| ESP-NN | **Enabled** (optimized C, not S3 assembly) |
| Inference time | **~800 ms** |
| Detection threshold | **60%** confidence |
| Clear-scene hysteresis | **20 frames** |
| Camera capture | **320 × 240 RGB565** |
| Camera frame size | **153,600 bytes (in PSRAM)** |
| Snapshot buffer | **27,648 bytes (in internal SRAM)** |
| Stream frame rate | **~12 FPS** (80ms cap) |
| Stream max duration | **5 minutes** |
| Servo step rate | **1° / 5ms = 200°/sec** |
| Servo task frequency | **~330 Hz on Core 0** |
| TLS session RAM | **~40 KB each** |
| MQTT buffer | **1 KB** (images via Cloudinary, not MQTT) |
| Wi-Fi TX power | **8.5 dBm** (reduced for brownout) |
| MQTT reconnect | **Every 5 seconds** |
| Status publish | **Every 15 seconds** |
