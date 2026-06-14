#!/usr/bin/env python3
"""
Evaluate the locally-trained int8 model (ei_local_int8.tflite) on the SAME
balanced validation split used by train_ei_local.py, and report a full set of
metrics: accuracy, confusion matrix, and per-class / macro precision, recall, F1.

Reuses train_ei_local's split + preprocessing so the val set is identical
(same seed, same balancing, same 80/20 cut).
"""
from __future__ import annotations

import numpy as np
import tensorflow as tf

from train_ei_local import (
    list_balanced_paths, decode_and_preprocess,
    VAL_SPLIT, BATCH_SIZE, AUTOTUNE, CLASS_ORDER, TFLITE_INT8_PATH,
)


def build_val_ds():
    paths, labels, _ = list_balanced_paths()
    split_at = int(len(paths) * (1.0 - VAL_SPLIT))
    va_p, va_l = paths[split_at:], labels[split_at:]
    ds = (
        tf.data.Dataset.from_tensor_slices((va_p, va_l))
        .map(decode_and_preprocess, num_parallel_calls=AUTOTUNE)
        .batch(BATCH_SIZE)
        .prefetch(AUTOTUNE)
    )
    return ds, len(va_p)


def predict_all(ds):
    interp = tf.lite.Interpreter(model_path=str(TFLITE_INT8_PATH))
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]
    in_scale, in_zp = inp["quantization"]
    y_true, y_pred = [], []
    for images, labels in ds:
        arr = images.numpy()
        labs = labels.numpy()
        for i in range(arr.shape[0]):
            q = np.round(arr[i] / in_scale + in_zp).astype(np.int8)
            interp.set_tensor(inp["index"], q[None, ...])
            interp.invoke()
            y_pred.append(int(np.argmax(interp.get_tensor(out["index"])[0])))
            y_true.append(int(labs[i]))
    return np.array(y_true), np.array(y_pred)


def main():
    ds, n = build_val_ds()
    y_true, y_pred = predict_all(ds)
    n_cls = len(CLASS_ORDER)

    # Confusion matrix: rows = true, cols = pred
    cm = np.zeros((n_cls, n_cls), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[t, p] += 1

    acc = (y_true == y_pred).mean()
    print(f"\nValidation samples: {n}   (balanced human/nonhuman)")
    print(f"Overall accuracy  : {acc:.4f}\n")

    print("Confusion matrix (rows=true, cols=pred):")
    header = "            " + "".join(f"{c:>10}" for c in CLASS_ORDER)
    print(header)
    for i, c in enumerate(CLASS_ORDER):
        print(f"{c:>10}  " + "".join(f"{cm[i, j]:>10}" for j in range(n_cls)))
    print()

    print(f"{'class':>10} {'precision':>10} {'recall':>10} {'f1':>10} {'support':>9}")
    precs, recs, f1s, sups = [], [], [], []
    for i, c in enumerate(CLASS_ORDER):
        tp = cm[i, i]
        fp = cm[:, i].sum() - tp
        fn = cm[i, :].sum() - tp
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        sup = cm[i, :].sum()
        precs.append(prec); recs.append(rec); f1s.append(f1); sups.append(sup)
        print(f"{c:>10} {prec:>10.4f} {rec:>10.4f} {f1:>10.4f} {sup:>9}")

    macro_f1 = float(np.mean(f1s))
    w = np.array(sups) / max(sum(sups), 1)
    weighted_f1 = float(np.sum(np.array(f1s) * w))
    print(f"\n{'macro avg':>10} {np.mean(precs):>10.4f} {np.mean(recs):>10.4f} {macro_f1:>10.4f} {sum(sups):>9}")
    print(f"{'weighted':>10} {np.sum(np.array(precs)*w):>10.4f} {np.sum(np.array(recs)*w):>10.4f} {weighted_f1:>10.4f} {sum(sups):>9}")

    h = CLASS_ORDER.index("human")
    print(f"\n[human / intruder detection]  precision={precs[h]:.4f}  "
          f"recall={recs[h]:.4f}  f1={f1s[h]:.4f}")


if __name__ == "__main__":
    main()
