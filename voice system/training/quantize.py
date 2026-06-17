"""
Quantize the trained head to several sizes and measure the accuracy cost.
Answers: "does reducing model size reduce accuracy?" with real numbers.
Outputs head_{float32,float16,dynamic,int8}.tflite in ./out and prints a table.
"""
import os, glob, numpy as np, soundfile as sf
from math import gcd
from scipy.signal import resample_poly
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import tensorflow as tf, tensorflow_hub as hub
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score, accuracy_score

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, "..", "dataset"))
OUT  = os.path.join(HERE, "out")
CLASSES = ["background", "footsteps", "glass"]
SR, SEED, MAXSEC = 16000, 1337, 5.0

print("[*] loading YAMNet + head ...")
yam  = hub.load("https://tfhub.dev/google/yamnet/1")
head = tf.keras.models.load_model(os.path.join(OUT, "head.keras"))

def load(p):
    x, sr = sf.read(p, dtype="float32", always_2d=False)
    if x.ndim > 1: x = x.mean(1)
    if sr != SR:
        g = gcd(SR, sr); x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    if x.size < SR // 2: x = np.pad(x, (0, SR // 2 - x.size))
    return x

def emb(p):
    _, e, _ = yam(tf.constant(load(p))); return e.numpy()

def gather(c):
    keep = []
    for f in glob.glob(os.path.join(DATA, c, "**", "*.wav"), recursive=True):
        n = os.path.basename(f).lower()
        if any(k in n for k in ("merged", "reduced", "normal")): continue
        try:
            i = sf.info(f)
            if i.frames / i.samplerate > MAXSEC: continue
        except Exception: continue
        keep.append(f)
    return keep

paths, labels = [], []
for ci, c in enumerate(CLASSES):
    fs = gather(c); paths += fs; labels += [ci] * len(fs)
labels = np.array(labels)
trp, tep, trl, tel = train_test_split(paths, labels, test_size=0.2, stratify=labels, random_state=SEED)
print(f"[*] embedding test clips ({len(tep)}) ...")
te_clip = [emb(p) for p in tep]
print("[*] embedding representative train sample ...")
rep = np.concatenate([emb(p) for p in trp[:60]]).astype(np.float32)

def eval_keras():
    preds = [int(head.predict(e, verbose=0).mean(0).argmax()) for e in te_clip]
    return accuracy_score(tel, preds), f1_score(tel, preds, average="weighted")

def convert(mode):
    c = tf.lite.TFLiteConverter.from_keras_model(head)
    if mode == "float16":
        c.optimizations = [tf.lite.Optimize.DEFAULT]; c.target_spec.supported_types = [tf.float16]
    elif mode == "dynamic":
        c.optimizations = [tf.lite.Optimize.DEFAULT]
    elif mode == "int8":
        c.optimizations = [tf.lite.Optimize.DEFAULT]
        c.representative_dataset = lambda: ([r[None, :].astype(np.float32)] for r in rep[:300])
        c.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        c.inference_input_type = tf.float32; c.inference_output_type = tf.float32
    return c.convert()

def eval_tflite(b):
    it = tf.lite.Interpreter(model_content=b); it.allocate_tensors()
    inp, out = it.get_input_details()[0], it.get_output_details()[0]
    def frames(e):
        ps = []
        for fr in e:
            it.set_tensor(inp["index"], fr[None, :].astype(np.float32)); it.invoke()
            ps.append(it.get_tensor(out["index"])[0])
        return np.mean(ps, 0)
    preds = [int(frames(e).argmax()) for e in te_clip]
    return accuracy_score(tel, preds), f1_score(tel, preds, average="weighted")

ba, bf = eval_keras()
print(f"\n  Keras head (float32 in RAM)  baseline       acc={ba:.4f}  F1={bf:.4f}")
print("  ---------------------------------------------------------------")
print(f"  {'variant':10} {'size':>9}   {'accuracy':>9}  {'weighted F1':>11}")
for mode in ["float32", "float16", "dynamic", "int8"]:
    b = convert(mode); kb = len(b) / 1024
    a, f = eval_tflite(b)
    open(os.path.join(OUT, f"head_{mode}.tflite"), "wb").write(b)
    print(f"  {mode:10} {kb:7.1f}KB   {a:9.4f}  {f:11.4f}")
print("\n[*] wrote head_float32/float16/dynamic/int8 .tflite to out/")
