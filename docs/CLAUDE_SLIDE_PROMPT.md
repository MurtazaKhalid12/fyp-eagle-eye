# Paste-into-Claude prompt — EagleEye FYP Final Defence deck

> **How to use:** copy **everything below the line** (from "You are an award-winning…" to the end)
> into a new chat at claude.ai and send it. Claude will return a single, self-contained,
> visually-polished slide deck with empty image boxes you fill in afterward. If the deck is long,
> just reply **"continue"** and Claude will finish the remaining slides.

---

You are an **award-winning presentation & information designer**. Build me a **stunning, defence-ready slide deck** for my **Final Year Project (FYP) Final Defence**. Follow this brief exactly.

## Deliverable & format
- Output **one single, self-contained HTML file** (16:9, 1920×1080) that I can open in any browser and **print to PDF** (one slide per page). You may load **reveal.js via CDN**; put each slide in its own `<section>`.
- Make it **genuinely beautiful**: strong visual hierarchy, consistent 12-column grid, generous white space (~30–40% empty), smooth section dividers. This is a billboard, not a paper — short phrases, **never** walls of text.
- Add **speaker notes** for every slide (reveal.js `<aside class="notes">`) summarising what the presenter should say.
- If it's too long for one message, **split across replies** — I'll say "continue".

## Audience & tone
University FYP final-defence panel (professors + external examiner). Confident, technical, evidence-driven. Every claim backed by a number from the content below — **do not invent or change any number**.

## Brand system (use exactly)
- **Deep blue `#1F4E79`** — headings, section bars, dividers.
- **Teal accent `#2196F3`** — the single "pop" colour; highlights, the active data bar, arrows. Use sparingly.
- **Ink `#1A1A1A`** body text · **Slate `#555555`** captions.
- **Background `#FFFFFF`**, light panels `#F4F6F8`, thin rules `#D0D5DB`.
- Status: **green `#2E7D32`** (positive) · **red `#E53935`** (the "intruder"/alert accent only).
- **Type:** one clean sans-serif — **Montserrat** (headings, bold) + **Inter** (body). Load via Google Fonts. Title ≥ 40pt-equiv, headings ≥ 28, body ≥ 18.
- Each content slide gets a slim deep-blue header bar with a small numbered badge (e.g. `08 · AI VISION — MODEL EVOLUTION`).

## Structure rules
- Add a **section divider slide** before each major part (centered large title on a deep-blue background): *Introduction · The System · AI Vision · Backend & App · Results · Wrap-up*. Map the content slides under those.
- **Max ~6 bullets per slide.** If a slide has more, **split it** into "(Part 1 / Part 2)". New slides are free; cramped text is not.
- Turn lists of features/techniques into **icon + short-label** rows (use clean inline SVG or Phosphor/Lucide-style icons, all in deep blue).
- Turn the **results comparison table into a horizontal bar chart** (Test Accuracy + Human Recall) with the ★ v7.16 bar in teal and the others in slate; keep a small data table beneath it.
- Turn the **architecture** and **layer-stack** descriptions into clean flat **diagrams** (boxes + labelled arrows), not paragraphs.

## Image placeholders (important)
Wherever a real photo/screenshot is needed, **leave an empty, clearly-styled placeholder box** — do **not** generate or fake an image. Style each as a dashed teal-bordered light-panel box, vertically centered, sized to the right aspect ratio, with a 📷 icon and a caption naming what goes there, e.g.:

```
┌───────────────────────────────┐
│   📷  IMAGE: ESP32-CAM         │
│   prototype photo (4:3)        │   ← dashed border, #F4F6F8 fill, centered
└───────────────────────────────┘
```

Anywhere you see `[IMAGE: …]` or `[DIAGRAM: …]` in the content, render it as such a placeholder, sized as hinted, leaving real room for me to drop the picture in later.

## Do / Don't
**Do:** one accent colour; big confident titles; diagrams as heroes; real numbers; align to the grid; leave whitespace; consistent icon set.
**Don't:** rainbow colours; drop-shadows/3D bevels; clip-art; tiny text; paragraphs of prose; change any metric.

---

# SLIDE CONTENT (use this text; design it per the brief above)

## Slide 1 — Title (divider style, deep-blue background)
- **Title:** EagleEye: Intelligent Edge AI Surveillance System
- **Subtitle:** Final Year Project — Final Defence
- **Presenters:** Murtaza Khalid (BSCE22004) · Huzaifa Khan (BSCE22025) · Haseeb Ahmed (BSCE22048)
- **Supervisor:** Dr. Rehan Hafiz (Professor) · **Co-Supervisor:** Dr. Rehan Ahmed (Asst. Professor & Chairperson)
- **Department:** Computer & Software Engineering, Faculty of Engineering, Information Technology University (ITU), Lahore
- **Date:** June 2026
- `[IMAGE: optional EagleEye logo / eagle mark, top-center, transparent PNG]`

## Slide 2 — Problem Statement
- **The issue:** traditional surveillance is bandwidth-heavy, expensive, and privacy-invasive (24/7 video streamed to the cloud).
- **The gap:** few affordable, *privacy-first* smart cameras that process data entirely on the edge.
- **Our goal:** a decentralised, low-power system that detects intruders **locally on an ESP32-CAM** and transmits **only confirmed threats**.

## Slide 3 — Proposed Solution & Core Functionalities
**Concept:** a proactive, multi-layered security system combining Edge AI with physical automation.
- 🧠 **AI Vision Detection** — real-time human recognition with TinyML (no motion false alarms).
- 🔊 **Voice Alert System** — audible TTS/siren warning on detection to deter intruders.
- 🛡️ **Smart Arming Logic** — automated Arm/Disarm from sensor states.
- 🎥 **Live Surveillance** — low-latency streaming for manual verification.
- 🕹️ **Dynamic Camera Control** — auto target-tracking + manual remote pan/tilt.
- 🔐 **Physical Security** — integrated remote door-lock control.

## Slide 4 — Literature: limits of existing systems
- **Commercial/cloud (Ring/Nest):** continuous cloud streaming → high bandwidth + privacy risk; recurring fees; high power (~1.25 V/hr) [1].
- **Early Edge AI:** MobileNet-SSD / YOLOv5 too heavy for ESP32 → 1–3 FPS, high latency; large tensors exhaust 520 KB SRAM → brownouts / "camera init failed".
- **Sensors:** bare PIR → 85–95% false positives (wind/animals).

## Slide 5 — Literature: TinyML advancements we build on
- **INT8 quantization:** 32-bit floats → 8-bit ints; ~75% smaller, fits limited SRAM.
- **Optimised custom architectures:** small resolutions + shallow CNNs beat generic "kitchen-sink" models on speed.
- **Sensor fusion + TFLite-Micro:** wake on trigger; OS-free, low-latency bare-metal inference.

## Slide 6 — System Architecture
`[DIAGRAM: horizontal flow — ESP32-CAM → MQTT → Python Gateway → Cloudinary/Firebase → Mobile App, with labelled, encrypted (lock-icon) arrows]`
- **Edge:** ESP32-CAM running a custom TinyML model (C++).
- **Transport:** MQTT (lightweight pub/sub).
- **Gateway:** Python bridge — secure uploader; isolates the camera from the open internet.
- **Cloud:** Cloudinary (evidence storage) + Firebase (real-time alert signalling).
- **User:** React Native (Expo) mobile app.

## Slide 7 — Engineering: the Edge Layer
`[IMAGE: photo of the ESP32-CAM prototype / 3D-printed mount (4:3)]`
- **Hardware:** AI-Thinker ESP32-CAM.
- **Pipeline:** Capture (RGB565) → center-crop & resize to **96×96 RGB**, normalise [0,1] → run the **from-scratch depthwise-separable INT8** model → if human-prob > threshold, trigger alert.
- **Innovation:** "Warm-up" + "Cooldown" state machines kill false-positive loops & sensor noise.

---
## SECTION DIVIDER → "AI Vision"  (the core technical contribution)
---

## Slide 8 — AI Vision: Model Evolution
`[DIAGRAM: 5-phase horizontal timeline plotting Accuracy vs Latency, ending at the ★ v7.16 marker]`
*Governing constraint:* the detector must run **on the ESP32-CAM itself** — ~100 kB tensor arena, no GPU, no cloud inference, sub-second latency. **17 engineered variants (v1.0 → v7.17)** across five phases; the recurring lesson — the *smallest* model isn't the *best*; converge on the smallest model that still generalises.
- **Phase 0 — Off-the-shelf reference (Oct–Dec 2025):** pre-built person detectors proved the on-device TFLite pipeline (first end-to-end IoT path ~712 ms). Generic = slow & not ours.
- **Phase 1 — Custom Tiny CNN, 48×48 grayscale (Feb–May 2026):** v1.0 (~80–85%, ~106 ms) → v2.1 hard-negative >90% → v3.0 Optuna 94.96% but >300 ms → v4.0 distilled 91.77% @ <150 ms.
- **Phase 2 — Edge Impulse cloud, 48×48 (mid-May):** project "final" (~1,862 imgs); v6.1 grayscale = long-running deployed EI model.
- **Phase 3 — Transfer learning: MobileNetV1 0.2, 96×96 RGB:** 48px grayscale couldn't generalise. Sweep peaks at **v7.3 = 92.35% test (project best)**; v7.4 64×64+EON fast pick. Findings: *resolution > colour*.
- **Phase 4 — From-scratch depthwise-separable → final:** v7.14 → v7.15 → **★ v7.16 (96×96 RGB): 90.83% test, 87.5% human recall, balanced, ~872 ms — the deployed final model.**
- **Phase 5 — In-house pipeline (13 Jun 2026):** local replica of the EI model (`train_rgb.py`) — own the whole train → quantize → flash loop (RGB 92.16% INT8).

## Slide 9 — AI Vision: Training Techniques (the toolbox)
- **INT8 post-training quantization** — 4× smaller, fast integer math on the MCU; calibrated on a representative dataset (exposed a real *quantization gap*).
- **Data augmentation** — flips / rotation / zoom / brightness for lighting & angle robustness.
- **Hard-negative mining** — a live ESP32 Wi-Fi capturer harvested the exact field mistakes; oversampled them past 90%.
- **Optuna hyperparameter search** — automated LR / dropout / architecture tuning.
- **Knowledge distillation** — MobileNetV2 *teacher* → tiny *student* (α=0.378, T=9.23) → 91.77% @ <150 ms.
- **Class balancing** — geometric augmentation vs **class weighting** (the winner) → no human-minority bias.
- **Transfer learning** — pretrained MobileNetV1 backbone (96×96 RGB) → project peak 92.35%.

## Slide 10 — AI Vision: Final Technique (deep dive) — Depthwise-Separable, From-Scratch
`[DIAGRAM: vertical layer stack — Input 96×96×3 RGB → Conv2D(8) +BN +MaxPool → SeparableConv2D(16) +BN +MaxPool → SeparableConv2D(32) +BN +MaxPool → Flatten → Dropout(0.5) → Dense(2, Softmax)]`
- **Why depthwise-separable:** each conv factorises into a **depthwise** (per-channel) + **1×1 pointwise** conv → ~8–10× fewer multiply-accumulates. Conv MACs ≈ **2.8 M** (vs 17–42 M standard) → a from-scratch CNN that fits the ESP32 and stays sub-second.
- **From-scratch (no borrowed backbone):** the novelty requirement — a custom architecture we own that still clears **>90%**.
- **ESP-NN disabled:** *ESP-NN is Espressif's neural-network kernel library — hand-optimised low-level conv/depthwise/pooling routines that accelerate TensorFlow Lite Micro inference on the ESP32.* Its depthwise kernel saturated the model to "always human" on the ESP32-S1 (the v7.14 bug); turning ESP-NN **off** (reference kernels) removed the bias with no accuracy loss — the model is light enough to stay sub-second without it.
- **Balanced training:** 929 human / 920 non-human + class weights → no class bias.
- **INT8 quantization:** input scale 1/255 (zp −128), output 1/256 — same calibration as the EI "final" pipeline; deployed as `model_data.h`.
- **Resolution as the final lever:** 80→96 added the last ~2.5 pts to cross 90%.

## Slide 11 — AI Vision: Results
`[DIAGRAM: horizontal bar chart — Test Accuracy & Human Recall for v7.16 (teal, ★) vs v7.15 vs v7.3 (slate)]`
**Final deployed model — ★ v7.16 (96×96 RGB depthwise, from-scratch, ESP-NN off):**
- Held-out **TEST accuracy 90.83%** (297/327) — **>90% target met**.
- **Human recall 87.5%** (98/112) · **non-human recall 92.6%** (199/215) — **balanced, no bias**.
- **On-device latency ~872 ms** on the ESP32-CAM — fully local, INT8, no GPU / no cloud.

**Two predecessors, for context:**
- **v7.15 (80×80 RGB depthwise, ESP-NN off)** — direct predecessor: balanced **88.38%** (recall 88.4% / 88.4%); proved depthwise+RGB+ESP-NN-off fixed the bias.
- **v7.3 (96×96 RGB MobileNetV1, class-weighted)** — project **peak 92.35%** (human recall 92.0%) but on a *borrowed* ImageNet backbone; v7.16 traded ~1.5 pts to be **fully from-scratch**.

| Model | Architecture | Input | Test acc | Human recall | Note |
|-------|--------------|-------|----------|--------------|------|
| v7.3 | MobileNetV1 0.2 (transfer) | 96×96 RGB | 92.35% | 92.0% | peak — borrowed backbone |
| v7.15 | Depthwise, from-scratch | 80×80 RGB | 88.38% | 88.4% | direct predecessor |
| ★ v7.16 | Depthwise, from-scratch | 96×96 RGB | **90.83%** | 87.5% | **deployed final** |

---
## SECTION DIVIDER → "Backend & App"
---

## Slide 12 — Backend Integration (Gateway & Cloud)
`[IMAGE: Python terminal output showing JPEG magic-byte verification (16:9)]`
- **MQTT:** lightweight pub/sub (`eagleeye/camera/image`) to save battery.
- **Python Bridge (Gateway):** security buffer (camera has no direct internet); verifies JPEG "magic bytes"; secure API handshakes with Cloudinary & Firebase.

## Slide 13 — Mobile Application
`[IMAGE: app screen + alert notification mockup (phone, 9:16)]`
- **Tech:** React Native (Expo).
- **Features:** real-time gallery sync via Firebase listeners; high-res evidence from Cloudinary; live connection/last-seen status.

---
## SECTION DIVIDER → "Results & Wrap-up"
---

## Slide 14 — Results & Performance (System)
- **End-to-end latency:** on-device detection **~872 ms** (v7.16, fully local) · upload ~2–3 s (network) · alert to phone <1 s.
- **Detection accuracy:** 90.8% held-out test, balanced (87.5% human / 92.6% non-human recall).
- **Stability:** decoupled architecture prevents the camera freezing during uploads.

## Slide 15 — Work Division
`[DIAGRAM: 3-column role table with member photos/icons]`
- **Murtaza Khalid — Computer Vision & Embedded AI:** dataset + TinyML training (INT8); ESP32-CAM C++ firmware & inference engine; warm-up/cooldown state machine.
- **Haseeb Ahmed — Audio Intelligence & Sensing:** audio classifier on UrbanSound8K; detects door-open / footsteps / glass-break; <300 ms acoustic alerts.
- **Huzaifa Khan — IoT Connectivity & Mobile App:** secure Python gateway, MQTT broker, Cloudinary/Firebase; React Native app; magic-byte + secure handshakes.

## Slide 16 — Societal Impact & Sustainability (UN SDGs)
`[IMAGE: SDG 9, SDG 11, SDG 16 icon row]`
- **SDG 9:** democratising AI security on ~$10 microcontrollers (vs $200+ systems).
- **SDG 11:** safer low-income housing where commercial security is unaffordable.
- **Privacy by design:** images processed locally; only confirmed threats leave the device.

## Slide 17 — Timeline & Milestones
`[DIAGRAM: Gantt / milestone chart]`
- **Completed:** ✅ AI Vision (human detection) · ✅ Voice alerts · ✅ Core system (live stream & arming) · ✅ Remote live video & camera pan.
- **Final integration:** door-lock control · full system integration testing.

## Slide 18 — Conclusion
- **Summary:** sophisticated smart security does **not** need expensive hardware.
- **Key achievement:** a **custom, from-scratch 96×96 RGB depthwise-separable CNN running fully on-device** (~872 ms, 90.8% balanced accuracy), with a cloud-connected mobile app that works from anywhere.
- **Future scope:** solar power; on-device face-recognition add-on.

## Slide 19 — Thank You / Q&A
- **EagleEye** — Smart AI surveillance, from anywhere.
- *Open for questions.*
- `[IMAGE: QR codes — demo video + GitHub repo]`

## Slide 20 — References (IEEE)
1. M. A. Al-Khedher, "Hybrid Vision-Based Surveillance System for Smart Home Applications," *IEEE Trans. Consumer Electronics*, vol. 65, no. 4, pp. 450–459, 2019.
2. S. Tanwar et al., "Privacy-Preserving Surveillance Using Edge Computing," *2020 IEEE GUCON*, 2020.
3. P. Warden, "TinyML: Machine Learning with TensorFlow Lite on Arduino and Ultra-Low-Power Microcontrollers," *O'Reilly Media*, 2019.

---
**Now build the deck.** Start with the title + dividers, keep it visually consistent, leave every image box empty and clearly labelled, and add speaker notes throughout. If you run out of room, stop at a clean slide boundary and wait for me to say "continue".
