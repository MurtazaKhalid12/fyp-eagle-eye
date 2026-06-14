# EagleEye — A1 Poster Designer Brief
### SparkUp Innovation Summit 2026 (Open House) · 19 June 2026 · ORIC

> **How to use this file.** Paste the whole thing to Claude (or follow it in Canva/Figma) to produce a
> print-ready **A1 portrait** academic research poster. Anything in `⟨angle brackets⟩` is a placeholder —
> replace before printing. Style = **clean academic**: light background, generous whitespace, one accent
> color, highly readable from ~1.5 m away.
>
> **Status: content-complete.** All names, affiliation, and metrics are final. Only **3 visual assets**
> remain before print: (1) **demo-video URL** for the QR, (2) a **real prototype photo + 1 app screenshot**,
> (3) the **SparkUp Innovation Summit 2026 / ORIC logo**. Everything else is ready to lay out.

---

## 0. Hard specs (do not deviate)

- **Canvas:** A1 portrait, **594 mm × 841 mm**, set up at **300 dpi** (7016 × 9933 px) with a **5 mm bleed** and **15 mm safe margin**. Export **PDF/X (CMYK)** for print + a PNG preview.
- **Readability rule (academic poster standard):** title readable at 3 m, headings at 1.5 m, body at 1 m.
  - Title ≥ **90 pt**, section headings ≥ **42 pt**, body ≥ **28 pt**, captions ≥ **22 pt**.
- **Text budget:** a poster is a billboard, not a paper. **≤ 800 words total.** Bullets and short phrases, not paragraphs. Lots of white space — aim for ~30–40% empty.
- **One reading path:** top-left → down the left column → center → right column → footer. Number the sections **1–6** so the eye knows the order.

---

## 1. Palette & typography

**Colors** (EagleEye's own brand, from the project):
- Primary deep blue `#1F4E79` (headings, rules, section bars)
- Accent teal `#2196F3` (highlights, arrows, the one "pop" color — use sparingly)
- Ink `#1A1A1A` (body text), Slate `#555555` (captions)
- Background `#FFFFFF` with very light panels `#F4F6F8`; thin rules `#D0D5DB`
- Status: free/positive green `#2E7D32`; alert red `#E53935` (only for the "intruder" accent)

**Type:** one clean sans-serif family throughout (e.g. **Inter**, **Source Sans 3**, or **Montserrat** for headings + **Inter** for body). Headings bold, body regular. No more than 2 weights per size. Avoid pure-black on white — use `#1A1A1A`.

**Section style:** each numbered section gets a slim deep-blue header bar with a white number badge, e.g. `①  THE PROBLEM`.

---

## 2. Layout (A1 portrait, 12-column grid)

```
┌──────────────────────────────────────────────────────────────┐
│ HEADER BAND  (full width, ~12% height)                        │
│ [ITU logo]   EAGLEEYE — Smart AI Surveillance, From Anywhere   │
│              one-line subtitle                     [SparkUp ▸] │
│   team names · supervisor · department · degree (small)       │
├───────────────────────────┬──────────────────────────────────┤
│ ① THE PROBLEM             │  ④ SYSTEM ARCHITECTURE (the star) │
│   (left col, 4 cols wide) │     full cloud diagram, large     │
│                           │     [redrawn — see §5]            │
│ ② OUR SOLUTION            │                                   │
│   + hero device image     ├──────────────────────────────────┤
│                           │  ⑤ HOW IT WORKS (pipeline)        │
│ ③ KEY FEATURES            │     Capture→AI→Alert→Phone strip   │
│   (icon bullets)          │                                   │
│                           ├──────────────────────────────────┤
│                           │  ⑥ RESULTS  +  TECH STACK         │
│                           │     metric tiles + logo row       │
├───────────────────────────┴──────────────────────────────────┤
│ FOOTER BAND: ⟨team + roll #s⟩ · Supervisor ⟨name⟩ · ITU FoE   │
│ [QR: demo] [QR: repo]            SparkUp Innovation Summit 2026 │
└──────────────────────────────────────────────────────────────┘
```

Center column is widest and carries the **architecture diagram** + **hero image** — these are the visual anchors a judge sees first.

---

## 3. Header content

- **Title (huge):** **EagleEye**
- **Subtitle (one line):** *Smart AI surveillance that runs on a $8 chip and watches your space from anywhere.*
  - Alt, more formal: *An ESP32-CAM edge-AI security camera with on-device human detection and a cloud-connected mobile app.*
- **Credit line (small, under title):** `Murtaza Khalid (BSCE22004) · Huzaifa Khan (BSCE22025) · Haseeb Ahmed (BSCE22048)  |  Supervisor: Dr. Rehan Hafiz (Professor) · Co-Supervisor: Dr. Rehan Ahmed (Asst. Professor & Chairperson)  |  Dept. of Computer & Software Engineering, Faculty of Engineering, Information Technology University (ITU), Lahore`
  - Team roles (optional small line or in footer): *Murtaza — Edge AI & Firmware · Huzaifa — Cloud & Mobile App · Haseeb — Audio Threat Detection.*
- **Logos:** **Official ITU logo** (torch + "Information Technology University" wordmark) top-left; **SparkUp Innovation Summit 2026 / ORIC** logo top-right. Optional EagleEye eagle mark beside the title. *(Nice touch: the supervisor, Dr. Rehan Hafiz, directs ITU's ORIC — the body hosting SparkUp.)*

---

## 4. Section copy (use almost verbatim — it's already poster-length)

### ① The Problem
Home & small-business security cameras force a bad trade-off:
- **Cloud cams** stream your footage to a company's servers — privacy risk + monthly subscription.
- **DIY/LAN cams** only work on the *same Wi-Fi* — they need the camera's IP typed in, a PC left running, and risky port-forwarding to reach from outside.
- Most also **record everything** and bury real events in hours of empty footage.

> *Goal: see real intrusions, from anywhere, privately, with no subscription.*

### ② Our Solution
**EagleEye** puts a tiny neural network **on the camera itself**. A low-cost **ESP32-CAM** decides *on-device* whether a human is present — so images are analysed locally, not in the cloud. When it spots an intruder it pushes a **photo alert to your phone**, and you can open an **on-demand live view** and **pan the camera** — all from **any network, anywhere** (home Wi-Fi, office, or 4G/LTE).

The trick: the camera **reaches *out* to the cloud** and stays connected (like a messaging app), so there's **no static IP, no port-forwarding, and no on-site PC**. Everything is **end-to-end encrypted** and runs entirely on **free service tiers**.

### ③ Key Features  *(icon + 4–6 words each)*
- 🧠 **On-device human detection** — TinyML, images never leave the device to be analysed
- 📲 **Instant intruder alerts** — captured photo pushed to your phone, anywhere
- 🎥 **On-demand remote live video** — stream only when you ask (saves data)
- 🕹️ **App-controlled camera pan** — servo aim from the app
- 🔔 **Arm / disarm + true online status** — real online/offline, not guesswork
- 🔒 **Encrypted & private** — TLS everywhere, per-device credentials
- 💸 **~$15–25 hardware · $0/month** — entire cloud stack on free tiers

### ④ System Architecture  *(the centerpiece — redraw, see §5)*
Caption: *The camera reaches out to the cloud; the phone reaches the same cloud; they meet in the middle — so it works on any network with no IP, no port-forwarding, no PC on site.*

### ⑤ How It Works  *(horizontal pipeline strip, left→right)*
`Capture frame` → `On-device AI: human?` → **(yes)** `Snap JPEG` → `Upload image (Cloudinary) + Alert (MQTT/Firebase)` → `Push to phone` → **on request:** `Live video via cloud relay`
**(no)** → `keep watching`
Sub-caption: *Only confirmed humans trigger an alert — no hours of empty footage.*

### ⑥ Results & Tech Stack
**Results tiles (big number + label)** — deployed model **v7.16** (96×96 RGB depthwise CNN, INT8), from `models/MODEL_VERSIONS.md`:
- `90.8%` detection accuracy *(held-out test; 87.5% human recall, balanced — no class bias)*
- `<1 s` fully on-device inference *(~872 ms on the ESP32-CAM — no cloud, no GPU)*
- `<3 s` detection → phone alert (end-to-end)
- `18` model versions engineered (v1.0 → v7.17)
- `~$10` device vs `$200+` commercial · `$0`/month cloud (free tiers)
- `100%` private — non-threat frames never leave the device

> *Optional rigor caption (great for judges):* "Selected from **18 trained variants** — spanning INT8 quantization, hard-negative mining, knowledge distillation, Optuna search, and depthwise-separable architectures — converging on a custom from-scratch CNN that holds **>90% accuracy entirely on-device**." (Peak across the line: 92.35%.)

**Tech stack (small labelled logo row):**
ESP32-CAM · Edge Impulse (TinyML) · MQTT / HiveMQ Cloud · Cloudinary · Firebase · Deno Deploy relay · React Native + Expo · TLS / WebSocket

**Why it's novel (one line):** *Edge AI on a microcontroller (privacy + zero inference cost) + an outbound-only architecture that works on any network — the same pattern commercial IoT platforms (AWS IoT, Ring/Nest) use, rebuilt at $0/month.*

---

## 5. The architecture diagram (redraw — most important visual)

Draw it clean and flat (matching academic style), **three zones left→right** with labelled arrows:

```
  SITE A                         CLOUD                          ANYWHERE
 ┌───────────────┐   outbound   ┌──────────────┐    wss/HTTPS   ┌──────────┐
 │  ESP32-CAM    │── TLS ───────►│ HiveMQ (MQTT)│◄───────────────│  Phone   │
 │  on-device AI │  status/alert │   broker     │  commands      │  app     │
 │  + servo pan  │  ◄── commands │              │  status/alert  │ (RN/Expo)│
 │               │               └──────────────┘                └──────────┘
 │   image ──────┼── HTTPS ─────► Cloudinary  ─────────────► photo in app
 │   alert ──────┼── REST  ─────► Firebase    ─────────────► alert history
 │   video ──────┼── wss (on-demand) ─► Deno relay ───────► live view
 └───────────────┘
```
- **Site A** box = the physical camera (use the hero device image or a clean line-icon of the ESP32-CAM + servo).
- **Cloud** = three stacked rounded cards: *HiveMQ broker*, *Cloudinary + Firebase*, *Deno relay*.
- **Anywhere** = a phone showing the app dashboard.
- Arrows **all point outward from the device** — visually reinforce "device reaches out." Label each arrow with what rides it (commands, status/alerts, image, live video).
- Add a tiny lock icon on each link to signal **end-to-end TLS**.

---

## 6. Imagery & assets

- **Hero image:** `⟨real photo of the built prototype⟩` (preferred) — else use the existing render `docs/assets/hardware_setup.png`. Place top of the center/left under §2. Add caption: *EagleEye node — ESP32-CAM in a 3D-printed mount.*
- **App screenshot(s):** `⟨1–2 real screenshots⟩` (dashboard + live view) as a small phone mockup near §3/⑥.
- **Flowchart:** reuse/clean `docs/assets/local_flowchart.png` for §⑤ if not redrawing.
- **Intruder inset (optional, small):** a cropped, de-saturated piece of `docs/assets/alert_interface.png` to convey the alert moment — keep it small so it doesn't fight the clean style.
- **Icons:** single consistent line-icon set (e.g. Lucide / Phosphor), all in deep-blue `#1F4E79`.

---

## 7. Footer band

`Team: Murtaza Khalid (BSCE22004) · Huzaifa Khan (BSCE22025) · Haseeb Ahmed (BSCE22048)`  ·  `Supervisor: Dr. Rehan Hafiz · Co-Supervisor: Dr. Rehan Ahmed`  ·  `Dept. of Computer & Software Engineering, Faculty of Engineering — Information Technology University (ITU), Lahore`
Left: **[QR → demo video ⟨url — still needed⟩]  [QR → github.com/muhammadAB123/fyp-eagle-eye]** with tiny labels.
Optional micro-line: *Aligned with UN SDG 9 · 11 · 16.*
Right: **SparkUp Innovation Summit 2026** lockup + date **19 June 2026**.

---

## 8. Do / Don't

**Do:** one accent color; big confident title; the architecture diagram as the hero; real numbers in §⑥; align everything to the grid; leave white space.
**Don't:** rainbow colors; drop-shadows/3D bevels; tiny 12 pt text; paragraphs of prose; clip-art; more than ~800 words; cram every detail (link the repo via QR for depth).

---

### Print & display checklist (for the event)
- Export **PDF/X, CMYK, 300 dpi, A1, with 5 mm bleed** — confirm with the print shop before sending.
- **Proof at 100%** on screen and print one **A4 test** to catch low-res images / clipped text.
- Get it **A1 printed + framed** (assessment requirement). Bring your **own laptop + LCD/monitor + mounting** for the live demo; **extension cords provided by ORIC**.
