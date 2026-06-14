# EagleEye — Remote-Access Product Plan

**Goal:** turn the current local-only prototype into a product where the **camera is at site A and the phone is anywhere** (different network, mobile data, etc.).
**Author:** architecture plan, June 2026.
**Status:** decision/budgeting document — no code committed against it yet.

---

## 1. Constraints that drive every decision

1. **Phone and camera are on different networks.** The app can never reach the camera by LAN IP.
2. **No port-forwarding.** Most home/mobile ISPs use CGNAT (port-forward impossible), and exposing the camera to the internet is a security hole even when it's possible.
3. **Therefore: the device must always connect *outbound*** to a cloud endpoint and stay connected. All commands, telemetry, alerts, and video signaling ride that outbound link. This is the single most important rule.
4. **Hardware reality:** ESP32-CAM (AI-Thinker) is **2.4 GHz Wi-Fi only**, modest CPU, no hardware video codec beyond the OV2640's JPEG. Realistic remote video is **QVGA–VGA, ~5–15 fps JPEG, on-demand** — not HD 24/7.
5. **No PC at the site.** A product can't assume a Windows PC is powered on running Mosquitto + `bridge.py`.

---

## 2. Current state — what survives remote, what breaks

| Capability | Today | Works remotely? | Action |
|---|---|---|---|
| Intruder alerts | ESP → local Mosquitto → `bridge.py` → Cloudinary + Firebase; app reads Firebase | ⚠️ Only while the **site PC** is on | Move upload to device-direct + FCM; drop the PC |
| Live video | App → camera LAN IP (HTTP MJPEG / WS JPEG) | ❌ LAN-only | Cloud relay or WebRTC |
| Servo / pan control | App → camera LAN IP (`GET /servo`) | ❌ LAN-only | Move to cloud MQTT command topic |
| Arm / disarm | App → Firebase `config/armed`; bridge gates | ✅ (cloud) | Keep; optionally move to MQTT for realtime |
| Wi-Fi credentials | Hardcoded in `secrets.h` | ❌ Not shippable | Add provisioning |
| Broker | Mosquitto on PC, anonymous, no TLS | ❌ Not shippable | Managed cloud broker, TLS, per-device creds |

**Takeaway:** alerts are *almost* there (just tied to the PC); **live video and control are the real remote gaps**, and the PC dependency + hardcoded creds + open broker are the "not a product yet" items.

---

## 3. Target architecture

```
   SITE A                                CLOUD                              ANYWHERE
 ┌──────────────┐    outbound TLS     ┌────────────────┐    wss / HTTPS    ┌───────────┐
 │ ESP32 main   │────────────────────►│  MQTT broker   │◄──────────────────│  Phone    │
 │  + helper    │  pub alert/status   │  (managed)     │   pub cmd,         │  (app)    │
 │              │  sub  cmd           │                │   sub alert/status └───────────┘
 │   image  ────┼──HTTPS POST──► Cloudinary / Firebase Storage
 │   metadata ──┼──HTTPS/SDK──► Firestore/RTDB ──► Cloud Function ──► FCM push ──► phone
 │   video  ────┼──outbound WS / WebRTC──► media relay ──► phone   (ON DEMAND only)
 └──────────────┘
```

Two planes with very different requirements:

- **Control + alerts plane** — low bandwidth, must be reliable, always-connected. → **MQTT over TLS** + **cloud storage** + **FCM**.
- **Video plane** — high bandwidth, bursty, latency-sensitive, on-demand. → **WebSocket relay** (start) → **WebRTC/TURN** (upgrade).

---

## 4. Component choices

### 4.1 MQTT broker (control plane backbone)
| Option | Pros | Cons | Cost (entry) |
|---|---|---|---|
| **HiveMQ Cloud** ⭐ | MQTT-native, free serverless tier, TLS, MQTT-over-WebSocket for the app, trivial setup | Vendor-managed | Free up to ~100 connections / limited data |
| **EMQX Cloud / self-hosted EMQX** | Powerful, rules engine, can self-host on VPS | Self-host = ops | Free tier / ~$5 VPS |
| **AWS IoT Core** | Most "industrial": per-device X.509, device shadows, fleet provisioning, rules → Lambda/S3 | Steeper learning curve | Pay-per-message, cheap at low volume |
| **Azure IoT Hub** | Device twins, DPS provisioning | Heavier | Free tier 8k msg/day |

**Recommendation:** start with **HiveMQ Cloud** (fastest to a working product); graduate to **AWS IoT Core** if you need fleet-scale provisioning and device shadows later.

### 4.2 Image storage + alert delivery
- **Cloudinary** (already integrated) or **Firebase Storage** for the JPEG.
- **Firestore / Realtime DB** (already integrated) for alert metadata + history.
- **FCM (Firebase Cloud Messaging)** for push notifications so the phone is alerted **even with the app closed** — mandatory for a surveillance product.
- A **Cloud Function** (Firebase Functions) triggered on a new alert document → sends the FCM push. This also removes server logic from the device/PC.

### 4.3 Video relay
| Option | Latency | Effort | Infra | When |
|---|---|---|---|---|
| **Cloud WebSocket relay** ⭐ start | ~0.3–1 s | Low (reuses current JPEG-over-WS) | $5 VPS / Render / Railway / Fly.io | First remote-video step |
| **WebRTC + TURN** (LiveKit / Janus / coturn) | ~0.1–0.3 s | High (DTLS-SRTP on ESP32) | TURN server (coturn or metered) | Latency-critical upgrade |
| **Media server ingest** (MediaMTX) | medium | Medium | one host | Many simultaneous viewers |

**Recommendation:** **WebSocket relay first** (camera and phone both dial *out* to the relay → no NAT problem), upgrade to WebRTC only if latency demands it.

### 4.4 Provisioning
- **ESP-IDF `wifi_provisioning`** (SoftAP or BLE) or **Improv-Wi-Fi**: user sets Wi-Fi creds + claims the device from the app. Removes `secrets.h` hardcoding.

---

## 5. Detailed design — control + alerts plane

### Topics (HiveMQ, TLS 8883 device / wss app)
```
eagleeye/<deviceId>/status      device → cloud   (online, rssi, fw, armed, battery)   retained
eagleeye/<deviceId>/alert       device → cloud   (event id, ts, image URL, score)
eagleeye/<deviceId>/cmd         cloud  → device  (servo angle, arm/disarm, stream on/off)
eagleeye/<deviceId>/cmd/ack     device → cloud   (command result)
```
- Device uses **MQTT LWT (last will)** → `status: offline` on disconnect, so the app shows a true online/offline badge.
- App publishes commands; device subscribes — **servo and arm/disarm now work from anywhere**, no IP.

### Alert flow (no site PC)
1. AI confirms human → device captures JPEG.
2. Device **HTTPS-POSTs the JPEG** directly to Cloudinary (unsigned upload preset) or Firebase Storage.
3. Device writes metadata (URL, timestamp, score) to Firestore via REST, **and/or** publishes `alert` over MQTT.
4. A **Cloud Function** on the new alert → **FCM push** to the user's phone.
5. App shows the alert + image from cloud — works anywhere, app open or closed.

**Result:** `bridge.py` and the site PC are no longer required for normal operation.

---

## 6. Detailed design — video plane

### On-demand streaming (bandwidth + cost discipline)
- App opens Live screen → publishes `cmd: {stream: on}` over MQTT.
- Device opens an **outbound WebSocket to the relay** and starts pushing frames.
- Relay fans frames out to the app's WebSocket.
- App closes screen → `cmd: {stream: off}` → device closes the socket. **Never stream 24/7.**

### Make the frames cheap
- Switch the **stream path to hardware JPEG** (`PIXFORMAT_JPEG` from the OV2640) instead of RGB565 + software `frame2jpg` — large CPU and bandwidth win. Keep the RGB565 center-crop only for the AI frame.
- **Adaptive quality / FPS:** drop resolution and frame rate when the uplink is weak; raise on a strong link.
- Target **QVGA–VGA, 5–15 fps**. Be explicit in the UI that this is a surveillance stream, not HD video.

### Upgrade path
- If latency matters, move to **WebRTC** with signaling over the existing MQTT broker and a **TURN** server (coturn self-hosted, or a metered TURN provider) for NAT traversal.

---

## 7. Security (mandatory once it leaves the LAN)
- **TLS everywhere:** `mqtts://` (8883) for device, `wss://` for app, HTTPS for uploads.
- **Per-device credentials** (HiveMQ user/pass per device, or **X.509 client certs** on AWS IoT). No anonymous broker.
- **Least-privilege topics:** a device may only publish/subscribe its own `eagleeye/<deviceId>/#`.
- **Signed OTA updates** (see §8). 
- **Remove the brownout-detector band-aid** and fix the 5 V supply (it currently masks resets).
- Rotate any API keys that were ever committed/pasted.

---

## 8. OTA updates
- ESP32 **HTTPS OTA** pulling a signed firmware image from cloud storage, triggered by an MQTT `cmd: {ota: <url>}`.
- Staged rollout + version reported in `status`. Essential for fixing a fleet you can't physically touch.

---

## 9. Power & hardware
- Regulated **5 V / ≥2 A** supply + **470–1000 µF** bulk cap near the ESP32-CAM; servo on its own 5 V rail with common ground.
- For sites without Wi-Fi: a **4G/LTE router** (the cloud-outbound design is location-independent), or a cellular module.
- Long-term: if HD 24/7 remote video is a hard requirement, plan a stronger camera SoC (Linux/RTSP cam); ESP32-CAM is great for AI-trigger + on-demand preview, not continuous HD.

---

## 10. Bandwidth budget (ESP32-CAM, 2.4 GHz)
| Mode | Resolution | FPS | ~Bitrate | Notes |
|---|---|---|---|---|
| Alert image | VGA/SVGA JPEG | — | one-shot ~30–80 KB | fine on any link |
| Live preview (relay) | QVGA JPEG q25 | 10 | ~0.5–1.5 Mbps | comfortable |
| Live preview (relay) | VGA JPEG q25 | 10 | ~1.5–4 Mbps | needs a good uplink |
- Real ESP32-CAM uplink is a few Mbps best-case; design around QVGA default with VGA as a "good link" option.

---

## 11. Migration map (what changes in the existing code)
- **Firmware (`eagleeye-main`):**
  - Add MQTT-over-TLS client to the cloud broker; publish `status/alert`, subscribe `cmd` (servo angle → forward to helper UART; arm/disarm; stream on/off).
  - Add **direct HTTPS image upload**; add **hardware-JPEG stream path**; add **outbound WS to the relay**, on-demand.
  - Add **provisioning** + **HTTPS OTA**; remove hardcoded `secrets.h`, remove brownout band-aid after power fix.
- **Helper (`helper_servo`):** unchanged — still receives `ANGLE:N` over UART from main.
- **`bridge.py`:** becomes optional/retired; its Cloudinary+Firebase logic moves to device-direct upload + a Cloud Function.
- **Mobile app:**
  - Add an **MQTT-over-WebSocket** client (`wss://` HiveMQ) for status + commands (servo, arm/disarm) — **delete the manual-IP field** for control.
  - Live view connects to the **relay** (by deviceId), not a camera IP.
  - Add **FCM** push registration + handling.
- **New cloud pieces:** managed MQTT broker, video relay host, Firebase Cloud Function for FCM.

---

## 12. Phased roadmap & effort (rough)
| Phase | Deliverable | Effort | Unblocks |
|---|---|---|---|
| **P1** Cloud MQTT backbone | Servo + arm/disarm + status over TLS broker, app uses deviceId not IP | ~3–5 d | Remote control; video signaling |
| **P2** Alerts anywhere | Device-direct upload + Cloud Function + FCM push; retire site PC | ~3–5 d | Real surveillance alerts |
| **P3** Remote live video | WS relay + on-demand + hardware JPEG | ~5–8 d | Remote live view |
| **P4** Productization | Provisioning, per-device security, OTA, power | ~1–2 wk | Shippable units |
| **P5** (optional) | WebRTC/TURN, fleet provisioning (AWS IoT), HD camera | as needed | Scale / latency |

---

## 13. Cost summary (low-volume / pilot)
| Item | Service | Entry cost |
|---|---|---|
| MQTT broker | HiveMQ Cloud free tier | $0 |
| Image storage | Cloudinary / Firebase (existing) | $0–low |
| Alert metadata + Functions + FCM | Firebase Spark/Blaze | $0–low (Blaze pay-as-you-go for Functions) |
| Video relay host | $5 VPS / Render / Railway / Fly.io | ~$0–5/mo |
| TURN (only if WebRTC) | coturn on VPS / metered.ca | ~$5/mo+ |
| **Total pilot** | | **~$0–10 / month** |
Scales with traffic; the video relay/TURN egress is the main variable cost.

---

## 14. Risks & mitigations
- **ESP32-CAM video is bandwidth/CPU limited** → QVGA default, hardware JPEG, on-demand, adaptive quality; set product expectations.
- **Relay egress cost if always-on** → on-demand streaming, idle timeout.
- **Security misconfig** → per-device creds, topic ACLs, TLS, no anonymous; rotate leaked keys.
- **Field debuggability** → status topic + LWT + OTA so you can diagnose/fix remotely.
- **Vendor lock-in** → MQTT is portable; keep broker config abstracted so HiveMQ → AWS IoT is a credential/endpoint swap.

---

## 15. Recommended starting point
**Phase 1 (Cloud MQTT backbone)** — it's the spine everything else hangs off (commands now, video signaling later) and immediately delivers *remote servo + arm/disarm + true online/offline status* with no IP typing. Your only setup task is creating a free HiveMQ Cloud account and a device credential; then the firmware + app + (retired) bridge changes follow.
