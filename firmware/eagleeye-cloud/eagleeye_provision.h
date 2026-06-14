#ifndef EAGLEEYE_PROVISION_H
#define EAGLEEYE_PROVISION_H

// ============================================================
//  EagleEye CLOUD — Wi-Fi setup portal (Phase 4)
// ============================================================
//  When ENABLE_PROVISIONING == 1 (config.h) and the device has no saved
//  Wi-Fi (or can't connect), it starts a captive-portal AP "EagleEye-Setup".
//  The user joins it, picks Wi-Fi + enters the cloud settings, and the
//  device saves them to NVS (config_save) and reconnects — no re-flashing.
//
//  Needs the Arduino library "WiFiManager" by tzapu.
//  When disabled (default), provision_begin() is a no-op and the firmware
//  uses the DEV_* defaults in config.h.
// ============================================================

#include <Arduino.h>
#include "config.h"

#if ENABLE_PROVISIONING
#include <WiFiManager.h>

inline bool provision_begin() {
  WiFiManager wm;
  char portBuf[8]; snprintf(portBuf, sizeof(portBuf), "%u", g_cfg.mqttPort);

  WiFiManagerParameter p_dev   ("dev",    "Device ID",       g_cfg.deviceId.c_str(),  32);
  WiFiManagerParameter p_host  ("mhost",  "MQTT host",       g_cfg.mqttHost.c_str(),  96);
  WiFiManagerParameter p_port  ("mport",  "MQTT port",       portBuf,                  8);
  WiFiManagerParameter p_user  ("muser",  "MQTT user",       g_cfg.mqttUser.c_str(),  48);
  WiFiManagerParameter p_pass  ("mpass",  "MQTT pass",       g_cfg.mqttPass.c_str(),  64);
  WiFiManagerParameter p_cloud ("ccloud", "Cloudinary name", g_cfg.cldCloud.c_str(),  48);
  WiFiManagerParameter p_preset("cpre",   "Upload preset",   g_cfg.cldPreset.c_str(), 48);
  WiFiManagerParameter p_relay ("relay",  "Relay host",      g_cfg.relayHost.c_str(), 96);
  wm.addParameter(&p_dev);  wm.addParameter(&p_host); wm.addParameter(&p_port);
  wm.addParameter(&p_user); wm.addParameter(&p_pass); wm.addParameter(&p_cloud);
  wm.addParameter(&p_preset); wm.addParameter(&p_relay);

  bool ok = wm.autoConnect("EagleEye-Setup");           // blocks in portal until configured
  if (ok) {
    g_cfg.deviceId  = p_dev.getValue();
    g_cfg.wifiSsid  = WiFi.SSID();
    g_cfg.wifiPass  = WiFi.psk();
    g_cfg.mqttHost  = p_host.getValue();
    g_cfg.mqttPort  = (uint16_t)atoi(p_port.getValue());
    g_cfg.mqttUser  = p_user.getValue();
    g_cfg.mqttPass  = p_pass.getValue();
    g_cfg.cldCloud  = p_cloud.getValue();
    g_cfg.cldPreset = p_preset.getValue();
    g_cfg.relayHost = p_relay.getValue();
    config_save();
    Serial.println("[PROV] saved config from portal");
  }
  return ok;
}

#else  // provisioning disabled -> use DEV_* config
inline bool provision_begin() { return false; }
#endif

#endif // EAGLEEYE_PROVISION_H
