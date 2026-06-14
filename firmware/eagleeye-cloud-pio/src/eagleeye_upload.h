#ifndef EAGLEEYE_UPLOAD_H
#define EAGLEEYE_UPLOAD_H

// ============================================================
//  EagleEye CLOUD — direct HTTPS upload (no PC bridge)
// ============================================================
//  1) cloudinary_upload(): POST the intruder JPEG straight to Cloudinary
//     using an UNSIGNED upload preset (no api_secret on the device).
//  2) ingest_alert(): tell a Cloud Function to write the alert into RTDB
//     (so the existing app `useAlerts` listener shows it). Optional —
//     skipped if g_cfg.ingestUrl is empty.
//
//  These are ONE-SHOT TLS sessions (scope-local client, freed immediately),
//  run only while the relay is closed. See the TLS-memory note in README.
// ============================================================

#include <Arduino.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <time.h>
#include "config.h"

// Read an HTTP response from a connected TLS client; return just the JSON object.
// Robust to chunked transfer-encoding: we slice from the first '{' to the last '}',
// which skips chunk-size markers / CRLFs that would otherwise break JSON parsing.
inline String _read_http_body(WiFiClientSecure &tls, uint32_t timeoutMs = 12000) {
  String resp; resp.reserve(1024);
  uint32_t start = millis();
  while ((tls.connected() || tls.available()) && (millis() - start < timeoutMs)) {
    while (tls.available()) { resp += (char)tls.read(); start = millis(); }
    delay(1);
  }
  int b0 = resp.indexOf('{');
  int b1 = resp.lastIndexOf('}');
  if (b0 >= 0 && b1 > b0) return resp.substring(b0, b1 + 1);   // the JSON object
  int split = resp.indexOf("\r\n\r\n");
  return (split >= 0) ? resp.substring(split + 4) : resp;       // fallback
}

// Upload a JPEG to Cloudinary. On success fills outUrl + outPublicId.
inline bool cloudinary_upload(uint8_t *jpg, size_t len, String &outUrl, String &outPublicId) {
  if (g_cfg.cldPreset.length() == 0) { Serial.println("[UPLOAD] no Cloudinary preset set"); return false; }

  WiFiClientSecure tls;
  tls.setInsecure();                                   // dev; pin Cloudinary CA in prod
  tls.setTimeout(15);
  if (!tls.connect("api.cloudinary.com", 443)) { Serial.println("[UPLOAD] TLS connect failed"); return false; }

  String boundary = "----eagleeye" + String((uint32_t)esp_random(), HEX);
  String head =
      "--" + boundary + "\r\n"
      "Content-Disposition: form-data; name=\"upload_preset\"\r\n\r\n" + g_cfg.cldPreset + "\r\n"
      "--" + boundary + "\r\n"
      "Content-Disposition: form-data; name=\"folder\"\r\n\r\n" + g_cfg.cldFolder + "\r\n"
      "--" + boundary + "\r\n"
      "Content-Disposition: form-data; name=\"file\"; filename=\"eagleeye.jpg\"\r\n"
      "Content-Type: image/jpeg\r\n\r\n";
  String tail = "\r\n--" + boundary + "--\r\n";
  size_t contentLen = head.length() + len + tail.length();
  String path = "/v1_1/" + g_cfg.cldCloud + "/image/upload";

  tls.printf("POST %s HTTP/1.1\r\n", path.c_str());
  tls.print("Host: api.cloudinary.com\r\n");
  tls.printf("Content-Type: multipart/form-data; boundary=%s\r\n", boundary.c_str());
  tls.printf("Content-Length: %u\r\n", (unsigned)contentLen);
  tls.print("Connection: close\r\n\r\n");

  tls.print(head);
  for (size_t sent = 0; sent < len; ) {               // stream the JPEG in chunks (no giant String)
    size_t n = min((size_t)1024, len - sent);
    if (tls.write(jpg + sent, n) == 0) { tls.stop(); Serial.println("[UPLOAD] write failed"); return false; }
    sent += n;
  }
  tls.print(tail);

  String body = _read_http_body(tls);
  tls.stop();                                          // free the ~40 KB TLS session NOW

  EE_JSON(doc, 1024);
  if (deserializeJson(doc, body)) { Serial.println("[UPLOAD] bad JSON response"); return false; }
  const char *url = doc["secure_url"] | "";
  const char *pid = doc["public_id"] | "";
  if (!url[0]) { Serial.printf("[UPLOAD] no secure_url. resp=%s\n", body.c_str()); return false; }
  outUrl = url; outPublicId = pid;
  Serial.printf("[UPLOAD] ok -> %s\n", outUrl.c_str());
  return true;
}

// Tell a Cloud Function to write the alert into RTDB (keeps app `alerts/` history).
// No-op (returns true) if no ingest URL is configured yet.
inline bool ingest_alert(const String &imageUrl, const String &publicId, float score) {
  if (g_cfg.ingestUrl.length() == 0) return true;      // not deployed yet -> skip silently

  // Parse host + path from the https URL.
  String u = g_cfg.ingestUrl;
  if (!u.startsWith("https://")) { Serial.println("[INGEST] url must be https"); return false; }
  u = u.substring(8);
  int slash = u.indexOf('/');
  String host = (slash >= 0) ? u.substring(0, slash) : u;
  String path = (slash >= 0) ? u.substring(slash)    : "/";

  WiFiClientSecure tls; tls.setInsecure(); tls.setTimeout(10);
  if (!tls.connect(host.c_str(), 443)) { Serial.println("[INGEST] connect failed"); return false; }

  EE_JSON(doc, 384);
  doc["deviceId"]  = g_cfg.deviceId;
  doc["image_url"] = imageUrl;
  doc["public_id"] = publicId;
  doc["score"]     = score;
  doc["type"]      = "Human Detected";
  char payload[384]; size_t plen = serializeJson(doc, payload);

  tls.printf("POST %s HTTP/1.1\r\n", path.c_str());
  tls.printf("Host: %s\r\n", host.c_str());
  tls.print("Content-Type: application/json\r\n");
  tls.printf("Content-Length: %u\r\n", (unsigned)plen);
  tls.print("Connection: close\r\n\r\n");
  tls.write((const uint8_t *)payload, plen);

  String body = _read_http_body(tls, 8000);
  tls.stop();
  Serial.println("[INGEST] alert posted");
  return true;
}

// Write the alert straight into Firebase Realtime DB via REST, in the exact shape
// the app already reads ({timestamp, image_url, public_id, type}). POST to
// /alerts.json creates a push-key child. Requires RTDB write rules to be open
// (test mode) — the same permission the app uses with no auth.
inline bool firebase_push_alert(const String &imageUrl, const String &publicId, float score) {
  const char *host = DEV_FIREBASE_DB;
  if (!host[0]) return true;                            // not configured -> skip

  WiFiClientSecure tls; tls.setInsecure(); tls.setTimeout(12);
  if (!tls.connect(host, 443)) { Serial.println("[FB] connect failed"); return false; }

  EE_JSON(doc, 384);
  doc["timestamp"] = (uint32_t)time(nullptr);          // unix seconds (SNTP-synced)
  doc["image_url"] = imageUrl;
  doc["public_id"] = publicId;
  doc["score"]     = score;
  doc["type"]      = "Human Detected";
  char payload[384]; size_t plen = serializeJson(doc, payload);

  tls.print("POST /alerts.json HTTP/1.1\r\n");
  tls.printf("Host: %s\r\n", host);
  tls.print("Content-Type: application/json\r\n");
  tls.printf("Content-Length: %u\r\n", (unsigned)plen);
  tls.print("Connection: close\r\n\r\n");
  tls.write((const uint8_t *)payload, plen);

  String body = _read_http_body(tls, 8000);
  tls.stop();
  Serial.println("[FB] alert written to RTDB");
  return true;
}

#endif // EAGLEEYE_UPLOAD_H
