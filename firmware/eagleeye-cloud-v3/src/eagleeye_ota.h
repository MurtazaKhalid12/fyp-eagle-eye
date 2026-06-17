#ifndef EAGLEEYE_OTA_H
#define EAGLEEYE_OTA_H

// ============================================================
//  EagleEye CLOUD — HTTPS OTA update (Plane / Phase 4)
// ============================================================
//  Triggered by an MQTT command: {"type":"ota","url":"https://.../fw.bin"}.
//  Only run from MODE_AI (never mid-stream/mid-upload). Rollback-capable
//  via the ESP32 OTA partition scheme (pick an OTA-capable partition in
//  the Arduino IDE: Tools > Partition Scheme > "Minimal SPIFFS"/"Default 4MB
//  with OTA" etc.).
// ============================================================

#include <Arduino.h>
#include <WiFiClientSecure.h>
#include <HTTPUpdate.h>
#include "config.h"

inline void ota_perform(const String &url) {
  if (url.length() == 0) return;
  Serial.printf("[OTA] updating from %s\n", url.c_str());

  WiFiClientSecure tls;
  tls.setInsecure();                 // dev; pin CA in production
  tls.setTimeout(20);

  httpUpdate.rebootOnUpdate(true);
  t_httpUpdate_return ret = httpUpdate.update(tls, url);
  switch (ret) {
    case HTTP_UPDATE_FAILED:
      Serial.printf("[OTA] FAILED (%d): %s\n", httpUpdate.getLastError(),
                    httpUpdate.getLastErrorString().c_str());
      break;
    case HTTP_UPDATE_NO_UPDATES: Serial.println("[OTA] no update"); break;
    case HTTP_UPDATE_OK:         Serial.println("[OTA] ok (rebooting)"); break;
  }
}

#endif // EAGLEEYE_OTA_H
