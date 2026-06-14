// ============================================================
//  EagleEye — MQTT service (singleton)
// ============================================================
//  One shared MQTT-over-WebSocket connection to HiveMQ Cloud. The app
//  publishes commands (arm / servo / stream) and subscribes to the
//  camera's retained status + stream-ready signal. Replaces the old
//  "type the camera IP" approach — works from anywhere.
//
//  Uses mqtt.js (pure JS, runs in Expo Go over wss://).
// ============================================================

import mqtt from 'mqtt';
import { CLOUD, topics } from '../config/cloudConfig';

let client = null;
let lastStatus = null;                  // last retained status JSON from the camera
const statusListeners = new Set();
const streamListeners = new Set();

const T = {
  status: topics.status(CLOUD.deviceId),
  stream: topics.stream(CLOUD.deviceId),
  cmd:    topics.cmd(CLOUD.deviceId),
};

export function connectMqtt() {
  if (client) return client;

  client = mqtt.connect(CLOUD.mqtt.url, {
    username: CLOUD.mqtt.username,
    password: CLOUD.mqtt.password,
    clientId: 'eagle-app-' + Math.random().toString(16).slice(2, 10),
    protocolVersion: 4,                 // MQTT 3.1.1
    keepalive: 30,
    reconnectPeriod: 3000,
    clean: true,
  });

  client.on('connect', () => {
    console.log('[mqtt] connected');
    client.subscribe([T.status, T.stream], { qos: 1 });
  });
  client.on('reconnect', () => console.log('[mqtt] reconnecting…'));
  client.on('error', (e) => console.log('[mqtt] error', e?.message || e));

  client.on('message', (topic, payload) => {
    let data;
    try { data = JSON.parse(payload.toString()); } catch { return; }
    if (topic === T.status) {
      lastStatus = data;
      statusListeners.forEach((cb) => cb(data));
    } else if (topic === T.stream) {
      streamListeners.forEach((cb) => cb(data));
    }
  });

  return client;
}

// ---- subscriptions (return an unsubscribe fn) ----
export function onStatus(cb) {
  statusListeners.add(cb);
  if (lastStatus) cb(lastStatus);        // replay last known immediately
  return () => statusListeners.delete(cb);
}
export function onStream(cb) {
  streamListeners.add(cb);
  return () => streamListeners.delete(cb);
}
export function getStatus() { return lastStatus; }

// ---- commands ----
//  qos 1 (default) for things that must arrive once: arm / stream / ota.
//  qos 0 for the high-rate servo stream — fire-and-forget, no PUBACK round-trip
//  and no inflight queue, so the latest joystick position reaches the camera
//  with the least possible lag (a dropped intermediate frame doesn't matter,
//  the next one supersedes it).
function publishCmd(obj, qos = 1) {
  const c = connectMqtt();
  c.publish(T.cmd, JSON.stringify(obj), { qos });
}
export function setArmed(value) { publishCmd({ type: 'arm', value }); }
// Servo control (angles 0–180). The pan/tilt joystick sends both axes each tick.
export function setServo(angle)       { publishCmd({ type: 'servo', angle }, 0); }       // legacy pan-only
export function setPanTilt(pan, tilt) { publishCmd({ type: 'servo', pan, tilt }, 0); }   // both axes
export function setPan(pan)           { publishCmd({ type: 'servo', pan }, 0); }
export function setTilt(tilt)         { publishCmd({ type: 'servo', tilt }, 0); }
export function startStream()   { publishCmd({ type: 'stream', value: true }); }
export function stopStream()    { publishCmd({ type: 'stream', value: false }); }

// ---- relay video URL the app connects to for live frames ----
export function viewUrl() { return `${CLOUD.relayBase}/view/${CLOUD.deviceId}`; }
