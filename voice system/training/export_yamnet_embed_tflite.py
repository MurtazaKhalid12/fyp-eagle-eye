"""
============================================================
 Export YAMNet's embedding frontend to a mobile-runnable TFLite
============================================================
 Produces out/yamnet_embed.tflite:
    input  : float32 waveform [15600]  (one ~0.975 s YAMNet frame @ 16 kHz, [-1,1])
    output : float32 embedding [1, 1024]

 This is the SAME 1024-d embedding the trained head (head_int8.tflite) was
 trained on, so on the phone the chain is:

    mic PCM 16 kHz -> yamnet_embed.tflite -> head_int8.tflite -> {bg, footsteps, glass}

 IMPORTANT: it converts with TFLITE_BUILTINS only (NO Select-TF / Flex ops),
 so it runs under react-native-fast-tflite's standard runtime on the phone.

 Run:  python export_yamnet_embed_tflite.py
 then copy out/yamnet_embed.tflite + out/head_int8.tflite into
      mobile-app/assets/models/
============================================================
"""
import os, glob
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
import numpy as np
import soundfile as sf
from math import gcd
from scipy.signal import resample_poly
import tensorflow as tf
import tensorflow_hub as hub

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
DATA = os.path.abspath(os.path.join(HERE, "..", "dataset"))
SR, WIN = 16000, 15600
CLASSES = ["background", "footsteps", "glass"]
os.makedirs(OUT, exist_ok=True)

print("[*] loading YAMNet from TF-Hub ...")
yamnet = hub.load("https://tfhub.dev/google/yamnet/1")


class Embed(tf.Module):
    """Wrap YAMNet so it takes a fixed 15600-sample frame and returns the 1024-d embedding."""
    def __init__(self, m):
        super().__init__()
        self.m = m

    @tf.function(input_signature=[tf.TensorSpec([WIN], tf.float32)])
    def __call__(self, waveform):
        _scores, embeddings, _spec = self.m(waveform)   # embeddings: [frames, 1024]
        return {"embedding": embeddings}


mod = Embed(yamnet)
print("[*] embedding shape for WIN=%d ->" % WIN, mod(tf.zeros([WIN], tf.float32))["embedding"].shape)

conv = tf.lite.TFLiteConverter.from_concrete_functions(
    [mod.__call__.get_concrete_function()], mod)
conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]   # no Flex
tflite = conv.convert()
path = os.path.join(OUT, "yamnet_embed.tflite")
open(path, "wb").write(tflite)
print("[*] wrote %s  (%d KB, builtins-only)" % (path, len(tflite) // 1024))

# ---- sanity check: yamnet_embed.tflite -> head_int8.tflite on one clip per class ----
head_path = os.path.join(OUT, "head_int8.tflite")
if os.path.exists(head_path):
    def load(p):
        x, sr = sf.read(p, dtype="float32", always_2d=False)
        if x.ndim > 1:
            x = x.mean(1)
        if sr != SR:
            g = gcd(SR, sr); x = resample_poly(x, SR // g, sr // g).astype(np.float32)
        return x

    def window(x):
        if x.size >= WIN:
            s = (x.size - WIN) // 2
            return x[s:s + WIN].astype(np.float32)
        return np.pad(x, (0, WIN - x.size)).astype(np.float32)

    yi = tf.lite.Interpreter(path); yi.allocate_tensors()
    yin, yout = yi.get_input_details()[0], yi.get_output_details()[0]
    hi = tf.lite.Interpreter(head_path); hi.allocate_tensors()
    hin, hout = hi.get_input_details()[0], hi.get_output_details()[0]

    def infer(p):
        yi.set_tensor(yin["index"], window(load(p))); yi.invoke()
        emb = yi.get_tensor(yout["index"]).mean(0, keepdims=True).astype(np.float32)
        hi.set_tensor(hin["index"], emb); hi.invoke()
        pr = hi.get_tensor(hout["index"])[0]
        return {CLASSES[i]: round(float(pr[i]), 3) for i in range(3)}

    print("\n[*] chain sanity check (yamnet_embed -> head_int8):")
    for c in CLASSES:
        fs = [f for f in glob.glob(os.path.join(DATA, c, "**", "*.wav"), recursive=True)
              if not any(k in f.lower() for k in ("merged", "reduced", "normal"))]
        if fs:
            print("    [%-10s] %-26s -> %s" % (c, os.path.basename(fs[0]), infer(fs[0])))
    print("\n[*] copy out/yamnet_embed.tflite + out/head_int8.tflite -> mobile-app/assets/models/")
else:
    print("[!] head_int8.tflite not found in out/ — run quantize.py first to get the head.")
