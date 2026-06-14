# EagleEye — Cloud (remote) firmware

The **remote/product** build: *camera at a site, phone anywhere*. The device connects **outbound** to the cloud and stays connected, so its IP never matters. This folder is **independent of `firmware/eagleeye-main/`** (the LAN build is untouched — keep using it for local testing).

> Implements the approved plan `distributed-roaming-candy.md`:
> **Plane 1** control + alerts over cloud MQTT/TLS, **Plane 2** on-demand live video via a cloud relay, plus Phase-4 provisioning / OTA / TLS hardening.

## Files
| File | Role |
|---|---|
| `eagleeye-cloud.ino` | Main: AI loop, `DeviceMode` dispatch, command handling, setup. |
| `config.h` | **All settings** (fill the `DEV_*` defaults) + NVS load/save + topic helpers + feature flags. |
| `eagleeye_camera.h` | Camera pins, `MODE_AI` (RGB565) vs `MODE_RELAY` (hardware JPEG), safe mode switch, `eagleeye_grab_jpeg`. |
| `EagleEye_Cloud_IoT.h` | MQTT-over-TLS: status (retained + LWT), `cmd` parsing, alert publish, SNTP, non-blocking reconnect, `capture_and_send_image`. |
| `eagleeye_upload.h` | Direct HTTPS upload to Cloudinary (unsigned preset) + `ingest_alert` to a Cloud Function. |
| `eagleeye_relay.h` | Outbound `wss` relay client (Plane 2), on-demand, idle/max-session caps. |
| `eagleeye_ota.h` | MQTT-triggered HTTPS OTA (Phase 4). |
| `eagleeye_provision.h` | Wi-Fi captive-portal setup (Phase 4, off by default). |

## Required Arduino libraries
- **PubSubClient** (knolleary) — MQTT
- **ArduinoJson** (v6) — JSON
- **WebSockets** (Markus Sattler / Links2004) — relay client
- **final_inferencing** — your EI v7.16 RGB 96×96 library (same one `eagleeye-main` uses)
- **WiFiManager** (tzapu) — *only if* you set `ENABLE_PROVISIONING 1`
- Board: **AI Thinker ESP32-CAM**, PSRAM enabled. For OTA pick an **OTA-capable Partition Scheme** (Tools → Partition Scheme).

## Before you flash — fill in `config.h`
Edit the `DEV_*` defaults: Wi-Fi, HiveMQ host/user/pass, Cloudinary cloud name + **unsigned upload preset**, (later) the Cloud Function URLs and relay host. These are compile-time defaults; the Phase-4 portal can override them at runtime into NVS.

## What you set up in the cloud (your accounts)
1. **HiveMQ Cloud** (free): create a cluster; add two credentials with topic permissions:
   - device `dev-cam-01`: publish `eagleeye/cam-01/{status,alert,stream}`, subscribe `eagleeye/cam-01/cmd`.
   - app `app-user`: publish `eagleeye/cam-01/cmd`, subscribe the rest.
2. **Cloudinary**: create an **unsigned upload preset** (force `folder=eagleeye_intrusions`, `resource_type=image`, max size). Do **not** put the API secret on the device.
3. **Firebase Cloud Functions** (Phase 2/3): `ingestAlert` (writes RTDB `alerts/` so the app's existing list shows it), `onDeletionRequest` (Cloudinary destroy — replaces `bridge.py`), `issueStreamToken` (short-lived relay tokens). *(App-side and these functions are separate deliverables; the firmware already calls them when the URLs are set.)*
4. **Relay** (Phase 3): a tiny Node `ws` server on Fly.io/Railway (`wss://`).

## Topics & command format
```
eagleeye/<id>/status   retained + LWT   {"online":true,"armed":true,"fw":"...","rssi":-62}
eagleeye/<id>/cmd      subscribe        {"type":"arm","value":true} | {"type":"servo","angle":90}
                                        | {"type":"stream","value":true} | {"type":"ota","url":"https://.../fw.bin"}
                                        | {"type":"factory_reset"}
eagleeye/<id>/alert    publish          {"ts":...,"image_url":...,"public_id":...,"score":...,"type":"Human Detected"}
eagleeye/<id>/stream   publish          {"ready":true}   (tells the app to attach to the relay)
```

## TLS memory (why it's structured this way)
The ESP32-S1 can't hold 3 TLS sessions at once. A single `DeviceMode { MODE_AI, MODE_UPLOADING, MODE_RELAY }` (in `eagleeye_camera.h`) guarantees **at most one of {HTTPS upload, WSS relay} is open at a time**; persistent **MQTTS** stays small because the old 50 KB image buffer is gone (`setBufferSize(1024)`). HTTPS clients are scope-local and freed immediately after each upload.

## Phase status (in this firmware)
- **P1 control/status** — ✅ implemented (MQTTS, LWT, retained status, cmd→servo/arm/stream).
- **P2 upload+alert** — ✅ implemented (Cloudinary unsigned upload; `ingest_alert` no-ops until you set `DEV_INGEST_URL`).
- **P3 relay video** — ✅ implemented (hardware-JPEG switch + `wss` client; needs the relay host + `issueStreamToken`).
- **P4 provisioning/OTA/security** — ✅ scaffolded: OTA on by default; provisioning behind `ENABLE_PROVISIONING`; TLS uses `setInsecure()` for dev — set `TLS_INSECURE 0` and pin CA certs (see `EagleEye_Cloud_IoT.h`) for production.

## Bring-up order (recommended)
1. Fill Wi-Fi + HiveMQ creds → flash → watch serial: WiFi, SNTP, `[MQTT] ok`, retained `status` in the HiveMQ web client; kill power → `online:false` via LWT.
2. From the HiveMQ web client publish to `eagleeye/cam-01/cmd`: `{"type":"servo","angle":120}` (servo moves), `{"type":"arm","value":false}`.
3. Add the Cloudinary preset → trigger a detection → image appears in `eagleeye_intrusions`; deploy `ingestAlert` so it lands in RTDB and the app shows it; then retire Mosquitto + `bridge.py`.
4. Deploy the relay + `issueStreamToken`, set `DEV_RELAY_HOST`/`DEV_TOKEN_URL` → `{"type":"stream","value":true}` → frames flow; `false` stops.
5. Production: rotate the leaked Cloudinary/Firebase creds, set `TLS_INSECURE 0` + pin CAs, enable provisioning.

## Security note
The Cloudinary API secret in `backend/bridge.py`/`.env` and the committed Firebase `serviceAccountKey.json` are **burned** — rotate them and purge from git history before shipping. This firmware deliberately holds **no** Cloudinary secret (unsigned preset) and only its own scoped MQTT credentials.
