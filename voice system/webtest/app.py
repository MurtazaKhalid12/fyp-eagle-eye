"""
============================================================
 EagleEye Sound Detector — test website
============================================================
 A small Flask web app to TEST the trained sound model
 (YAMNet embeddings -> trained head) from a browser:
   - record 3 s from your mic, or
   - upload a .wav
 ...and see live confidence bars for background / footsteps / glass.

 Run:   python app.py     ->  open http://127.0.0.1:5000
 (Loads YAMNet + voice system/training/out/head.keras)
============================================================
"""
import os, io
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import numpy as np
import soundfile as sf
from math import gcd
from scipy.signal import resample_poly
import tensorflow as tf
import tensorflow_hub as hub
from flask import Flask, request, jsonify

HERE   = os.path.dirname(os.path.abspath(__file__))
HEAD   = os.path.abspath(os.path.join(HERE, "..", "training", "out", "head.keras"))
LABELS = os.path.abspath(os.path.join(HERE, "..", "training", "out", "labels.txt"))
SR = 16000

print("[*] Loading YAMNet (Google AudioSet, pretrained) ...")
yamnet = hub.load("https://tfhub.dev/google/yamnet/1")
CLASSES = ["background", "footsteps", "glass"]
PRETTY = {"background": "Background", "footsteps": "Footsteps", "glass": "Glass Break"}
print("[*] Loading retrained head (head.keras, augmented) ...")
head = tf.keras.models.load_model(HEAD)
print("[*] Ready - retrained head (default) + pretrained YAMNet (toggle).")

app = Flask(__name__)

def to_16k_mono(raw_bytes):
    x, sr = sf.read(io.BytesIO(raw_bytes), dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != SR:
        g = gcd(SR, sr)
        x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    if x.size < SR // 2:
        x = np.pad(x, (0, SR // 2 - x.size))
    return x

# --- Zero-training: read YAMNet's own AudioSet class scores and "lock on" only
#     the ones we need. Nothing is trained on local data. ---
GLASS_IDX = [435, 437, 464, 436, 434]   # Glass, Shatter, Breaking, Chink/clink, Crack
FOOT_IDX  = [48, 46, 47]                # Walk/footsteps, Run, Shuffle

def classify_pretrained(x):
    scores, _, _ = yamnet(tf.constant(x))
    s = scores.numpy().mean(axis=0)
    g  = float(s[GLASS_IDX].max())
    f  = float(s[FOOT_IDX].max())
    bg = max(0.0, 1.0 - max(g, f))
    tot = g + f + bg + 1e-9
    return {"background": bg / tot, "footsteps": f / tot, "glass": g / tot}

def classify_head(x):
    """Your locally-trained (augmented) head on YAMNet embeddings."""
    _, emb, _ = yamnet(tf.constant(x))
    probs = head.predict(emb.numpy(), verbose=0).mean(axis=0)
    return {CLASSES[i]: float(probs[i]) for i in range(len(CLASSES))}

def classify(x, mode="trained"):
    return classify_head(x) if mode == "trained" else classify_pretrained(x)

@app.route("/")
def index():
    return INDEX_HTML

@app.route("/predict", methods=["POST"])
def predict():
    if "audio" not in request.files:
        return jsonify({"error": "no audio"}), 400
    try:
        mode = request.form.get("mode", "trained")
        x = to_16k_mono(request.files["audio"].read())
        probs = classify(x, mode)
        top = max(probs, key=probs.get)
        return jsonify({"probs": probs, "top": top, "top_pretty": PRETTY.get(top, top),
                        "top_conf": probs[top]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

INDEX_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EagleEye Sound Detector</title>
<style>
:root{--bg:#0b1220;--card:#131c31;--line:#243150;--txt:#e7eefc;--mut:#90a0c0;
      --bgc:#38bdf8;--foot:#f59e0b;--glass:#22c55e;}
*{box-sizing:border-box;font-family:'Segoe UI',system-ui,sans-serif}
body{margin:0;background:radial-gradient(1200px 600px at 50% -10%,#16223e,var(--bg));color:var(--txt);min-height:100vh}
.wrap{max-width:560px;margin:0 auto;padding:28px 18px 60px}
h1{font-weight:800;letter-spacing:.3px;margin:.2em 0 .1em;font-size:28px}
.sub{color:var(--mut);margin-bottom:22px;font-size:14px}
.logo{font-size:13px;color:var(--bgc);font-weight:700;letter-spacing:2px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px;margin-bottom:18px;
       box-shadow:0 10px 40px rgba(0,0,0,.35)}
.recbtn{width:130px;height:130px;border-radius:50%;border:0;cursor:pointer;font-size:16px;font-weight:800;
        color:#04121f;background:linear-gradient(145deg,#38bdf8,#22d3ee);box-shadow:0 0 0 0 rgba(56,189,248,.6);
        transition:transform .15s,box-shadow .2s;margin:6px auto;display:block}
.recbtn:active{transform:scale(.96)}
.recbtn.rec{background:linear-gradient(145deg,#ef4444,#f97316);animation:pulse 1s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(239,68,68,.5)}70%{box-shadow:0 0 0 22px rgba(239,68,68,0)}100%{box-shadow:0 0 0 0 rgba(239,68,68,0)}}
.status{text-align:center;color:var(--mut);min-height:20px;margin-top:10px;font-size:14px}
.up{display:flex;align-items:center;gap:10px;justify-content:center;color:var(--mut);font-size:14px;margin-top:8px}
.up input{display:none}
.up label{color:var(--bgc);cursor:pointer;font-weight:700;text-decoration:underline}
.modes{display:flex;gap:18px;justify-content:center;margin-top:14px;color:var(--mut);font-size:13px}
.modes label{cursor:pointer} .modes input{accent-color:var(--bgc);margin-right:4px}
.verdict{text-align:center;font-size:22px;font-weight:800;margin:4px 0 18px;min-height:28px}
.row{margin:14px 0}
.row .top{display:flex;justify-content:space-between;font-size:14px;margin-bottom:6px}
.row .name{font-weight:700}
.bar{height:14px;background:#0c1426;border-radius:10px;overflow:hidden;border:1px solid var(--line)}
.fill{height:100%;width:0;border-radius:10px;transition:width .4s ease}
.f-background{background:var(--bgc)} .f-footsteps{background:var(--foot)} .f-glass{background:var(--glass)}
.c-background{color:var(--bgc)} .c-footsteps{color:var(--foot)} .c-glass{color:var(--glass)}
.foot{color:var(--mut);font-size:12px;text-align:center;margin-top:18px}
</style></head>
<body><div class="wrap">
  <div class="logo">EAGLEEYE</div>
  <h1>Sound Detector</h1>
  <div class="sub">Tap <b>Start Listening</b> and the model listens to your mic <b>continuously</b>, updating live &mdash; Background, Footsteps, or Glass Break. (Or upload a .wav.)</div>

  <div class="panel">
    <button id="rec" class="recbtn">Start<br>Listening</button>
    <div class="status" id="status">Ready.</div>
    <div class="up">or <label for="file">upload a .wav</label><input id="file" type="file" accept=".wav,audio/wav"></div>
    <div class="modes">
      <label><input type="radio" name="mode" value="trained" checked> Trained (97%, augmented)</label>
      <label><input type="radio" name="mode" value="pretrained"> Pretrained YAMNet</label>
    </div>
  </div>

  <div class="panel">
    <div class="verdict" id="verdict">—</div>
    <div class="row"><div class="top"><span class="name c-background">Background</span><span id="p-background">0%</span></div><div class="bar"><div class="fill f-background" id="b-background"></div></div></div>
    <div class="row"><div class="top"><span class="name c-footsteps">Footsteps</span><span id="p-footsteps">0%</span></div><div class="bar"><div class="fill f-footsteps" id="b-footsteps"></div></div></div>
    <div class="row"><div class="top"><span class="name c-glass">Glass Break</span><span id="p-glass">0%</span></div><div class="bar"><div class="fill f-glass" id="b-glass"></div></div></div>
  </div>

  <div class="foot">Trained head (local, augmented, ~97%) + pretrained YAMNet &bull; pick above</div>
</div>
<script>
const PRETTY={background:"Background",footsteps:"Footsteps",glass:"Glass Break"};
const $=id=>document.getElementById(id);
const getMode=()=>(document.querySelector('input[name=mode]:checked')||{value:'pretrained'}).value;
function setStatus(t){$("status").innerText=t;}
function render(d){
  const probs=d.probs;
  for(const k of ["background","footsteps","glass"]){
    const pct=Math.round((probs[k]||0)*100);
    $("p-"+k).innerText=pct+"%"; $("b-"+k).style.width=pct+"%";
  }
  $("verdict").innerHTML='Detected: <span class="c-'+d.top+'">'+d.top_pretty+'</span> — '+Math.round(d.top_conf*100)+'%';
}
async function send(blob){
  setStatus("Analyzing...");
  const fd=new FormData(); fd.append("audio",blob,"clip.wav"); fd.append("mode",getMode());
  try{
    const r=await fetch("/predict",{method:"POST",body:fd});
    const d=await r.json();
    if(d.error){setStatus("Error: "+d.error);return;}
    render(d); setStatus("Done.");
  }catch(e){setStatus("Request failed: "+e);}
}
// ---- file upload ----
$("file").addEventListener("change",e=>{ if(e.target.files[0]) send(e.target.files[0]); });
// ---- shared WAV helpers ----
function flatten(chunks){let n=chunks.reduce((a,c)=>a+c.length,0),o=new Float32Array(n),i=0;for(const c of chunks){o.set(c,i);i+=c.length;}return o;}
function encodeWAV(samples,sr){
  const buf=new ArrayBuffer(44+samples.length*2),v=new DataView(buf);
  const w=(o,s)=>{for(let i=0;i<s.length;i++)v.setUint8(o+i,s.charCodeAt(i));};
  w(0,"RIFF");v.setUint32(4,36+samples.length*2,true);w(8,"WAVE");w(12,"fmt ");
  v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);
  v.setUint32(24,sr,true);v.setUint32(28,sr*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);
  w(36,"data");v.setUint32(40,samples.length*2,true);
  let o=44;for(let i=0;i<samples.length;i++){let s=Math.max(-1,Math.min(1,samples[i]));v.setInt16(o,s<0?s*0x8000:s*0x7FFF,true);o+=2;}
  return new Blob([v],{type:"audio/wav"});
}
// ---- CONTINUOUS listening: a rolling ~1s window is classified a few times/sec ----
const WINDOW_SEC=1.0, HOP_MS=600;
let listening=false, ctx=null, proc=null, src=null, micStream=null, ring=[], ringLen=0, inflight=false, timer=null, ema=null;
function pushSamples(buf){
  ring.push(buf); ringLen+=buf.length;
  const maxLen=Math.ceil(ctx.sampleRate*(WINDOW_SEC+0.4));
  while(ringLen>maxLen && ring.length>1){ ringLen-=ring[0].length; ring.shift(); }
}
function lastWindow(){
  const need=Math.floor(ctx.sampleRate*WINDOW_SEC), all=flatten(ring);
  return all.length<=need ? all : all.slice(all.length-need);
}
function renderSmooth(probs){
  if(!ema) ema=Object.assign({},probs); else for(const k in probs) ema[k]=0.5*ema[k]+0.5*probs[k];
  let top=Object.keys(ema).reduce((a,b)=>ema[a]>=ema[b]?a:b);
  for(const k of ["background","footsteps","glass"]){const pct=Math.round((ema[k]||0)*100);$("p-"+k).innerText=pct+"%";$("b-"+k).style.width=pct+"%";}
  $("verdict").innerHTML='Hearing: <span class="c-'+top+'">'+PRETTY[top]+'</span> &mdash; '+Math.round(ema[top]*100)+'%';
}
async function tick(){
  if(!listening||inflight) return;
  const win=lastWindow();
  if(win.length < ctx.sampleRate*0.4) return;          // need ~0.4s before first guess
  inflight=true;
  const fd=new FormData(); fd.append("audio",encodeWAV(win,ctx.sampleRate),"clip.wav"); fd.append("mode",getMode());
  try{ const r=await fetch("/predict",{method:"POST",body:fd}); const d=await r.json(); if(!d.error) renderSmooth(d.probs); }catch(e){}
  inflight=false;
}
async function startListen(){
  try{micStream=await navigator.mediaDevices.getUserMedia({audio:true});}
  catch(e){setStatus("Mic blocked. Open http://127.0.0.1:5000 and allow the mic.");return;}
  ctx=new (window.AudioContext||window.webkitAudioContext)();
  src=ctx.createMediaStreamSource(micStream);
  proc=ctx.createScriptProcessor(4096,1,1);
  const mute=ctx.createGain();mute.gain.value=0;       // no echo to speakers
  ring=[];ringLen=0;ema=null;listening=true;
  proc.onaudioprocess=e=>{ if(listening) pushSamples(new Float32Array(e.inputBuffer.getChannelData(0))); };
  src.connect(proc);proc.connect(mute);mute.connect(ctx.destination);
  $("rec").classList.add("rec");$("rec").innerHTML="Stop";setStatus("Listening live — make a sound");
  timer=setInterval(tick,HOP_MS);
}
function stopListen(){
  listening=false; if(timer)clearInterval(timer); timer=null;
  try{proc.disconnect();src.disconnect();micStream.getTracks().forEach(t=>t.stop());ctx.close();}catch(e){}
  $("rec").classList.remove("rec");$("rec").innerHTML="Start<br>Listening";setStatus("Stopped.");
}
$("rec").addEventListener("click",()=> listening ? stopListen() : startListen());
</script></body></html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
