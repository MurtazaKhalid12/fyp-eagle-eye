/*
 * ============================================================
 *  EagleEye — CLOUD build (remote: camera at a site, phone anywhere)
 * ============================================================
 *  Separate from firmware/eagleeye-main/ (that LAN build is untouched).
 *
 *  Device dials OUT to the cloud and stays connected:
 *    - Plane 1: MQTT-over-TLS (HiveMQ) for control + status + alerts
 *    - Plane 2: on-demand live video via a cloud WebSocket relay
 *    - Direct HTTPS image upload to Cloudinary (no PC bridge)
 *    - Phase 4: Wi-Fi setup portal, HTTPS OTA, TLS hardening
 *
 *  Power mode: ALWAYS ON (deep sleep disabled for now). The device stays awake
 *    running AI / MQTT / video continuously. PIR is wired but not used to wake.
 *
 *  Camera modes share one sensor (MODE_AI = RGB565 for the classifier,
 *  MODE_RELAY = hardware JPEG for streaming). Only ONE TLS-heavy task
 *  runs at a time (see README "TLS memory").
 *
 *  Fill in config.h before flashing. Required Arduino libraries:
 *    PubSubClient, ArduinoJson, WebSockets (Links2004),
 *    eagleeye_vision (v7.16 RGB, ESP-NN), [WiFiManager only if provisioning].
 * ============================================================
 */
#include <Arduino.h>
#include "esp_camera.h"
#include <eagleeye_vision.h>            // EagleEye v7.16 human detection (96x96 RGB, ESP-NN)
#include "esp_heap_caps.h"
#include "esp_sleep.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

#include "config.h"
#include "eagleeye_camera.h"
#include "eagleeye_servos.h"          // 2 servos: PAN=GPIO12  TILT=GPIO14
#include "eagleeye_oled.h"
#include "eagleeye_pir.h"
#include "EagleEye_Cloud_IoT.h"
#include "eagleeye_lanctrl.h"         // direct-LAN low-latency servo control (needs servos + IoT)
#include "eagleeye_relay.h"
#include "eagleeye_ota.h"
#include "eagleeye_provision.h"

// --- RTC RAM: survives deep sleep (reset on power-cycle or flash) ---
RTC_DATA_ATTR static uint32_t g_boot_count = 0;
RTC_DATA_ATTR static bool     g_rtc_armed  = true;  // armed state across sleep cycles

// --- EagleEye inference API (wraps eagleeye-sdk internals so application code stays EI-free) ---
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

// --- AI config (from the EagleEye vision library metadata) ---
#define IMG_WIDTH          EE_MODEL_INPUT_WIDTH    // 96
#define IMG_HEIGHT         EE_MODEL_INPUT_HEIGHT   // 96
#define HUMAN_THRESHOLD    0.6f
#define CLEAR_SCENE_FRAMES 20

// --- servo command entry points (called by mqtt_callback) ---
//  PAN=GPIO12  TILT=GPIO14  (see eagleeye_servos.h)
void eagleeye_send_servo(int angle) {       // PAN
  set_pan(angle);
  Serial.printf(">>> pan  -> %d\n", servo_clamp(angle));
}
void eagleeye_send_tilt(int angle) {        // TILT
  set_tilt(angle);
  Serial.printf(">>> tilt -> %d\n", servo_clamp(angle));
}

// --- AI buffers/state ---
static uint8_t *snapshot_buf = nullptr;                // IMG_WIDTH*IMG_HEIGHT*3
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

// 320x240 RGB565 -> center-crop 240x240 -> 96x96 RGB888 (same as eagleeye-main)
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

// One AI frame (MODE_AI only).
void run_ai_step() {
  // Pull any pending cloud command BEFORE the ~0.8 s inference. If the user is
  // panning/tilting, skip this inference so the servo reacts now instead of one
  // full inference late — loop() then services the servo and stays in the fast
  // window. This is the single biggest cut to joystick latency.
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
    oled_fullscreen_human(human);
    Serial.printf("[AI %lu] HUMAN H=%.3f N=%.3f\n", frame_count, human, nonhuman);
    if (!image_sent_this_event) {
      capture_and_send_image(human);                 // upload + alert (cloud)
      image_sent_this_event = true;
    }
  } else {
    oled_fullscreen_no_human();
    Serial.printf("[AI %lu] no human  H=%.3f N=%.3f\n", frame_count, human, nonhuman);
    if (image_sent_this_event && ++clear_scene_count >= CLEAR_SCENE_FRAMES) {
      image_sent_this_event = false; clear_scene_count = 0;
      Serial.println("[AI] scene cleared - re-armed for next detection");
      oled_fullscreen_scene_cleared();
    }
  }
}

// ---------------------------------------------------------------
//  Core-0 servo task — runs the smooth servo stepper at ~330 Hz,
//  independent of Core 1 (AI/MQTT/video). Only LEDC writes happen
//  here; both WebSocket servers stay on Core 1 (not thread-safe).
// ---------------------------------------------------------------
void servo_core0_task(void *pv) {
  for (;;) {
    servos_service();
    vTaskDelay(pdMS_TO_TICKS(3));
  }
}

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);           // brownout band-aid (fix power for real)
  Serial.begin(115200);
  delay(400);

  g_boot_count++;
  bool from_pir = pir_is_wakeup_source();
  Serial.printf("\n=== EagleEye CLOUD build  boot#%u  wakeup=%s ===\n",
                g_boot_count, from_pir ? "PIR" : "cold");

  // Restore armed state from RTC RAM (survives across sleep cycles)
  is_system_armed = g_rtc_armed;

  // Initialize OLED first so every stage below shows on screen
  oled_begin(EE_MODEL_NAME);
  oled_set_system(is_system_armed ? "Armed" : "Disarmed");

  // Show wakeup reason on the event line
  {
    char bootMsg[22];
    snprintf(bootMsg, sizeof(bootMsg), from_pir ? "Wake #%u" : "Boot #%u", (unsigned)g_boot_count);
    oled_log(bootMsg);
  }

  config_load();
  Serial.printf("[cfg] deviceId=%s mqtt=%s:%u\n", g_cfg.deviceId.c_str(), g_cfg.mqttHost.c_str(), g_cfg.mqttPort);

#if ENABLE_PROVISIONING
  provision_begin();                                   // captive portal if unconfigured
#endif

  snapshot_buf = (uint8_t *)malloc(IMG_WIDTH * IMG_HEIGHT * 3);
  if (!snapshot_buf) { Serial.println("[FATAL] snapshot alloc failed"); while (1) delay(1000); }

  // Camera init AFTER oled_begin — camera driver reinstalls I2C0 for SCCB (GPIO26/27).
  // OLED uses Wire1 (I2C1) so it is unaffected.
  if (!setup_camera_ai()) { Serial.println("[FATAL] camera init failed"); while (1) delay(1000); }

  servos_begin();                                      // PAN=GPIO12  TILT=GPIO14
  pir_begin();                                         // PIR input on GPIO2

  init_wifi_mqtt();                                    // WiFi + SNTP + secure MQTT
  lanctrl_begin();                                     // direct-LAN servo control (ws://<ip>:81)

  // Pin the servo stepper to Core 0 so video/AI on Core 1 can never stall PTZ motion.
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

  oled_log("System Ready");
}

void loop() {
  oled_tick();                                         // spinner + alert flash animation
  mqtt_service();                                      // pump + non-blocking reconnect
  lanctrl_service();                                   // direct-LAN command RX (Core 1)

  // PIR is WAKE-ONLY: it boots the device from deep sleep (ext0, GPIO2 HIGH).
  // No PIR value/motion is printed to serial or shown on the OLED.

  // Periodic status refresh (rssi/armed) so the app stays current
  if (client.connected() && millis() > g_status_next) {
    g_status_next = millis() + 15000;
    publish_status();
  }

  // --- act on cloud commands (set by mqtt_callback) ---
  if (g_req_factory_reset) { Serial.println("[CMD] factory reset"); config_factory_reset(); delay(200); ESP.restart(); }
  if (g_req_servo_angle >= 0) { eagleeye_send_servo(g_req_servo_angle); g_req_servo_angle = -1; }
  if (g_req_tilt_angle  >= 0) { eagleeye_send_tilt(g_req_tilt_angle);   g_req_tilt_angle  = -1; }
#if ENABLE_OTA
  if (g_req_ota_url.length() && g_mode == MODE_AI) { String u = g_req_ota_url; g_req_ota_url = ""; ota_perform(u); }
#endif
  if (g_req_stream_on)  { g_req_stream_on = false;  if (g_mode != MODE_RELAY) relay_start(); }
  if (g_req_stream_off) { g_req_stream_off = false; if (g_mode == MODE_RELAY) relay_stop();  }

  // --- mode dispatch ---
  if (g_mode == MODE_RELAY)    { relay_loop(); return; }
  if (g_mode == MODE_UPLOADING){ delay(2);    return; }

  // Skip AI while joystick commands are flowing (keeps panning snappy)
  if (millis() - g_last_cmd_ms < 2500) { delay(5); return; }

  run_ai_step();                                       // MODE_AI
}
