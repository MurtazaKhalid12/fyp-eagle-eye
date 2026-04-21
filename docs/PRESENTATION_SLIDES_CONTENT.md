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
    -   Follow the numerical order (Slide 1 to Slide 15) exactly.

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

## Slide 6: System Architecture
**[Diagram Request: Horizontal Flowchart]**
*ESP32 -> MQTT -> Python Bridge -> Cloudinary/Firebase -> Mobile App*

-   **Edge Layer:** ESP32-CAM running Custom TinyML Model (C++).
-   **Transport Layer:** MQTT (Mosquitto) for generic, lightweight messaging.
-   **Gateway Layer:** Python Bridge script acting as the secure uploader and improving security by isolating the camera from the open internet.
-   **Cloud Layer:**
    -   **Cloudinary:** High-res evidence storage.
    -   **Firebase:** Real-time database for alert signaling.
-   **User Layer:** React Native Mobile App (Expo) for immediate user response.

---

## Slide 7: Engineering Design: The Edge Layer
**[Visual Request: Photo of ESP32-CAM setup]**

-   **Hardware:** AI-Thinker ESP32-CAM.
-   **Workflow:**
    1.  **Capture:** Frame (RGB565).
    2.  **Pre-processing:** Downscale to 48x48 & Convert to Greyscale (Software Optimized).
    3.  **Inference:** Run Custom TFLite Micro Int8 Quantized Model.
    4.  **Logic:** If Probability > 80% -> Trigger Alert state.
-   **Innovation:** Implemented "Warm-up" and "Cooldown" state machines to prevent false positive loops and sensor noise.

---

## Slide 8: AI Model Evolution & Optimization
**[Visual Request: Latency Comparison Graph (5.4s vs 112ms)]**

-   **Phase 1 (Initial):** Edge Impulse MobileNet.
    -   **Result:** Heavy (5.4s latency), barely fit in RAM.
-   **Phase 2 (Optimization):** Custom CNN (RGB).
    -   **Result:** Better, but color processing slowed down the tensor operations (1.1s).
-   **Phase 3 (Current):** Custom "Tiny" CNN (Grayscale).
    -   **Input:** 48x48x1.
    -   **Inference Time:** ~112ms per frame.
    -   **Size:** Model fits comfortably within PSRAM, leaving room for frame buffers.

---

## Slide 9: AI Model Architecture & Training Strategy
**[Diagram Request: Vertical Layer Stack Diagram]**
*Input (48x48) -> Conv2D (8 filters) -> MaxPool -> Conv2D (16 filters) -> MaxPool -> Dense (Softmax)*

-   **Custom CNN Architecture (Designed for ESP32):**
    1.  **Input Layer:** 48x48x1 Grayscale (Drastically reduces data vs RGB).
    2.  **Feature Extraction:** 3 Shallow Convolutional Blocks with small filter counts (8, 16, 32) to minimize RAM usage.
    3.  **Pooling:** MaxPooling2D layers aggressively reduce spatial dimensions (48->24->12->6) to focus on shapes, not pixels.
    4.  **Classifier:** GlobalAveragePooling + Softmax for binary output (Human vs Background).
-   **Training & Quantization:**
    -   **Dataset:** Augmented with random flips/zooms to prevent overfitting.
    -   **Post-Training Quantization:** Converted 32-bit Floats -> **8-bit Integers**.
    -   **Result:** 4x smaller model size, enabling fast integer arithmetic on the microcontroller.

---

## Slide 10: Backend Integration (Gateway & Cloud)
**[Visual Request: Python Terminal Output showing Magic Byte verification]**

-   **MQTT Protocol:** Uses lightweight publish/subscribe model (`eagleeye/camera/image`) to save battery.
-   **Python Bridge (Gateway):**
    -   Acts as a security buffer (the camera has no direct internet access).
    -   Verifies JPEG "Magic Bytes" to ensure data integrity before upload.
    -   Handles secure API handshakes with Cloudinary and Firebase.

---

## Slide 11: Mobile Application
**[Visual Request: App Screen & Alert Notification]**

-   **Technology:** React Native (Expo).
-   **Key Features:**
    -   **Real-time Sync:** Gallery updates instantly via Firebase listeners.
    -   **Visual Evidence:** Fetches high-res secure URLs from Cloudinary.
    -   **System Health:** Displays connection status and last-seen timestamps.

---

## Slide 12: Results & Performance Analysis
-   **Latency Metrics:**
    -   **Detection:** ~112ms (Edge).
    -   **Upload:** ~2-3s (Network dependent).
    -   **Alert:** < 1s (App).
-   **Accuracy:** Successfully detects human presence in varying light conditions using grayscale features.
-   **Stability:** Decoupled architecture prevents the camera from freezing during network uploads.

---

## Slide 13: Revised Work Division
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

## Slide 14: Societal Impact & Sustainability (UN SDGs)
**[Visual Request: Icons of SDG 9, SDG 11, and SDG 16]**

-   **Alignment with UN Sustainable Development Goals:**
    -   **SDG 9 (Industry, Innovation & Infrastructure):** Democratizing access to AI security by using low-cost, readily available microcontrollers (~$10 vs $200+ systems).
    -   **SDG 11 (Sustainable Cities & Communities):** Enhancing safety in low-income housing where expensive security systems are unaffordable.
-   **Privacy & Ethics:**
    -   **Privacy by Design:** Images are processed locally. Only confirmed threats are transmitted. Empty frames or non-threats never leave the device, preserving user privacy.

---

## Slide 15: Updated Timeline & Milestones
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

## Slide 16: Conclusion
-   **Summary:** EagleEye proves that sophisticated "Smart Security" does not need expensive hardware.
-   **Key Achievement:** Reduced inference to **112ms** on a microcontroller while maintaining a cloud-connected, user-friendly mobile app.
-   **Future Scope:** Exploring solar power integration and "Face Recognition" add-ons.

---

## Slide 17: Q&A
-   **Thank You.**
-   *Open for Questions.*

---

## Slide 18: References (IEEE)
1.  [1] M. A. Al-Khedher, "Hybrid Vision-Based Surveillance System for Smart Home Applications," *IEEE Transactions on Consumer Electronics*, vol. 65, no. 4, pp. 450-459, 2019.
2.  [2] S. Tanwar et al., "Privacy-Preserving Surveillance Using Edge Computing," *2020 IEEE International Conference on Computing, Power and Communication Technologies (GUCON)*, 2020.
3.  [3] P. Warden, "TinyML: Machine Learning with TensorFlow Lite on Arduino and Ultra-Low-Power Microcontrollers," *O'Reilly Media*, 2019.
