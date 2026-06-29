# EagleEye — Complete Setup Guide

This guide walks a **brand new user** through every step needed to run EagleEye from scratch: creating cloud accounts, configuring credentials, flashing firmware, and starting the app. Follow each section in order.

---

## What you will set up

| Service | Purpose | Cost |
|---|---|---|
| **HiveMQ Cloud** | Cloud MQTT broker (ESP32 ↔ Mobile app) | Free tier (100 connections) |
| **Cloudinary** | Intrusion image storage | Free tier (25 GB) |
| **Firebase** | Realtime alert database | Free Spark plan |
| **Deno Deploy** | Live-video WebSocket relay | Free |
| **PlatformIO** | Firmware build + flash tool | Free |
| **Expo** | Mobile app development | Free |

---

## Prerequisites

Install these on your PC before starting:

- **Git** — to clone the repo
- **Python 3.10+** — for the optional local bridge
- **Node.js 18+** and **npm** — for the mobile app
- **PlatformIO CLI or VS Code extension** — to build + flash firmware
- **Android device** with USB Debugging enabled, or the Expo Go app

---

## Step 1 — Create a HiveMQ Cloud account

HiveMQ Cloud is the MQTT broker. The ESP32 and the mobile app both connect to it over TLS — no router port-forwarding needed.

1. Go to **console.hivemq.cloud** and sign up for a free account.
2. After email verification, click **Create new cluster** → choose the **Free** tier → pick any region → **Create cluster**.
3. Wait ~30 seconds for the cluster to become **Running**.
4. Note your **Cluster URL** — it looks like:
   ```
   abc123xyz.s1.eu.hivemq.cloud
   ```
5. Go to **Access Management** → **Credentials** → **Add new credentials**:
   - Username: `cam-01` (or any name you like)
   - Password: choose a strong password
   - Permission: **Publish and Subscribe**
   - Click **Save**
6. Keep this page open — you will paste the host, username, and password into `config.h` in Step 4.

> The broker port is always **8883** (MQTT over TLS). The WebSocket port (for the mobile app) is **8884**.

---

## Step 2 — Create a Cloudinary account

Cloudinary stores the high-resolution intrusion images captured by the ESP32.

1. Go to **cloudinary.com** → **Sign Up for Free**.
2. After login, note your **Cloud name** on the Dashboard (top-left, e.g. `mycloud123`).
3. Create an **unsigned upload preset** (this lets the ESP32 upload without API keys):
   - Go to **Settings** (gear icon) → **Upload** tab.
   - Scroll to **Upload presets** → click **Add upload preset**.
   - Set **Signing mode** = **Unsigned**.
   - Set a preset name, e.g. `eagleeye_unsigned`.
   - Under **Folder**, type `eagleeye_intrusions`.
   - Click **Save**.
4. Note: **Cloud name** and **preset name** — needed in `config.h` and `backend/.env`.

---

## Step 3 — Create a Firebase project

Firebase stores alert records (timestamp, image URL, detection confidence) and syncs them to the mobile app in real time.

1. Go to **console.firebase.google.com** → **Add project**.
2. Enter a project name (e.g. `eagleeye-fyp`) → disable Google Analytics if you don't need it → **Create project**.
3. Enable the Realtime Database:
   - In the left sidebar click **Build** → **Realtime Database** → **Create database**.
   - Choose a region (e.g. `us-central1`).
   - Select **Start in test mode** (allows reads + writes without auth — fine for development).
   - Click **Enable**.
4. Note your **Database URL** — it looks like:
   ```
   https://eagleeye-fyp-default-rtdb.firebaseio.com
   ```
5. (For the Python bridge only) Download a service account key:
   - Go to **Project Settings** (gear icon) → **Service accounts** tab.
   - Click **Generate new private key** → confirm → download the JSON file.
   - Rename it `serviceAccountKey.json` and place it in the `backend/` folder.

---

## Step 4 — Deploy the Deno relay

The relay is a small WebSocket server that lets the mobile app receive live JPEG frames from the ESP32 across any network.

1. Go to **deno.com/deploy** → **Sign in with GitHub** (or create a free account).
2. Click **New Project**.
3. Choose **Deploy from GitHub** → connect your GitHub account and authorize Deno Deploy.
4. Select your fork of this repo (or push the `relay/` folder to a new repo first).
5. Set the **Entry point** to `relay/deno_relay.ts`.
6. Click **Deploy** — Deno assigns a URL like:
   ```
   your-project-name.deno.dev
   ```
7. Open that URL in a browser — you should see:
   ```
   EagleEye relay up
   ```
8. Note this hostname (no `https://`, no trailing slash) — needed in `config.h`.

> **Alternative: deploy the Node.js relay to Railway**
> Push `relay/` to GitHub → railway.app → New Project → Deploy from repo → pick the folder. Railway runs `npm start` and gives you a URL like `eagleeye-relay-production.up.railway.app`. Use that as the relay host instead.

---

## Step 5 — Configure and flash the firmware

The active firmware is in `firmware/eagleeye-cloud-v2/` and uses PlatformIO.

### 5a. Install PlatformIO

- **VS Code**: install the **PlatformIO IDE** extension from the extensions marketplace.
- **CLI only**: `pip install platformio`

### 5b. Create config.h

```bash
cd firmware/eagleeye-cloud-v2/src
cp config.example.h config.h
```

Open `config.h` and fill in every `DEV_*` value:

```c
// Your Wi-Fi network (2.4 GHz only — ESP32 does not support 5 GHz)
#define DEV_WIFI_SSID   "YourWiFiName"
#define DEV_WIFI_PASS   "YourWiFiPassword"

// HiveMQ Cloud — from Step 1
#define DEV_MQTT_HOST   "abc123xyz.s1.eu.hivemq.cloud"
#define DEV_MQTT_PORT   8883
#define DEV_MQTT_USER   "cam-01"
#define DEV_MQTT_PASS   "YourHiveMQPassword"

// Cloudinary — from Step 2
#define DEV_CLD_CLOUD   "mycloud123"
#define DEV_CLD_PRESET  "eagleeye_unsigned"
#define DEV_CLD_FOLDER  "eagleeye_intrusions"

// Firebase — from Step 3 (host only, no https://, no trailing slash)
#define DEV_FIREBASE_DB "eagleeye-fyp-default-rtdb.firebaseio.com"

// Deno relay — from Step 4 (host only, no https://, no trailing slash)
#define DEV_RELAY_HOST  "your-project-name.deno.dev"
#define DEV_RELAY_PORT  443
```

Leave `DEV_INGEST_URL` and `DEV_TOKEN_URL` as empty strings `""` for now.

### 5c. Wire the ESP32-CAM for flashing

| FTDI pin | ESP32-CAM pin |
|---|---|
| GND | GND |
| 5V | 5V |
| TX | U0R (GPIO3) |
| RX | U0T (GPIO1) |
| GND | IO0 (hold LOW during upload only) |

Jumper **IO0 to GND** to enter bootloader mode. Remove the jumper after flashing.

### 5d. Flash

Open the `firmware/eagleeye-cloud-v2/` folder in VS Code with the PlatformIO extension, then:

```
PlatformIO sidebar → Upload (arrow icon)
```

Or via CLI:
```bash
cd firmware/eagleeye-cloud-v2
pio run --target upload --upload-port COM3    # change COM3 to your port
```

After upload completes: **remove the IO0 jumper**, press the reset button, and open Serial Monitor at **115200 baud**. You should see:

```
EagleEye v1.0.0-cloud starting...
[WiFi] Connected — IP: 192.168.x.x
[MQTT] Connected to abc123xyz.s1.eu.hivemq.cloud
[CAM] Camera OK
```

---

## Step 6 — Run the Python bridge (optional — local mode)

The Python bridge is needed if you want the intrusion images and alerts to also be stored locally via a Mosquitto broker. If the ESP32 writes directly to Firebase and Cloudinary (the default cloud mode), you can skip this step.

### 6a. Install Mosquitto

- **Windows**: download the installer from mosquitto.org → install → add `C:\Program Files\mosquitto` to your system PATH.
- **Linux/macOS**: `sudo apt install mosquitto` or `brew install mosquitto`

Verify: `mosquitto --version`

### 6b. Configure backend credentials

Edit `backend/.env`:

```env
CLOUDINARY_CLOUD_NAME=mycloud123
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
FIREBASE_DATABASE_URL=https://eagleeye-fyp-default-rtdb.firebaseio.com/
```

Get the Cloudinary API key and secret from **cloudinary.com → Dashboard → API Keys**.

Also place the Firebase `serviceAccountKey.json` (downloaded in Step 3) inside the `backend/` folder.

### 6c. Start Mosquitto

Open **Terminal 1**:

```powershell
cd c:\fyp-eagle-eye\backend
mosquitto -c mosquitto.conf -v
```

You should see:
```
mosquitto version ... starting
Opening ipv4 listen socket on port 1883.
Opening ipv4 listen socket on port 9001 (websockets).
```

Keep this terminal open.

### 6d. Start the Python bridge

Open **Terminal 2**:

```powershell
cd c:\fyp-eagle-eye\backend
pip install paho-mqtt firebase-admin cloudinary python-dotenv
python bridge.py
```

You should see:
```
[Success] Bridge Connected to Local Mosquitto! Listening for intruders...
```

---

## Step 7 — Run the mobile app

### 7a. Install dependencies

```bash
cd mobile-app
npm install
```

### 7b. Configure cloud credentials

```bash
cp src/config/cloudConfig.example.js src/config/cloudConfig.js
```

Edit `cloudConfig.js` and fill in:
- Firebase database URL
- HiveMQ Cloud host, port (8884 for WebSocket), username, password
- Deno relay URL

### 7c. Start on Android (USB)

Connect your Android phone via USB with **USB Debugging** enabled.

```powershell
# Allow the phone to reach Metro bundler on your PC
adb reverse tcp:8081 tcp:8081

# Start the app
cd mobile-app
npm run android
```

### 7d. Start with Expo Go (Wi-Fi)

```bash
cd mobile-app
npx expo start
```

Scan the QR code in the **Expo Go** app on your phone. Both the phone and PC must be on the same Wi-Fi network.

---

## Step 8 — Verify everything works

| Check | Expected result |
|---|---|
| Serial Monitor | `[MQTT] Connected`, `[CAM] Camera OK` |
| HiveMQ Console → Clients | `cam-01` shows as connected |
| Walk in front of camera | ESP32 captures image, uploads to Cloudinary, writes to Firebase |
| Firebase Console → Realtime DB | New alert entry appears under `/alerts/cam-01/` |
| Cloudinary Media Library | New JPEG appears under `eagleeye_intrusions/` |
| Mobile app Dashboard | Alert notification appears in real time |
| Mobile app → Live | Tap Live → stream starts (if Deno relay is deployed) |

---

## Troubleshooting

### MQTT not connecting
- Verify the HiveMQ cluster is in **Running** state (console.hivemq.cloud).
- Double-check `DEV_MQTT_HOST` — no `mqtt://` prefix, no trailing slash.
- Ensure the credentials match exactly what you created in HiveMQ Access Management.
- Check `TLS_INSECURE` is `1` in `config.h` for development (skips cert pinning).

### Cloudinary upload fails
- Verify the upload preset name matches exactly (`eagleeye_unsigned` is case-sensitive).
- Ensure the preset's signing mode is **Unsigned** — Signed presets require an API secret on the device.

### Firebase writes fail
- Confirm Realtime Database rules are in **test mode** (allow read + write to all paths).
- The `DEV_FIREBASE_DB` value must not have `https://` or a trailing `/`.

### Deno relay: `wss` connection refused
- Open the relay URL in a browser first — if it doesn't show "EagleEye relay up", the deploy failed.
- Re-check the entry point is set to `relay/deno_relay.ts` in Deno Deploy settings.

### Mosquitto not found (local bridge)
- Add Mosquitto's install directory to your system PATH environment variable.
- Restart your terminal after changing PATH.

### Port 1883 blocked
- Windows Firewall: create an inbound rule allowing TCP 1883.
- Or run: `netsh advfirewall firewall add rule name="Mosquitto" dir=in action=allow protocol=TCP localport=1883`

### IP address changed (local mode)
- Run `ipconfig` (Windows) or `ip addr` (Linux/macOS) to find your PC's current IP.
- Update it in `backend/bridge.py` (the `MQTT_BROKER` variable) and in the firmware secrets.

### Serial Monitor shows garbage characters
- Baud rate must be **115200** — not 9600 or any other value.

---

## Summary of credentials to collect

| Location | Value needed |
|---|---|
| `firmware/eagleeye-cloud-v2/src/config.h` | HiveMQ host, port, user, pass · Cloudinary cloud name + preset · Firebase DB host · Deno relay host |
| `backend/.env` | Cloudinary cloud name, API key, API secret · Firebase DB URL |
| `backend/serviceAccountKey.json` | Firebase service account JSON (for Python bridge) |
| `mobile-app/src/config/cloudConfig.js` | Firebase URL · HiveMQ WSS host + port 8884 + credentials · Deno relay URL |
