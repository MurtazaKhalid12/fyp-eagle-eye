/*
 * ============================================================
 *  EagleEye — CLOUD build  (standalone single-file edition)
 * ============================================================
 *  All module functions are inlined here in dependency order so the
 *  entire firmware lives in one file.  Only credentials are kept in
 *  config.h so they are easy to edit without touching this file.
 *
 *  Plane 1 : MQTT-over-TLS (HiveMQ)  — control / status / alerts
 *  Plane 2 : on-demand live video via cloud WebSocket relay
 *  Direct HTTPS upload to Cloudinary  (no PC bridge)
 *  Phase 4 : Wi-Fi setup portal, HTTPS OTA, TLS hardening
 * ============================================================
 */

// ============================================================
//  External library includes
// ============================================================
#include <Arduino.h>
#include "esp_camera.h"
#include <eagleeye_vision.h>        // EagleEye v7.16 human detection (96x96 RGB, ESP-NN)
#include "esp_heap_caps.h"
#include "img_converters.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <WebSocketsServer.h>
#include <WebSocketsClient.h>
#include <ESP32Servo.h>
#include <Preferences.h>
#include <HTTPUpdate.h>
#include <time.h>
#include "esp_system.h"
#include "config.h"

// ============================================================
//  EagleEye inference API
//  Wraps eagleeye-sdk internals — application code never sees EI_ names.
// ============================================================
#define EE_MODEL_INPUT_WIDTH     EI_CLASSIFIER_INPUT_WIDTH
#define EE_MODEL_INPUT_HEIGHT    EI_CLASSIFIER_INPUT_HEIGHT
#define EE_MODEL_LABEL_COUNT     EI_CLASSIFIER_LABEL_COUNT
#define EE_INFERENCE_OK          EI_IMPULSE_OK
#define EE_MODEL_NAME            EI_CLASSIFIER_PROJECT_NAME
#define EE_MODEL_VERSION         EI_CLASSIFIER_PROJECT_DEPLOY_VERSION
#define EE_MODEL_ESP_NN          EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN
#define ee_run_inference         run_classifier
using ee_signal_t           = ei::signal_t;
using ee_inference_result_t = ei_impulse_result_t;

// ArduinoJson v6 / v7 compatibility
#if ARDUINOJSON_VERSION_MAJOR >= 7
  #define EE_JSON(name, cap) JsonDocument name
#else
  #define EE_JSON(name, cap) StaticJsonDocument<cap> name
#endif

// ============================================================
//  AI dimensions
// ============================================================
#define IMG_WIDTH          EE_MODEL_INPUT_WIDTH    // 96
#define IMG_HEIGHT         EE_MODEL_INPUT_HEIGHT   // 96
#define HUMAN_THRESHOLD    0.6f
#define CLEAR_SCENE_FRAMES 20

// ============================================================
//  CONFIG — runtime struct + NVS load/save
// ============================================================
struct Config {
  String deviceId;
  String wifiSsid, wifiPass;
  String mqttHost; uint16_t mqttPort;
  String mqttUser, mqttPass;
  String cldCloud, cldPreset, cldFolder;
  String ingestUrl, tokenUrl;
  String relayHost; uint16_t relayPort;
};
Config      g_cfg;
Preferences g_prefs;

inline void config_load() {
  g_prefs.begin("eagleeye", true);
  g_cfg.deviceId  = g_prefs.getString("deviceId",  DEV_DEVICE_ID);
  g_cfg.wifiSsid  = g_prefs.getString("ssid",      DEV_WIFI_SSID);
  g_cfg.wifiPass  = g_prefs.getString("pass",      DEV_WIFI_PASS);
  g_cfg.mqttHost  = g_prefs.getString("mqttHost",  DEV_MQTT_HOST);
  g_cfg.mqttPort  = g_prefs.getUShort("mqttPort",  DEV_MQTT_PORT);
  g_cfg.mqttUser  = g_prefs.getString("mqttUser",  DEV_MQTT_USER);
  g_cfg.mqttPass  = g_prefs.getString("mqttPass",  DEV_MQTT_PASS);
  g_cfg.cldCloud  = g_prefs.getString("cldCloud",  DEV_CLD_CLOUD);
  g_cfg.cldPreset = g_prefs.getString("cldPreset", DEV_CLD_PRESET);
  g_cfg.cldFolder = g_prefs.getString("cldFolder", DEV_CLD_FOLDER);
  g_cfg.ingestUrl = g_prefs.getString("ingestUrl", DEV_INGEST_URL);
  g_cfg.tokenUrl  = g_prefs.getString("tokenUrl",  DEV_TOKEN_URL);
  g_cfg.relayHost = g_prefs.getString("relayHost", DEV_RELAY_HOST);
  g_cfg.relayPort = g_prefs.getUShort("relayPort", DEV_RELAY_PORT);
  g_prefs.end();
}

inline void config_save() {
  g_prefs.begin("eagleeye", false);
  g_prefs.putString("deviceId",  g_cfg.deviceId);
  g_prefs.putString("ssid",      g_cfg.wifiSsid);
  g_prefs.putString("pass",      g_cfg.wifiPass);
  g_prefs.putString("mqttHost",  g_cfg.mqttHost);
  g_prefs.putUShort("mqttPort",  g_cfg.mqttPort);
  g_prefs.putString("mqttUser",  g_cfg.mqttUser);
  g_prefs.putString("mqttPass",  g_cfg.mqttPass);
  g_prefs.putString("cldCloud",  g_cfg.cldCloud);
  g_prefs.putString("cldPreset", g_cfg.cldPreset);
  g_prefs.putString("cldFolder", g_cfg.cldFolder);
  g_prefs.putString("ingestUrl", g_cfg.ingestUrl);
  g_prefs.putString("tokenUrl",  g_cfg.tokenUrl);
  g_prefs.putString("relayHost", g_cfg.relayHost);
  g_prefs.putUShort("relayPort", g_cfg.relayPort);
  g_prefs.end();
}

inline void config_factory_reset() {
  g_prefs.begin("eagleeye", false);
  g_prefs.clear();
  g_prefs.end();
}

inline String topic_status() { return "eagleeye/" + g_cfg.deviceId + "/status"; }
inline String topic_alert()  { return "eagleeye/" + g_cfg.deviceId + "/alert";  }
inline String topic_cmd()    { return "eagleeye/" + g_cfg.deviceId + "/cmd";    }
inline String topic_stream() { return "eagleeye/" + g_cfg.deviceId + "/stream"; }

// ============================================================
//  CAMERA — pin map, modes, init helpers
// ============================================================
#define PWDN_GPIO_NUM   32
#define RESET_GPIO_NUM  -1
#define XCLK_GPIO_NUM    0
#define SIOD_GPIO_NUM   26
#define SIOC_GPIO_NUM   27
#define Y9_GPIO_NUM     35
#define Y8_GPIO_NUM     34
#define Y7_GPIO_NUM     39
#define Y6_GPIO_NUM     36
#define Y5_GPIO_NUM     21
#define Y4_GPIO_NUM     19
#define Y3_GPIO_NUM     18
#define Y2_GPIO_NUM      5
#define VSYNC_GPIO_NUM  25
#define HREF_GPIO_NUM   23
#define PCLK_GPIO_NUM   22

enum DeviceMode { MODE_AI, MODE_UPLOADING, MODE_RELAY };
DeviceMode g_mode = MODE_AI;

inline bool setup_camera(pixformat_t fmt, framesize_t size, int jpegQ) {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM; config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM; config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 10000000;
  config.pixel_format = fmt;
  config.frame_size   = size;
  config.jpeg_quality = jpegQ;
  config.fb_count     = 2;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_LATEST;
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) { Serial.printf("[CAM] init failed: 0x%x\n", err); return false; }
  return true;
}

inline bool setup_camera_ai()     { return setup_camera(PIXFORMAT_RGB565, FRAMESIZE_QVGA, 12); }
inline bool setup_camera_stream() { return setup_camera(PIXFORMAT_JPEG,   FRAMESIZE_VGA,  12); }
inline bool switch_camera_to_ai()     { esp_camera_deinit(); return setup_camera_ai(); }
inline bool switch_camera_to_stream() { esp_camera_deinit(); return setup_camera_stream(); }

inline bool eagleeye_grab_jpeg(uint8_t **jpg_buf, size_t *jpg_len) {
  *jpg_buf = NULL; *jpg_len = 0;
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) return false;
  if (fb->format == PIXFORMAT_JPEG) {
    uint8_t *buf = (uint8_t *)malloc(fb->len);
    if (!buf) { esp_camera_fb_return(fb); return false; }
    memcpy(buf, fb->buf, fb->len);
    *jpg_buf = buf; *jpg_len = fb->len;
    esp_camera_fb_return(fb);
    return true;
  }
  uint8_t *buf = NULL; size_t len = 0;
  bool ok = frame2jpg(fb, 25, &buf, &len);
  esp_camera_fb_return(fb);
  if (!ok || !buf) return false;
  *jpg_buf = buf; *jpg_len = len;
  return true;
}

// ============================================================
//  SERVOS — smooth pan/tilt stepper (Core-0 safe, LEDC only)
// ============================================================
#define SERVO_PAN_PIN   15
#define SERVO_TILT_PIN  14
#define SERVO_STEP_MS    5
#define SERVO_STEP_DEG   1

Servo servoPan;
Servo servoTilt;
int panCur  = 90, panTgt  = 90;
int tiltCur = 90, tiltTgt = 90;
unsigned long servoLastStep = 0;

static inline int servo_clamp(int a) { if (a < 0) a = 0; if (a > 180) a = 180; return a; }

inline void servos_begin() {
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);
  servoPan.setPeriodHertz(50);
  servoPan.attach(SERVO_PAN_PIN, 500, 2400);
  servoPan.write(panCur);
  servoTilt.setPeriodHertz(50);
  servoTilt.attach(SERVO_TILT_PIN, 500, 2400);
  servoTilt.write(tiltCur);
  Serial.println("[OK] servos: PAN=GPIO15  TILT=GPIO14");
}

inline void set_pan(int a)  { panTgt  = servo_clamp(a); }
inline void set_tilt(int a) { tiltTgt = servo_clamp(a); }

inline void servos_service() {
  unsigned long now = millis();
  if (now - servoLastStep < SERVO_STEP_MS) return;
  servoLastStep = now;
  if (panCur != panTgt) {
    if (panCur < panTgt) { panCur += SERVO_STEP_DEG; if (panCur > panTgt) panCur = panTgt; }
    else                 { panCur -= SERVO_STEP_DEG; if (panCur < panTgt) panCur = panTgt; }
    servoPan.write(panCur);
  }
  if (tiltCur != tiltTgt) {
    if (tiltCur < tiltTgt) { tiltCur += SERVO_STEP_DEG; if (tiltCur > tiltTgt) tiltCur = tiltTgt; }
    else                   { tiltCur -= SERVO_STEP_DEG; if (tiltCur < tiltTgt) tiltCur = tiltTgt; }
    servoTilt.write(tiltCur);
  }
}

// ============================================================
//  UPLOAD — Cloudinary JPEG upload + Firebase / Cloud-Fn alert
// ============================================================
inline String _read_http_body(WiFiClientSecure &tls, uint32_t timeoutMs = 12000) {
  String resp; resp.reserve(1024);
  uint32_t start = millis();
  while ((tls.connected() || tls.available()) && (millis() - start < timeoutMs)) {
    while (tls.available()) { resp += (char)tls.read(); start = millis(); }
    delay(1);
  }
  int b0 = resp.indexOf('{');
  int b1 = resp.lastIndexOf('}');
  if (b0 >= 0 && b1 > b0) return resp.substring(b0, b1 + 1);
  int split = resp.indexOf("\r\n\r\n");
  return (split >= 0) ? resp.substring(split + 4) : resp;
}

inline bool cloudinary_upload(uint8_t *jpg, size_t len, String &outUrl, String &outPublicId) {
  if (g_cfg.cldPreset.length() == 0) { Serial.println("[UPLOAD] no Cloudinary preset set"); return false; }
  WiFiClientSecure tls;
  tls.setInsecure(); tls.setTimeout(15);
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
  for (size_t sent = 0; sent < len; ) {
    size_t n = min((size_t)1024, len - sent);
    if (tls.write(jpg + sent, n) == 0) { tls.stop(); Serial.println("[UPLOAD] write failed"); return false; }
    sent += n;
  }
  tls.print(tail);

  String body = _read_http_body(tls);
  tls.stop();
  EE_JSON(doc, 1024);
  if (deserializeJson(doc, body)) { Serial.println("[UPLOAD] bad JSON response"); return false; }
  const char *url = doc["secure_url"] | "";
  const char *pid = doc["public_id"] | "";
  if (!url[0]) { Serial.printf("[UPLOAD] no secure_url. resp=%s\n", body.c_str()); return false; }
  outUrl = url; outPublicId = pid;
  Serial.printf("[UPLOAD] ok -> %s\n", outUrl.c_str());
  return true;
}

inline bool ingest_alert(const String &imageUrl, const String &publicId, float score) {
  if (g_cfg.ingestUrl.length() == 0) return true;
  String u = g_cfg.ingestUrl;
  if (!u.startsWith("https://")) { Serial.println("[INGEST] url must be https"); return false; }
  u = u.substring(8);
  int slash = u.indexOf('/');
  String host = (slash >= 0) ? u.substring(0, slash) : u;
  String path = (slash >= 0) ? u.substring(slash) : "/";
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
  _read_http_body(tls, 8000);
  tls.stop();
  Serial.println("[INGEST] alert posted");
  return true;
}

inline bool firebase_push_alert(const String &imageUrl, const String &publicId, float score) {
  const char *host = DEV_FIREBASE_DB;
  if (!host[0]) return true;
  WiFiClientSecure tls; tls.setInsecure(); tls.setTimeout(12);
  if (!tls.connect(host, 443)) { Serial.println("[FB] connect failed"); return false; }
  EE_JSON(doc, 384);
  doc["timestamp"] = (uint32_t)time(nullptr);
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
  _read_http_body(tls, 8000);
  tls.stop();
  Serial.println("[FB] alert written to RTDB");
  return true;
}

// ============================================================
//  CLOUD IoT — Wi-Fi, SNTP, MQTT-over-TLS (Plane 1)
// ============================================================
#define FLASH_GPIO_NUM 4

WiFiClientSecure secureClient;
PubSubClient     client(secureClient);

bool   is_system_armed   = true;
bool   g_req_stream_on   = false;
bool   g_req_stream_off  = false;
int    g_req_servo_angle = -1;
int    g_req_tilt_angle  = -1;
String g_req_ota_url     = "";
bool   g_req_factory_reset = false;
unsigned long g_last_cmd_ms = 0;
unsigned long g_mqtt_next_attempt = 0;

// Forward declarations for servo entry-points defined later in this file.
void eagleeye_send_servo(int angle);
void eagleeye_send_tilt(int angle);

inline void publish_status() {
  EE_JSON(d, 256);
  d["online"] = true;
  d["armed"]  = is_system_armed;
  d["fw"]     = FW_VERSION;
  d["rssi"]   = (int)WiFi.RSSI();
  d["ip"]     = WiFi.localIP().toString();
  d["lan"]    = 81;
  char buf[256]; size_t n = serializeJson(d, buf);
  client.publish(topic_status().c_str(), (const uint8_t *)buf, n, true);
}

inline void mqtt_callback(char *topic, byte *payload, unsigned int length) {
  EE_JSON(doc, 256);
  if (deserializeJson(doc, payload, length)) { Serial.println("[MQTT] bad cmd JSON"); return; }
  const char *type = doc["type"] | "";

  if (!strcmp(type, "arm")) {
    is_system_armed = doc["value"] | true;
    Serial.printf("[CMD] armed=%d\n", is_system_armed);
    publish_status();
  } else if (!strcmp(type, "servo")) {
    int pan  = doc["pan"]  | (doc["angle"] | -1);
    int tilt = doc["tilt"] | -1;
    if (pan  >= 0) g_req_servo_angle = pan;
    if (tilt >= 0) g_req_tilt_angle  = tilt;
    g_last_cmd_ms = millis();
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

inline void init_time() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  struct tm t;
  for (int i = 0; i < 20 && !getLocalTime(&t, 500); i++) { Serial.print("."); }
  Serial.println();
}

inline void init_wifi_mqtt() {
  pinMode(FLASH_GPIO_NUM, OUTPUT);
  digitalWrite(FLASH_GPIO_NUM, LOW);
  Serial.printf("[WiFi] connecting to %s ...\n", g_cfg.wifiSsid.c_str());
  WiFi.mode(WIFI_STA);
  WiFi.begin(g_cfg.wifiSsid.c_str(), g_cfg.wifiPass.c_str());
  WiFi.setTxPower(WIFI_POWER_8_5dBm);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 30000) { delay(400); Serial.print("."); }
  Serial.printf("\n[WiFi] %s  IP=%s\n",
                WiFi.status() == WL_CONNECTED ? "connected" : "TIMEOUT",
                WiFi.localIP().toString().c_str());
  init_time();
#if TLS_INSECURE
  secureClient.setInsecure();
#else
  secureClient.setInsecure();  // replace with secureClient.setCACert(...) for production
#endif
  client.setServer(g_cfg.mqttHost.c_str(), g_cfg.mqttPort);
  client.setCallback(mqtt_callback);
  client.setBufferSize(1024);
  client.setKeepAlive(30);
}

inline void mqtt_service() {
  if (client.connected()) { client.loop(); return; }
  if (millis() < g_mqtt_next_attempt) return;
  g_mqtt_next_attempt = millis() + 5000;
  String cid = "eagle-" + g_cfg.deviceId + "-" + String((uint32_t)esp_random(), HEX);
  String willTopic = topic_status();
  const char *willMsg = "{\"online\":false}";
  Serial.print("[MQTT] connecting...");
  if (client.connect(cid.c_str(), g_cfg.mqttUser.c_str(), g_cfg.mqttPass.c_str(),
                     willTopic.c_str(), 1, true, willMsg)) {
    Serial.println("ok");
    client.subscribe(topic_cmd().c_str(), 1);
    publish_status();
  } else {
    Serial.printf("failed rc=%d (retry in 5s)\n", client.state());
  }
}

inline void capture_and_send_image(float score) {
  if (!is_system_armed) { Serial.println("[CAP] disarmed - skip"); return; }
  g_mode = MODE_UPLOADING;
  digitalWrite(FLASH_GPIO_NUM, HIGH);
  delay(300);
  camera_fb_t *flush = esp_camera_fb_get();
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
    firebase_push_alert(url, pid, score);
    ingest_alert(url, pid, score);
    EE_JSON(a, 384);
    a["ts"] = (uint32_t)time(nullptr);
    a["image_url"] = url; a["public_id"] = pid;
    a["score"] = score;   a["type"] = "Human Detected";
    char buf[384]; size_t n = serializeJson(a, buf);
    client.publish(topic_alert().c_str(), (const uint8_t *)buf, n, false);
  }
  free(jpg);
  g_mode = MODE_AI;
}

// ============================================================
//  LAN CONTROL — direct low-latency servo control (ws://<ip>:81)
// ============================================================
#define LANCTRL_PORT 81
WebSocketsServer lanCtrl(LANCTRL_PORT);

inline void lanctrl_event(uint8_t num, WStype_t type, uint8_t *payload, size_t len) {
  if (type == WStype_CONNECTED) { Serial.printf("[LAN] viewer %u connected\n", num); return; }
  if (type != WStype_TEXT || !payload) return;
  EE_JSON(d, 128);
  if (deserializeJson(d, payload, len)) return;
  if (strcmp(d["type"] | "", "servo") != 0) return;
  int pan  = d["pan"]  | (d["angle"] | -1);
  int tilt = d["tilt"] | -1;
  if (pan  >= 0) set_pan(pan);
  if (tilt >= 0) set_tilt(tilt);
  g_last_cmd_ms = millis();
}

inline void lanctrl_begin() {
  lanCtrl.begin();
  lanCtrl.onEvent(lanctrl_event);
  Serial.printf("[LAN] servo control on ws://%s:%d/\n",
                WiFi.localIP().toString().c_str(), LANCTRL_PORT);
}

inline void lanctrl_service() { lanCtrl.loop(); }

// ============================================================
//  RELAY — live video via cloud WebSocket (Plane 2)
// ============================================================
#define EAGLEEYE_RELAY_FRAME_MS   80
#define EAGLEEYE_RELAY_MAX_MS     300000

WebSocketsClient  relayWs;
bool          g_relay_connected  = false;
unsigned long g_relay_last_frame = 0;
unsigned long g_relay_started_at = 0;

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
      client.publish(topic_stream().c_str(), "{\"ready\":true}", false);
      break;
    case WStype_DISCONNECTED:
      g_relay_connected = false;
      Serial.println("[RELAY] disconnected");
      break;
    case WStype_TEXT:
      if (payload && (strstr((char *)payload, "no-viewers") || strstr((char *)payload, "stop")))
        g_req_stream_off = true;
      break;
    default: break;
  }
}

inline void relay_start() {
  Serial.println("[RELAY] starting...");
  g_mode = MODE_RELAY;
  String token = relay_get_token();
  String path  = "/cam/" + g_cfg.deviceId + (token.length() ? ("?token=" + token) : "");
  relayWs.beginSSL(g_cfg.relayHost.c_str(), g_cfg.relayPort, path.c_str());
  relayWs.onEvent(relay_event);
  relayWs.setReconnectInterval(3000);
  g_relay_started_at = millis();
  g_relay_last_frame = 0;
}

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
    Serial.printf("[RELAY] jpeg grab failed (free internal heap=%u)\n",
                  (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
  }
}

inline void relay_stop() {
  Serial.println("[RELAY] stopping...");
  relayWs.disconnect();
  g_relay_connected = false;
  g_mode = MODE_AI;
}

// ============================================================
//  OTA — HTTPS firmware update triggered by MQTT cmd
// ============================================================
inline void ota_perform(const String &url) {
  if (url.length() == 0) return;
  Serial.printf("[OTA] updating from %s\n", url.c_str());
  WiFiClientSecure tls;
  tls.setInsecure(); tls.setTimeout(20);
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

// ============================================================
//  PROVISIONING — Wi-Fi captive-portal setup (Phase 4)
// ============================================================
#if ENABLE_PROVISIONING
#include <WiFiManager.h>
inline bool provision_begin() {
  WiFiManager wm;
  char portBuf[8]; snprintf(portBuf, sizeof(portBuf), "%u", g_cfg.mqttPort);
  WiFiManagerParameter p_dev   ("dev",    "Device ID",       g_cfg.deviceId.c_str(),  32);
  WiFiManagerParameter p_host  ("mhost",  "MQTT host",       g_cfg.mqttHost.c_str(),  96);
  WiFiManagerParameter p_port  ("mport",  "MQTT port",       portBuf,                   8);
  WiFiManagerParameter p_user  ("muser",  "MQTT user",       g_cfg.mqttUser.c_str(),  48);
  WiFiManagerParameter p_pass  ("mpass",  "MQTT pass",       g_cfg.mqttPass.c_str(),  64);
  WiFiManagerParameter p_cloud ("ccloud", "Cloudinary name", g_cfg.cldCloud.c_str(),  48);
  WiFiManagerParameter p_preset("cpre",   "Upload preset",   g_cfg.cldPreset.c_str(), 48);
  WiFiManagerParameter p_relay ("relay",  "Relay host",      g_cfg.relayHost.c_str(), 96);
  wm.addParameter(&p_dev);  wm.addParameter(&p_host); wm.addParameter(&p_port);
  wm.addParameter(&p_user); wm.addParameter(&p_pass); wm.addParameter(&p_cloud);
  wm.addParameter(&p_preset); wm.addParameter(&p_relay);
  bool ok = wm.autoConnect("EagleEye-Setup");
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
#else
inline bool provision_begin() { return false; }
#endif

// ============================================================
//  MAIN — AI buffers, servo entry-points, setup(), loop()
// ============================================================
static uint8_t *snapshot_buf = nullptr;
unsigned long frame_count = 0;
bool image_sent_this_event = false;
int  clear_scene_count = 0;
unsigned long g_status_next = 0;

static int ee_get_data_cb(size_t offset, size_t length, float *out_ptr) {
  size_t px = offset * 3;
  for (size_t i = 0; i < length; i++) {
    out_ptr[i] = (snapshot_buf[px] << 16) + (snapshot_buf[px + 1] << 8) + snapshot_buf[px + 2];
    px += 3;
  }
  return 0;
}

void resize_rgb565_to_rgb888(uint8_t *src, int sw, int sh, uint8_t *dst, int dw, int dh) {
  int crop = sh; int ox = (sw - crop) / 2;
  int di = 0;
  for (int y = 0; y < dh; y++) {
    for (int x = 0; x < dw; x++) {
      int sx = ox + (x * crop / dw); int sy = (y * sh / dh);
      if (sx >= sw) sx = sw - 1; if (sy >= sh) sy = sh - 1;
      int idx = (sy * sw + sx) * 2;
      uint16_t p = (src[idx] << 8) | src[idx + 1];
      uint8_t r = (p >> 11) & 0x1F, g = (p >> 5) & 0x3F, b = p & 0x1F;
      dst[di++] = (r << 3) | (r >> 2);
      dst[di++] = (g << 2) | (g >> 4);
      dst[di++] = (b << 3) | (b >> 2);
    }
  }
}

void eagleeye_send_servo(int angle) {
  set_pan(angle);
  Serial.printf(">>> pan  -> %d\n", servo_clamp(angle));
}
void eagleeye_send_tilt(int angle) {
  set_tilt(angle);
  Serial.printf(">>> tilt -> %d\n", servo_clamp(angle));
}

void run_ai_step() {
  mqtt_service();
  lanctrl_service();
  if (g_req_servo_angle >= 0 || g_req_tilt_angle >= 0 || millis() - g_last_cmd_ms < 2500) return;

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) { Serial.println("[AI] capture failed"); delay(80); return; }
  resize_rgb565_to_rgb888(fb->buf, fb->width, fb->height, snapshot_buf, IMG_WIDTH, IMG_HEIGHT);
  esp_camera_fb_return(fb);

  ee_signal_t signal;
  signal.total_length = IMG_WIDTH * IMG_HEIGHT;
  signal.get_data = &ee_get_data_cb;
  ee_inference_result_t result = { 0 };
  if (ee_run_inference(&signal, &result, false) != EE_INFERENCE_OK) { Serial.println("[AI] classify err"); return; }

  float human = 0.f, nonhuman = 0.f;
  for (uint16_t i = 0; i < EE_MODEL_LABEL_COUNT; i++) {
    if (!strcmp(result.classification[i].label, "human")) human = result.classification[i].value;
    else nonhuman = result.classification[i].value;
  }
  frame_count++;
  bool detected = (human >= HUMAN_THRESHOLD && human > nonhuman);

  if (detected) {
    clear_scene_count = 0;
    Serial.printf("[AI %lu] HUMAN H=%.3f N=%.3f\n", frame_count, human, nonhuman);
    if (!image_sent_this_event) { capture_and_send_image(human); image_sent_this_event = true; }
  } else {
    Serial.printf("[AI %lu] no human  H=%.3f N=%.3f\n", frame_count, human, nonhuman);
    if (image_sent_this_event && ++clear_scene_count >= CLEAR_SCENE_FRAMES) {
      image_sent_this_event = false; clear_scene_count = 0;
      Serial.println("[AI] scene cleared - re-armed for next detection");
    }
  }
}

void servo_core0_task(void *pv) {
  for (;;) {
    servos_service();
    vTaskDelay(pdMS_TO_TICKS(3));
  }
}

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
  Serial.begin(115200);
  delay(400);
  Serial.println("\n=== EagleEye CLOUD build ===");

  config_load();
  Serial.printf("[cfg] deviceId=%s mqtt=%s:%u\n", g_cfg.deviceId.c_str(), g_cfg.mqttHost.c_str(), g_cfg.mqttPort);

#if ENABLE_PROVISIONING
  provision_begin();
#endif

  snapshot_buf = (uint8_t *)malloc(IMG_WIDTH * IMG_HEIGHT * 3);
  if (!snapshot_buf) { Serial.println("[FATAL] snapshot alloc failed"); while (1) delay(1000); }

  if (!setup_camera_ai()) { Serial.println("[FATAL] camera init failed"); while (1) delay(1000); }

  servos_begin();
  init_wifi_mqtt();
  lanctrl_begin();

  xTaskCreatePinnedToCore(servo_core0_task, "servoCtl", 4096, NULL, 2, NULL, 0);

  Serial.printf("[heap] free internal=%u  PSRAM=%u\n",
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
  Serial.printf("[model] %s v%d  %dx%d  ESP-NN=%d\n",
                EE_MODEL_NAME, EE_MODEL_VERSION,
                IMG_WIDTH, IMG_HEIGHT, EE_MODEL_ESP_NN);

#if STREAM_AUTOSTART
  Serial.println("[DEBUG] STREAM_AUTOSTART=1 -> opening relay on boot");
  g_req_stream_on = true;
#endif
}

void loop() {
  mqtt_service();
  lanctrl_service();

  if (client.connected() && millis() > g_status_next) { g_status_next = millis() + 15000; publish_status(); }

  if (g_req_factory_reset) { Serial.println("[CMD] factory reset"); config_factory_reset(); delay(200); ESP.restart(); }
  if (g_req_servo_angle >= 0) { eagleeye_send_servo(g_req_servo_angle); g_req_servo_angle = -1; }
  if (g_req_tilt_angle  >= 0) { eagleeye_send_tilt(g_req_tilt_angle);   g_req_tilt_angle  = -1; }
#if ENABLE_OTA
  if (g_req_ota_url.length() && g_mode == MODE_AI) { String u = g_req_ota_url; g_req_ota_url = ""; ota_perform(u); }
#endif
  if (g_req_stream_on)  { g_req_stream_on = false;  if (g_mode != MODE_RELAY) relay_start(); }
  if (g_req_stream_off) { g_req_stream_off = false; if (g_mode == MODE_RELAY) relay_stop();  }

  if (g_mode == MODE_RELAY)    { relay_loop(); return; }
  if (g_mode == MODE_UPLOADING) { delay(2); return; }
  if (millis() - g_last_cmd_ms < 2500) { delay(5); return; }

  run_ai_step();
}
