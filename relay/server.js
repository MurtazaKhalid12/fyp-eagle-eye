// ============================================================
//  EagleEye — live-video relay (Plane 2)
// ============================================================
//  A tiny "meeting room" both sides dial OUT to, so neither needs the
//  other's IP (solves NAT / phone-anywhere).
//
//    camera  ->  wss://<host>/cam/<deviceId>?token=...    (pushes JPEG frames)
//    phone   ->  wss://<host>/view/<deviceId>?token=...   (receives frames)
//
//  The relay just forwards the producer's binary frames to every viewer in
//  the same room. When the last viewer leaves it tells the camera
//  {"type":"no-viewers"} so the firmware stops streaming (saves power/egress).
//
//  Tokens: if RELAY_SECRET is set, a short-lived HMAC token is required
//  (issued by the issueStreamToken Cloud Function). If RELAY_SECRET is empty,
//  tokens are NOT enforced (handy for first bring-up).
// ============================================================

const http = require('http');
const crypto = require('crypto');
const { WebSocketServer } = require('ws');

const PORT = process.env.PORT || 8080;
const RELAY_SECRET = process.env.RELAY_SECRET || '';      // empty = auth disabled (dev)
const MAX_FPS = Number(process.env.MAX_FPS || 15);        // soft cap, advisory

// roomId -> { producer: ws|null, viewers: Set<ws> }
const rooms = new Map();

function getRoom(id) {
  if (!rooms.has(id)) rooms.set(id, { producer: null, viewers: new Set() });
  return rooms.get(id);
}

// token = base64url(payload).hexHMAC, payload = {d:deviceId, r:role, exp:unixSeconds}
function verifyToken(token, deviceId, role) {
  if (!RELAY_SECRET) return true;                          // auth disabled
  if (!token) return false;
  const dot = token.lastIndexOf('.');
  if (dot < 0) return false;
  const body = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  const expect = crypto.createHmac('sha256', RELAY_SECRET).update(body).digest('hex');
  if (sig.length !== expect.length || !crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expect))) return false;
  let p;
  try { p = JSON.parse(Buffer.from(body, 'base64url').toString('utf8')); } catch { return false; }
  if (p.d !== deviceId) return false;
  if (p.r !== role) return false;
  if (!p.exp || p.exp < Math.floor(Date.now() / 1000)) return false;
  return true;
}

// Parse "/cam/<id>" or "/view/<id>" + ?token=
function parsePath(reqUrl) {
  const u = new URL(reqUrl, 'http://x');
  const parts = u.pathname.split('/').filter(Boolean);     // ["cam","cam-01"]
  if (parts.length !== 2) return null;
  const role = parts[0] === 'cam' ? 'cam' : parts[0] === 'view' ? 'view' : null;
  if (!role) return null;
  return { role, deviceId: parts[1], token: u.searchParams.get('token') || '' };
}

const server = http.createServer((req, res) => {
  if (req.url === '/health') { res.writeHead(200); res.end('ok'); return; }
  res.writeHead(200, { 'Content-Type': 'text/plain' });
  res.end('EagleEye relay up. Connect via /cam/<id> or /view/<id>.');
});

const wss = new WebSocketServer({ server });

wss.on('connection', (ws, req) => {
  const info = parsePath(req.url);
  if (!info) { ws.close(1008, 'bad path'); return; }
  const { role, deviceId, token } = info;
  if (!verifyToken(token, deviceId, role)) { ws.close(1008, 'bad token'); return; }

  const room = getRoom(deviceId);
  ws._role = role;
  ws._deviceId = deviceId;
  ws.isAlive = true;
  ws.on('pong', () => { ws.isAlive = true; });

  if (role === 'cam') {
    if (room.producer && room.producer !== ws) { try { room.producer.close(1000, 'replaced'); } catch {} }
    room.producer = ws;
    console.log(`[cam] connected room=${deviceId} viewers=${room.viewers.size}`);

    // forward every binary frame to all viewers
    ws.on('message', (data, isBinary) => {
      if (!isBinary) return;                                // ignore control text from cam
      for (const v of room.viewers) {
        if (v.readyState === v.OPEN && v.bufferedAmount < 2_000_000) v.send(data, { binary: true });
      }
    });
    ws.on('close', () => {
      if (room.producer === ws) room.producer = null;
      console.log(`[cam] closed room=${deviceId}`);
      cleanup(deviceId);
    });

  } else { // viewer
    room.viewers.add(ws);
    console.log(`[view] connected room=${deviceId} viewers=${room.viewers.size}`);
    // nudge the camera to start if it's already connected (it also gets "stream on" over MQTT)
    if (room.producer && room.producer.readyState === room.producer.OPEN) {
      try { room.producer.send(JSON.stringify({ type: 'viewer-joined' })); } catch {}
    }
    ws.on('close', () => {
      room.viewers.delete(ws);
      console.log(`[view] closed room=${deviceId} viewers=${room.viewers.size}`);
      // last viewer gone -> tell the camera to stop streaming
      if (room.viewers.size === 0 && room.producer && room.producer.readyState === room.producer.OPEN) {
        try { room.producer.send(JSON.stringify({ type: 'no-viewers' })); } catch {}
      }
      cleanup(deviceId);
    });
  }
});

function cleanup(id) {
  const r = rooms.get(id);
  if (r && !r.producer && r.viewers.size === 0) rooms.delete(id);
}

// drop dead sockets (heartbeat every 30s)
const ping = setInterval(() => {
  for (const ws of wss.clients) {
    if (!ws.isAlive) { try { ws.terminate(); } catch {} continue; }
    ws.isAlive = false;
    try { ws.ping(); } catch {}
  }
}, 30000);
wss.on('close', () => clearInterval(ping));

server.listen(PORT, () => {
  console.log(`EagleEye relay listening on :${PORT}  auth=${RELAY_SECRET ? 'ON' : 'OFF (dev)'}  maxfps≈${MAX_FPS}`);
});
