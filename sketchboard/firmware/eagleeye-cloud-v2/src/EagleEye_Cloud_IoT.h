#ifndef EAGLEEYE_CLOUD_IOT_H
#define EAGLEEYE_CLOUD_IOT_H

// ============================================================
//  EagleEye CLOUD — MQTT-over-TLS control/status/alerts (Plane 1)
// ============================================================
//  The device connects OUTBOUND to a cloud broker (HiveMQ) over TLS and
//  stays connected, so its IP never matters. Topics (per device):
//    .../status  (retained, + LWT)  device -> cloud   online/armed/fw/rssi
//    .../cmd     (subscribe)        cloud  -> device  arm/servo/stream/ota
//    .../alert   (publish)          device -> cloud   {ts,image_url,public_id,...}
//    .../stream  (publish)          device -> app     relay-ready signal
// ============================================================

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "config.h"
#include "eagleeye_camera.h"   // g_mode, esp_camera, fmt2jpg
#include "eagleeye_upload.h"   // cloudinary_upload, ingest_alert

#define FLASH_GPIO_NUM 4

WiFiClientSecure secureClient;
PubSubClient     client(secureClient);

// --- control / request state (set by mqtt_callback, acted on in loop()) ---
bool   is_system_armed   = true;     // gates capture
bool   g_req_stream_on   = false;
bool   g_req_stream_off  = false;
int    g_req_servo_angle = -1;       // pan  target (-1 = none pending)  GPIO15
int    g_req_tilt_angle  = -1;       // tilt target (-1 = none pending)  GPIO14
String g_req_ota_url     = "";
bool   g_req_factory_reset = false;
unsigned long g_last_cmd_ms = 0;     // last control command time; main pauses AI briefly so panning is smooth

unsigned long g_mqtt_next_attempt = 0;

// Forward decls (defined in the .ino — drive the servos on GPIO15 / GPIO14).
void eagleeye_send_servo(int angle);   // pan
void eagleeye_send_tilt(int angle);    // tilt

// --- publish retained status ---
inline void publish_status() {
  EE_JSON(d, 256);
  d["online"] = true;
  d["armed"]  = is_system_armed;
  d["fw"]     = FW_VERSION;
  d["rssi"]   = (int)WiFi.RSSI();
  d["ip"]     = WiFi.localIP().toString();   // app uses this for the direct-LAN control socket
  d["lan"]    = 81;                          // ws://<ip>:81 servo control port
  char buf[256]; size_t n = serializeJson(d, buf);
  client.publish(topic_status().c_str(), (const uint8_t *)buf, n, true);  // retained
}

// --- command handler: JSON on .../cmd ---
inline void mqtt_callback(char *topic, byte *payload, unsigned int length) {
  EE_JSON(doc, 256);
  if (deserializeJson(doc, payload, length)) { Serial.println("[MQTT] bad cmd JSON"); return; }
  const char *type = doc["type"] | "";

  if (!strcmp(type, "arm")) {
    is_system_armed = doc["value"] | true;
    Serial.printf("[CMD] armed=%d\n", is_system_armed);
    publish_status();
  } else if (!strcmp(type, "servo")) {
    // Pan/tilt joystick:  {type:"servo", pan:0-180, tilt:0-180}
    // Back-compat single axis:  {type:"servo", angle:N}  -> treated as pan.
    // A missing axis (-1) leaves that servo where it is.
    int pan  = doc["pan"]  | (doc["angle"] | -1);
    int tilt = doc["tilt"] | -1;
    if (pan  >= 0) g_req_servo_angle = pan;
    if (tilt >= 0) g_req_tilt_angle  = tilt;
    g_last_cmd_ms = millis();                 // keep the loop responsive while panning
    Serial.printf("[CMD] servo pan=%d tilt=%d\n", pan, tilt);
  } else if (!strcmp(type, "stream")) {
    bool on = doc["value"] | false;
    if (on) g_req_stream_on = true; else g_req_stream_off = true;
    g_last_cmd_ms = millis();
    Serial.printf("[CMD] stream=%d\n", on);
  } else if (!strcmp(type, "ota")) {
    g_req_ota_url = String((const char *)(doc["url"] | ""));
    Serial.printf("[CMD] ota=%s\n", g_req_ota_url.c_str());
  } else if (!strcmp(type, "factory_reset")) {
    g_req_factory_reset = true;
  } else {
    Serial.printf("[CMD] unknown type '%s'\n", type);
  }
}

// --- SNTP (TLS cert validation needs a real clock) ---
inline void init_time() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  struct tm t;
  for (int i = 0; i < 20 && !getLocalTime(&t, 500); i++) { Serial.print("."); }
  Serial.println();
}

// --- Wi-Fi + secure MQTT setup ---
inline void init_wifi_mqtt() {
  pinMode(FLASH_GPIO_NUM, OUTPUT);
  digitalWrite(FLASH_GPIO_NUM, LOW);

  Serial.printf("[WiFi] connecting to %s ...\n", g_cfg.wifiSsid.c_str());
  WiFi.mode(WIFI_STA);
  WiFi.begin(g_cfg.wifiSsid.c_str(), g_cfg.wifiPass.c_str());
  // Lower Wi-Fi TX power to soften the current spike that browns out weak ESP32-CAM
  // supplies during association. Raise toward WIFI_POWER_19_5dBm if range suffers.
  WiFi.setTxPower(WIFI_POWER_8_5dBm);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 30000) { delay(400); Serial.print("."); }
  Serial.printf("\n[WiFi] %s  IP=%s\n",
                WiFi.status() == WL_CONNECTED ? "connected" : "TIMEOUT",
                WiFi.localIP().toString().c_str());

  init_time();

#if TLS_INSECURE
  secureClient.setInsecure();                 // dev: skip cert validation
#else
  // PROD: pin the broker's root CA here, e.g.:
  // secureClient.setCACert(HIVEMQ_ROOT_CA_PEM);
  secureClient.setInsecure();                 // <-- replace with setCACert in production
#endif

  client.setServer(g_cfg.mqttHost.c_str(), g_cfg.mqttPort);
  client.setCallback(mqtt_callback);
  client.setBufferSize(1024);                 // small: JPEG no longer goes over MQTT (~50 KB heap saved)
  client.setKeepAlive(30);
}

// --- non-blocking reconnect + pump (call every loop) ---
inline void mqtt_service() {
  if (client.connected()) { client.loop(); return; }
  if (millis() < g_mqtt_next_attempt) return;
  g_mqtt_next_attempt = millis() + 5000;

  String cid = "eagle-" + g_cfg.deviceId + "-" + String((uint32_t)esp_random(), HEX);
  String willTopic = topic_status();
  const char *willMsg = "{\"online\":false}";
  Serial.print("[MQTT] connecting...");
  if (client.connect(cid.c_str(), g_cfg.mqttUser.c_str(), g_cfg.mqttPass.c_str(),
                     willTopic.c_str(), 1, true, willMsg)) {     // LWT: offline on drop
    Serial.println("ok");
    client.subscribe(topic_cmd().c_str(), 1);
    publish_status();
  } else {
    Serial.printf("failed rc=%d (retry in 5s)\n", client.state());
  }
}

// --- capture an intruder JPEG, upload to cloud, publish the alert ---
//  score = the human confidence from the classifier (for the alert payload).
inline void capture_and_send_image(float score) {
  if (!is_system_armed) { Serial.println("[CAP] disarmed - skip"); return; }

  g_mode = MODE_UPLOADING;
  digitalWrite(FLASH_GPIO_NUM, HIGH);
  delay(300);
  camera_fb_t *flush = esp_camera_fb_get();             // flush 1 frame for flash exposure
  if (flush) esp_camera_fb_return(flush);
  delay(80);
  camera_fb_t *fb = esp_camera_fb_get();
  digitalWrite(FLASH_GPIO_NUM, LOW);
  if (!fb) { Serial.println("[CAP] capture failed"); g_mode = MODE_AI; return; }

  uint8_t *jpg = NULL; size_t jpgLen = 0;
  bool ok = fmt2jpg(fb->buf, fb->len, fb->width, fb->height, PIXFORMAT_RGB565, 85, &jpg, &jpgLen);
  esp_camera_fb_return(fb);
  if (!ok || !jpg) { Serial.println("[CAP] jpeg encode failed"); if (jpg) free(jpg); g_mode = MODE_AI; return; }

  String url, pid;
  if (cloudinary_upload(jpg, jpgLen, url, pid)) {
    firebase_push_alert(url, pid, score);                // write straight into Firebase RTDB (app reads this)
    ingest_alert(url, pid, score);                       // optional Cloud Function path (no-op if unset)
    EE_JSON(a, 384);                                     // also publish realtime alert over MQTT
    a["ts"] = (uint32_t)time(nullptr);
    a["image_url"] = url; a["public_id"] = pid;
    a["score"] = score;   a["type"] = "Human Detected";
    char buf[384]; size_t n = serializeJson(a, buf);
    client.publish(topic_alert().c_str(), (const uint8_t *)buf, n, false);
  }
  free(jpg);
  g_mode = MODE_AI;
}

#endif // EAGLEEYE_CLOUD_IOT_H
