// ============================================================
//  EagleEye relay — Deno Deploy version (free, no card, always-on)
// ============================================================
//  Paste this whole file into a Deno Deploy *Playground*
//  (https://dash.deno.com -> New Playground), Save & Deploy.
//  You get a URL like  https://your-name.deno.dev  -> that is your relay.
//
//    camera ->  wss://<host>/cam/<deviceId>?token=...    pushes JPEG frames
//    phone  ->  wss://<host>/view/<deviceId>?token=...   receives frames
//
//  Frames are fanned out to viewers. Because Deno Deploy may run several
//  isolates, we use BroadcastChannel so a camera on one isolate still
//  reaches viewers on another. Stopping the stream is driven by the app
//  over MQTT (cmd stream:false), so the relay stays simple.
//
//  Optional auth: set env var RELAY_SECRET (Playground -> Settings -> Env)
//  to require short-lived HMAC tokens from issueStreamToken. Leave it unset
//  for first bring-up (auth disabled).
// ============================================================

const RELAY_SECRET = Deno.env.get("RELAY_SECRET") ?? "";

// per-isolate state
const localViewers = new Map<string, Set<WebSocket>>();
const localProducer = new Map<string, WebSocket>();
const channels = new Map<string, BroadcastChannel>();

function viewerSet(room: string): Set<WebSocket> {
  let s = localViewers.get(room);
  if (!s) { s = new Set(); localViewers.set(room, s); }
  return s;
}

// One BroadcastChannel per room bridges frames across Deno Deploy isolates.
// Returns null if BroadcastChannel is unavailable (newer deno.net runtime) —
// the relay then still works within a single isolate (fine for 1 cam + 1 viewer).
function getChannel(room: string): BroadcastChannel | null {
  if (typeof BroadcastChannel === "undefined") return null;
  const existing = channels.get(room);
  if (existing) return existing;
  try {
    const ch = new BroadcastChannel(`eagleeye:${room}`);
    ch.onmessage = (ev: MessageEvent) => {
      const m = ev.data;
      if (m?.t === "frame") {
        const vs = localViewers.get(room);
        if (vs) for (const v of vs) { try { if (v.readyState === WebSocket.OPEN) v.send(m.d); } catch { /*drop*/ } }
      }
    };
    channels.set(room, ch);
    return ch;
  } catch {
    return null;   // unsupported -> single-isolate fallback
  }
}

async function verifyToken(token: string, deviceId: string, role: string): Promise<boolean> {
  if (!RELAY_SECRET) return true;                 // auth disabled (dev)
  if (!token) return false;
  const dot = token.lastIndexOf(".");
  if (dot < 0) return false;
  const body = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(RELAY_SECRET),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  const expect = [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
  if (sig !== expect) return false;
  try {
    const p = JSON.parse(atob(body.replace(/-/g, "+").replace(/_/g, "/")));
    if (p.d !== deviceId || p.r !== role) return false;
    if (!p.exp || p.exp < Math.floor(Date.now() / 1000)) return false;
    return true;
  } catch { return false; }
}

// Minimal browser viewer: connects to /view/<id> and shows JPEG frames in an <img>.
function watchPage(id: string): string {
  return `<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>EagleEye ${id}</title><style>body{margin:0;background:#111;color:#ccc;font-family:sans-serif;text-align:center}
img{max-width:100%;height:auto}#s{padding:8px;font-size:14px}</style></head><body>
<div id=s>connecting…</div><img id=v alt="">
<script>
const id=${JSON.stringify(id)};
const proto=location.protocol==='https:'?'wss':'ws';
const ws=new WebSocket(proto+'://'+location.host+'/view/'+id);
ws.binaryType='arraybuffer';
const img=document.getElementById('v'),s=document.getElementById('s');
let url=null,n=0,t=Date.now();
ws.onopen=()=>s.textContent='connected — waiting for frames…';
ws.onclose=()=>s.textContent='closed';
ws.onerror=()=>s.textContent='error';
ws.onmessage=e=>{const b=new Blob([e.data],{type:'image/jpeg'});const u=URL.createObjectURL(b);
img.onload=()=>{if(url)URL.revokeObjectURL(url);url=u;};img.src=u;
n++;if(Date.now()-t>1000){s.textContent='live ~'+n+' fps';n=0;t=Date.now();}};
</script></body></html>`;
}

Deno.serve(async (req: Request) => {
  const url = new URL(req.url);

  if (url.pathname === "/" || url.pathname === "/health") {
    return new Response("EagleEye relay up. Connect via /cam/<id> or /view/<id>.", { status: 200 });
  }

  // Browser test viewer (no app needed): open  https://<host>/watch/<deviceId>
  {
    const wp = url.pathname.split("/").filter(Boolean);
    if (wp.length === 2 && wp[0] === "watch") {
      return new Response(watchPage(wp[1]), { headers: { "content-type": "text/html; charset=utf-8" } });
    }
  }

  const parts = url.pathname.split("/").filter(Boolean);   // ["cam","cam-01"]
  if (parts.length !== 2 || (parts[0] !== "cam" && parts[0] !== "view")) {
    return new Response("bad path", { status: 404 });
  }
  if (req.headers.get("upgrade")?.toLowerCase() !== "websocket") {
    return new Response("expected websocket", { status: 426 });
  }

  const role = parts[0] === "cam" ? "cam" : "view";
  const deviceId = parts[1];
  const token = url.searchParams.get("token") ?? "";
  if (!(await verifyToken(token, deviceId, role))) {
    return new Response("bad token", { status: 401 });
  }

  const { socket, response } = Deno.upgradeWebSocket(req);
  socket.binaryType = "arraybuffer";
  const ch = getChannel(deviceId);

  if (role === "cam") {
    socket.onopen = () => { localProducer.set(deviceId, socket); console.log(`[cam] connected ${deviceId}`); };
    socket.onmessage = (e: MessageEvent) => {
      if (typeof e.data === "string") return;               // ignore control text
      const data = e.data as ArrayBuffer;
      const vs = localViewers.get(deviceId);                // local viewers
      if (vs) for (const v of vs) { try { if (v.readyState === WebSocket.OPEN) v.send(data); } catch { /*drop*/ } }
      try { ch?.postMessage({ t: "frame", d: data }); } catch { /*drop*/ }  // remote isolates (if supported)
    };
    socket.onclose = () => { if (localProducer.get(deviceId) === socket) localProducer.delete(deviceId); };
  } else {
    socket.onopen = () => { viewerSet(deviceId).add(socket); console.log(`[view] connected ${deviceId}`); };
    socket.onclose = () => { localViewers.get(deviceId)?.delete(socket); };
  }

  return response;
});
