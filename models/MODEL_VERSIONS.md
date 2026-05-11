# EagleEye Model Versions

This document tracks the evolution of the `EagleEye` human detection models, detailing the training methodology, new techniques introduced, and the performance goals for each version.

## `model_v1.0_baseline.tflite`
* **Architecture:** Custom Tiny CNN (Separable Convolutions, 48x48 Grayscale)
* **Purpose:** The original production model for edge deployment. Designed specifically to run on the ESP32-CAM within strict memory constraints (~100kB tensor arena) while minimizing inference latency (~106ms).
* **Methods:** Standard cross-entropy loss, INT8 Quantization.
* **Accuracy:** Initial baseline (~80-85% depending on environment).

## `model_v1.1_color.tflite`
* **Architecture:** Custom Tiny CNN (48x48 RGB)
* **Purpose:** An experimental variant to test if color channels provided enough feature improvement to justify the higher memory and latency costs.
* **Methods:** RGB565 input preprocessing.
* **Status:** Superseded. Reverted back to grayscale due to excessive inference latency and memory limit constraints on the ESP32.

## `model_v2.0_augmented.tflite`
* **Architecture:** Custom Tiny CNN (48x48 Grayscale)
* **Purpose:** An iteration built in the `sketchboard` workspace to improve model robustness against varied lighting and camera angles.
* **Methods:** Introduced Data Augmentation directly into the training pipeline (`RandomFlip`, `RandomRotation`, `RandomZoom`).
* **Accuracy:** Improved generalization, reducing overfitting compared to v1.0.

## `model_v2.1_hard_negative_90plus.tflite`
* **Architecture:** Custom Tiny CNN (48x48 Grayscale)
* **Purpose:** The definitive "Hard Negative" model. Specifically trained to overcome persistent false positives/negatives observed in real-world live deployment.
* **Methods:** 
  * Injected and over-sampled with newly captured "Hard Negative" images from the live ESP32 Wi-Fi Capturer tool.
  * Employed Early Stopping based on strict validation accuracy.
  * Rigorous evaluation to ensure it consistently crossed the >90% metric threshold without overfitting.
* **Accuracy:** 90%+ target achieved. Currently the highest performing model for production edge inference.

---
**Note:** All models are formatted as INT8 quantized TensorFlow Lite (`.tflite`) files. To deploy any of these to the ESP32, they must be converted to a C-header file hex array (e.g., `human_detect_model_data.h`).
