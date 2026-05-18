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

## `model_v3.0_optuna_optimized.tflite`
* **Architecture:** Custom Heavy CNN (48x48 Grayscale). Filters: 16 -> 32 -> 64.
* **Purpose:** The highest-accuracy production model, optimized strictly for maximum F1 score via Optuna, irrespective of edge-device computational constraints.
* **Methods:**
  * Automated hunt for the optimal learning rate (0.0032) and dropout (0.244).
  * Replaced lightweight `SeparableConv2D` layers with standard heavy `Conv2D` layers.
  * Doubled the base filter count from 8 to 16.
* **Accuracy:** Peak performance confirmed by strict 5-Fold CV (94.96% Accuracy, 94.86% F1 Score).
* **Trade-offs:** 
  * **Latency Hit:** Inference time spiked from ~106ms (v1.0) to **>300ms** on the ESP32-CAM.
  * **Reason:** Standard Convolutions and doubled filter counts drastically increase the Multiply-Accumulate (MAC) math operations the CPU must perform. This model deliberately sacrifices real-time latency (~3 FPS) in exchange for absolute maximum accuracy in detecting hard negatives.

## `model_v4.0_knowledge_distilled.tflite`
* **Architecture:** Custom Tiny CNN (48x48 Grayscale). Base Filters: 16.
* **Purpose:** Bridging the gap between the blazing fast latency of the v1.0 architecture and the extremely high accuracy of the v3.0 model.
* **Methods:**
  * **Knowledge Distillation:** A massive MobileNetV2 Teacher model transferred its learned probabilities into this tiny Student model.
  * **Optuna Hyperparameter Tuning:** Optuna mathematically found the perfect distillation balance (`alpha`: 0.378, `temperature`: 9.23, `learning_rate`: 0.0015).
* **Accuracy:** 91.77% Overall Accuracy, 91.65% Macro F1-Score. Specifically achieved 98.44% Human Recall and 97.98% NonHuman Precision, almost entirely eliminating false positives.
* **Trade-offs:** Eliminated! Restored the `<150ms` real-time edge performance on the ESP32 while maintaining >91% accuracy.

## `model_v5.0_tiny_dropout.tflite`
* **Architecture:** Custom Tiny CNN (48x48 Grayscale) with aggressive Dropout.
* **Purpose:** Built to prevent the overfitting observed in previous iterations on complex hard-negative data.
* **Methods:**
  * Added `Dropout(0.2)` layers after every single convolutional block.
  * Implemented strict `EarlyStopping` monitoring `val_loss` with patience of 15 epochs and best-weights restoration.
* **Accuracy:** Reached 91.7% validation accuracy while maintaining a perfectly balanced training/validation curve (no overfitting).
* **Trade-offs:** The model remains extremely lightweight (12.6 KB) with very fast edge inference, solving the generalization issue without sacrificing latency.

## `model_v6.1_edge_impulse_grayscale.tflite` (current EI export)
* **Architecture:** Edge Impulse Keras classifier (INT8), project **1000575**
* **Input:** 48×48×1 grayscale (`2304` bytes), int8 `(gray - 128)` — matches `eagleeye-main`
* **Output:** `human` (0), `nonhuman` (1)
* **DSP:** Image block `channels: Grayscale` (retrained May 2026)
* **Size:** ~18.5 KB TFLite
* **Deploy:** `sketchboard/firmware/hard_negative_capturer/human_detect_model_data.h`

## `model_v6.0_edge_impulse_final.tflite` (superseded — RGB)
* **Architecture:** Edge Impulse Keras classifier (INT8), exported from Studio project **1000575** (`final`)
* **Input:** 48×48×3 RGB (`6912` bytes), int8 `(channel - 128)` per channel — **not** grayscale
* **Output:** 2 classes — `human` (index 0), `nonhuman` (index 1)
* **Purpose:** Cloud-trained model on the full sketchboard dataset (~1862 images) via Edge Impulse; used for sketchboard hard-negative live testing (`sketchboard/firmware/hard_negative_capturer/`).
* **Methods:** EI Image DSP + visual Keras (conv/dropout/conv/flatten), 30 epochs, `augmentationPolicyImage: none`
* **Source copy:** Extracted from deployment build; also embedded in `sketchboard/firmware/hard_negative_capturer/human_detect_model_data.h`
* **Also at:** `model-training/exported-models/model_v6.1_edge_impulse_grayscale.tflite`, `sketchboard/ei_grayscale_int8.tflite`
* **Optional firmware header:** `firmware/tools/hard_negative_capturer/human_detect_model_data_ei_grayscale.h`

---
**Note:** All models are formatted as INT8 quantized TensorFlow Lite (`.tflite`) files. To deploy to the ESP32, convert with `models/tflite_to_cpp_header.py`.

| Model | Archive header | Typical use |
|-------|----------------|-------------|
| `model_v1.0_baseline.tflite` | `models/model_v1.0_baseline.h` | Production `eagleeye-main` / `firmware/tools/hard_negative_capturer` (v1 baseline header) |
| `model_v6.1_edge_impulse_grayscale.tflite` | `models/model_v6.1_edge_impulse_grayscale.h` | Sketchboard / EI live test (48×48 grayscale) |
| `model_v6.0_edge_impulse_final.tflite` | `models/model_v6.0_edge_impulse_final.h` | Deprecated RGB export (6912-byte input) |
