#!/usr/bin/env python3
"""
EagleEye — Knowledge Distillation Training Script
===================================================
Phase 2: A large MobileNetV2 teacher transfers learned probability
distributions ("dark knowledge") to our lightweight student CNN.

WHY KNOWLEDGE DISTILLATION:
  The Simple CNN (Phase 1) hit 67-76% recall at 48x48 grayscale.
  Instead of making the model bigger (which the ESP32 can't run),
  we train a small student model using a big teacher's knowledge.

  The teacher (MobileNetV2) was trained on 1.4 million ImageNet images
  and already knows how to identify shapes, textures, and objects.
  By softening its output probabilities (temperature scaling), it
  shares inter-class similarity information ("dark knowledge") that
  hard 0/1 labels throw away.

HOW IT WORKS:
  1. Teacher (MobileNetV2, frozen) produces soft predictions at temperature T
  2. Student (tiny CNN 8->16->16) learns from both:
     - Hard labels: real ground truth (weighted by alpha)
     - Soft labels: teacher's softened output (weighted by 1-alpha)
  3. Loss = alpha * CE(hard) + (1-alpha) * T^2 * KL(teacher_soft || student_soft)

OPTUNA HYPERPARAMETER SEARCH (50 trials) found:
  Temperature T = 9.23    (very soft — teacher shares maximum uncertainty)
  Alpha       = 0.378     (trusts teacher 62% more than ground truth)
  Learning rate = 0.0015

RESULT:
  Validation accuracy: 91.77% with 98.44% human recall
  HOWEVER: Did not generalize to real ESP32-CAM frames because 48x48
  grayscale input cannot capture the spatial detail the teacher described.
  This motivated the resolution increase to 96x96 RGB in Phase 3.

NOTE: This script was originally run on Edge Impulse cloud. This is the
local reproduction of that pipeline for documentation purposes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models, applications

# --------------------------------------------------------------------------- #
#  Config
# --------------------------------------------------------------------------- #
REPO = Path(__file__).resolve().parent.parent
DATASET_PATH = REPO / "datasets" / "Human_Detection_Dataset" / "Human_Detection_Dataset_4" / "Human_Detection_Dataset"

IMG_SIZE = 48                       # 48x48 — the resolution bottleneck
CHANNELS = 1                       # Grayscale — another bottleneck
INPUT_SHAPE = (IMG_SIZE, IMG_SIZE, CHANNELS)
CLASS_ORDER = ["Humans", "NonHuman"]

BATCH_SIZE = 32
EPOCHS = 100
SEED = 42

# Optuna-found hyperparameters (50 trials)
TEMPERATURE = 9.23                  # High T = teacher shares maximum uncertainty
ALPHA = 0.378                       # Trust teacher (62%) > ground truth (38%)
LEARNING_RATE = 0.0015

VAL_SPLIT = 0.20


# --------------------------------------------------------------------------- #
#  Data loading
# --------------------------------------------------------------------------- #
def load_datasets():
    """Load 48x48 grayscale images with 80/20 split."""
    train_ds = tf.keras.utils.image_dataset_from_directory(
        str(DATASET_PATH),
        validation_split=VAL_SPLIT,
        subset="training",
        seed=SEED,
        image_size=(IMG_SIZE, IMG_SIZE),
        batch_size=BATCH_SIZE,
        color_mode="grayscale",
        shuffle=True,
    )
    val_ds = tf.keras.utils.image_dataset_from_directory(
        str(DATASET_PATH),
        validation_split=VAL_SPLIT,
        subset="validation",
        seed=SEED,
        image_size=(IMG_SIZE, IMG_SIZE),
        batch_size=BATCH_SIZE,
        color_mode="grayscale",
    )

    class_names = train_ds.class_names
    print(f"Classes: {class_names}")
    print(f"  0 = {class_names[0]}, 1 = {class_names[1]}")

    # Normalize to [0, 1]
    normalize = layers.Rescaling(1.0 / 255)
    train_ds = train_ds.map(lambda x, y: (normalize(x), y))
    val_ds = val_ds.map(lambda x, y: (normalize(x), y))

    AUTOTUNE = tf.data.AUTOTUNE
    train_ds = train_ds.cache().prefetch(AUTOTUNE)
    val_ds = val_ds.cache().prefetch(AUTOTUNE)

    return train_ds, val_ds, class_names


# --------------------------------------------------------------------------- #
#  Teacher — MobileNetV2 (frozen, pretrained on ImageNet)
# --------------------------------------------------------------------------- #
def build_teacher() -> tf.keras.Model:
    """Large MobileNetV2 teacher. Grayscale input is tiled to 3 channels
    because MobileNetV2 expects RGB."""
    base = applications.MobileNetV2(
        input_shape=(IMG_SIZE, IMG_SIZE, 3),
        alpha=1.0,
        include_top=False,
        weights="imagenet",
        pooling="avg",
    )
    base.trainable = False  # Freeze — teacher never learns

    inp = layers.Input(shape=INPUT_SHAPE, name="teacher_input")
    # Tile grayscale to 3 channels for MobileNetV2
    x = layers.Concatenate()([inp, inp, inp])
    x = base(x, training=False)
    x = layers.Dense(2, name="teacher_logits")(x)  # Raw logits (no softmax)
    return models.Model(inp, x, name="teacher")


# --------------------------------------------------------------------------- #
#  Student — Tiny CNN (the model we actually deploy to ESP32)
# --------------------------------------------------------------------------- #
def build_student() -> tf.keras.Model:
    """Tiny CNN: Conv2D(8) -> Conv2D(16) -> Conv2D(16) -> Dense(2).
    Same architecture as Phase 1 Simple CNN."""
    inp = layers.Input(shape=INPUT_SHAPE, name="student_input")
    x = layers.Conv2D(8, 3, padding="same", activation="relu")(inp)
    x = layers.MaxPooling2D(2)(x)
    x = layers.Conv2D(16, 3, padding="same", activation="relu")(x)
    x = layers.MaxPooling2D(2)(x)
    x = layers.Conv2D(16, 3, padding="same", activation="relu")(x)
    x = layers.MaxPooling2D(2)(x)
    x = layers.Flatten()(x)
    logits = layers.Dense(2, name="student_logits")(x)  # Raw logits (no softmax)
    return models.Model(inp, logits, name="student")


# --------------------------------------------------------------------------- #
#  Distillation Trainer
# --------------------------------------------------------------------------- #
class Distiller(tf.keras.Model):
    """Custom training loop that combines hard-label CE + soft-label KL."""

    def __init__(self, teacher, student, temperature, alpha):
        super().__init__()
        self.teacher = teacher
        self.student = student
        self.T = temperature
        self.alpha = alpha

    def compile(self, optimizer, **kwargs):
        super().compile(optimizer=optimizer, **kwargs)
        self.ce_loss = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True)
        self.kl_loss = tf.keras.losses.KLDivergence()

    def train_step(self, data):
        images, labels = data

        # Teacher forward pass (no gradient — frozen)
        teacher_logits = self.teacher(images, training=False)
        teacher_soft = tf.nn.softmax(teacher_logits / self.T)

        with tf.GradientTape() as tape:
            # Student forward pass
            student_logits = self.student(images, training=True)
            student_soft = tf.nn.softmax(student_logits / self.T)

            # Loss 1: Hard label cross-entropy (student vs ground truth)
            hard_loss = self.ce_loss(labels, student_logits)

            # Loss 2: KL divergence (student_soft vs teacher_soft)
            # Multiply by T^2 to compensate for gradient scaling
            soft_loss = self.kl_loss(teacher_soft, student_soft) * (self.T ** 2)

            # Combined loss
            # alpha = 0.378 → 38% hard labels, 62% teacher knowledge
            total_loss = self.alpha * hard_loss + (1 - self.alpha) * soft_loss

        # Update student only (teacher is frozen)
        grads = tape.gradient(total_loss, self.student.trainable_variables)
        self.optimizer.apply_gradients(zip(grads, self.student.trainable_variables))

        # Metrics
        student_preds = tf.argmax(student_logits, axis=1)
        accuracy = tf.reduce_mean(tf.cast(
            tf.equal(student_preds, tf.cast(labels, tf.int64)), tf.float32
        ))

        return {
            "loss": total_loss,
            "hard_loss": hard_loss,
            "soft_loss": soft_loss,
            "accuracy": accuracy,
        }

    def test_step(self, data):
        images, labels = data
        student_logits = self.student(images, training=False)
        loss = self.ce_loss(labels, student_logits)
        preds = tf.argmax(student_logits, axis=1)
        accuracy = tf.reduce_mean(tf.cast(
            tf.equal(preds, tf.cast(labels, tf.int64)), tf.float32
        ))
        return {"loss": loss, "accuracy": accuracy}


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    print("=" * 60)
    print("  EagleEye — Knowledge Distillation (Phase 2)")
    print(f"  Temperature = {TEMPERATURE}, Alpha = {ALPHA}")
    print(f"  Input: {IMG_SIZE}x{IMG_SIZE} Grayscale")
    print("=" * 60)

    train_ds, val_ds, class_names = load_datasets()

    print("\n[1] Building teacher (MobileNetV2, frozen, ImageNet) ...")
    teacher = build_teacher()
    teacher.summary()

    print("\n[2] Building student (Tiny CNN 8→16→16) ...")
    student = build_student()
    student.summary()

    print(f"\n[3] Training with distillation (T={TEMPERATURE}, α={ALPHA}) ...")
    distiller = Distiller(teacher, student, TEMPERATURE, ALPHA)
    distiller.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=LEARNING_RATE))

    early = tf.keras.callbacks.EarlyStopping(
        monitor="val_accuracy", patience=20, restore_best_weights=True, verbose=1
    )
    history = distiller.fit(
        train_ds, validation_data=val_ds, epochs=EPOCHS,
        callbacks=[early], verbose=2,
    )

    # Evaluate
    results = distiller.evaluate(val_ds, verbose=0)
    print(f"\nFinal validation: loss={results['loss']:.4f}, accuracy={results['accuracy']:.4f}")

    # Save student model
    out_dir = Path(__file__).resolve().parent
    student_path = out_dir / "kd_student_model.keras"
    student.save(str(student_path))
    print(f"\nSaved student model: {student_path}")

    # Add softmax for deployment
    deploy = models.Sequential([
        student,
        layers.Activation("softmax"),
    ])
    converter = tf.lite.TFLiteConverter.from_keras_model(deploy)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8

    # Representative dataset for quantization
    def representative_dataset():
        for images, _ in train_ds.take(10):
            for i in range(images.shape[0]):
                yield [images[i:i+1].numpy()]

    converter.representative_dataset = representative_dataset
    tflite_bytes = converter.convert()

    tflite_path = out_dir / "kd_student_int8.tflite"
    tflite_path.write_bytes(tflite_bytes)
    print(f"Saved INT8 tflite: {tflite_path} ({len(tflite_bytes)} bytes)")

    print("\n" + "=" * 60)
    print("  RESULT: Validation accuracy ~91.77% (on this distribution)")
    print("  BUT: Does not generalize to real ESP32-CAM frames")
    print("  REASON: 48x48 grayscale cannot capture spatial detail")
    print("          that the teacher's soft labels describe.")
    print("  → This motivated Phase 3: increase to 96x96 RGB")
    print("=" * 60)


if __name__ == "__main__":
    np.random.seed(SEED)
    tf.random.set_seed(SEED)
    main()
