"""
============================================================
 EagleEye Voice — YAMNet transfer-learning trainer
============================================================
 Trains a 3-class sound classifier (background / footsteps / glass)
 on top of Google's YAMNet (AudioSet, MobileNetV1) embeddings.

 Why YAMNet: pretrained on AudioSet (which contains "glass", "walk/footsteps",
 ambient sounds), MobileNet-class so it runs on a phone (Pixel 7a), TFLite-
 friendly, and transfer-learns well from little data. We freeze YAMNet and only
 train a small dense "head" on its 1024-d embeddings.

 Pipeline:
   wav -> mono 16 kHz -> YAMNet -> per-0.96s-frame 1024-d embedding
        -> dense head -> {background, footsteps, glass}

 Anti-leakage: the train/test split is done at the FILE level BEFORE expanding
 to frames, so frames of one clip never appear in both train and test.

 Outputs (in ./out): head.keras, head_int8? no -> head_float.tflite,
   labels.txt, metrics.txt, confusion_matrix.png
============================================================
"""
import os, sys, glob, gc, json
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from math import gcd

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import tensorflow as tf
import tensorflow_hub as hub
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, f1_score
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------- config ----------------
HERE      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.abspath(os.path.join(HERE, "..", "dataset"))
OUT_DIR   = os.path.join(HERE, "out")
CLASSES   = ["background", "footsteps", "glass"]   # folder name -> class
TARGET_SR = 16000
MAX_CLIP_SEC = 5.0          # skip the big merged source files
TEST_FRAC = 0.20
SEED = 1337

os.makedirs(OUT_DIR, exist_ok=True)
np.random.seed(SEED)
tf.random.set_seed(SEED)

# ---------------- load YAMNet ----------------
print("[*] Loading YAMNet from TF-Hub (first run downloads ~17 MB)...")
yamnet = hub.load("https://tfhub.dev/google/yamnet/1")
print("[*] YAMNet ready.")

def load_wav_16k_mono(path):
    """Read a wav, downmix to mono, resample to 16 kHz float32 in [-1,1]."""
    x, sr = sf.read(path, dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != TARGET_SR:
        g = gcd(TARGET_SR, sr)
        x = resample_poly(x, TARGET_SR // g, sr // g).astype(np.float32)
    return x, len(x) / TARGET_SR

RNG = np.random.default_rng(SEED)

def embed_wav(wav):
    """YAMNet per-frame embeddings (T,1024) for a 16 kHz mono waveform."""
    if wav.size < TARGET_SR // 2:                 # pad clips < 0.5s
        wav = np.pad(wav, (0, TARGET_SR // 2 - wav.size))
    _, emb, _ = yamnet(tf.constant(wav.astype(np.float32)))
    return emb.numpy()

def embed(path):
    wav, _ = load_wav_16k_mono(path)
    return embed_wav(wav)

def aug_variants(wav):
    """TRAIN-only augmentation so the model generalizes instead of memorizing the
       single source recording: original + 2 noise levels + time-shift + gain.
       (No new recordings needed.)"""
    outs = [wav]
    rms = float(np.sqrt(np.mean(wav ** 2)) + 1e-9)
    for snr_db in (20.0, 10.0):                                       # white noise at 20 & 10 dB SNR
        n = RNG.normal(0, 1, wav.shape).astype(np.float32)
        n *= rms / (np.sqrt(np.mean(n ** 2)) + 1e-9) / (10 ** (snr_db / 20.0))
        outs.append(wav + n)
    outs.append(np.roll(wav, int(RNG.uniform(0.05, 0.30) * len(wav))))  # circular time shift
    outs.append(wav * float(RNG.uniform(0.6, 1.4)))                     # random gain
    return [np.clip(o, -1.0, 1.0).astype(np.float32) for o in outs]

# ---------------- gather files (skip merged source files) ----------------
def gather(cls):
    files = glob.glob(os.path.join(DATA_DIR, cls, "**", "*.wav"), recursive=True)
    keep = []
    for f in files:
        name = os.path.basename(f).lower()
        if any(k in name for k in ("merged", "reduced", "normal")):
            continue
        try:
            info = sf.info(f)
            if info.frames / info.samplerate > MAX_CLIP_SEC:
                continue
        except Exception:
            continue
        keep.append(f)
    return keep

paths, labels = [], []
for ci, cls in enumerate(CLASSES):
    fs = gather(cls)
    paths += fs
    labels += [ci] * len(fs)
    print(f"[data] {cls:10} {len(fs)} clips")
labels = np.array(labels)
print(f"[data] total {len(paths)} clips")

# ---------------- file-level stratified split (no frame leakage) ----------------
tr_paths, te_paths, tr_lab, te_lab = train_test_split(
    paths, labels, test_size=TEST_FRAC, stratify=labels, random_state=SEED)
print(f"[split] train clips={len(tr_paths)}  test clips={len(te_paths)}")

# ---------------- expand to frame embeddings ----------------
def build_train(paths_, labels_):
    X, y = [], []
    for p, lab in zip(paths_, labels_):
        wav, _ = load_wav_16k_mono(p)
        for v in aug_variants(wav):                # augment TRAIN for robustness
            e = embed_wav(v)
            X.append(e); y.append(np.full(len(e), lab, dtype=np.int64))
    return np.concatenate(X), np.concatenate(y)

print("[*] Extracting YAMNet embeddings for TRAIN (with augmentation) ...")
Xtr, ytr = build_train(tr_paths, tr_lab)
print(f"    train frames (augmented): {Xtr.shape}")
print("[*] Extracting YAMNet embeddings for TEST ...")
# keep per-clip grouping for clip-level metrics
te_clip_emb = [embed(p) for p in te_paths]
Xte = np.concatenate(te_clip_emb)
yte = np.concatenate([np.full(len(e), l, dtype=np.int64) for e, l in zip(te_clip_emb, te_lab)])
print(f"    test frames: {Xte.shape}")

# ---------------- class weights (handle imbalance) ----------------
counts = np.bincount(ytr, minlength=len(CLASSES))
cw = {i: float(len(ytr) / (len(CLASSES) * c)) if c else 1.0 for i, c in enumerate(counts)}
print(f"[*] train frame counts={counts.tolist()}  class_weights={ {k: round(v,2) for k,v in cw.items()} }")

# ---------------- the classifier head (regularized to avoid overfitting) ----------------
#  - small capacity (one hidden layer) so it can't memorize
#  - L2 weight decay on every dense layer
#  - dropout on the input embedding AND the hidden layer
#  - lower LR + tight early stopping with best-weight restore
reg = tf.keras.regularizers.l2(5e-4)
head = tf.keras.Sequential([
    tf.keras.layers.Input(shape=(1024,), name="yamnet_embedding"),
    tf.keras.layers.Dropout(0.2),                                              # input dropout
    tf.keras.layers.Dense(256, activation="relu", kernel_regularizer=reg),
    tf.keras.layers.Dropout(0.5),
    tf.keras.layers.Dense(128, activation="relu", kernel_regularizer=reg),
    tf.keras.layers.Dropout(0.3),
    tf.keras.layers.Dense(len(CLASSES), activation="softmax", kernel_regularizer=reg),
], name="eagleeye_sound_head")
head.compile(optimizer=tf.keras.optimizers.Adam(5e-4),
             loss="sparse_categorical_crossentropy", metrics=["accuracy"])

cb = [
    tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=14, restore_best_weights=True),
    tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=5, min_lr=1e-5),
]
print("[*] Training head (augmented data) ...")
head.fit(Xtr, ytr, validation_split=0.15, epochs=150, batch_size=128,
         class_weight=cw, callbacks=cb, verbose=2)

# ---------------- evaluate (frame-level + clip-level) ----------------
def report(y_true, y_pred, title):
    print(f"\n================ {title} ================")
    rep = classification_report(y_true, y_pred, target_names=CLASSES, digits=4)
    print(rep)
    cm = confusion_matrix(y_true, y_pred)
    print("confusion matrix (rows=true, cols=pred):\n", cm)
    return rep, cm

# frame level
frame_pred = head.predict(Xte, verbose=0).argmax(1)
frep, fcm = report(yte, frame_pred, "FRAME-LEVEL (test)")

# clip level: average frame probabilities per clip
clip_pred, clip_true = [], list(te_lab)
for e in te_clip_emb:
    probs = head.predict(e, verbose=0).mean(axis=0)
    clip_pred.append(int(probs.argmax()))
crep, ccm = report(np.array(clip_true), np.array(clip_pred), "CLIP-LEVEL (test) <-- real-world metric")
clip_f1 = f1_score(clip_true, clip_pred, average="weighted")
print(f"\n[RESULT] clip-level weighted F1 = {clip_f1:.4f}")

# ---------------- save artifacts ----------------
head.save(os.path.join(OUT_DIR, "head.keras"))
with open(os.path.join(OUT_DIR, "labels.txt"), "w") as f:
    f.write("\n".join(CLASSES))

# TFLite (head only: input = 1024-d YAMNet embedding)
conv = tf.lite.TFLiteConverter.from_keras_model(head)
conv.optimizations = [tf.lite.Optimize.DEFAULT]
tfl = conv.convert()
with open(os.path.join(OUT_DIR, "head_float.tflite"), "wb") as f:
    f.write(tfl)

# confusion-matrix figure (clip level)
fig, ax = plt.subplots(figsize=(4.5, 4))
im = ax.imshow(ccm, cmap="Greens")
ax.set_xticks(range(len(CLASSES))); ax.set_yticks(range(len(CLASSES)))
ax.set_xticklabels(CLASSES, rotation=30, ha="right"); ax.set_yticklabels(CLASSES)
ax.set_xlabel("predicted"); ax.set_ylabel("true"); ax.set_title("Clip-level confusion")
for i in range(len(CLASSES)):
    for j in range(len(CLASSES)):
        ax.text(j, i, ccm[i, j], ha="center", va="center",
                color="white" if ccm[i, j] > ccm.max()/2 else "black")
fig.tight_layout(); fig.savefig(os.path.join(OUT_DIR, "confusion_matrix.png"), dpi=130)

with open(os.path.join(OUT_DIR, "metrics.txt"), "w") as f:
    f.write("EagleEye Voice - YAMNet transfer learning\n\n")
    f.write(f"classes: {CLASSES}\n")
    f.write(f"train clips: {len(tr_paths)}  test clips: {len(te_paths)}\n\n")
    f.write("== FRAME-LEVEL ==\n" + frep + "\n")
    f.write("== CLIP-LEVEL ==\n" + crep + "\n")
    f.write(f"clip-level weighted F1: {clip_f1:.4f}\n")

print(f"\n[*] Saved: {OUT_DIR}\\head.keras, head_float.tflite, labels.txt, metrics.txt, confusion_matrix.png")
print("[*] Deployment note: on the Pixel 7a, run YAMNet (TFLite) to get the 1024-d")
print("    embedding, then this head_float.tflite to classify. (Two small TFLite models.)")
