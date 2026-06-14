#!/usr/bin/env python3
"""
EagleEye — LOCAL replica of the Edge Impulse training pipeline.
===============================================================

This reproduces, on your own machine, the *exact* model that Edge Impulse
trained and exported as:

    third_party/current_model/ei_arduino_library_rgb96_depthwise_espnn.zip
    (project "final", impulse "EagleEye 96x96 RGB Depthwise CNN human")

What was reverse-engineered from that EI export (model_metadata.h /
model_variables.h / the int8 .tflite) and is matched here 1:1:

  * Input            : 96x96 RGB, pixels normalised to [0,1] (done in the data
                       pipeline, NOT inside the graph — EI does it in its image
                       DSP block, so the Keras graph starts at Conv2D).
  * Architecture     : Conv2D(8,3x3,same,relu) -> MaxPool2x2
                       Conv2D(16,3x3,same,relu) -> MaxPool2x2
                       Conv2D(16,3x3,same,relu) -> MaxPool2x2
                       Flatten(2304) -> Dense(2, softmax)
                       Ops: CONV_2D, MAX_POOL_2D, RESHAPE, FULLY_CONNECTED,
                       SOFTMAX  (identical to EI's tflite-resolver.h).
  * Labels (order)   : 0 = human, 1 = nonhuman   (EI category order).
  * Quantisation     : full int8 (input int8 scale=1/255 zp=-128,
                       output int8 scale=1/256 zp=-128) via a representative
                       dataset of real [0,1] frames — same as EI.
  * Training recipe  : Adam, categorical-crossentropy, batch 32, [0,1] input,
                       EI's image data-augmentation (flip / crop-zoom /
                       brightness), 80/20 validation split.

USER REQUIREMENT honoured here: the dataset is *class-balanced* — we take an
equal number of Human and NonHuman images (min of the two class counts), so the
model is not biased by the 763 vs 1099 imbalance on disk.

Outputs (all under sketchboard/):
    ei_local_int8.tflite                              the deployable int8 model
    ei_local_float.tflite                             float reference
    firmware/eagleeye_local/model_data.h              g_model[] for the firmware
    ei_local_metrics.json                             accuracy / config report

The firmware (firmware/eagleeye_local/eagleeye_local.ino) runs this exact int8
model on the ESP32-CAM through the Edge Impulse SDK *as a TFLM + ESP-NN runtime*
(EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN = 1), giving hardware-accelerated int8.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models

# --------------------------------------------------------------------------- #
#  Config — kept faithful to the Edge Impulse "final" project defaults.
# --------------------------------------------------------------------------- #
SKETCHBOARD = Path(__file__).resolve().parent
DATASET_PATH = SKETCHBOARD / "dataset"
FIRMWARE_DIR = SKETCHBOARD / "firmware" / "eagleeye_local" / "src"

# EI category order is ["human", "nonhuman"]; map our folders onto it so the
# integer label matches the deployed model exactly (0=human, 1=nonhuman).
CLASS_DIRS = {"human": "Humans", "nonhuman": "NonHuman"}
CLASS_ORDER = ["human", "nonhuman"]            # index == training label

IMG_SIZE = 96
CHANNELS = 3
INPUT_SHAPE = (IMG_SIZE, IMG_SIZE, CHANNELS)

BATCH_SIZE = 32
EPOCHS = 100                                   # EI-style cycles + best-val restore
LEARNING_RATE = 0.0005                         # EI image-classification default
VAL_SPLIT = 0.20
SEED = 42

TFLITE_INT8_PATH = SKETCHBOARD / "ei_local_int8.tflite"
TFLITE_FLOAT_PATH = SKETCHBOARD / "ei_local_float.tflite"
HEADER_PATH = FIRMWARE_DIR / "model_data.h"
METRICS_PATH = SKETCHBOARD / "ei_local_metrics.json"

AUTOTUNE = tf.data.AUTOTUNE


# --------------------------------------------------------------------------- #
#  Data — balanced, EI-style preprocessing.
# --------------------------------------------------------------------------- #
def list_balanced_paths() -> tuple[np.ndarray, np.ndarray, int]:
    """Collect an EQUAL number of images per class (min class count)."""
    rng = np.random.default_rng(SEED)
    per_class_paths: dict[str, list[str]] = {}
    for name in CLASS_ORDER:
        folder = DATASET_PATH / CLASS_DIRS[name]
        paths: list[Path] = []
        for pattern in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
            paths.extend(folder.glob(pattern))
        per_class_paths[name] = sorted(str(p) for p in paths)

    counts = {k: len(v) for k, v in per_class_paths.items()}
    n_per_class = min(counts.values())
    print(f"On-disk counts: {counts}  ->  balanced to {n_per_class} per class")

    all_paths: list[str] = []
    all_labels: list[int] = []
    for label, name in enumerate(CLASS_ORDER):
        chosen = list(per_class_paths[name])
        idx = rng.permutation(len(chosen))[:n_per_class]
        for i in idx:
            all_paths.append(chosen[i])
            all_labels.append(label)

    paths = np.array(all_paths)
    labels = np.array(all_labels, dtype=np.int32)
    shuffle = rng.permutation(len(paths))
    return paths[shuffle], labels[shuffle], n_per_class


def decode_and_preprocess(path, label):
    """EI image block: center-square crop -> resize 96x96 -> RGB in [0,1]."""
    raw = tf.io.read_file(path)
    img = tf.io.decode_image(raw, channels=CHANNELS, expand_animations=False)
    img = tf.cast(img, tf.float32)

    shape = tf.shape(img)
    side = tf.minimum(shape[0], shape[1])
    off_y = (shape[0] - side) // 2
    off_x = (shape[1] - side) // 2
    img = tf.image.crop_to_bounding_box(img, off_y, off_x, side, side)
    img = tf.image.resize(img, (IMG_SIZE, IMG_SIZE), method="bilinear")
    img = img / 255.0                          # -> [0,1], exactly like EI
    img.set_shape(INPUT_SHAPE)
    return img, label


def ei_augment(image, label):
    """Edge Impulse's image data-augmentation, applied in the [0,1] domain.

    Mirrors ei_tensorflow's augment_image(): horizontal flip, a small random
    zoom implemented as pad-then-random-crop, and +/- brightness jitter.
    """
    image = tf.image.random_flip_left_right(image)

    factor = tf.random.uniform([], 1.0, 1.2)
    new_h = tf.cast(tf.math.floor(factor * IMG_SIZE), tf.int32)
    new_w = tf.cast(tf.math.floor(factor * IMG_SIZE), tf.int32)
    image = tf.image.resize_with_crop_or_pad(image, new_h, new_w)
    image = tf.image.random_crop(image, size=INPUT_SHAPE)

    image = tf.image.random_brightness(image, max_delta=0.2)
    image = tf.clip_by_value(image, 0.0, 1.0)
    image.set_shape(INPUT_SHAPE)
    return image, label


def build_datasets():
    paths, labels, n_per_class = list_balanced_paths()
    split_at = int(len(paths) * (1.0 - VAL_SPLIT))
    tr_p, va_p = paths[:split_at], paths[split_at:]
    tr_l, va_l = labels[:split_at], labels[split_at:]
    print(f"Split: train={len(tr_p)}  val={len(va_p)}  (balanced, seed={SEED})")

    train_ds = (
        tf.data.Dataset.from_tensor_slices((tr_p, tr_l))
        .shuffle(2048, seed=SEED)
        .map(decode_and_preprocess, num_parallel_calls=AUTOTUNE)
        .map(ei_augment, num_parallel_calls=AUTOTUNE)
        .batch(BATCH_SIZE)
        .prefetch(AUTOTUNE)
    )
    # Un-augmented training set, used only to build the representative dataset.
    rep_ds = (
        tf.data.Dataset.from_tensor_slices((tr_p, tr_l))
        .map(decode_and_preprocess, num_parallel_calls=AUTOTUNE)
        .batch(BATCH_SIZE)
        .prefetch(AUTOTUNE)
    )
    val_ds = (
        tf.data.Dataset.from_tensor_slices((va_p, va_l))
        .map(decode_and_preprocess, num_parallel_calls=AUTOTUNE)
        .batch(BATCH_SIZE)
        .prefetch(AUTOTUNE)
    )
    return train_ds, rep_ds, val_ds, n_per_class


# --------------------------------------------------------------------------- #
#  Model — byte-for-byte the EI graph (no in-graph rescaling).
# --------------------------------------------------------------------------- #
def build_model() -> tf.keras.Model:
    model = models.Sequential(
        [
            layers.Input(shape=INPUT_SHAPE, name="x"),
            layers.Conv2D(8, 3, padding="same", activation="relu", name="conv2d"),
            layers.MaxPooling2D(pool_size=2, strides=2, padding="same",
                                name="max_pooling2d"),
            layers.Conv2D(16, 3, padding="same", activation="relu", name="conv2d_1"),
            layers.MaxPooling2D(pool_size=2, strides=2, padding="same",
                                name="max_pooling2d_1"),
            layers.Conv2D(16, 3, padding="same", activation="relu", name="conv2d_2"),
            layers.MaxPooling2D(pool_size=2, strides=2, padding="same",
                                name="max_pooling2d_2"),
            layers.Flatten(name="flatten"),
            layers.Dense(len(CLASS_ORDER), activation="softmax", name="y_pred"),
        ],
        name="eagleeye_ei_rgb96_cnn",
    )
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=LEARNING_RATE),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
        metrics=["accuracy"],
    )
    return model


# --------------------------------------------------------------------------- #
#  Quantisation + export.
# --------------------------------------------------------------------------- #
def representative_dataset(rep_ds):
    def gen():
        taken = 0
        for images, _ in rep_ds:
            for i in range(images.shape[0]):
                yield [images[i: i + 1]]
                taken += 1
                if taken >= 300:
                    return
    return gen


def convert_int8(model, rep_ds) -> bytes:
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = representative_dataset(rep_ds)
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    return conv.convert()


def convert_float(model) -> bytes:
    return tf.lite.TFLiteConverter.from_keras_model(model).convert()


def eval_int8(tflite_bytes: bytes, val_ds) -> float:
    interp = tf.lite.Interpreter(model_content=tflite_bytes)
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]
    in_scale, in_zp = inp["quantization"]
    correct = total = 0
    for images, labels in val_ds:
        arr = images.numpy()
        labs = labels.numpy()
        for i in range(arr.shape[0]):
            q = np.round(arr[i] / in_scale + in_zp).astype(np.int8)
            interp.set_tensor(inp["index"], q[None, ...])
            interp.invoke()
            pred = int(np.argmax(interp.get_tensor(out["index"])[0]))
            correct += int(pred == int(labs[i]))
            total += 1
    return correct / max(total, 1)


def hex_to_c_array(data: bytes) -> str:
    lines = [
        "// Auto-generated by sketchboard/train_ei_local.py",
        "// EagleEye local int8 model — EI-faithful 96x96 RGB CNN (human/nonhuman).",
        "// Input: int8, normalise pixel/255 then quantise with input scale/zp.",
        "// Output softmax order: [0]=human, [1]=nonhuman.",
        "#ifndef MODEL_DATA_H",
        "#define MODEL_DATA_H",
        "",
        'alignas(16) const unsigned char g_model[] = {',
    ]
    for i in range(0, len(data), 12):
        chunk = ", ".join(f"0x{b:02x}" for b in data[i: i + 12])
        lines.append(f"  {chunk},")
    lines += [
        "};",
        f"const unsigned int g_model_len = {len(data)};",
        "#endif  // MODEL_DATA_H",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
def main():
    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Dataset not found: {DATASET_PATH}")

    train_ds, rep_ds, val_ds, n_per_class = build_datasets()
    model = build_model()
    model.summary()

    early = tf.keras.callbacks.EarlyStopping(
        monitor="val_accuracy", patience=20, restore_best_weights=True, verbose=1
    )
    history = model.fit(
        train_ds, validation_data=val_ds, epochs=EPOCHS,
        callbacks=[early], verbose=2,
    )

    tr_loss, tr_acc = model.evaluate(train_ds, verbose=0)
    va_loss, va_acc = model.evaluate(val_ds, verbose=0)
    print(f"\nKeras float  : train_acc={tr_acc:.4f}  val_acc={va_acc:.4f}")

    print("Converting -> float tflite ...")
    float_bytes = convert_float(model)
    TFLITE_FLOAT_PATH.write_bytes(float_bytes)

    print("Converting -> int8 tflite (full integer, EI-style) ...")
    int8_bytes = convert_int8(model, rep_ds)
    TFLITE_INT8_PATH.write_bytes(int8_bytes)

    # Sanity: confirm the int8 input quant matches EI's (scale 1/255, zp -128).
    interp = tf.lite.Interpreter(model_content=int8_bytes)
    interp.allocate_tensors()
    in_q = interp.get_input_details()[0]["quantization"]
    out_q = interp.get_output_details()[0]["quantization"]
    print(f"int8 input quant : scale={in_q[0]:.8f} zp={in_q[1]}  (EI: 0.00392157, -128)")
    print(f"int8 output quant: scale={out_q[0]:.8f} zp={out_q[1]}  (EI: 0.00390625, -128)")

    int8_acc = eval_int8(int8_bytes, val_ds)
    print(f"int8 val accuracy: {int8_acc:.4f}  (size {len(int8_bytes)} bytes)")

    FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
    HEADER_PATH.write_text(hex_to_c_array(int8_bytes), encoding="utf-8")

    metrics = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "replicates": "Edge Impulse project 'final' (EagleEye 96x96 RGB CNN)",
        "class_order": CLASS_ORDER,
        "balanced_per_class": n_per_class,
        "input": "96x96 RGB, [0,1] normalised",
        "epochs_run": len(history.history["accuracy"]),
        "learning_rate": LEARNING_RATE,
        "keras_train_acc": float(tr_acc),
        "keras_val_acc": float(va_acc),
        "int8_val_acc": float(int8_acc),
        "int8_input_quant": {"scale": float(in_q[0]), "zero_point": int(in_q[1])},
        "int8_output_quant": {"scale": float(out_q[0]), "zero_point": int(out_q[1])},
        "int8_tflite_bytes": len(int8_bytes),
        "tflite_int8_path": str(TFLITE_INT8_PATH),
        "header_path": str(HEADER_PATH),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(f"\nSaved int8 tflite : {TFLITE_INT8_PATH}")
    print(f"Saved firmware hdr: {HEADER_PATH}")
    print(f"Saved metrics     : {METRICS_PATH}")


if __name__ == "__main__":
    np.random.seed(SEED)
    tf.random.set_seed(SEED)
    main()
