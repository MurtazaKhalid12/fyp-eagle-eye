#!/usr/bin/env python3
"""
EagleEye LOCAL — GRAYSCALE variant (1-channel) with black-frame negatives.
===========================================================================

Same CNN topology as train_ei_local.py, but:
  * Input is 96x96 x1 GRAYSCALE (not RGB). Luminance uses the SAME integer
    weights as the firmware: gray = (77*R + 150*G + 29*B) >> 8, then /255.
  * A set of PURE-BLACK frames is added to the NonHuman class so the model
    reliably classifies an all-black image (camera covered / no signal) as
    non-human. The black frames are NOT brightness-augmented, so the model
    learns "all-black frame = non-human" specifically — it does NOT learn
    "any dark scene = non-human" (which would make it miss people in low light).
  * Classes stay balanced: 763 human vs (763 - N_BLACK) real non-human + N_BLACK
    black = 763 non-human.

Architecture (unchanged from the EI-faithful model, only input channels differ):
    Conv2D(8,3x3,same,relu) -> MaxPool2x2
    Conv2D(16,3x3,same,relu) -> MaxPool2x2
    Conv2D(16,3x3,same,relu) -> MaxPool2x2
    Flatten(2304) -> Dense(2, softmax)      # 0=human, 1=nonhuman

Outputs:
    ei_local_gray_int8.tflite
    firmware/eagleeye_local/src/model_data.h    (g_model[] for the firmware)
    ei_local_gray_metrics.json
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models

# This script lives in <repo>/model-training/. Anchor to <repo>/sketchboard/ so
# it reads the same dataset and writes model_data.h to the same firmware folder.
SKETCHBOARD = Path(__file__).resolve().parent.parent / "sketchboard"
DATASET_PATH = SKETCHBOARD / "dataset"
FIRMWARE_DIR = SKETCHBOARD / "firmware" / "eagleeye_local" / "src"

CLASS_DIRS = {"human": "Humans", "nonhuman": "NonHuman"}
CLASS_ORDER = ["human", "nonhuman"]            # index == training label

IMG_SIZE = 96
CHANNELS = 1
INPUT_SHAPE = (IMG_SIZE, IMG_SIZE, CHANNELS)

BATCH_SIZE = 32
EPOCHS = 100
LEARNING_RATE = 0.0005
VAL_SPLIT = 0.20
SEED = 42

PER_CLASS = 763          # balanced count per class (== #human images)
N_BLACK = 100            # pure-black negatives injected into the non-human class
N_REAL_NONHUMAN = PER_CLASS - N_BLACK   # real non-human images used (= 663)

# Firmware luminance weights (must match eagleeye_local main.cpp exactly).
LUMA = (77.0, 150.0, 29.0)   # sum = 256  -> (77R+150G+29B)>>8

TFLITE_INT8_PATH = SKETCHBOARD / "ei_local_gray_int8.tflite"
HEADER_PATH = FIRMWARE_DIR / "model_data.h"
METRICS_PATH = SKETCHBOARD / "ei_local_gray_metrics.json"
AUTOTUNE = tf.data.AUTOTUNE


def list_paths(human_n: int, nonhuman_n: int):
    rng = np.random.default_rng(SEED)
    chosen_paths, chosen_labels = [], []
    targets = {"human": human_n, "nonhuman": nonhuman_n}
    for label, name in enumerate(CLASS_ORDER):
        folder = DATASET_PATH / CLASS_DIRS[name]
        paths = []
        for pat in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
            paths.extend(folder.glob(pat))
        paths = sorted(str(p) for p in paths)
        idx = rng.permutation(len(paths))[: targets[name]]
        for i in idx:
            chosen_paths.append(paths[i])
            chosen_labels.append(label)
    p = np.array(chosen_paths)
    l = np.array(chosen_labels, dtype=np.int32)
    sh = rng.permutation(len(p))
    return p[sh], l[sh]


def decode_gray(path, label):
    """Decode -> center-square crop -> resize 96x96 -> firmware-matched gray [0,1]."""
    raw = tf.io.read_file(path)
    img = tf.io.decode_image(raw, channels=3, expand_animations=False)
    img = tf.cast(img, tf.float32)
    shape = tf.shape(img)
    side = tf.minimum(shape[0], shape[1])
    oy = (shape[0] - side) // 2
    ox = (shape[1] - side) // 2
    img = tf.image.crop_to_bounding_box(img, oy, ox, side, side)
    img = tf.image.resize(img, (IMG_SIZE, IMG_SIZE), method="bilinear")
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    gray = (LUMA[0] * r + LUMA[1] * g + LUMA[2] * b) / 256.0   # [0,255]
    gray = gray / 255.0                                        # [0,1]
    gray = tf.expand_dims(gray, axis=-1)
    gray.set_shape(INPUT_SHAPE)
    return gray, label


def ei_augment(image, label):
    """EI image augmentation, grayscale domain. (Real images only — not black frames.)"""
    image = tf.image.random_flip_left_right(image)
    factor = tf.random.uniform([], 1.0, 1.2)
    nh = tf.cast(tf.math.floor(factor * IMG_SIZE), tf.int32)
    image = tf.image.resize_with_crop_or_pad(image, nh, nh)
    image = tf.image.random_crop(image, size=INPUT_SHAPE)
    image = tf.image.random_brightness(image, max_delta=0.2)
    image = tf.clip_by_value(image, 0.0, 1.0)
    image.set_shape(INPUT_SHAPE)
    return image, label


def build_datasets():
    paths, labels = list_paths(human_n=PER_CLASS, nonhuman_n=N_REAL_NONHUMAN)
    split = int(len(paths) * (1.0 - VAL_SPLIT))
    tr_p, va_p = paths[:split], paths[split:]
    tr_l, va_l = labels[:split], labels[split:]

    # Pure-black negatives (label = nonhuman = 1).
    black = np.zeros((N_BLACK, IMG_SIZE, IMG_SIZE, CHANNELS), np.float32)
    black_lab = np.ones((N_BLACK,), np.int32)
    bsplit = int(N_BLACK * (1.0 - VAL_SPLIT))
    tr_b, va_b = black[:bsplit], black[bsplit:]
    tr_bl, va_bl = black_lab[:bsplit], black_lab[bsplit:]

    print(f"Real files: train={len(tr_p)} val={len(va_p)} | "
          f"black: train={len(tr_b)} val={len(va_b)}")
    print(f"Balance: human={PER_CLASS}  nonhuman={N_REAL_NONHUMAN}+{N_BLACK} black "
          f"= {N_REAL_NONHUMAN + N_BLACK}")

    tr_files = tf.data.Dataset.from_tensor_slices((tr_p, tr_l)).map(decode_gray, AUTOTUNE)
    va_files = tf.data.Dataset.from_tensor_slices((va_p, va_l)).map(decode_gray, AUTOTUNE)
    tr_black = tf.data.Dataset.from_tensor_slices((tr_b, tr_bl))
    va_black = tf.data.Dataset.from_tensor_slices((va_b, va_bl))

    train_ds = (tr_files.map(ei_augment, AUTOTUNE)
                .concatenate(tr_black)
                .shuffle(2048, seed=SEED)
                .batch(BATCH_SIZE).prefetch(AUTOTUNE))
    rep_ds = (tr_files.concatenate(tr_black).batch(BATCH_SIZE).prefetch(AUTOTUNE))
    val_ds = (va_files.concatenate(va_black).batch(BATCH_SIZE).prefetch(AUTOTUNE))
    return train_ds, rep_ds, val_ds


def build_model() -> tf.keras.Model:
    model = models.Sequential([
        layers.Input(shape=INPUT_SHAPE, name="x"),
        layers.Conv2D(8, 3, padding="same", activation="relu", name="conv2d"),
        layers.MaxPooling2D(2, 2, padding="same", name="max_pooling2d"),
        layers.Conv2D(16, 3, padding="same", activation="relu", name="conv2d_1"),
        layers.MaxPooling2D(2, 2, padding="same", name="max_pooling2d_1"),
        layers.Conv2D(16, 3, padding="same", activation="relu", name="conv2d_2"),
        layers.MaxPooling2D(2, 2, padding="same", name="max_pooling2d_2"),
        layers.Flatten(name="flatten"),
        layers.Dense(len(CLASS_ORDER), activation="softmax", name="y_pred"),
    ], name="eagleeye_gray_cnn")
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=LEARNING_RATE),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(),
        metrics=["accuracy"],
    )
    return model


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


def eval_int8(tflite_bytes, val_ds):
    interp = tf.lite.Interpreter(model_content=tflite_bytes)
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]
    s, z = inp["quantization"]
    correct = total = 0
    for images, labels in val_ds:
        a = images.numpy(); lb = labels.numpy()
        for i in range(a.shape[0]):
            q = np.round(a[i] / s + z).astype(np.int8)
            interp.set_tensor(inp["index"], q[None, ...])
            interp.invoke()
            pred = int(np.argmax(interp.get_tensor(out["index"])[0]))
            correct += int(pred == int(lb[i])); total += 1
    return correct / max(total, 1), inp, out


def predict_black(tflite_bytes):
    """Feed a pure-black frame; return (human_prob, nonhuman_prob)."""
    interp = tf.lite.Interpreter(model_content=tflite_bytes)
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]
    s, z = inp["quantization"]
    black = np.zeros(INPUT_SHAPE, np.float32)
    q = np.round(black / s + z).astype(np.int8)
    interp.set_tensor(inp["index"], q[None, ...])
    interp.invoke()
    os_, oz = out["quantization"]
    o = interp.get_tensor(out["index"])[0].astype(np.int32)
    probs = (o - oz) * os_
    return float(probs[0]), float(probs[1])


def hex_to_c_array(data: bytes) -> str:
    lines = [
        "// Auto-generated by sketchboard/train_local_gray.py",
        "// EagleEye local int8 model — 96x96 GRAYSCALE CNN (human/nonhuman).",
        "// Input: int8, 1 channel. Firmware luma = (77R+150G+29B)>>8 then /255,",
        "// quantised with the model input scale/zp. Black frame -> nonhuman.",
        "// Output softmax order: [0]=human, [1]=nonhuman.",
        "#ifndef MODEL_DATA_H",
        "#define MODEL_DATA_H",
        "",
        "alignas(16) const unsigned char g_model[] = {",
    ]
    for i in range(0, len(data), 12):
        lines.append("  " + ", ".join(f"0x{b:02x}" for b in data[i:i + 12]) + ",")
    lines += ["};", f"const unsigned int g_model_len = {len(data)};",
              "#endif  // MODEL_DATA_H", ""]
    return "\n".join(lines)


def main():
    train_ds, rep_ds, val_ds = build_datasets()
    model = build_model()
    model.summary()

    early = tf.keras.callbacks.EarlyStopping(
        monitor="val_accuracy", patience=20, restore_best_weights=True, verbose=1)
    hist = model.fit(train_ds, validation_data=val_ds, epochs=EPOCHS,
                     callbacks=[early], verbose=2)

    _, tr_acc = model.evaluate(train_ds, verbose=0)
    _, va_acc = model.evaluate(val_ds, verbose=0)
    print(f"\nKeras float: train_acc={tr_acc:.4f} val_acc={va_acc:.4f}")

    print("Converting -> int8 (full integer) ...")
    int8_bytes = convert_int8(model, rep_ds)
    TFLITE_INT8_PATH.write_bytes(int8_bytes)

    int8_acc, inp, out = eval_int8(int8_bytes, val_ds)
    h_blk, nh_blk = predict_black(int8_bytes)
    print(f"int8 val acc: {int8_acc:.4f}  | input {inp['shape']} "
          f"scale={inp['quantization'][0]:.8f} zp={inp['quantization'][1]}")
    print(f"BLACK-FRAME test -> human={h_blk:.3f}  nonhuman={nh_blk:.3f}  "
          f"=> {'NONHUMAN OK' if nh_blk > h_blk else 'WARNING: predicts human!'}")

    FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
    HEADER_PATH.write_text(hex_to_c_array(int8_bytes), encoding="utf-8")

    metrics = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "variant": "grayscale-1ch + pure-black negatives",
        "class_order": CLASS_ORDER,
        "per_class": PER_CLASS, "n_black": N_BLACK, "n_real_nonhuman": N_REAL_NONHUMAN,
        "luma_weights": LUMA,
        "epochs_run": len(hist.history["accuracy"]),
        "keras_train_acc": float(tr_acc), "keras_val_acc": float(va_acc),
        "int8_val_acc": float(int8_acc),
        "black_frame_human": h_blk, "black_frame_nonhuman": nh_blk,
        "int8_input_quant": {"scale": float(inp["quantization"][0]),
                              "zero_point": int(inp["quantization"][1])},
        "int8_tflite_bytes": len(int8_bytes),
        "header_path": str(HEADER_PATH),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"\nSaved int8 tflite: {TFLITE_INT8_PATH}")
    print(f"Saved firmware hdr: {HEADER_PATH}")
    print(f"Saved metrics:     {METRICS_PATH}")


if __name__ == "__main__":
    np.random.seed(SEED)
    tf.random.set_seed(SEED)
    main()
