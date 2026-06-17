// ============================================================
//  EagleEye — direct-LAN servo control (low latency)
// ============================================================
//  When the phone is on the SAME Wi-Fi as the camera, we open a plain
//  WebSocket straight to the device (ws://<ip>:81/) and send joystick
//  commands with no cloud hop — typically <50 ms instead of the
//  ~150-300 ms MQTT broker round-trip.
//
//  The device's local IP arrives in its retained MQTT status ({ip, lan}).
//  Call lanConnect(ip) with it. sendServoLan() returns false when the LAN
//  socket isn't open (e.g. you're remote) so the caller falls back to MQTT.
//
//  Plain ws:// to a LAN IP works in Expo Go (cleartext is allowed). In a
//  standalone release build you'd whitelist cleartext for the device IP.
// ============================================================

let ws = null;
let ip = null;
let port = 81;
let connected = false;
let reconnectTimer = null;
const listeners = new Set();           // notified with (true|false) on LAN up/down

function notify() { listeners.forEach((cb) => cb(connected)); }

function open() {
  try { if (ws) ws.close(); } catch {}
  ws = null;
  connected = false;
  notify();
  if (!ip) return;

  const url = `ws://${ip}:${port}/`;
  const sock = new WebSocket(url);
  ws = sock;

  sock.onopen = () => { if (ws === sock) { connected = true; notify(); } };
  sock.onclose = () => { if (ws === sock) { connected = false; notify(); scheduleReconnect(); } };
  sock.onerror = () => { if (ws === sock) { connected = false; notify(); } };
}

function scheduleReconnect() {
  if (reconnectTimer || !ip) return;
  reconnectTimer = setTimeout(() => { reconnectTimer = null; if (ip && !connected) open(); }, 3000);
}

// Point the LAN socket at a device IP (from MQTT status). Re-opens if changed.
export function lanConnect(deviceIp, devicePort = 81) {
  if (!deviceIp) return;
  if (deviceIp === ip && devicePort === port && (connected || ws)) return;
  ip = deviceIp;
  port = devicePort || 81;
  open();
}

export function lanDisconnect() {
  ip = null;
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  try { if (ws) ws.close(); } catch {}
  ws = null;
  connected = false;
  notify();
}

export function lanReady() { return connected; }

// Returns true if the command went out over the LAN socket, false otherwise
// (caller should then send via MQTT).
export function sendServoLan(pan, tilt) {
  if (!connected || !ws || ws.readyState !== 1) return false;
  try { ws.send(JSON.stringify({ type: 'servo', pan, tilt })); return true; }
  catch { return false; }
}

export function onLanStatus(cb) {
  listeners.add(cb);
  cb(connected);
  return () => listeners.delete(cb);
}
