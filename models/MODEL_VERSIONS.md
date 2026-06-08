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

## `model_v7.0_rgb96_mobilenetv1_a2_int8` (current sketchboard EI model)
* **Architecture:** Pretrained MobileNetV1 transfer model, width multiplier `0.2`, 96×96 RGB input, INT8 quantized.
* **Purpose:** Replaces the earlier 48×48 grayscale custom-tiny experiments for sketchboard live testing. The custom model family was very fast, but its tiny parameter budget and grayscale 48×48 input removed too much human shape/detail for robust generalization in real camera scenes.
* **Methods:**
  * Switched the input pipeline from 48×48 grayscale to 96×96 RGB so the model can use body outline, posture, clothing contrast, and scene context.
  * Used a pretrained MobileNetV1 backbone with a 32-neuron classification head and `0.25` dropout.
  * Trained with class weights, full image augmentation, 40 epochs, learning rate `0.00035`, and batch size `16`.
  * Built an Arduino library package with ESP-NN disabled because earlier ESP32-CAM S1 testing showed saturated wrong predictions with the optimized path.
* **Validation:** INT8 validation accuracy `89.86%`; human precision `~95.2%`, human recall `~83.1%`, human F1 `~88.1%`.
* **Trade-offs:** Higher latency than the smallest custom CNN, but much better generalization. This model represents the current best balance between accuracy, latency, memory, and reliability for the sketchboard ESP32-CAM S1 experiments.
* **Firmware:** `sketchboard/firmware/hard_negative_capturer/hard_negative_capturer.ino` now uses the installed `final_inferencing` Arduino library for the Wi-Fi AI-assisted hard-negative capture workflow.

## `model_v7.1_rgb96_mobilenetv1_a2_int8_expanded` (current sketchboard EI model — EI version 5)
* **Architecture:** Identical to v7.0 — pretrained MobileNetV1 transfer model, width multiplier `0.2`, 96×96 RGB input, 32-neuron head, `0.25` dropout, INT8 quantized, ESP-NN disabled.
* **Purpose:** Retrain of the v7.0 "smart" model on an **expanded dataset** (`datasets/Human_Detection_Dataset/Human_Detection_Dataset_4`). EI project **1000575** training set grew from 736 → **1,445** samples (testing held at 309; +709 new unique images after duplicate filtering).
* **Methods:** Same pipeline (`tools/edge_impulse/retrain_rgb_96_mobilenetv1_a2_smart_no_espnn.py`): 40 epochs + 10 fine-tune, learning rate `0.00035`, batch size `16`, full image augmentation, auto class weights, INT8 profiling. Trained 2026-06-07.
* **Validation (float32):** `92.04%` accuracy, `val_loss 0.214` — up **+2.2 pts** from v7.0's 89.86%.
* **Validation (INT8 — deployed):** `89.27%` accuracy, `loss 0.2460`, confusion matrix `[[78, 22], [9, 180]]` (label order `human`, `nonhuman`). Derived: human precision `~89.7%`, human recall `~78.0%`, human F1 `~83.4%`; nonhuman recall `~95.2%`.
* **Note:** The float32 model improved with more data, but the INT8 (quantized) accuracy is essentially flat vs v7.0 (89.27% vs 89.86%) — a larger quantization gap this run, measured on a bigger, more reliable validation set (289 vs 148 samples). The deployed-model accuracy on hardware is therefore comparable to v7.0.
* **Artifacts:** EI project version snapshot **v5**, deployment version 15. Library zip rebuilt at `third_party/ei_arduino_library_rgb96_mobilenetv1_a2_no_espnn.zip` (ESP-NN disabled), `#include <final_inferencing.h>`.

## `model_v7.2_rgb96_mobilenetv1_a2_int8_balanced` (current — EI version 6)
* **Architecture:** Identical to v7.0/v7.1 — MobileNetV1 0.2, 96×96 RGB, 32-neuron head, `0.25` dropout, INT8, ESP-NN disabled.
* **Purpose:** Fix the class imbalance (human was the minority: 519 train vs 926 nonhuman). The human class was augmented up to parity so the model is balanced on both classes.
* **Balancing method:** **Geometric-only augmentation** (`tools/edge_impulse/augment_humans_geometric.py`) — horizontal flip, ±12° reflect-padded rotation, and crop-zoom/translation. **No color/brightness/contrast/hue changes** (RGB preserved exactly). 420 augmented humans generated from 520 *training-only* base images (EI test-set humans excluded → no train/test leakage), uploaded to the training set. Result: training balance **939 human / 926 nonhuman (50/50)**; test set unchanged at 92h/217n.
* **Validation (float32):** `93.83%` (val_loss 0.171). **Validation (INT8):** `87.13%`, loss 0.301, matrix `[[159,43],[5,166]]` — note this val split now contains augmented humans, so it is not directly comparable to v7.1.
* **Held-out TEST (309 real images, INT8):** accuracy **91.26%** (282/309). Human recall **82.6%** (76/92; confident misses 13→**8** vs v7.1, +4 uncertain); nonhuman recall **94.9%** (206/217, unchanged). Weighted precision/recall/F1 ≈ 0.93, ROC AUC 0.91.
* **Result:** Balancing gave a modest, real improvement in human detection (confident human→nonhuman errors down ~38%) with nonhuman performance fully preserved. Remaining levers: reduce the INT8 quantization gap and collect more genuine human photos.
* **Artifacts:** EI project version snapshot **v6**, deployment version 16. Library zip rebuilt at `third_party/ei_arduino_library_rgb96_mobilenetv1_a2_no_espnn.zip` (ESP-NN disabled), `#include <final_inferencing.h>`.

## `model_v7.3_rgb96_mobilenetv1_a2_int8_classweighted` (current — EI version 7)
* **Architecture:** Identical to v7.0–v7.2 — MobileNetV1 0.2, 96×96 RGB, 32-neuron head, `0.25` dropout, INT8, ESP-NN disabled.
* **Purpose:** Handle the human/nonhuman imbalance with **class weighting (cost-sensitive learning)** instead of augmentation — penalize misclassifying the minority (human) class more heavily. Trained on a **cleaned** dataset.
* **Method:** Full EI dataset reset, then re-uploaded the cleaned folder (`datasets/Human_Detection_Dataset/Human_Detection_Dataset_4`, ~38 bad/mislabeled images removed). Unique data 1,716 → train 469 human / 920 nonhuman, test 112 human / 215 nonhuman. Training used `autoClassWeights: True` (≈2× loss weight on the human class). No augmented images.
* **Validation (INT8):** **92.45%** accuracy, loss 0.309, matrix `[[68,12],[9,189]]` (human recall ~85%).
* **Held-out TEST (327 real images, INT8):** accuracy **92.35%** (302/327). **Human recall 92.0%** (103/112; only 4 confident misses), nonhuman recall 92.6% (199/215). Weighted precision/recall/F1 = **0.95**, ROC AUC **0.95**.
* **Result:** Best model to date and **balanced on both classes** (human 92.0% / nonhuman 92.6%). Both validation and test accuracy exceed 90%. Human recall improved +10 pts over v7.1/v7.2 with confident human misses cut from 13→4, while nonhuman stayed strong. Class weighting on cleaned data clearly beat geometric augmentation (v7.2).
* **Artifacts:** EI project version snapshot **v7**, deployment version 17. Library zip rebuilt at `third_party/ei_arduino_library_rgb96_mobilenetv1_a2_no_espnn.zip` (ESP-NN disabled), `#include <final_inferencing.h>`.

## `model_v7.4_rgb64_mobilenetv1_a2_int8_eon` (current — EI version 8, fast)
* **Architecture:** Same MobileNetV1 0.2 + 32-neuron head / 0.25 dropout as v7.3, but **64×64 RGB input** (vs 96×96) and built with the **EON Compiler** (`engine: tflite-eon`), ESP-NN disabled.
* **Purpose:** Cut inference latency for the ESP32-CAM S1 (which cannot use ESP-NN). Dropping 96×96→64×64 removes ~56% of the convolution MACs; EON removes interpreter overhead and lowers RAM/flash.
* **Method:** Retrained on the same cleaned/balanced dataset (train 469 human / 920 nonhuman, test 112/215) with `autoClassWeights: True`, 40+10 epochs, lr 0.00035, batch 16, aug all. `tools/edge_impulse/retrain_rgb_64_mobilenetv1_a2_eon_no_espnn.py`.
* **Validation (INT8):** **92.81%**, loss 0.299, matrix `[[67,13],[7,191]]`.
* **Held-out TEST (327 real images, INT8):** accuracy **91.13%** (298/327). **Human recall 92.0%** (103/112 — identical to 96×96), nonhuman recall 90.7% (195/215). Weighted P/R/F1 = 0.94, ROC AUC 0.94.
* **Result:** ~4× lighter than the 96×96 model with **human recall fully preserved at 92%** and only ~1.2 pts lower overall — the fast-and-accurate target without ESP-NN. Expected on-device latency roughly half of the 96×96 (~550–700 ms range; confirm with `eagleeye_latency_test`).
* **Artifacts:** EI project version snapshot **v8**, deployment version 19, EON-compiled. Library: `third_party/ei_arduino_library_rgb64_mobilenetv1_a2_eon_no_espnn.zip` (64×64, EON, ESP-NN disabled), `#include <final_inferencing.h>`.

## `model_v7.5_rgb64_mobilenetv1_a1_light` (lightest/fastest — lower accuracy)
* **Architecture:** MobileNetV1 **0.1** (half-width of 0.2), 16-neuron head, 0.1 dropout, 64×64 RGB, INT8, standard TFLite build (NO EON), ESP-NN disabled.
* **Purpose:** Maximum speed / smallest model experiment. Trained on a deliberately small balanced set.
* **Dataset:** Tried two sizes — (a) downsampled **350/350** (560 train), and (b) the **full ~1,389-image set** (469 human / 920 nonhuman); test set 112/215 both times.
* **Held-out TEST (327, INT8):**
  * 350/350: accuracy **81.96%**, human recall 81.3%, nonhuman 82.3% (val INT8 86.43%).
  * **Full data (current, deploy 21):** accuracy **83.79%**, human recall **77.7%** (87/112), nonhuman 87.0% (187/215), weighted F1 0.89, ROC AUC 0.88 (val INT8 89.21%).
* **Result:** Lightest MobileNet config (0.5 MB weights; expected ~300–400 ms on device). Full data lifted overall accuracy ~2 pts but **human recall stayed ~78%** — the 0.1 backbone lacks the capacity to separate the classes well, and more (imbalanced) data pushed it further toward nonhuman. Too low on human recall for reliable detection. **v7.4 (64×64 0.2, 91% / 92% human recall) remains the recommended fast model.**
* **Artifacts:** EI version snapshots **v9** (350/350) and **v10** (full data, deploy 21). Library: `third_party/ei_arduino_library_rgb64_mobilenetv1_a1_light_no_espnn.zip` (64×64, no EON, ESP-NN disabled).

## `model_v7.6_gray64_mobilenetv1_a2` (greyscale 0.2 — lighter input)
* **Architecture:** MobileNetV1 **0.2** + 32-neuron head / 0.25 dropout, **64×64 GREYSCALE** input (1 channel, `NN_INPUT_FRAME_SIZE = 4096`), INT8, standard TFLite (no EON), ESP-NN disabled. Full dataset (469 human / 920 nonhuman), class weights.
* **Purpose:** Test greyscale + the stronger 0.2 backbone — cut input to 1 channel for lower RAM / modest speed while keeping 0.2 capacity.
* **Validation (INT8):** 90.29%, matrix `[[60,17],[10,191]]`.
* **Held-out TEST (327, INT8):** accuracy **89.91%** (294/327). **Human recall 84.8%** (95/112), nonhuman 92.6% (199/215). Weighted P/R/F1 = 0.94, ROC AUC 0.93.
* **Result:** Greyscale is genuinely 1-channel (real input reduction → less RAM, ~10–20% faster than RGB 0.2 at 64×64), and far better than the 0.1 light model. But losing color cost ~7 pts of **human recall** (92%→85%) vs RGB 0.2. For intruder detection (where human recall matters most), **v7.4 RGB 0.2 @ 64×64 remains preferred**; greyscale 0.2 is a viable lower-RAM alternative.
* **Artifacts:** EI version snapshot **v11**, deployment version 22. Library: `third_party/ei_arduino_library_gray64_mobilenetv1_a2_no_espnn.zip`. NOTE: greyscale model needs a greyscale preprocessing path in firmware.

## `model_v7.7_gray96_mobilenetv1_a2` (greyscale 0.2 at 96×96)
* **Architecture:** MobileNetV1 0.2 + 32-neuron head / 0.25 dropout, **96×96 GREYSCALE** (1 channel, `NN_INPUT_FRAME_SIZE = 9216`), INT8, standard TFLite (no EON), ESP-NN disabled. Full dataset (469/920), class weights.
* **Validation (INT8):** 91.37%, matrix `[[60,17],[7,194]]`.
* **Held-out TEST (327, INT8):** accuracy **91.44%** (299/327). Human recall 86.6% (97/112), nonhuman 94.0% (202/215). Weighted P/R/F1 = 0.93, ROC AUC 0.92.
* **Result:** Higher resolution recovered what greyscale-64 lost (human recall 84.8%→86.6%, overall 89.9%→91.4%). But still ~5–6 pts human recall below RGB-96, and **no meaningful speed gain over RGB-96** (greyscale only shrinks the first layer; the deep layers dominate). Benefit is lower RAM only. **RGB 64×64 (v7.4) remains the best speed+accuracy pick; RGB 96×96 (v7.3) the most accurate.**
* **Firmware:** runs with the (now greyscale) `eagleeye_ei_runtime_rgb.ino` — it reads input dims from the library, so gray64/gray96 both work unchanged.
* **Artifacts:** EI version snapshot **v12**, deployment version 23. Library: `third_party/ei_arduino_library_gray96_mobilenetv1_a2_no_espnn.zip`.

## `model_v7.8_rgb48_mobilenetv1_a2_classweighted` (48×48 — too small)
* **Architecture:** MobileNetV1 0.2 + 32-neuron head / 0.25 dropout, **48×48 RGB**, INT8, standard TFLite (no EON), ESP-NN disabled. Full dataset (469 human / 920 nonhuman), `autoClassWeights: True` (human ≈ 2× loss weight to balance).
* **Validation (INT8):** 87.41%, matrix `[[64,13],[22,179]]`.
* **Held-out TEST (327, INT8):** accuracy **85.02%** (278/327). **Human recall 76.8%** (86/112; 15 uncertain + 11 misclassified), nonhuman 89.3% (192/215). Weighted P/R/F1 = 0.89, ROC AUC 0.87.
* **Result:** 48×48 is too low-resolution — even with the 0.2 backbone, RGB, and class weighting, human recall collapsed to ~77% (same failure mode as the old v6.0 48×48 models: too little human detail). Class weights balanced what they could but can't recover lost resolution. **Confirms 64×64 is the practical floor; v7.4 (RGB 0.2 @ 64×64, 91%/92% recall) remains the recommended fast model.**
* **Artifacts:** EI version snapshot **v13**, deployment version 24. Library: `third_party/ei_arduino_library_rgb48_mobilenetv1_a2_no_espnn.zip`.

## `model_v7.9_*_mobilenetv1_a1_light` (0.1 backbone on 400/400 balanced — size/colour sweep)
* **Setup:** Training downsampled to a balanced **400 human / 400 nonhuman** (random), MobileNetV1 **0.1**, 16-neuron head, dropout 0.1, INT8, no EON, ESP-NN disabled. Test set 112/215.
* **Runs:**
  * **RGB @ 64×64** (deploy 25): INT8 val 84.38%; **TEST 80.43%**, human recall 82.1% (92/112).
  * **Greyscale @ 96×96** (deploy 26, `ei_arduino_library_gray96_mobilenetv1_a1_light_no_espnn.zip`): INT8 val 86.25%, matrix `[[51,20],[2,87]]`; **TEST 85.93%**, human recall 83.9% (94/112), nonhuman 87.0%.
* **Finding:** Greyscale@96 beat RGB@64 by +5.5 pts — **resolution matters more than colour**. But the 0.1 backbone still caps at ~86% / ~84% human recall regardless; it cannot reach the 0.2 models (91–92%). Confirms 0.2 is required for >90%.
* **Recommendation unchanged:** v7.4 (RGB 0.2 @ 64×64, 91%/92%) for fast+accurate; v7.3 (RGB 0.2 @ 96×96) for max accuracy.

## `model_v7.11_gray96_tinycnn` (custom tiny CNN — fast but poor generalization)
* **Architecture:** Custom from-scratch CNN (NOT transfer) — Conv2D(32)+Conv2D(16) [baseline] or Conv2D(16,32,32)+Dropout(0.5) [regularized], 96×96 greyscale, INT8, **ESP-NN ENABLED** (not patched off — to test whether plain Conv2D avoids the MobileNet saturation bug). Full data + autoClassWeights.
* **Baseline (2 conv, dropout 0.25, 60 ep):** INT8 val 91.73%, but train 99% / val 90% = overfitting.
* **Regularized (3 conv, dropout 0.5, 40 ep, deploy 29):** train/val gap cut to ~3 pts (train ~95%, INT8 val **93.17%**) — BUT **held-out TEST only 84.71%**, human recall **72.3%** (81/112), nonhuman 91.2%.
* **Finding:** Regularization fixed train→val overfitting, but the **8-pt val-vs-test gap** exposes poor real-world generalization. A from-scratch tiny CNN on ~1,100 images can't match the MobileNet's ImageNet-pretrained features (which give 92% human recall). Tiny CNN is fast but misses ~1 in 4 humans — not viable for detection. **MobileNet transfer (v7.4) remains the answer.**
* **Artifacts:** deploy versions 28 (baseline) / 29 (regularized). Library: `third_party/ei_arduino_library_gray96_tinycnn_reg_espnn.zip` (ESP-NN on — verify no saturation on hardware).

## `model_v7.12_gray80_tinycnn` (tiny CNN @ 80×80 — latency-reduced)
* **Goal:** reduce tiny-CNN latency toward ~700 ms by dropping 96×96 → 80×80 (≈0.69× conv MACs). Same baseline 2-conv arch, greyscale, ESP-NN on, full data + class weights.
* **Validation (INT8):** 89.21%, matrix `[[72,15],[15,176]]`.
* **Held-out TEST (327):** accuracy **79.82%**, **human recall 67.0%** (75/112), nonhuman 86.5% (186/215).
* **Finding:** Hits the ~700 ms latency target (resolution knob) but human recall fell to 67% — lower resolution worsens the tiny CNN's already-poor generalization. Confirms the wall: a from-scratch tiny CNN can't be both fast AND accurate on this dataset. The transfer-learning v7.4 (64×64) is ~570 ms AND 92% recall — better on both axes.
* **Artifacts:** deploy version 30. Library: `third_party/ei_arduino_library_gray80_tinycnn_espnn.zip` (ESP-NN on).

## `model_v7.13_gray80_tinycnn_reg_balanced` (tiny CNN — overfitting fixed + recall up)
* **Goal:** remove overfitting AND raise human recall on the from-scratch tiny CNN. Two changes: (1) regularized arch — 3 conv blocks + dropout 0.5 + 40 epochs; (2) human class **augmented to parity** (geometric, → 929 human / 920 nonhuman training).
* **Training:** train≈val (89% / 90%) — **overfitting eliminated** (vs baseline 99% / 88%). INT8 val 91.62%, matrix `[[160,20],[11,179]]`.
* **Held-out TEST (327):** accuracy **85.63%** (was 79.82%), **human recall 75.9%** (85/112, was 67.0% → **+8.9 pts**), nonhuman 90.7% (195/215). 15 humans fell in the uncertain band (threshold-tunable for more recall).
* **Finding:** Best tiny-CNN result. Regularization fixed overfitting; human augmentation + balance lifted recall +9 pts. Still below transfer learning's 92% recall — the from-scratch ceiling — but a strong fully-from-scratch model at ~700 ms / 80×80 / ESP-NN-on.
* **Artifacts:** deploy version 31. Library: `third_party/ei_arduino_library_gray80_tinycnn_reg_espnn.zip` (ESP-NN on — verify no saturation on hardware).

## `model_v7.14_gray80_depthwise` (depthwise-separable tiny CNN — fast + best tiny accuracy)
* **Architecture:** Custom from-scratch CNN via EI **expert mode** — `Conv2D(8) → SeparableConv2D(16) → SeparableConv2D(32) → Flatten → Dropout(0.5) → Dense`, each conv + BatchNorm + MaxPool. 80×80 greyscale, INT8, ESP-NN ENABLED. Balanced data (929/920), class weights. Script: `tools/edge_impulse/retrain_gray80_depthwise_espnn.py`.
* **Why:** SeparableConv2D (depthwise + 1×1 pointwise) cuts conv MACs ~8–10× vs standard Conv2D. Conv MACs ≈ **1.7M** (vs ~42M for 16-32-32 standard, ~17M for 8-16-16). ESP-NN accelerates depthwise/pointwise well on the S1.
* **Validation (INT8):** 92.70%, matrix `[[167,13],[14,176]]`.
* **Held-out TEST (327):** accuracy **86.85%** (284/327) — best of any tiny CNN. Human recall 83.0% (93/112; 13 uncertain), nonhuman 88.8% (191/215).
* **Result:** Best from-scratch tiny model: highest tiny-CNN test accuracy AND ~10–25× fewer MACs than the standard-conv versions → expected ~150–300 ms (vs 1145 ms for the 16-32-32 standard). Verify latency + no ESP-NN saturation on device.
* **Artifacts:** deploy version 33. Library: `third_party/ei_arduino_library_gray80_depthwise_espnn.zip`.
* **⚠️ On-device bias:** with ESP-NN ON, this greyscale depthwise model saturated to "always human" on the ESP32-S1 (cloud test was balanced 86.85% — so it's an ESP-NN depthwise-kernel bug, not the model). Fix = ESP-NN OFF (see v7.15).

## `model_v7.15_rgb80_depthwise_no_espnn` (RGB depthwise, ESP-NN off — bias fixed)
* **Architecture:** Same expert-mode depthwise net (`Conv2D(8) → SeparableConv2D(16) → SeparableConv2D(32)`), but **RGB** 80×80, **ESP-NN DISABLED**. Balanced data (929/920), class weights.
* **Why:** (1) ESP-NN OFF removes the depthwise saturation that made the greyscale model "always human" on device; (2) RGB restores colour cues (lifted human recall in transfer models).
* **Validation (INT8):** 95.41%, matrix `[[170,10],[7,183]]`.
* **Held-out TEST (327):** accuracy **88.38%** (289/327) — **balanced**: human recall **88.4%** (99/112), nonhuman 88.4% (190/215). Bias eliminated.
* **Result:** Best balanced tiny CNN. ESP-NN off + RGB fixed the on-device bias; light (depthwise) so still fast without ESP-NN. Just under the 90% target → v7.16 tries 96×96 for the extra points.
* **Artifacts:** deploy version 34. Library: `third_party/ei_arduino_library_rgb80_depthwise_no_espnn.zip` (RGB, ESP-NN off).

## `model_v7.16_rgb96_depthwise_no_espnn` (★ from-scratch, >90%, balanced, ESP-NN off)
* **Architecture:** Expert-mode depthwise CNN (`Conv2D(8) → SeparableConv2D(16) → SeparableConv2D(32)` + BN/pool → Flatten → Dropout(0.5) → Dense), **96×96 RGB**, INT8, **ESP-NN DISABLED**. Balanced data (929/920), class weights.
* **Validation (INT8):** 93.78%, matrix `[[166,14],[9,181]]`.
* **Held-out TEST (327):** accuracy **90.83%** (297/327) — **>90% target met**. Human recall 87.5% (98/112), nonhuman 92.6% (199/215). Balanced, no bias.
* **Result:** Best from-scratch model — meets every requirement at once: >90% accuracy, balanced (no human bias), custom depthwise architecture (trained from scratch), light (~2.8M conv MACs), and ESP-NN off so no on-device saturation. Bumping 80→96 added the ~2.5 pts needed to cross 90%.
* **Firmware:** RGB sketch (`eagleeye_latency_test` or `hard_negative_capturer`) — reads dims from library, adapts to 96×96. NOT the greyscale runtime sketch.
* **Artifacts:** deploy version 35. Library: `third_party/ei_arduino_library_rgb96_depthwise_no_espnn.zip`. On-device (ESP-NN on): **872 ms, clean** (`Human 0.133 / NonHuman 0.867`).

## `model_v7.17_gray96_depthwise_no_espnn` (greyscale variant of v7.16)
* **Architecture:** Same as v7.16 (expert-mode depthwise→standard Conv2D 8→16→32, Dropout 0.5), but **96×96 GREYSCALE**, INT8, ESP-NN-off build. Balanced data (929/920), class weights.
* **Validation (INT8):** 91.35%, matrix `[[162,18],[14,176]]`.
* **Held-out TEST (327):** accuracy **86.24%** (282/327). Human recall 84.8% (95/112), nonhuman 87.0% (187/215).
* **Result:** ~4.6 pts below the RGB v7.16 (90.83%) — dropping color cost overall accuracy and nonhuman recall. **Under the 90% target.** Worth it only for lower RAM (1-channel) or to reuse the greyscale runtime sketch. Otherwise RGB v7.16 stays the pick. Runs on `eagleeye_ei_runtime_grayscale` unchanged.
* **Artifacts:** deploy version 36. Library: `third_party/ei_arduino_library_gray96_depthwise_no_espnn.zip`.

## `model_v7.10_gray96_mobilenetv1_a1_full_classweighted` (0.1 on FULL data + class weights)
* **Architecture:** MobileNetV1 **0.1**, 16-neuron head, dropout 0.1, **96×96 GREYSCALE**, INT8, no EON, ESP-NN disabled. **Full dataset** (469 human / 920 nonhuman) with `autoClassWeights: True` (human ≈ 2× weight).
* **Validation (INT8):** 91.73%, matrix `[[71,16],[7,184]]`.
* **Held-out TEST (327, INT8):** accuracy **89.30%** (292/327). Human recall 81.3% (91/112), nonhuman 93.5% (201/215). 
* **Finding:** Full data + class weights lifted the 0.1 backbone from 85.9% (v7.9, 400/400 balanced) to **89.3%** — revises the earlier "0.1 caps ~86%" claim (that was small-data/64×64). The 0.1 light model is a viable lightweight option at ~89% IF ~81% human recall is acceptable. The 0.2 backbone still wins on human recall (86–92%).
* **Artifacts:** EI version snapshot **v14**, deployment version 27. Library: `third_party/ei_arduino_library_gray96_mobilenetv1_a1_light_no_espnn.zip` (now the full-data version).

---
**Note:** All models are formatted as INT8 quantized TensorFlow Lite (`.tflite`) files. To deploy to the ESP32, convert with `models/tflite_to_cpp_header.py`.

| Model | Archive header | Typical use |
|-------|----------------|-------------|
| `model_v1.0_baseline.tflite` | `models/model_v1.0_baseline.h` | Production `eagleeye-main` / `firmware/tools/hard_negative_capturer` (v1 baseline header) |
| `model_v6.1_edge_impulse_grayscale.tflite` | `models/model_v6.1_edge_impulse_grayscale.h` | Sketchboard / EI live test (48×48 grayscale) |
| `model_v6.0_edge_impulse_final.tflite` | `models/model_v6.0_edge_impulse_final.h` | Deprecated RGB export (6912-byte input) |
| `model_v7.0_rgb96_mobilenetv1_a2_int8` | `third_party/ei_arduino_library_rgb96_mobilenetv1_a2_no_espnn.zip` | Superseded by v7.1 (retrained on 736 samples) |
| `model_v7.1_rgb96_mobilenetv1_a2_int8_expanded` | `third_party/ei_arduino_library_rgb96_mobilenetv1_a2_no_espnn.zip` | Superseded by v7.2 — expanded but class-imbalanced (EI version 5) |
| `model_v7.2_rgb96_mobilenetv1_a2_int8_balanced` | `third_party/ei_arduino_library_rgb96_mobilenetv1_a2_no_espnn.zip` | Superseded by v7.3 — geometric augmentation balance (EI version 6) |
| `model_v7.3_rgb96_mobilenetv1_a2_int8_classweighted` | `third_party/ei_arduino_library_rgb96_mobilenetv1_a2_no_espnn.zip` | Most accurate (96×96) — class-weighted, val 92.45% / test 92.35% (EI version 7) |
| `model_v7.4_rgb64_mobilenetv1_a2_int8_eon` | `third_party/ei_arduino_library_rgb64_mobilenetv1_a2_eon_no_espnn.zip` | **Current/fast** — 64×64 + EON, test 91.13%, human recall 92%, ~4× lighter, no ESP-NN (EI version 8) |
