#!/usr/bin/env python3
"""
Retrain EagleEye's sketchboard human/non-human model until both training and
validation accuracy pass 90%, then export the model for the sketchboard hard
negative capturer.

Everything written by this script stays under sketchboard/.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models


SKETCHBOARD = Path(__file__).resolve().parent
DATASET_PATH = SKETCHBOARD / "dataset"
FIRMWARE_DIR = SKETCHBOARD / "firmware" / "hard_negative_capturer"

IMG_HEIGHT = 48
IMG_WIDTH = 48
BATCH_SIZE = 32
EPOCHS = 120
TARGET_ACCURACY = 0.90
SEED = 123

MODEL_BASENAME = "sketchboard_hard_negative_90plus"
TFLITE_PATH = SKETCHBOARD / f"{MODEL_BASENAME}.tflite"
HEADER_PATH = SKETCHBOARD / "human_detect_model_data.h"
FIRMWARE_HEADER_PATH = FIRMWARE_DIR / "human_detect_model_data.h"
METRICS_PATH = SKETCHBOARD / f"{MODEL_BASENAME}_metrics.json"


class StopAtTarget(tf.keras.callbacks.Callback):
    def __init__(self, target: float):
        super().__init__()
        self.target = target
        self.reached = False
        self.best_epoch = None

    def on_epoch_end(self, epoch: int, logs=None):
        logs = logs or {}
        acc = float(logs.get("accuracy", 0.0))
        val_acc = float(logs.get("val_accuracy", 0.0))
        if acc >= self.target and val_acc >= self.target:
            self.reached = True
            self.best_epoch = epoch + 1
            print(
                f"\nTarget reached at epoch {epoch + 1}: "
                f"accuracy={acc:.4f}, val_accuracy={val_acc:.4f}"
            )
            self.model.stop_training = True


def build_datasets():
    class_names = sorted(p.name for p in DATASET_PATH.iterdir() if p.is_dir())
    image_paths = []
    labels = []
    for label, class_name in enumerate(class_names):
        class_dir = DATASET_PATH / class_name
        paths = []
        for pattern in ("*.jpg", "*.jpeg", "*.png"):
            paths.extend(class_dir.glob(pattern))
        image_paths.extend(str(path) for path in sorted(paths))
        labels.extend([label] * len(paths))

    rng = np.random.default_rng(SEED)
    indices = rng.permutation(len(image_paths))
    image_paths = np.array(image_paths)[indices]
    labels = np.array(labels, dtype=np.int32)[indices]
    split_at = int(len(image_paths) * 0.8)

    train_paths, val_paths = image_paths[:split_at], image_paths[split_at:]
    train_labels, val_labels = labels[:split_at], labels[split_at:]

    print(f"Classes: {class_names}")
    print(f"Samples: train={len(train_paths)}, val={len(val_paths)}, total={len(image_paths)}")

    def load_like_firmware(path, label):
        image_bytes = tf.io.read_file(path)
        image = tf.io.decode_image(image_bytes, channels=3, expand_animations=False)
        image = tf.cast(image, tf.float32)

        shape = tf.shape(image)
        height = shape[0]
        width = shape[1]
        side = tf.minimum(height, width)
        offset_y = (height - side) // 2
        offset_x = (width - side) // 2
        image = tf.image.crop_to_bounding_box(image, offset_y, offset_x, side, side)
        image = tf.image.resize(image, (IMG_HEIGHT, IMG_WIDTH), method="bilinear")

        # Same luminance weights used in firmware: (r*77 + g*150 + b*29) >> 8.
        r, g, b = image[..., 0], image[..., 1], image[..., 2]
        gray = (r * 77.0 + g * 150.0 + b * 29.0) / 256.0
        gray = tf.expand_dims(gray, axis=-1)
        return gray, label

    train_ds = tf.data.Dataset.from_tensor_slices((train_paths, train_labels))
    val_ds = tf.data.Dataset.from_tensor_slices((val_paths, val_labels))

    autotune = tf.data.AUTOTUNE
    return (
        train_ds.shuffle(1024, seed=SEED).map(load_like_firmware, num_parallel_calls=autotune).batch(BATCH_SIZE).cache().prefetch(autotune),
        val_ds.map(load_like_firmware, num_parallel_calls=autotune).batch(BATCH_SIZE).cache().prefetch(autotune),
        class_names,
    )


def build_ultratiny_model(num_classes: int) -> tf.keras.Model:
    # Augmentation intentionally changes geometry only: rotation + zoom.
    data_augmentation = tf.keras.Sequential(
        [
            layers.RandomRotation(0.12),
            layers.RandomZoom(height_factor=0.18, width_factor=0.18),
        ],
        name="geometry_only_augmentation",
    )

    model = models.Sequential(
        [
            layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1)),
            layers.Rescaling(1.0 / 127.5, offset=-1.0),
            data_augmentation,
            layers.Conv2D(16, 3, strides=2, padding="same", activation="relu"),
            layers.MaxPooling2D(),
            layers.Conv2D(32, 3, strides=2, padding="same", activation="relu"),
            layers.MaxPooling2D(),
            layers.Conv2D(64, 3, padding="same", activation="relu"),
            layers.GlobalAveragePooling2D(),
            layers.Dropout(0.2447),
            layers.Dense(num_classes, activation="softmax"),
        ],
        name="eagleeye_ultratiny_geometry_aug",
    )

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.003234),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
        metrics=["accuracy"],
    )
    return model


def representative_data_gen(train_ds):
    for images, _ in train_ds.take(100):
        for i in range(images.shape[0]):
            yield [tf.cast(images[i : i + 1], tf.float32)]


def convert_to_int8_tflite(model: tf.keras.Model, train_ds) -> bytes:
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = lambda: representative_data_gen(train_ds)
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    return converter.convert()


def hex_to_c_array(data: bytes, var_name: str) -> str:
    guard = f"{var_name.upper()}_H"
    lines = [
        "// Auto-generated in sketchboard by retrain_to_90.py",
        "// Geometry-only augmentation: rotation and zoom. No colour/lightness changes.",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        f"extern const unsigned char {var_name}[];",
        f"extern const unsigned int {var_name}_len;",
        "",
        f"const unsigned char {var_name}[] = {{",
    ]
    for i in range(0, len(data), 12):
        chunk = ", ".join(f"0x{b:02x}" for b in data[i : i + 12])
        lines.append(f"  {chunk},")
    lines.extend(
        [
            "};",
            f"const unsigned int {var_name}_len = {len(data)};",
            f"#endif  // {guard}",
            "",
        ]
    )
    return "\n".join(lines)


def main():
    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Sketchboard dataset not found: {DATASET_PATH}")

    train_ds, val_ds, class_names = build_datasets()
    model = build_ultratiny_model(num_classes=len(class_names))
    model.summary()

    target_cb = StopAtTarget(TARGET_ACCURACY)
    early_stop = tf.keras.callbacks.EarlyStopping(
        monitor="val_accuracy",
        patience=25,
        restore_best_weights=True,
        verbose=1,
    )

    history = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=EPOCHS,
        callbacks=[target_cb, early_stop],
        verbose=1,
    )

    final_train_loss, final_train_acc = model.evaluate(train_ds, verbose=0)
    final_val_loss, final_val_acc = model.evaluate(val_ds, verbose=0)
    target_met = final_train_acc >= TARGET_ACCURACY and final_val_acc >= TARGET_ACCURACY

    print(
        f"Final Keras metrics: accuracy={final_train_acc:.4f}, "
        f"val_accuracy={final_val_acc:.4f}"
    )
    if not target_met:
        raise RuntimeError(
            "Target not met. Nothing exported. "
            f"accuracy={final_train_acc:.4f}, val_accuracy={final_val_acc:.4f}"
        )

    print("Converting to int8 TFLite...")
    tflite_model = convert_to_int8_tflite(model, train_ds)
    TFLITE_PATH.write_bytes(tflite_model)

    header = hex_to_c_array(tflite_model, "g_human_detect_model_data")
    HEADER_PATH.write_text(header, encoding="utf-8")
    FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
    FIRMWARE_HEADER_PATH.write_text(header, encoding="utf-8")

    metrics = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(DATASET_PATH),
        "class_names": class_names,
        "preprocessing": "firmware-match center square crop, 48x48 resize, grayscale 77/150/29",
        "target_accuracy": TARGET_ACCURACY,
        "target_met": target_met,
        "train_accuracy": float(final_train_acc),
        "train_loss": float(final_train_loss),
        "val_accuracy": float(final_val_acc),
        "val_loss": float(final_val_loss),
        "stopped_at_epoch": target_cb.best_epoch or len(history.history["accuracy"]),
        "tflite_path": str(TFLITE_PATH),
        "header_path": str(HEADER_PATH),
        "firmware_header_path": str(FIRMWARE_HEADER_PATH),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(f"Saved TFLite: {TFLITE_PATH}")
    print(f"Saved header: {HEADER_PATH}")
    print(f"Attached header to firmware: {FIRMWARE_HEADER_PATH}")
    print(f"Saved metrics: {METRICS_PATH}")


if __name__ == "__main__":
    np.random.seed(SEED)
    tf.random.set_seed(SEED)
    main()
