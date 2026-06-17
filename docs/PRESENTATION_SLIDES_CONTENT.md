# Instructions for Google NotebookLM / Slide Generator

**Role:** You are an expert presentation designer focused on high-end, uncluttered corporate presentations.
**Task:** Create a presentation deck based *strictly* on the content below.

**CRITICAL DESIGN RULES:**

1.  **Strict "Divider Slide" Strategy (For EVERY Section):**
    -   Do **NOT** put the section title and the bullet points on the same slide.
    -   **Step 1:** Create a **Separator Slide** that contains ONLY the Section Title (centered, large font) and a clean, high-contrast background.
    -   **Step 2:** Create the **Content Slide** immediately after, which contains the bullet points, text, and diagrams for that section.
    -   *Goal:* This prevents cognitive overload. The audience sees the topic first, then the details.

2.  **Zero Clutter Policy:**
    -   If a slide has too much text (more than 5-6 bullets), **SPLIT IT** into two content slides (Part 1 & Part 2).
    -   Do **NOT** shrink the font size to fit text. New slides are free; unreadable text is not.

3.  **Content Fidelity:**
    -   Do **NOT** summarize, shorten, or skip any bullet points. Use the text exactly as provided.
    -   Do **NOT** add filler text or "hallucinated" explanations.

4.  **Visual Minimalism & Technical Depth:**
    -   **Diagrams:** When `[Diagram Request]` is found, use simple 2D icons but include **SPECIFIC TECHNICAL LABELS**.
        -   *Example:* Do not just say "Data Transfer". Say "**MQTT Publish: eagleeye/camera/image**".
        -   *Example:* Do not just say "Upload". Say "**API Call: Cloudinary.upload()**" or "**Check: Magic Bytes (0xFFD8)**".
    -   **Fonts:** Use professional Sans-Serif fonts (Inter, Roboto, Arial).

5.  **Strict Ordering:**
    -   Follow the numerical order (Slide 1 to Slide 22) exactly.

---

# Presentation Slide Deck Content

## Slide 1: Title Slide
-   **Title:** EagleEye: Intelligent Edge AI Surveillance System
-   **Subtitle:** Mid-Project Evaluation
-   **Presenters:** [Member 1], [Member 2], [Member 3]
-   **Supervisor:** [Advisor Name]
-   **Date:** [Date]

---

## Slide 2: Problem Statement (Recap)
-   **The Issue:** Traditional surveillance systems are bandwidth-heavy, expensive, and privacy-invasive (streaming 24/7 video to the cloud).
-   **The Gap:** Lack of affordable, "privacy-first" smart cameras that process data entirely on the edge.
-   **Our Goal:** Develop a decentralized, low-power surveillance system that detects intruders locally on an ESP32-CAM and only transmits confirmed threats.

---

## Slide 3: Proposed Solution & Core Functionalities
**Project Concept:** A proactive, multi-layered security system combining Edge AI with physical automation.

**Key Functionalities:**
1.  **AI Vision Detection:** Real-time human recognition using TinyML (eliminating simple motion false alarms).
2.  **Voice Alert System:** Immediate audible warnings (Text-to-Speech/Siren) upon detection to deter intruders.
3.  **Smart Arming Logic:** Automated "Arm/Disarm" triggers based on sensor states.
4.  **Live Surveillance:** Low-latency video streaming for manual verification.
5.  **Dynamic Camera Control:**
    -   **Auto:** Intelligent tracking of moving targets.
    -   **Manual:** Remote Pan/Tilt control via the mobile app.
6.  **Physical Security:** Integrated Remote Door Lock control to secure premises instantly.

**The Solution:**
-   Bridging the gap between passive CCTVs and expensive smart security.
-   Providing a system that *detects, acts, and secures* autonomously.

---

## Slide 4: Previous Literature Review Findings
-   **Commercial & Cloud-Centric Limits:**
    -   **Systems (Ring/Nest):** Rely on continuous cloud streaming, causing high bandwidth usage and privacy risks (data stored externally) [1].
    -   **Cost & Power:** Recurring subscription fees and high power consumption (~1.25V/hour) make them unsuitable for off-grid use.
-   **Early Edge AI Limitations:**
    -   **Complex Models:** Standard architectures like **MobileNet-SSD** or **YOLOv5** are too heavy for ESP32, causing low frame rates (1–3 FPS) and high latency.
    -   **Hardware Failures:** Large tensors exhausted the 520KB SRAM, leading to frequent "Brownout" and "Camera Init Failed" errors.
    -   **Sensor Reliability:** Reliance on simple PIR sensors caused 85-95% false positive rates (triggered by wind/animals).

---

## Slide 5: Current Literature & TinyML Advancements
-   **Quantization Revolution:**
    -   **Technique:** Converting 32-bit floating-point weights to **8-bit integers (Int8)**.
    -   **Result:** Reduces model size by ~75% while retaining ~97% detection accuracy, allowing fit within limited SRAM.
-   **Optimized Custom Architectures:**
    -   **Grayscale Inputs:** shifting from RGB to 1-channel (48x48) inputs reduces tensor interactions by 3x.
    -   **Shallow CNNs:** Custom layers designed for specific object detection (Human) outperform generic "Kitchen Sink" models in speed (~112ms inference).
-   **Energy & Architecture:**
    -   **Sensor Fusion:** Waking the camera only on PIR triggers reduces idle consumption (~0.93V/hour).
    -   **Frameworks:** TensorFlow Lite for Microcontrollers enables OS-free, low-latency inference on bare metal.

---

## Slide 6: System Architecture — v1: Local Prototype (LAN-only)
**[Diagram Request: 3-zone flat diagram — SITE (ESP32-CAM) → SITE PC (Mosquitto broker + bridge.py → Cloudinary/Firebase) → Phone (same LAN). Mark live-video & servo as ❌ camera-LAN-IP links.]**
*One network for everything; a PC had to stay powered on at the site.*

-   **Flow:** ESP32-CAM → local **Mosquitto** broker on a site **PC** → **`bridge.py`** uploads the JPEG to **Cloudinary** + writes alert metadata to **Firebase** → app reads Firebase.
-   **Live video & servo:** the app talks **directly to the camera's LAN IP** (HTTP MJPEG / `GET /servo`).
-   **Arm / disarm:** app → Firebase `config/armed`; the bridge gates on it.
-   **Limitations:** ❌ same network only · ❌ a PC must stay on running Mosquitto + `bridge.py` · ❌ type the camera's IP (breaks on CGNAT / no port-forwarding) · ❌ open broker, no TLS, hardcoded Wi-Fi creds → **not shippable**.

---

## Slide 7: System Architecture — v2: Cloud & Outbound-Only (HiveMQ + Relay) ★ current
**[Diagram Request: 3-zone flat diagram — SITE A (ESP32-CAM, any network / 4G) → CLOUD (HiveMQ Cloud MQTT broker · Cloudinary · Firebase → Cloud Function → FCM · Deno Deploy WS relay) → ANYWHERE (Phone). All device arrows point OUTWARD (teal); 🔒 lock on every link.]**
*The device dials **out** to the cloud and stays connected — so it works from any network with no IP, no port-forwarding, no PC on site.*

-   **Outbound-only rule (the key idea):** the camera always connects **out** and stays connected, like a messaging app → no static IP, no port-forwarding, no on-site PC.
-   **Control + alerts plane:** **MQTT over TLS to HiveMQ Cloud** (managed broker). Topics `status` (with **LWT** → true online/offline), `alert`, `cmd` (servo, arm/disarm, stream on/off), `cmd/ack`. The app speaks **MQTT-over-WebSocket** — servo & arm/disarm work from anywhere.
-   **Alerts anywhere:** device **HTTPS-POSTs the JPEG directly** to **Cloudinary**, writes metadata to **Firebase** → a **Cloud Function fires an FCM push** → phone is alerted **even with the app closed**. (No `bridge.py`, no site PC.)
-   **Video plane (on-demand):** app sends `cmd:{stream:on}` → device opens an **outbound WebSocket to the Deno Deploy relay** → relay fans frames to the app; closing the screen stops it. **Never 24/7** (QVGA–VGA JPEG, ~5–15 fps).
-   **Security & cost:** **TLS everywhere** (`mqtts` 8883 / `wss` / HTTPS), **per-device credentials**, least-privilege topics; works on Wi-Fi / office / **4G-LTE**; entire stack on **free tiers (~$0–10 / month)**.

---

## Slide 8: Engineering Design: The Edge Layer
**[Visual Request: Photo of ESP32-CAM setup]**

-   **Hardware:** AI-Thinker ESP32-CAM.
-   **Workflow:**
    1.  **Capture:** Frame (RGB565).
    2.  **Pre-processing:** Center-crop & resize to **96x96 RGB**, normalize to [0,1] (matches the deployed v7.16 model).
    3.  **Inference:** Run the custom from-scratch **depthwise-separable** TFLite Micro INT8 model.
    4.  **Logic:** If human probability exceeds the alert threshold -> Trigger Alert state.
-   **Innovation:** Implemented "Warm-up" and "Cooldown" state machines to prevent false positive loops and sensor noise.

---

## Slide 9: AI Vision — Model Evolution
**[Visual Request: Horizontal 5-phase timeline plotting Accuracy vs Latency, ending at the ★ v7.16 marker]**

*Governing constraint:* the detector must run **on the ESP32-CAM itself** — ~100 kB tensor arena, no GPU, no cloud inference, sub-second latency. Every version is a negotiation between accuracy, latency, memory, and real-world reliability. **17 engineered variants (v1.0 → v7.17)** across five phases — the recurring lesson: the *smallest* model is not the *best* model; converge on the smallest model that still generalizes.

-   **Phase 0 — Off-the-shelf reference (Oct–Dec 2025):** bootstrapped on pre-built person detectors (Edge Impulse + a TFLite ESP32 reference). Proved the on-device TFLite pipeline works (first end-to-end IoT path ~712 ms). *Lesson:* inference works on-device, but a generic model is slow and not ours.
-   **Phase 1 — Custom "Tiny CNN", 48×48 grayscale (Feb–May 2026):** trained our own. v1.0 baseline (~80–85%, ~106 ms) → v1.1 color reverted (latency/memory) → v2.0 augmented → **v2.1 hard-negative >90%** (live ESP32 capturer) → v3.0 Optuna-heavy 94.96% but >300 ms → v4.0 knowledge-distilled 91.77% @ <150 ms → v5.0 tiny-dropout 91.7%, 12.6 KB. *Lesson:* accuracy is available, but not for free.
-   **Phase 2 — Edge Impulse cloud, 48×48 (mid-May 2026):** EI project 1000575 "final", ~1,862 images. v6.0 RGB (superseded — firmware fed 1-channel) → **v6.1 grayscale** (long-running deployed EI model). *Firmware lesson:* AllOpsResolver → MicroMutableOpResolver (register only needed ops).
-   **Phase 3 — Transfer learning: MobileNetV1 0.2, 96×96 RGB (mid-May–Jun 2026):** the 48×48 grayscale tiny CNN couldn't generalize in real scenes. Jumped to a pretrained MobileNetV1 backbone — with **ESP-NN** (*Espressif's optimized neural-network kernel library that accelerates TensorFlow Lite Micro inference on the ESP32*) **disabled**, because it produced saturated/wrong predictions for the MobileNet path on the ESP32-S1. Sweep v7.0 (89.86%) → **v7.3 class-weighted = 92.35% test (project peak)** → v7.4 64×64 + EON 91.13% / ~570 ms (fast pick). *Findings:* resolution > color; 48px collapses recall; 0.1-width can't reach 90%.
-   **Phase 4 — From-scratch depthwise-separable → the final model (late May–Jun 2026):** for the FYP novelty we wanted a custom, from-scratch model still >90%. Standard from-scratch convs (v7.11–v7.13) overfit (recall 67–76%). Breakthrough = **depthwise-separable convolutions** (~8–10× fewer MACs): v7.14 gray80 (86.85%, but an ESP-NN depthwise-kernel bug saturated it → "always human") → v7.15 rgb80, ESP-NN off (bias fixed, balanced 88.38%) → **★ v7.16 rgb96, ESP-NN off: 90.83% test, 87.5% human recall, balanced, ~872 ms — the deployed final model.** v7.17 is the grayscale sibling (86.24%, below target).
-   **Phase 5 — In-house local pipeline (13 Jun 2026):** a local replica of the EI "final" CNN (`model-training/train_rgb.py`) so the team owns the whole train → quantize → `model_data.h` → flash loop. RGB 92.16% INT8; grayscale 91.83% (with 100 pure-black frames added as non-human negatives so a blacked-out camera reads non-human).

**Model evolution — at a glance** *(latency = on-device ESP32-CAM; `*` = estimated / not separately benchmarked):*

| Ver. | Architecture | Input | Trained on | Accuracy¹ | Latency² | Verdict |
|------|--------------|-------|------------|-----------|----------|---------|
| P0 ref | Pretrained person detector (EI / TFLite) | ~96×96 | COCO-person (pretrained) | — | ~700 ms* | proved on-device TFLite; generic, not ours |
| v1.0 | Tiny separable CNN | 48×48 gray | ~1.5k human / non-human* | 80–85% | ~106 ms | original prod; too weak |
| v2.1 | Tiny CNN + hard-negatives | 48×48 gray | + live field hard-negatives | >90% | ~106 ms | field-hardened |
| v3.0 | Heavy CNN 16-32-64 (Optuna) | 48×48 gray | same set, 5-fold CV | 94.96% | >300 ms | most accurate, too slow |
| v4.0 | Distilled tiny (MobileNetV2 teacher) | 48×48 gray | distillation set | 91.77% | <150 ms | fast, but 48px ceiling |
| v6.1 | Edge Impulse CNN | 48×48 gray | EI cloud ~1,862 imgs | ~90% | ~110 ms* | long-deployed; detail-limited |
| v7.3 | MobileNetV1 0.2 (transfer) | 96×96 RGB | cleaned 469h / 920n + class-wt | 92.35% (peak) | ~1 s* | most accurate (borrowed backbone) |
| v7.4 | MobileNetV1 0.2 + EON | 64×64 RGB | same cleaned / balanced | 91.13% | ~570 ms | fast pick |
| v7.15 | Depthwise-separable, from-scratch | 80×80 RGB | balanced 929h / 920n | 88.38% | ~750 ms* | bias fixed; just under 90 |
| ★ v7.16 | Depthwise-separable, from-scratch | 96×96 RGB | balanced 929h / 920n | 90.83% | ~872 ms | **deployed final** |
| v7.17 | Depthwise-separable (gray) | 96×96 gray | balanced 929h / 920n | 86.24% | ~820 ms* | lower-RAM sibling |
| Local-RGB | From-scratch (EI replica, `train_rgb.py`) | 96×96 RGB | balanced 763 / 763 | 92.16%³ | ~872 ms* | in-house pipeline |
| Local-gray | From-scratch (+100 black frames) | 96×96 gray | balanced 763 / 763 + black | 91.83%³ | ~820 ms* | currently flashed |

¹ Held-out **test** accuracy, INT8, unless noted (v3.0 = 5-fold CV; v1.0 / v6.1 ≈ validation). ² On-device ESP32-CAM; `*` = estimated. ³ INT8 validation (local pipeline). Full per-version log: `models/MODEL_VERSIONS.md`.

---

## Slide 10: AI Vision — Training Techniques (the toolbox)
*Across the evolution, each phase contributed a reusable technique. The key ones:*

-   **INT8 post-training quantization** — 32-bit floats → 8-bit integers (~4× smaller, fast integer math on the MCU) via representative-dataset calibration. Exposed a real **"quantization gap"** (float ↑ but INT8 flat — v7.1) that later phases had to close.
-   **Data augmentation** — RandomFlip / Rotation / Zoom / brightness jitter for robustness to lighting and camera angle (v2.0+).
-   **Hard-negative mining** — a live ESP32 Wi-Fi capturer harvested the exact false positives/negatives the camera saw in the field; oversampled them to push past 90% (v2.1). *Train on what the device actually gets wrong.*
-   **Optuna hyperparameter search** — automated tuning of learning rate, dropout, and architecture (v3.0: 94.96% F1; also tuned the distillation in v4.0).
-   **Knowledge distillation** — a large MobileNetV2 *teacher* transferred its learned probabilities into a tiny *student* (α = 0.378, T = 9.23) → 91.77% @ <150 ms (v4.0).
-   **Class balancing** — geometric augmentation to parity (v7.2) vs **class weighting / cost-sensitive learning** (v7.3, the winner) — fixed the human-minority bias on cleaned data.
-   **Transfer learning** — a pretrained (ImageNet) MobileNetV1 backbone, width 0.2, 96×96 RGB (v7.0–v7.9) — reached the project's peak accuracy of 92.35% (v7.3).

---

## Slide 11: AI Vision — Four Approaches, One Winner
**[Diagram Request: four status cards in a row — ❌ / ❌ / ⚠️ / ✅ — the 4th (Depthwise-separable RGB) highlighted in teal with a ✓ tick; optional small "accuracy vs latency" quadrant with ★ v7.16 sitting in the sweet spot (high accuracy + low latency).]**
*We tried four model families to satisfy accuracy + latency + from-scratch all at once on the ESP32-CAM. Only the last cleared all three.*

-   **1 · Simple CNN — standard convolutions, from-scratch** ❌ — **couldn't generalize**: overfit on ~1k images, human recall only **67–76%** (and the heavier versions were also slow). Low capacity ≠ robust.
-   **2 · Knowledge distillation — big teacher → tiny student** ❌ — strong on paper (**91.77%**), but the student stayed **48×48 grayscale**, so it hit the same real-scene **detail ceiling**; extra training complexity for no real-world gain.
-   **3 · Pre-trained transfer — MobileNetV1 0.2** ⚠️ — **most accurate (92.35%)** but **too slow (~1 s)** on the ESP32, and a **borrowed** ImageNet backbone → weak novelty for the FYP.
-   **4 · Depthwise-separable, from-scratch, RGB** ✅ ★ — **the winner (v7.16):** depthwise factorization cut conv MACs **~8–10×** → light enough to run *from-scratch* **sub-second (~872 ms)**; **RGB at 96×96** kept the colour/detail grayscale strips out (≈ +5–7 pts human recall). **90.83%, balanced, custom.**

**Why it finally worked (one line):** depthwise-separable makes a *from-scratch* network **light enough to be fast**, and **RGB at 96×96** makes it **detailed enough to generalize** — the one combination that hit all three constraints at once.

---

## Slide 12: AI Vision — Final Technique (Deep Dive): Depthwise-Separable, From-Scratch
**[Diagram Request: Vertical Layer Stack Diagram]**
*Input 96×96×3 RGB → Conv2D(8) +BN +MaxPool → SeparableConv2D(16) +BN +MaxPool → SeparableConv2D(32) +BN +MaxPool → Flatten → Dropout(0.5) → Dense(2, Softmax)*

-   **Why depthwise-separable:** each standard convolution is factorized into a **depthwise** (per-channel) conv + a **1×1 pointwise** conv → ~8–10× fewer multiply-accumulates. Conv MACs ≈ **2.8M** (v7.16) vs ~17–42M for standard convs — this is what makes a from-scratch CNN fit the ESP32 budget and stay sub-second.
-   **From-scratch (no borrowed backbone):** satisfies the FYP novelty requirement — a custom architecture the team owns, *not* a pretrained MobileNet, that still clears **>90%**.
-   **ESP-NN disabled (on-device bias fix):** *ESP-NN is Espressif's neural-network kernel library — hand-optimized low-level conv / depthwise / pooling routines that accelerate TensorFlow Lite Micro inference on the ESP32.* Here its depthwise kernel saturated the model to "always human" on the ESP32-S1 (the v7.14 bug); turning ESP-NN **off** (falling back to the reference kernels) removed the bias with no accuracy loss — the model is light enough to stay sub-second even without the accelerator.
-   **Balanced training:** 929 human / 920 non-human + class weights → no class bias.
-   **INT8 quantization:** input scale 1/255 (zero-point −128), output scale 1/256 — the same calibration as the EI "final" pipeline; deployed as `model_data.h`.
-   **Resolution as the final lever:** bumping 80×80 → 96×96 (v7.15 → v7.16) added the last **~2.5 pts** needed to cross 90%.

---

## Slide 13: AI Vision — Results
**[Visual Request: Comparison bar chart — Test Accuracy & Human Recall for v7.16 vs v7.15 vs v7.3]**

**Final deployed model — ★ v7.16 (96×96 RGB depthwise, from-scratch, ESP-NN off):**
-   Held-out **TEST accuracy 90.83%** (297/327) — the **>90% target met**.
-   **Human recall 87.5%** (98/112) · **non-human recall 92.6%** (199/215) — **balanced, no class bias**.
-   **On-device latency ~872 ms** on the ESP32-CAM — fully local, INT8, no GPU, no cloud.
-   From-scratch depthwise CNN (~2.8M conv MACs); ESP-NN off → no on-device saturation (runs cleanly, no bias).

**Two predecessors, for context:**
-   **v7.15 (80×80 RGB depthwise, ESP-NN off)** — the *direct predecessor*: balanced **88.38%** test (human/non-human recall both 88.4%). Proved depthwise + RGB + ESP-NN-off fixed the on-device bias; v7.16 then bumped 80→96 for the last ~2.5 pts.
-   **v7.3 (96×96 RGB MobileNetV1, class-weighted)** — the project's **peak accuracy 92.35%** test (human recall 92.0%), but on a *borrowed* ImageNet backbone. v7.16 deliberately traded ~1.5 pts to be **fully from-scratch** (novelty) while staying balanced and ESP-NN-safe.

| Model | Architecture | Input | Test acc | Human recall | Note |
|-------|--------------|-------|----------|--------------|------|
| v7.3 | MobileNetV1 0.2 (transfer) | 96×96 RGB | 92.35% | 92.0% | peak — borrowed backbone |
| v7.15 | Depthwise, from-scratch | 80×80 RGB | 88.38% | 88.4% | direct predecessor |
| ★ v7.16 | Depthwise, from-scratch | 96×96 RGB | **90.83%** | 87.5% | **deployed final** |

---

## Slide 14: Backend Integration (Gateway & Cloud)
**[Visual Request: Python Terminal Output showing Magic Byte verification]**

-   **MQTT Protocol:** Uses lightweight publish/subscribe model (`eagleeye/camera/image`) to save battery.
-   **Python Bridge (Gateway):**
    -   Acts as a security buffer (the camera has no direct internet access).
    -   Verifies JPEG "Magic Bytes" to ensure data integrity before upload.
    -   Handles secure API handshakes with Cloudinary and Firebase.

---

## Slide 15: Mobile Application
**[Visual Request: App Screen & Alert Notification]**

-   **Technology:** React Native (Expo).
-   **Key Features:**
    -   **Real-time Sync:** Gallery updates instantly via Firebase listeners.
    -   **Visual Evidence:** Fetches high-res secure URLs from Cloudinary.
    -   **System Health:** Displays connection status and last-seen timestamps.

---

## Slide 16: Results & Performance Analysis (System)
-   **Latency Metrics (end-to-end):**
    -   **On-device detection:** ~872 ms (ESP32-CAM, v7.16 — fully local, no cloud/GPU).
    -   **Upload:** ~2-3s (Network dependent).
    -   **Alert to phone:** < 1s (App).
-   **Detection accuracy:** 90.8% held-out test, balanced (87.5% human / 92.6% non-human recall) — detail in "AI Vision — Results".
-   **Stability:** Decoupled architecture prevents the camera from freezing during network uploads.

---

## Slide 17: Revised Work Division
**[Visual Request: Table/Chart showing roles]**

-   **Murtaza Khalid (Computer Vision & Embedded AI):**
    -   **Dataset & Training:** Curated the human detection dataset and trained the custom TinyML model (Int8 Quantized).
    -   **Firmware Development:** Developed the ESP32-CAM C++ firmware, optimizing the inference engine and camera driver.
    -   **State Machine Logic:** Implemented the "Warm-up" and "Cooldown" algorithms to eliminate false positives.

-   **Haseeb (Audio Intelligence & Sensing):**
    -   **Audio Model Development:** Trained the Audio Classification Model on urban sound datasets (UrbanSound8K).
    -   **Threat Detection:** Optimized the model to specifically detect "Door Opening", "Footsteps", and "Glass Breaking".
    -   **Integration:** Tuned the inference to run within 300ms latency for real-time acoustic alerts.

-   **Huzaifa Khan (IoT Connectivity & Mobile App):**
    -   **Backend Architecture:** Designed the secure Python Gateway, MQTT Broker, and Cloud integrations (Cloudinary/Firebase).
    -   **Mobile App:** Built the React Native application for real-time alerts, live streaming, and history retrieval.
    -   **System Security:** Implemented Magic Byte verification and secure API handshakes.

---

## Slide 18: Societal Impact & Sustainability (UN SDGs)
**[Visual Request: Icons of SDG 9, SDG 11, and SDG 16]**

-   **Alignment with UN Sustainable Development Goals:**
    -   **SDG 9 (Industry, Innovation & Infrastructure):** Democratizing access to AI security by using low-cost, readily available microcontrollers (~$10 vs $200+ systems).
    -   **SDG 11 (Sustainable Cities & Communities):** Enhancing safety in low-income housing where expensive security systems are unaffordable.
-   **Privacy & Ethics:**
    -   **Privacy by Design:** Images are processed locally. Only confirmed threats are transmitted. Empty frames or non-threats never leave the device, preserving user privacy.

---

## Slide 19: Updated Timeline & Milestones
*(Mapping: Rubric MR5 - Revised Milestones)*
**[Visual Request: Gantt Chart]**

-   **Completed:**
    -   ✅ **AI Vision:** Confirmed as finished (Human Detection).
    -   ✅ **Voice Integration:** Confirmed as finished (Alerts).
    -   ✅ **Core System:** Confirmed as finished (Live Stream & Arming).
-   **Upcoming (Final Phase):**
    -   ⬜ **Dynamic Control:** Pan/Tilt & Auto-Tracking.
    -   ⬜ **Physical Security:** Door Lock Integration.
    -   ⬜ **Final Steps:** System Integration Testing.

---

## Slide 20: Conclusion
-   **Summary:** EagleEye proves that sophisticated "Smart Security" does not need expensive hardware.
-   **Key Achievement:** Runs a custom, **from-scratch 96×96 RGB depthwise-separable CNN fully on-device** (~872 ms, 90.8% balanced accuracy) while maintaining a cloud-connected, user-friendly mobile app.
-   **Future Scope:** Exploring solar power integration and "Face Recognition" add-ons.

---

## Slide 21: Q&A
-   **Thank You.**
-   *Open for Questions.*

---

## Slide 22: References (IEEE)
1.  [1] M. A. Al-Khedher, "Hybrid Vision-Based Surveillance System for Smart Home Applications," *IEEE Transactions on Consumer Electronics*, vol. 65, no. 4, pp. 450-459, 2019.
2.  [2] S. Tanwar et al., "Privacy-Preserving Surveillance Using Edge Computing," *2020 IEEE International Conference on Computing, Power and Communication Technologies (GUCON)*, 2020.
3.  [3] P. Warden, "TinyML: Machine Learning with TensorFlow Lite on Arduino and Ultra-Low-Power Microcontrollers," *O'Reilly Media*, 2019.
