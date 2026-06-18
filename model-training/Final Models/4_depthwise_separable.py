#!/usr/bin/env python3


from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
HUMAN_DIRS = [
    REPO / "datasets/Human_Detection_Dataset/Human_Detection_Dataset_4/Human_Detection_Dataset/Humans",
    REPO / "datasets/augmented_humans_geometric",
]
NONHUMAN_DIRS = [
    REPO / "datasets/Human_Detection_Dataset/Human_Detection_Dataset_4/Human_Detection_Dataset/NonHuman",
]
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp"}
OUT_DIR = REPO / "model-training" / "exported-models"
SEED = 42


def list_images(dirs):
    files = []
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.suffix.lower() in IMG_EXT and "esp32_injected_v" not in p.name.lower():
                files.append(p)
    return sorted(set(files))


def load_xy(img_size):
    human, nonhuman = list_images(HUMAN_DIRS), list_images(NONHUMAN_DIRS)
    print(f"images: human={len(human)}  nonhuman={len(nonhuman)}")
    X, y = [], []
    for label, files in ((1, human), (0, nonhuman)):  # 1=human, 0=nonhuman
        for p in files:
            try:
                im = Image.open(p).convert("RGB").resize((img_size, img_size), Image.BILINEAR)
            except Exception:
                continue
            X.append(np.asarray(im, dtype=np.uint8)); y.append(label)
    return np.array(X, dtype=np.uint8), np.array(y, dtype=np.int64)


def stratified_split(y, test_frac, rng):
    """Return (train_idx, test_idx) stratified by class."""
    tr, te = [], []
    for c in np.unique(y):
        idx = np.where(y == c)[0]; rng.shuffle(idx)
        n_te = int(round(len(idx) * test_frac))
        te += idx[:n_te].tolist(); tr += idx[n_te:].tolist()
    rng.shuffle(tr); rng.shuffle(te)
    return np.array(tr), np.array(te)


def class_weights(y):
    n = len(y); k = len(np.unique(y))
    return {int(c): n / (k * int((y == c).sum())) for c in np.unique(y)}


def confusion(y_true, y_pred):
    # rows/cols ordered [human(1), nonhuman(0)]
    order = [1, 0]
    return [[int(((y_true == t) & (y_pred == p)).sum()) for p in order] for t in order]


def build_model(img_size, arch):
    Conv = layers.SeparableConv2D if arch == "separable" else layers.Conv2D
    return models.Sequential([
        layers.Input((img_size, img_size, 3)),
        layers.Rescaling(1.0 / 255),
        layers.RandomFlip("horizontal", seed=SEED),
        layers.RandomRotation(0.08, seed=SEED),
        layers.RandomZoom(0.1, seed=SEED),
        layers.Conv2D(8, 3, padding="same", activation="relu"),
        layers.BatchNormalization(), layers.MaxPooling2D(),
        Conv(16, 3, padding="same", activation="relu"),
        layers.BatchNormalization(), layers.MaxPooling2D(),
        Conv(32, 3, padding="same", activation="relu"),
        layers.BatchNormalization(), layers.MaxPooling2D(),
        layers.Flatten(),
        layers.Dropout(0.1),
        layers.Dense(2, activation="softmax", name="y_pred"),
    ])


def to_int8_tflite(keras_model, X_repr, img_size):
    infer = models.Sequential(
        [layers.Input((img_size, img_size, 3))] +
        [l for l in keras_model.layers
         if not isinstance(l, (layers.RandomFlip, layers.RandomRotation, layers.RandomZoom))])
    infer.set_weights(keras_model.get_weights())
    conv = tf.lite.TFLiteConverter.from_keras_model(infer)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    def rep():
        for i in range(min(200, len(X_repr))):
            yield [X_repr[i:i + 1].astype(np.float32)]
    conv.representative_dataset = rep
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    return conv.convert()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", type=int, default=96)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=0.0005)
    ap.add_argument("--arch", choices=("standard", "separable"), default="standard")
    ap.add_argument("--test-split", type=float, default=0.15)
    ap.add_argument("--val-split", type=float, default=0.15)
    ap.add_argument("--export-header", action="store_true")
    args = ap.parse_args()

    tf.random.set_seed(SEED); np.random.seed(SEED)
    rng = np.random.default_rng(SEED)

    X, y = load_xy(args.img)
    if len(X) == 0:
        raise SystemExit("No images found — check dataset paths.")
    tr, te = stratified_split(y, args.test_split, rng)
    X_tr, y_tr, X_te, y_te = X[tr], y[tr], X[te], y[te]
    val_frac_of_train = args.val_split / (1.0 - args.test_split)
    n_val = int(round(len(X_tr) * val_frac_of_train))
    n_train = len(X_tr) - n_val
    print(f"train={n_train}  val={n_val}  test={len(X_te)}  (human frac train={y_tr.mean():.2f})")

    cw = class_weights(y_tr)
    print(f"class weights (0=nonhuman,1=human): {cw}")

    model = build_model(args.img, args.arch)
    model.compile(optimizer=tf.keras.optimizers.Adam(args.lr),
                  loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    cb = [tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=12, restore_best_weights=True)]
    model.fit(X_tr, y_tr, validation_split=val_frac_of_train, epochs=args.epochs,
              batch_size=args.batch, class_weight=cw, callbacks=cb, verbose=2)

    pf = model.predict(X_te, verbose=0).argmax(1)
    print(f"\nFLOAT test accuracy: {(pf == y_te).mean() * 100:.2f}%")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tfl = to_int8_tflite(model, X_tr, args.img)
    tfl_path = OUT_DIR / f"eagleeye_v716_local_{args.arch}_{args.img}_int8.tflite"
    tfl_path.write_bytes(tfl)

    interp = tf.lite.Interpreter(model_content=tfl); interp.allocate_tensors()
    inp, out = interp.get_input_details()[0], interp.get_output_details()[0]
    s, zp = inp["quantization"]
    preds = []
    for img in X_te:
        q = np.clip(np.round(img.astype(np.float32) / (s if s else 1) + zp), -128, 127).astype(np.int8)
        interp.set_tensor(inp["index"], q[None, ...]); interp.invoke()
        preds.append(int(interp.get_tensor(out["index"])[0].argmax()))
    preds = np.array(preds)
    acc = (preds == y_te).mean()
    cm = confusion(y_te, preds)
    hr = cm[0][0] / max(1, (cm[0][0] + cm[0][1]))
    print(f"INT8  test accuracy: {acc * 100:.2f}%")
    print(f"INT8  confusion [human,nonhuman] rows=true: {cm}")
    print(f"INT8  human recall: {hr * 100:.1f}%")
    print(f"\nSaved: {tfl_path}  ({len(tfl):,} bytes)")

    if args.export_header:
        import subprocess, sys
        h = tfl_path.with_suffix(".h")
        subprocess.run([sys.executable, str(REPO / "models" / "tflite_to_cpp_header.py"),
                        str(tfl_path), str(h)], check=False)
        print(f"Header: {h}")


if __name__ == "__main__":
    main()
