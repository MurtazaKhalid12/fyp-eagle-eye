# EagleEye: Intelligent Edge AI Surveillance System

[![Status](https://img.shields.io/badge/Status-Active-success)](https://github.com/muhammadAB123/fyp-eagle-eye)
[![Platform](https://img.shields.io/badge/Platform-ESP32--CAM-blue)](https://espressif.com)
[![AI](https://img.shields.io/badge/AI-TinyML%20v7.16%20RGB%2096x96-orange)](https://www.tensorflow.org/lite/microcontrollers)
[![MQTT](https://img.shields.io/badge/MQTT-HiveMQ%20Cloud%20TLS-teal)](https://www.hivemq.com/mqtt-cloud-broker/)
[![Storage](https://img.shields.io/badge/Storage-Cloudinary-blue)](https://cloudinary.com)
[![Database](https://img.shields.io/badge/Database-Firebase-yellow)](https://firebase.google.com)

**EagleEye** is a decentralized, privacy-focused surveillance system that processes video **on the edge**. Using the ESP32-CAM and TinyML, it detects intruders locally and only transmits evidence to the cloud when a threat is confirmed. Live video streaming works across any network without port forwarding.

---

## System Architecture

```
ESP32-CAM (Edge)
    |-- Human detected? No  --> deep sleep / continue
    |-- Human detected? Yes --> capture high-res JPEG
    |       |-- upload directly to  Cloudinary (unsigned preset)
    |       |-- write alert record  Firebase Realtime DB (REST)
    |       \-- publish MQTT event  HiveMQ Cloud (TLS 8883)
    |
    \-- Live view requested --> WebSocket frames --> Deno Relay --> Mobile App

Mobile App (React Native / Expo)
    |-- Firebase listener  --> real-time alert feed + image URLs
    |-- HiveMQ WebSocket   --> MQTT (arm / disarm / status)
    \-- Deno Relay WSS     --> live JPEG stream from camera

Python Bridge (backend/bridge.py)  [optional / local mode]
    \-- subscribes to local Mosquitto → uploads to Cloudinary + Firebase
```

### Layer overview

| Layer | Component | Role |
|---|---|---|
| **Edge** | ESP32-CAM (AI-Thinker) | On-device inference, JPEG capture, MQTT client |
| **ML Model** | v7.16 RGB 96×96 INT8 | Human detection — 90.83% accuracy, ~872 ms inference |
| **MQTT Broker** | HiveMQ Cloud (TLS 8883) | Cloud MQTT — no open ports, works anywhere |
| **Image Storage** | Cloudinary | Unsigned-preset direct upload from ESP32 |
| **Database** | Firebase Realtime DB | Alerts, timestamps, arm/disarm state (REST from ESP32) |
| **Live Video** | Deno Deploy relay | WebSocket room — camera pushes, phone receives |
| **Mobile App** | React Native + Expo | Dashboard, alerts gallery, live stream, arm/disarm |
| **Backend Bridge** | Python (paho-mqtt) | Optional local-mode: Mosquitto → Cloudinary + Firebase |

---

## Project Structure

> **Active firmware:** `firmware/eagleeye-cloud-v2/`
> PlatformIO build — ESP32-CAM connects to **HiveMQ Cloud** (TLS 8883), streams live video through the **Deno relay**, uploads intrusion images to **Cloudinary**, and writes alerts to **Firebase** via REST.
> Flash with: `cd firmware/eagleeye-cloud-v2 && pio run --target upload`

```
fyp-eagle-eye/
|
|-- firmware/                          ESP32-CAM firmware
|   |-- eagleeye-cloud-v2/            *** ACTIVE FIRMWARE (flash this one) ***
|   |                                 PlatformIO — HiveMQ TLS, Deno relay, cloud upload
|   |   |-- src/
|   |   |   |-- eagleeye-cloud.ino    Main sketch (setup + loop)
|   |   |   |-- config.h             All credentials + feature flags (fill before flash)
|   |   |   |-- config.example.h     Blank template to copy
|   |   |   |-- EagleEye_Cloud_IoT.h MQTT + TLS connection manager
|   |   |   |-- eagleeye_camera.h    OV2640 capture + AI inference pipeline
|   |   |   |-- eagleeye_oled.cpp    SSD1306 status display
|   |   |   |-- eagleeye_servos.h    Pan/tilt servo control
|   |   |   |-- eagleeye_ota.h       MQTT-triggered HTTPS OTA update
|   |   |   |-- eagleeye_provision.h Wi-Fi captive-portal setup (optional)
|   |   |   \-- eagleeye_lanctrl.h   LAN direct control
|   |   |-- lib/                     Vendored libraries (PubSubClient, ArduinoJson, WebSockets, etc.)
|   |   \-- platformio.ini           Build config: esp32cam, 240 MHz, huge_app partition
|   |
|   |-- eagleeye-main/               Legacy Arduino IDE build (PIR + deep sleep + greyscale model)
|   |-- eagleeye-cloud/              Legacy: initial cloud integration (Arduino IDE)
|   |-- eagleeye-cloud-v3/           WIP next iteration
|   |-- eagleeye-cloud-standalone/   Standalone backup build
|   |-- eagleeye-cloud-pio/          Self-contained PlatformIO port
|   |-- tests/                       PIR sensor + UART test sketches
|   |-- helper_servo/                Servo calibration sketch
|   |-- pir-test-pio/                PIR sensor PlatformIO test
|   |-- tools/                       hard_negative_capturer, ai_assisted_capturer
|   |-- current model/               Snapshot of active Edge Impulse library (.zip)
|   \-- backup/                      Deprecated firmware variants
|
|-- relay/                            WebSocket live-video relay
|   |-- deno_relay.ts                [ACTIVE] Deno Deploy version (free, no card required)
|   |-- server.js                    Node.js fallback (Railway / Fly.io)
|   |-- package.json
|   \-- README.md                    Deploy instructions + test procedure
|
|-- backend/                          Python cloud bridge (local / fallback mode)
|   |-- bridge.py                    MQTT -> Cloudinary + Firebase bridge
|   |-- bridge_modfy.py              Modified variant
|   |-- mosquitto.conf               Local Mosquitto broker (port 1883 + WS 9001)
|   |-- .env                         Cloudinary + Firebase credentials
|   \-- captures/                    Locally saved intrusion JPEGs
|
|-- mobile-app/                       React Native / Expo app
|   \-- src/
|       |-- screens/                 DashboardScreen, LiveMonitorScreen, GalleryScreen
|       |-- services/                mqttClient.js (HiveMQ WSS), lanControl.js
|       \-- config/                  cloudConfig.example.js
|
|-- models/                           Canonical .tflite archives
|   |-- EAGLEEYE_MODEL_CATALOG.md    Version history + benchmarks
|   |-- model_v1.0_baseline.tflite
|   |-- model_v6.0_edge_impulse_final.tflite
|   |-- model_v6.1_edge_impulse_grayscale.tflite
|   \-- tflite_to_cpp_header.py      Convert .tflite -> C header
|
|-- model-training/                   TensorFlow/Keras training scripts
|   |-- train_rgb.py                 96x96 RGB model training
|   |-- train_grayscale.py           96x96 grayscale with black-frame negatives
|   \-- exported-models/             Output .tflite files
|
|-- third_party/                      Vendored Edge Impulse Arduino libraries
|   \-- ei_arduino_library_rgb96_depthwise_espnn/   [CURRENT v7.16, ESP-NN enabled]
|
|-- tools/                            Dataset + Edge Impulse utilities
|   |-- edge_impulse/                Upload / train / download scripts
|   \-- hard_negative_capturer/
|
|-- datasets/                         Training image datasets
|-- docs/                             Research papers, presentations, daily changelog
|-- scratch/                          Experimental working files
|-- reports/                          FYP reports
|-- _archive/                         Obsolete experiments
|-- README.md
\-- PROJECT_MANUAL_START.md           Full setup guide for new users
```

---

## Model Performance (v7.16 — deployed)

| Metric | Value |
|---|---|
| Architecture | Custom depthwise CNN (Conv2D 8→16→32) |
| Input | 96×96 RGB, INT8 quantized |
| Test accuracy | **90.83%** |
| Human recall | 87.5% |
| Non-human recall | 92.6% |
| Inference time | **~872 ms** @ 240 MHz |
| Training dataset | 929 human / 920 non-human (balanced) |

---

## Quick Start

See [PROJECT_MANUAL_START.md](PROJECT_MANUAL_START.md) for the complete new-user setup guide, including account creation on HiveMQ Cloud, Cloudinary, Firebase, and Deno Deploy.

### Hardware needed
- AI-Thinker ESP32-CAM
- FTDI USB-to-TTL adapter (for flashing)
- 5 V / 2 A power supply

### Firmware (active build)
```
firmware/eagleeye-cloud-v2/   (PlatformIO)
```
1. Copy `src/config.example.h` → `src/config.h`
2. Fill in your credentials (HiveMQ host/user/pass, Cloudinary cloud name, Firebase DB host, Deno relay host)
3. Flash with PlatformIO: `pio run --target upload`

### Backend bridge (local / optional)
```bash
cd backend
pip install paho-mqtt firebase-admin cloudinary python-dotenv
# edit .env with your Cloudinary + Firebase credentials
mosquitto -c mosquitto.conf -v        # terminal 1
python bridge.py                      # terminal 2
```

### Mobile app
```bash
cd mobile-app
npm install
npx expo start
```

---

## Tech Stack

| Area | Technology |
|---|---|
| Edge AI | TensorFlow Lite Micro (custom INT8 CNN via Edge Impulse) |
| Cloud MQTT | HiveMQ Cloud (TLS 8883 / WSS 8884) |
| Image storage | Cloudinary (unsigned upload preset) |
| Database | Firebase Realtime Database (REST) |
| Live video | Deno Deploy / Node.js WebSocket relay |
| Mobile | React Native + Expo |
| Firmware build | PlatformIO (espressif32 @ 6.5.0, arduino-esp32 2.0.14) |
| Hardware | ESP32-CAM (AI-Thinker, OV2640) |

---

## License

Developed as part of a Final Year Project (FYP) at ITU. See [LICENSE](LICENSE) for details.
