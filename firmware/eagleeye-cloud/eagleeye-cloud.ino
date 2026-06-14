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
 *  Camera modes share one sensor (MODE_AI = RGB565 for the classifier,
 *  MODE_RELAY = hardware JPEG for streaming). Only ONE TLS-heavy task
 *  runs at a time (see README "TLS memory").
 *
 *  Fill in config.h before flashing. Required Arduino libraries:
 *    PubSubClient, ArduinoJson, WebSockets (Links2004),
 *    eagleeye_inferencing (v7.16 RGB, ESP-NN), [WiFiManager only if provisioning].
 * ============================================================
 */
#include <Arduino.h>
#include "esp_camera.h"
#include <eagleeye_inferencing.h>       // EagleEye v7.16 human detection (96x96 RGB, ESP-NN)
#include "esp_heap_caps.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

#include "config.h"
#include "eagleeye_camera.h"
#include "eagleeye_servos.h"          // 2 servos + PIR, driven on the main board
#include "EagleEye_Cloud_IoT.h"
#include "eagleeye_lanctrl.h"         // direct-LAN low-latency servo control (needs servos + IoT)
#include "eagleeye_relay.h"
#include "eagleeye_ota.h"
#include "eagleeye_provision.h"

// --- AI config (from the EI library metadata) ---
#define IMG_WIDTH          EI_CLASSIFIER_INPUT_WIDTH   // 96
#define IMG_HEIGHT         EI_CLASSIFIER_INPUT_HEIGHT  // 96
#define HUMAN_THRESHOLD    0.6f
#define CLEAR_SCENE_FRAMES 20

// --- servo command entry points (called by mqtt_callback) ---
//  Two servos driven directly on this board: PAN=GPIO15, TILT=GPIO14
//  (see eagleeye_servos.h). The smooth stepper runs in servos_service().
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

static int ei_get_data_cb(size_t offset, size_t length, float *out_ptr) {
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

  ei::signal_t signal;
  signal.total_length = IMG_WIDTH * IMG_HEIGHT;
  signal.get_data = &ei_get_data_cb;
  ei_impulse_result_t result = { 0 };
  if (run_classifier(&signal, &result, false) != EI_IMPULSE_OK) { Serial.println("[AI] classify err"); return; }

  float human = 0.f, nonhuman = 0.f;
  for (uint16_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
    if (!strcmp(result.classification[i].label, "human")) human = result.classification[i].value;
    else nonhuman = result.classification[i].value;
  }
  frame_count++;
  bool detected = (human >= HUMAN_THRESHOLD && human > nonhuman);

  if (detected) {
    clear_scene_count = 0;
    Serial.printf("[AI %lu] HUMAN H=%.3f N=%.3f\n", frame_count, human, nonhuman);
    if (!image_sent_this_event) {
      capture_and_send_image(human);                 // upload + alert (cloud)
      image_sent_this_event = true;
    }
  } else {
    Serial.printf("[AI %lu] no human  H=%.3f N=%.3f\n", frame_count, human, nonhuman);
    if (image_sent_this_event && ++clear_scene_count >= CLEAR_SCENE_FRAMES) {
      image_sent_this_event = false; clear_scene_count = 0;
      Serial.println("[AI] scene cleared - re-armed for next detection");
    }
  }
}

// ---------------------------------------------------------------
//  Core-0 servo task — runs the LAN control server and the smooth
//  servo stepper at a fixed ~330 Hz, fully independent of the main
//  loop() on Core 1. This is what makes pan/tilt stay smooth and
//  low-latency even while Core 1 is busy pushing video frames / AI.
//  (LEDC PWM writes are hardware, so driving servos from Core 0 is
//  safe; servo targets are plain ints — atomic across cores.)
// ---------------------------------------------------------------
void servo_core0_task(void *pv) {
  for (;;) {
    // ONLY the LEDC servo stepper runs here — no WebSocket/lwIP calls. The LAN
    // and relay WebSocket servers both stay on Core 1 (serialized) because the
    // Links2004 library is not safe to drive from two cores concurrently.
    servos_service();                  // smooth-step both servos toward their targets (LEDC only)
    vTaskDelay(pdMS_TO_TICKS(3));      // ~330 Hz stepper; yields to WiFi/idle (watchdog-safe)
  }
}

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);           // brownout band-aid (fix power for real)
  Serial.begin(115200);
  delay(400);
  Serial.println("\n=== EagleEye CLOUD build ===");

  config_load();
  Serial.printf("[cfg] deviceId=%s mqtt=%s:%u\n", g_cfg.deviceId.c_str(), g_cfg.mqttHost.c_str(), g_cfg.mqttPort);

#if ENABLE_PROVISIONING
  provision_begin();                                   // captive portal if unconfigured
#endif

  snapshot_buf = (uint8_t *)malloc(IMG_WIDTH * IMG_HEIGHT * 3);
  if (!snapshot_buf) { Serial.println("[FATAL] snapshot alloc failed"); while (1) delay(1000); }

  if (!setup_camera_ai()) { Serial.println("[FATAL] camera init failed"); while (1) delay(1000); }

  servos_begin();                                      // 2 servos (GPIO15/14) + PIR (GPIO13), camera-safe timers

  init_wifi_mqtt();                                    // WiFi + SNTP + secure MQTT
  lanctrl_begin();                                     // direct-LAN servo control (ws://<ip>:81)

  // Pin the servo stepper to Core 0 so video streaming / AI on Core 1 can never
  // starve servo motion (smooth PTZ). Tiny task — only LEDC writes — 4 KB stack.
  xTaskCreatePinnedToCore(servo_core0_task, "servoCtl", 4096, NULL, 2, NULL, 0);

  Serial.printf("[heap] free internal=%u  PSRAM=%u\n",
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
  Serial.printf("[model] %s v%d  %dx%d  ESP-NN=%d\n",
                EI_CLASSIFIER_PROJECT_NAME, EI_CLASSIFIER_PROJECT_DEPLOY_VERSION,
                IMG_WIDTH, IMG_HEIGHT, EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN);

#if STREAM_AUTOSTART
  Serial.println("[DEBUG] STREAM_AUTOSTART=1 -> opening relay on boot (no MQTT/app needed)");
  g_req_stream_on = true;     // loop() picks this up and calls relay_start()
#endif
}

void loop() {
  mqtt_service();                                      // pump + non-blocking reconnect (cloud fallback)
  lanctrl_service();                                   // direct-LAN command RX (Core 1, serialized w/ relay)
  // Servo MOTION runs on a dedicated Core-0 task (servo_core0_task) so streaming
  // on Core 1 can't make it stutter. Only the LEDC stepper is on Core 0 — both
  // WebSocket endpoints stay on Core 1 to avoid a cross-core library race.

  // periodic status refresh (rssi/armed) so the app stays current
  if (client.connected() && millis() > g_status_next) { g_status_next = millis() + 15000; publish_status(); }

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
  if (g_mode == MODE_RELAY) { relay_loop(); return; } // stream; AI paused
  if (g_mode == MODE_UPLOADING) { delay(2); return; } // capture is synchronous; just idle

  // While the user is actively panning, skip the ~0.8 s AI inference for a short
  // window so the loop spins fast (MQTT pumped every ~5 ms, servo steps smoothly,
  // commands act with minimal lag). AI resumes ~2.5 s after the last command.
  if (millis() - g_last_cmd_ms < 2500) { delay(5); return; }

  run_ai_step();                                       // MODE_AI
}
