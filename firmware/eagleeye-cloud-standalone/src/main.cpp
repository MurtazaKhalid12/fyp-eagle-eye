/*
 * EagleEye CLOUD — main.cpp (modular build)
 *
 * Plane 1 : MQTT-over-TLS (HiveMQ)   control / status / alerts
 * Plane 2 : on-demand live video via cloud WebSocket relay
 * Direct HTTPS upload to Cloudinary + Firebase RTDB alert
 * Phase 4 : Wi-Fi provisioning portal, HTTPS OTA, TLS hardening
 *
 * Inference: standalone TFLite Micro (eagleeye_inference.h / model_data.h)
 *            No Edge Impulse SDK dependency.
 *
 * PIR (GPIO2 / PIR_PIN): after CLEAR_SCENE_FRAMES consecutive no-human
 *   frames the CPU enters deep sleep (ext0 wakeup on GPIO2 HIGH).
 *   RTC RAM preserves boot count and armed-state across sleep cycles.
 */

// ── System headers ──────────────────────────────────────────────────────────
#include <Arduino.h>
#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "esp_sleep.h"
#include "img_converters.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include <ArduinoJson.h>

// Must be defined before any module header that calls EE_JSON()
#if ARDUINOJSON_VERSION_MAJOR >= 7
  #define EE_JSON(name, cap) JsonDocument name
#else
  #define EE_JSON(name, cap) StaticJsonDocument<cap> name
#endif

#define EE_MODEL_NAME "EagleEye CNN v7.16"

// ── Project headers (order matters — see comments) ──────────────────────────
#include "config.h"               // credentials, feature flags, FW_VERSION
#include "eagleeye_inference.h"   // eagleeye_init(), eagleeye_classify()
#include "model_data.h"           // EAGLEEYE_INPUT_WIDTH/HEIGHT, ARENA_SIZE, …
#include "eagleeye_camera.h"      // DeviceMode, setup_camera_ai(), switch_camera_*()
#include "eagleeye_servos.h"      // servos_begin(), set_pan/tilt(), servos_service()
#include "eagleeye_pir.h"         // pir_begin(), pir_configure_wakeup(), pir_is_wakeup_source()
#include "eagleeye_upload.h"      // cloudinary_upload(), firebase_push_alert(), ingest_alert()
#include "EagleEye_Cloud_IoT.h"   // WiFi/MQTT; includes camera, upload, oled transitively
#include "eagleeye_lanctrl.h"     // LAN WebSocket servo control (needs servos + Cloud_IoT)
#include "eagleeye_relay.h"       // live-video relay (needs Cloud_IoT + upload)
#include "eagleeye_ota.h"         // ota_perform()
#include "eagleeye_provision.h"   // provision_begin()
#include "esp-nnc.h"                // ESP-NN compatibility header (for TFLite Micro)

// ── AI constants ─────────────────────────────────────────────────────────────
#define IMG_WIDTH          EAGLEEYE_INPUT_WIDTH    // 96
#define IMG_HEIGHT         EAGLEEYE_INPUT_HEIGHT   // 96
#define HUMAN_THRESHOLD    0.6f
#define CLEAR_SCENE_FRAMES 20

// ── RTC RAM — survives deep sleep ────────────────────────────────────────────
RTC_DATA_ATTR static uint32_t g_boot_count = 0;
RTC_DATA_ATTR static bool     g_rtc_armed  = true;

// ── AI state ─────────────────────────────────────────────────────────────────
static uint8_t      *snapshot_buf         = nullptr;
static bool          image_sent_this_event = false;
static int           clear_scene_count    = 0;
static unsigned long frame_count          = 0;
static unsigned long g_status_next        = 0;

// ── Helpers ──────────────────────────────────────────────────────────────────

// Resize RGB565 QVGA (320×240) → 96×96 RGB888 via square center-crop.
static void resize_rgb565_to_rgb888(uint8_t *src, int sw, int sh,
                                     uint8_t *dst, int dw, int dh) {
  int crop = sh, ox = (sw - crop) / 2, di = 0;
  for (int y = 0; y < dh; y++) {
    for (int x = 0; x < dw; x++) {
      int sx = ox + (x * crop / dw), sy = y * sh / dh;
      if (sx >= sw) sx = sw - 1;
      if (sy >= sh) sy = sh - 1;
      int      idx = (sy * sw + sx) * 2;
      uint16_t p   = ((uint16_t)src[idx] << 8) | src[idx + 1];
      uint8_t  r   = (p >> 11) & 0x1F;
      uint8_t  g   = (p >>  5) & 0x3F;
      uint8_t  b   =  p        & 0x1F;
      dst[di++] = (r << 3) | (r >> 2);
      dst[di++] = (g << 2) | (g >> 4);
      dst[di++] = (b << 3) | (b >> 2);
    }
  }
}

// Servo entry-points declared in EagleEye_Cloud_IoT.h; implemented here.
void eagleeye_send_servo(int angle) {
  set_pan(angle);
  Serial.printf(">>> pan  -> %d\n", servo_clamp(angle));
}
void eagleeye_send_tilt(int angle) {
  set_tilt(angle);
  Serial.printf(">>> tilt -> %d\n", servo_clamp(angle));
}

// Cleanly disconnect, release camera, then enter deep sleep.
// GPIO2 (PIR) HIGH wakes the device.
static void enter_deep_sleep() {
  Serial.printf("[SLEEP] %d no-human frames — entering deep sleep\n", CLEAR_SCENE_FRAMES);
  Serial.printf("[SLEEP] GPIO%d (PIR) HIGH will wake device\n", PIR_PIN);
  oled_show_sleeping();
  Serial.flush();
  client.disconnect();
  esp_camera_deinit();
  pir_configure_wakeup();   // ext0 wakeup on GPIO2 HIGH
  esp_deep_sleep_start();
}

// ── AI loop step ─────────────────────────────────────────────────────────────
static void run_ai_step() {
  // Pause AI while a servo command is in-flight (keeps motion smooth).
  if (g_req_servo_angle >= 0 || g_req_tilt_angle >= 0 ||
      millis() - g_last_cmd_ms < 2500) return;

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) { Serial.println("[AI] capture failed"); delay(80); return; }
  resize_rgb565_to_rgb888(fb->buf, fb->width, fb->height,
                           snapshot_buf, IMG_WIDTH, IMG_HEIGHT);
  esp_camera_fb_return(fb);

  float human = 0.f, nonhuman = 0.f;
  if (!eagleeye_classify(snapshot_buf, &human, &nonhuman)) {
    Serial.println("[AI] classify err"); return;
  }

  frame_count++;
  bool detected = (human >= HUMAN_THRESHOLD && human > nonhuman);

  if (detected) {
    clear_scene_count = 0;
    Serial.printf("[AI %lu] HUMAN    H=%.3f N=%.3f\n", frame_count, human, nonhuman);
    oled_show_alert(human);
    if (!image_sent_this_event) {
      capture_and_send_image(human);
      image_sent_this_event = true;
    }
  } else {
    Serial.printf("[AI %lu] no human  H=%.3f N=%.3f\n", frame_count, human, nonhuman);
    oled_clear_alert();
    if (++clear_scene_count >= CLEAR_SCENE_FRAMES) {
      image_sent_this_event = false;
      enter_deep_sleep();   // PIR will wake us when motion is detected again
    }
  }
}

// ── FreeRTOS servo task (Core 0) ─────────────────────────────────────────────
static void servo_core0_task(void *) {
  for (;;) { servos_service(); vTaskDelay(pdMS_TO_TICKS(3)); }
}

// ── setup() ──────────────────────────────────────────────────────────────────
void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);   // suppress brown-out detector on startup spike
  Serial.begin(115200);
  delay(400);

  g_boot_count++;
  bool from_pir = pir_is_wakeup_source();
  Serial.printf("\n=== EagleEye CLOUD  boot#%u  wakeup=%s ===\n",
                g_boot_count, from_pir ? "PIR" : "cold");

  is_system_armed = g_rtc_armed;   // restore armed state from RTC RAM

  config_load();
  Serial.printf("[cfg] deviceId=%s  mqtt=%s:%u\n",
                g_cfg.deviceId.c_str(), g_cfg.mqttHost.c_str(), g_cfg.mqttPort);

  oled_begin(EE_MODEL_NAME);
  if (from_pir) oled_log("PIR Wakeup");

#if ENABLE_PROVISIONING
  provision_begin();
#endif

  snapshot_buf = (uint8_t *)malloc(IMG_WIDTH * IMG_HEIGHT * 3);
  if (!snapshot_buf) {
    Serial.println("[FATAL] snapshot alloc failed");
    oled_log("FATAL: no heap");
    while (1) delay(1000);
  }

  if (!setup_camera_ai()) {
    Serial.println("[FATAL] camera init failed");
    oled_log("FATAL: camera");
    while (1) delay(1000);
  }
  if (!eagleeye_init()) {
    Serial.println("[FATAL] model init failed");
    oled_log("FATAL: model");
    while (1) delay(1000);
  }

  servos_begin();
  pir_begin();
  init_wifi_mqtt();
  lanctrl_begin();

  xTaskCreatePinnedToCore(servo_core0_task, "servoCtl", 4096, NULL, 2, NULL, 0);

  Serial.printf("[heap] internal=%u  PSRAM=%u\n",
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
  Serial.printf("[model] %s v%d  %dx%d  PIR=GPIO%d  wakeup=%s\n",
                EE_MODEL_NAME, EAGLEEYE_MODEL_VERSION,
                IMG_WIDTH, IMG_HEIGHT, PIR_PIN,
                from_pir ? "PIR" : "cold");

#if STREAM_AUTOSTART
  g_req_stream_on = true;
#endif
}

// ── loop() ───────────────────────────────────────────────────────────────────
void loop() {
  mqtt_service();
  lanctrl_service();
  oled_tick();

  if (client.connected() && millis() > g_status_next) {
    g_status_next = millis() + 15000;
    publish_status();
  }

  if (g_req_factory_reset) {
    Serial.println("[CMD] factory reset");
    config_factory_reset(); delay(200); ESP.restart();
  }
  if (g_req_servo_angle >= 0) { eagleeye_send_servo(g_req_servo_angle); g_req_servo_angle = -1; }
  if (g_req_tilt_angle  >= 0) { eagleeye_send_tilt(g_req_tilt_angle);   g_req_tilt_angle  = -1; }

#if ENABLE_OTA
  if (g_req_ota_url.length() && g_mode == MODE_AI) {
    String u = g_req_ota_url; g_req_ota_url = "";
    ota_perform(u);
  }
#endif

  if (g_req_stream_on)  { g_req_stream_on  = false; if (g_mode != MODE_RELAY) relay_start(); }
  if (g_req_stream_off) { g_req_stream_off = false; if (g_mode == MODE_RELAY) relay_stop();  }

  if (g_mode == MODE_RELAY)     { relay_loop(); return; }
  if (g_mode == MODE_UPLOADING) { delay(2);     return; }
  if (millis() - g_last_cmd_ms < 2500) { delay(5); return; }

  run_ai_step();
}
