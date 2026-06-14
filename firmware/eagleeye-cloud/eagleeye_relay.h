#ifndef EAGLEEYE_RELAY_H
#define EAGLEEYE_RELAY_H

// ============================================================
//  EagleEye CLOUD — live video via cloud WebSocket relay (Plane 2)
// ============================================================
//  On-demand only. When the app asks (cmd stream:true) the device:
//    1) switches the camera to hardware JPEG,
//    2) (optionally) fetches a short-lived token from issueStreamToken,
//    3) opens an OUTBOUND wss connection to the relay room /cam/<id>,
//    4) pushes JPEG frames; the relay fans them out to the app.
//  Stops on cmd stream:false, relay "no-viewers", or a max-session cap.
//
//  Library: "WebSockets" by Markus Sattler (Links2004) — WebSocketsClient.
// ============================================================

#include <Arduino.h>
#include <WiFiClientSecure.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include "config.h"
#include "eagleeye_camera.h"
#include "EagleEye_Cloud_IoT.h"   // client (to publish stream-ready), g_req_stream_off

#define EAGLEEYE_RELAY_FRAME_MS   80       // ~12 fps cap
#define EAGLEEYE_RELAY_MAX_MS     300000   // 5 min hard session cap (bounds egress)

WebSocketsClient relayWs;
bool          g_relay_connected = false;
unsigned long g_relay_last_frame = 0;
unsigned long g_relay_started_at = 0;

// Fetch a short-lived relay token (role = "cam"). Empty if no token URL configured.
inline String relay_get_token() {
  if (g_cfg.tokenUrl.length() == 0) return "";
  String u = g_cfg.tokenUrl;
  if (!u.startsWith("https://")) return "";
  u = u.substring(8);
  int slash = u.indexOf('/');
  String host = (slash >= 0) ? u.substring(0, slash) : u;
  String path = (slash >= 0) ? u.substring(slash) : "/";
  path += (path.indexOf('?') >= 0 ? "&" : "?");
  path += "deviceId=" + g_cfg.deviceId + "&role=cam";

  WiFiClientSecure tls; tls.setInsecure(); tls.setTimeout(8);
  if (!tls.connect(host.c_str(), 443)) return "";
  tls.printf("GET %s HTTP/1.1\r\n", path.c_str());
  tls.printf("Host: %s\r\n", host.c_str());
  tls.print("Connection: close\r\n\r\n");
  String body = _read_http_body(tls, 8000);
  tls.stop();
  EE_JSON(d, 256);
  if (deserializeJson(d, body)) return "";
  return String((const char *)(d["token"] | ""));
}

inline void relay_event(WStype_t type, uint8_t *payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      g_relay_connected = true;
      Serial.println("[RELAY] connected");
      client.publish(topic_stream().c_str(), "{\"ready\":true}", false);  // tell the app to attach
      break;
    case WStype_DISCONNECTED:
      g_relay_connected = false;
      Serial.println("[RELAY] disconnected");
      break;
    case WStype_TEXT:
      // relay control messages, e.g. {"type":"no-viewers"} -> stop to save power/egress
      if (payload && (strstr((char *)payload, "no-viewers") || strstr((char *)payload, "stop")))
        g_req_stream_off = true;
      break;
    default: break;
  }
}

// Enter relay mode: pause AI and open the wss client.
// NOTE: we keep the camera in its RGB565 AI mode and software-encode JPEG for the
// relay (eagleeye_grab_jpeg handles that). Hardware PIXFORMAT_JPEG is NOT used —
// this board's sensor rejects it ("JPEG format is not supported on this sensor").
inline void relay_start() {
  Serial.println("[RELAY] starting...");
  g_mode = MODE_RELAY;            // pause AI; camera stays RGB565, frames are software-JPEG'd

  String token = relay_get_token();
  String path  = "/cam/" + g_cfg.deviceId + (token.length() ? ("?token=" + token) : "");
  relayWs.beginSSL(g_cfg.relayHost.c_str(), g_cfg.relayPort, path.c_str());
  relayWs.onEvent(relay_event);
  relayWs.setReconnectInterval(3000);
  g_relay_started_at = millis();
  g_relay_last_frame = 0;
}

// Pump while in MODE_RELAY (called every loop instead of the AI step).
inline void relay_loop() {
  relayWs.loop();

  if (millis() - g_relay_started_at > EAGLEEYE_RELAY_MAX_MS) { g_req_stream_off = true; return; }
  if (!g_relay_connected) return;
  if (millis() - g_relay_last_frame < EAGLEEYE_RELAY_FRAME_MS) return;
  g_relay_last_frame = millis();

  uint8_t *jpg = NULL; size_t len = 0;
  if (eagleeye_grab_jpeg(&jpg, &len)) {
    relayWs.sendBIN(jpg, len);
    free(jpg);
  } else {
    // No frame produced -> app stays on "waiting for camera stream". Almost
    // always low/fragmented heap during streaming. Log it (throttled by FRAME_MS).
    Serial.printf("[RELAY] jpeg grab failed (free internal heap=%u)\n",
                  (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
  }
}

// Leave relay mode: close socket, resume AI (camera was never switched).
inline void relay_stop() {
  Serial.println("[RELAY] stopping...");
  relayWs.disconnect();
  g_relay_connected = false;
  g_mode = MODE_AI;
}

#endif // EAGLEEYE_RELAY_H
