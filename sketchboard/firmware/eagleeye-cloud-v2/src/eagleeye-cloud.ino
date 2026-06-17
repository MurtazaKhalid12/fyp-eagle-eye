/*
 * ============================================================
 *  EagleEye — CLOUD build  (fixed inference pipeline)
 * ============================================================
 *  Plane 1 : MQTT-over-TLS (HiveMQ) — control / status / alerts
 *  Plane 2 : on-demand live video via cloud WebSocket relay
 *  Direct HTTPS upload to Cloudinary  (no PC bridge)
 *  Phase 4 : Wi-Fi setup portal, HTTPS OTA
 *
 *  Inference: TFLite Micro (direct) + ESP-NN — pixel data is
 *  normalised /255 then quantised with the model's own input
 *  scale/zero-point.  Same pipeline as eagleeye_local_rgb.
 * ============================================================
 */

// ============================================================
//  External libraries
// ============================================================
#include <Arduino.h>
#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "img_converters.h"
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
#include <math.h>

// ============================================================
//  EagleEye inference engine  (TFLite Micro + ESP-NN)
// ============================================================
#include <eagleeye_inferencing.h>
#include "eagleeye-sdk/tensorflow/lite/micro/micro_interpreter.h"
#include "eagleeye-sdk/tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "eagleeye-sdk/tensorflow/lite/schema/schema_generated.h"
#include "model_data.h"          // g_model[] — EagleEye v7.16 RGB INT8 weights

// Alias the SDK's ESP-NN flag so application code uses EagleEye naming
#define EE_ESP_NN EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN

// ============================================================
//  Project config (credentials / feature flags)
// ============================================================
#include "config.h"
#include "eagleeye_camera.h"
#include "eagleeye_servos.h"
#include "EagleEye_Cloud_IoT.h"
#include "eagleeye_lanctrl.h"
#include "eagleeye_relay.h"
#include "eagleeye_ota.h"
#include "eagleeye_provision.h"

// ============================================================
//  AI model dimensions & threshold
// ============================================================
#define IMG_WIDTH          96
#define IMG_HEIGHT         96
#define HUMAN_THRESHOLD    0.6f
#define CLEAR_SCENE_FRAMES 20

// ============================================================
//  TFLite Micro state  (EagleEye-prefixed)
// ============================================================
namespace {
const tflite::Model*      ee_tflite_model       = nullptr;
tflite::MicroInterpreter* ee_tflite_interpreter = nullptr;
TfLiteTensor*             ee_model_input        = nullptr;
TfLiteTensor*             ee_model_output       = nullptr;
uint8_t*                  ee_tensor_arena        = nullptr;
constexpr int             EE_ARENA_SIZE          = 160 * 1024;
}

// ============================================================
//  AI buffers / state
// ============================================================
static uint8_t *ee_snapshot_buf = nullptr;   // IMG_WIDTH * IMG_HEIGHT * 3  (RGB888)
unsigned long ee_frame_count        = 0;
bool          ee_image_sent         = false;
int           ee_clear_scene_count  = 0;
unsigned long g_status_next         = 0;

// ============================================================
//  Servo entry-points  (called by mqtt_callback)
// ============================================================
void eagleeye_send_servo(int angle) {
  set_pan(angle);
  Serial.printf(">>> pan  -> %d\n", servo_clamp(angle));
}
void eagleeye_send_tilt(int angle) {
  set_tilt(angle);
  Serial.printf(">>> tilt -> %d\n", servo_clamp(angle));
}

// ============================================================
//  ee_crop_resize — RGB565 QVGA -> centre-crop 240x240 -> 96x96 RGB888
//  Matches eagleeye_local_rgb exactly: full 240px square → nearest-
//  neighbour resize to 96x96 so the model sees the same field of view
//  it was trained on.  offset_x = (320-240)/2 = 40px left margin.
// ============================================================
static void ee_crop_resize(const uint8_t *src, int sw, int sh,
                            uint8_t *dst, int dw, int dh) {
  int crop_w   = sh;                    // 240 — use full height as square side
  int offset_x = (sw - crop_w) / 2;    // 40
  for (int y = 0; y < dh; y++) {
    for (int x = 0; x < dw; x++) {
      int sx = offset_x + (x * crop_w / dw);
      int sy = (y * sh / dh);
      if (sx >= sw) sx = sw - 1;
      if (sy >= sh) sy = sh - 1;
      int      idx = (sy * sw + sx) * 2;
      uint16_t pix = ((uint16_t)src[idx] << 8) | src[idx + 1];
      uint8_t  r   = (pix >> 11) & 0x1F;
      uint8_t  g   = (pix >>  5) & 0x3F;
      uint8_t  b   =  pix        & 0x1F;
      r = (r << 3) | (r >> 2);
      g = (g << 2) | (g >> 4);
      b = (b << 3) | (b >> 2);
      int di  = (y * dw + x) * 3;
      dst[di] = r; dst[di + 1] = g; dst[di + 2] = b;
    }
  }
}

// ============================================================
//  ee_run_inference — normalise ee_snapshot_buf, invoke model,
//  return dequantised human / nonhuman scores.
// ============================================================
static void ee_run_inference(float &human, float &nonhuman) {
  const float in_sc = ee_model_input->params.scale
                        ? ee_model_input->params.scale : (1.0f / 255.0f);
  const int   in_zp = ee_model_input->params.zero_point;
  const int   n     = IMG_WIDTH * IMG_HEIGHT * 3;

  for (int i = 0; i < n; i++) {
    float norm = (float)ee_snapshot_buf[i] / 255.0f;
    int   q    = (int)lroundf(norm / in_sc) + in_zp;
    if (q < -128) q = -128;
    if (q >  127) q =  127;
    ee_model_input->data.int8[i] = (int8_t)q;
  }

  if (ee_tflite_interpreter->Invoke() != kTfLiteOk) {
    Serial.println("[AI] Invoke failed");
    human = nonhuman = 0.f;
    return;
  }

  const float o_sc = ee_model_output->params.scale;
  const int   o_zp = ee_model_output->params.zero_point;
  human    = ((int)ee_model_output->data.int8[0] - o_zp) * o_sc;
  nonhuman = ((int)ee_model_output->data.int8[1] - o_zp) * o_sc;
}

// ============================================================
//  ee_model_init — set up TFLite Micro arena + interpreter
// ============================================================
static void ee_model_init() {
  ee_tensor_arena = (uint8_t *)heap_caps_malloc(EE_ARENA_SIZE,
                                  MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (!ee_tensor_arena)
    ee_tensor_arena = (uint8_t *)heap_caps_malloc(EE_ARENA_SIZE,
                                    MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!ee_tensor_arena) {
    Serial.println("[FATAL] arena alloc failed");
    while (1) delay(1000);
  }

  ee_tflite_model = tflite::GetModel(g_model);
  if (ee_tflite_model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.printf("[FATAL] model schema %lu != %d\n",
                  (unsigned long)ee_tflite_model->version(), TFLITE_SCHEMA_VERSION);
    while (1) delay(1000);
  }

  static tflite::MicroMutableOpResolver<10> ee_resolver;
  ee_resolver.AddConv2D();
  ee_resolver.AddMaxPool2D();
  ee_resolver.AddReshape();
  ee_resolver.AddFullyConnected();
  ee_resolver.AddSoftmax();
  ee_resolver.AddQuantize();
  ee_resolver.AddDequantize();
  ee_resolver.AddShape();
  ee_resolver.AddStridedSlice();
  ee_resolver.AddPack();

  static tflite::MicroInterpreter ee_interp(
      ee_tflite_model, ee_resolver, ee_tensor_arena, EE_ARENA_SIZE, nullptr, nullptr);
  ee_tflite_interpreter = &ee_interp;

  if (ee_tflite_interpreter->AllocateTensors(true) != kTfLiteOk) {
    Serial.println("[FATAL] AllocateTensors failed — raise EE_ARENA_SIZE");
    while (1) delay(1000);
  }

  ee_model_input  = ee_tflite_interpreter->input(0);
  ee_model_output = ee_tflite_interpreter->output(0);

  Serial.printf("[model] EagleEye v7.16  input %dx%dx%d  scale=%.6f  zp=%d  arena=%u B\n",
                ee_model_input->dims->data[1],
                ee_model_input->dims->data[2],
                ee_model_input->dims->data[3],
                ee_model_input->params.scale,
                ee_model_input->params.zero_point,
                (unsigned)ee_tflite_interpreter->arena_used_bytes());
#if EE_ESP_NN
  Serial.println("[model] ESP-NN: ENABLED");
#else
  Serial.println("[model] ESP-NN: DISABLED");
#endif
}

// ============================================================
//  run_ai_step — one inference cycle (MODE_AI only)
// ============================================================
void run_ai_step() {
  // Skip inference while servos are being commanded — keeps latency low.
  mqtt_service();
  lanctrl_service();
  if (g_req_servo_angle >= 0 || g_req_tilt_angle >= 0 ||
      millis() - g_last_cmd_ms < 2500) return;

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) { Serial.println("[AI] capture failed"); delay(80); return; }

  ee_crop_resize(fb->buf, fb->width, fb->height,
                 ee_snapshot_buf, IMG_WIDTH, IMG_HEIGHT);
  esp_camera_fb_return(fb);

  float human = 0.f, nonhuman = 0.f;
  ee_run_inference(human, nonhuman);

  ee_frame_count++;
  bool detected = (human >= HUMAN_THRESHOLD && human > nonhuman);

  if (detected) {
    ee_clear_scene_count = 0;
    Serial.printf("[AI %lu] HUMAN H=%.3f N=%.3f\n", ee_frame_count, human, nonhuman);
    if (!ee_image_sent) {
      capture_and_send_image(human);
      ee_image_sent = true;
    }
  } else {
    Serial.printf("[AI %lu] no human  H=%.3f N=%.3f\n", ee_frame_count, human, nonhuman);
    if (ee_image_sent && ++ee_clear_scene_count >= CLEAR_SCENE_FRAMES) {
      ee_image_sent = false; ee_clear_scene_count = 0;
      Serial.println("[AI] scene cleared — re-armed");
    }
  }
}

// ============================================================
//  Core-0 servo task — smooth stepper at ~330 Hz
// ============================================================
void servo_core0_task(void *pv) {
  for (;;) {
    servos_service();
    vTaskDelay(pdMS_TO_TICKS(3));
  }
}

// ============================================================
//  setup
// ============================================================
void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
  Serial.begin(115200);
  delay(400);
  Serial.println("\n=== EagleEye CLOUD build ===");

  config_load();
  Serial.printf("[cfg] deviceId=%s  mqtt=%s:%u\n",
                g_cfg.deviceId.c_str(), g_cfg.mqttHost.c_str(), g_cfg.mqttPort);

#if ENABLE_PROVISIONING
  provision_begin();
#endif

  ee_model_init();     // TFLite Micro + ESP-NN (must be before camera — uses internal SRAM)

  ee_snapshot_buf = (uint8_t *)malloc(IMG_WIDTH * IMG_HEIGHT * 3);
  if (!ee_snapshot_buf) {
    Serial.println("[FATAL] snapshot buf alloc failed");
    while (1) delay(1000);
  }

  if (!setup_camera_ai()) {
    Serial.println("[FATAL] camera init failed");
    while (1) delay(1000);
  }

  servos_begin();
  init_wifi_mqtt();
  lanctrl_begin();

  xTaskCreatePinnedToCore(servo_core0_task, "servoCtl", 4096, NULL, 2, NULL, 0);

  Serial.printf("[heap] internal=%u  PSRAM=%u\n",
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));

#if STREAM_AUTOSTART
  Serial.println("[DEBUG] STREAM_AUTOSTART=1");
  g_req_stream_on = true;
#endif
}

// ============================================================
//  loop
// ============================================================
void loop() {
  mqtt_service();
  lanctrl_service();

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
    String u = g_req_ota_url; g_req_ota_url = ""; ota_perform(u);
  }
#endif
  if (g_req_stream_on)  { g_req_stream_on  = false; if (g_mode != MODE_RELAY) relay_start(); }
  if (g_req_stream_off) { g_req_stream_off = false; if (g_mode == MODE_RELAY) relay_stop();  }

  if (g_mode == MODE_RELAY)    { relay_loop(); return; }
  if (g_mode == MODE_UPLOADING) { delay(2); return; }
  if (millis() - g_last_cmd_ms < 2500) { delay(5); return; }

  run_ai_step();
}
