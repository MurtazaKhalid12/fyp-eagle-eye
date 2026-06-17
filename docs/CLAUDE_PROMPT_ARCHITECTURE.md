# Paste-into-Claude prompt — EagleEye System Architecture slides (old + latest)

> **How to use:** copy **everything below the line** into Claude (claude.ai). If you're already in the
> chat that's building the EagleEye deck, you can instead say *"Replace the System Architecture slide
> with the two slides specified below"* and paste it. Claude will render two visually-matched
> architecture slides with proper diagrams. Reply **"continue"** if it stops partway.

---

You are an **award-winning information designer**. Produce **two slides** for my EagleEye FYP final-defence deck that tell the **system-architecture evolution story**: **(1) the original local-only prototype**, and **(2) the latest cloud, outbound-only architecture built on HiveMQ + a video relay**. Keep them in the same visual language as the rest of the deck.

## Format & style
- Two slides, **16:9**, same brand as my deck. If you're generating standalone, output a **self-contained HTML** file (reveal.js OK) I can open and print to PDF.
- **Render the diagrams as clean, flat, professional diagrams** — labelled boxes + directional arrows (inline SVG or styled HTML divs). **Do NOT paste literal ASCII art**; the ASCII below is only a layout reference for you.
- Add **speaker notes** to each slide.
- Don't invent components or change any label — use exactly what's given.

## Brand system
- Deep blue `#1F4E79` (boxes, headers), teal `#2196F3` (the one accent — use for the "device dials out" arrows and the ★ highlights), ink `#1A1A1A`, slate `#555555`, panels `#F4F6F8`, rules `#D0D5DB`, alert red `#E53935`, positive green `#2E7D32`. Fonts: Montserrat (headings) + Inter (body).
- Three vertical **zones** in each diagram with light dividers and zone labels at the top.
- Put a **🔒 lock glyph on every encrypted link** in the new architecture. Show **❌ red markers** on the broken/limited links in the old one.

---

# SLIDE A — System Architecture v1 (Local Prototype)

**Title:** System Architecture — v1: Local Prototype (LAN-only)
**Subtitle / one-liner:** *Everything had to be on the same Wi-Fi, with a PC left running on site.*

**Diagram (render as a flat 3-zone diagram; ASCII is layout-only):**
```
   ── SAME Wi-Fi / LAN (one network for everything) ──
 ┌───────────────┐   Wi-Fi/LAN   ┌──────────────────────────────┐        ┌──────────────┐
 │  ESP32-CAM    │── MQTT pub ──►│   SITE PC  (must stay ON)     │        │  Phone app   │
 │  on-device AI │   alert/img   │  Mosquitto broker (no TLS)    │        │ (same LAN)   │
 │               │               │      +  bridge.py gateway     │        └──────┬───────┘
 │               │               │            │ HTTPS upload     │  reads        │
 │               │               │            ▼                  │  Firebase     │
 │               │               │   Cloudinary (images)         │◄──────────────┘
 │               │               │   Firebase  (alert metadata)  │
 └──────┬────────┘               └──────────────────────────────┘
        │  ❌ Live video: app → camera LAN IP (HTTP MJPEG / WS JPEG)
        └─ ❌ Servo/pan: app → camera LAN IP (GET /servo)      ← LAN-only, type the IP
```

**Bullets:**
- **Flow:** ESP32-CAM → local **Mosquitto** broker on a site **PC** → **`bridge.py`** uploads the JPEG to **Cloudinary** + writes alert metadata to **Firebase** → app reads Firebase.
- **Live video & servo control:** app talks **directly to the camera's LAN IP** (MJPEG / `GET /servo`).
- **Arm/disarm:** app → Firebase `config/armed`; the bridge gates on it.

**Limitations (call these out in red — the "why we changed"):**
- ❌ **Same network only** — phone and camera must share the LAN; no remote access.
- ❌ **A PC must stay on** at the site running Mosquitto + `bridge.py`.
- ❌ **Type the camera's IP**; breaks on CGNAT / no port-forwarding.
- ❌ **Open broker, no TLS**; hardcoded Wi-Fi creds → **not shippable**.

---

# SLIDE B — System Architecture v2 (Cloud, Outbound-Only) ★ current

**Title:** System Architecture — v2: Cloud & Outbound-Only (HiveMQ + Relay)
**Subtitle / one-liner:** *The device dials **out** to the cloud and stays connected — so it works from any network with no IP, no port-forwarding, no PC on site.*

**Diagram (render as a flat 3-zone diagram; all device arrows point OUTWARD in teal; 🔒 on every link):**
```
   SITE A (any network / 4G-LTE)        CLOUD (managed, free tiers, TLS)          ANYWHERE
 ┌────────────────┐  🔒 outbound TLS   ┌────────────────────────┐  🔒 wss / HTTPS ┌────────────┐
 │  ESP32-CAM     │── mqtts:8883 ─────►│   HiveMQ Cloud         │◄────────────────│  Phone app │
 │  on-device AI  │   status / alert   │   (managed MQTT)       │  cmd: servo,    │ (RN/Expo)  │
 │  + servo pan   │◄──── cmd ──────────│   topics: status·alert │  arm, stream    └─────┬──────┘
 │                │                    │           ·cmd·cmd/ack │                       │
 │  image ────────┼── 🔒 HTTPS POST ──► Cloudinary ─────────────────► photo in app      │
 │  alert meta ───┼── 🔒 REST/SDK ────► Firebase ──► Cloud Function ──► FCM push ───────►│ (app closed too)
 │  video ────────┼── 🔒 outbound WS (ON-DEMAND) ─► Deno Deploy relay ─► live view ─────►│
 └────────────────┘
        ▲  Rule: device DIALS OUT and stays connected (like a messaging app)
           → no static IP · no port-forwarding · no site PC
```

**Bullets (group into "Control + Alerts plane" and "Video plane"):**
- **Outbound-only rule (the key idea):** the camera always connects **out** to the cloud and stays connected — eliminates static IPs, port-forwarding, and any on-site PC.
- **Control + alerts plane — MQTT over TLS to HiveMQ Cloud** (managed broker). Topics: `status` (with **LWT** → true online/offline badge), `alert`, `cmd` (servo angle, arm/disarm, stream on/off), `cmd/ack`. The app speaks **MQTT-over-WebSocket (wss)** — **servo & arm/disarm now work from anywhere**.
- **Alerts anywhere:** device **HTTPS-POSTs the JPEG directly** to Cloudinary, writes metadata to Firebase → a **Cloud Function fires an FCM push** → phone is alerted **even with the app closed**. (No `bridge.py`, no site PC.)
- **Video plane — on-demand only:** app sends `cmd:{stream:on}` → device opens an **outbound WebSocket to the Deno Deploy relay** → relay fans frames to the app; closing the screen stops it. **Never streams 24/7.** Target QVGA–VGA JPEG, ~5–15 fps.
- **Security:** **TLS everywhere** (`mqtts` 8883 / `wss` / HTTPS), **per-device credentials**, least-privilege per-device topics.
- **Anywhere + cheap:** works on home Wi-Fi, office, or **4G/LTE**; entire stack on **free tiers (~$0–10/month)**.

---

# OPTIONAL — a small "What changed" comparison strip (if it fits cleanly)
Render as a compact 2-column before→after callout (red ❌ left, green ✅ right), do not overcrowd:

| | v1 Local Prototype | v2 Cloud (current) |
|---|---|---|
| Reach | ❌ Same LAN only | ✅ Any network / 4G |
| On-site PC | ❌ Required (Mosquitto + bridge.py) | ✅ None — device uploads directly |
| Broker | ❌ Local, open, no TLS | ✅ HiveMQ Cloud, per-device creds, TLS |
| Live video / servo | ❌ Camera LAN IP | ✅ Outbound relay / MQTT cmd, by deviceId |
| Alerts | ⚠️ Only while PC on | ✅ FCM push, app open or closed |

---
**Now build the two slides** (plus the optional comparison if it stays clean), diagrams as real flat graphics in the EagleEye brand, teal outward-arrows on the device, 🔒 on encrypted links, and speaker notes on each.
