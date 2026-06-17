#ifndef EAGLEEYE_CAMERA_H
#define EAGLEEYE_CAMERA_H

// ============================================================
//  EagleEye CLOUD — camera + device-mode core
// ============================================================
//  Two camera modes share one sensor:
//    MODE_AI    -> RGB565 QVGA  (raw pixels for the EI classifier)
//    MODE_RELAY -> hardware JPEG (fast/small frames for live video)
//  We switch by deinit/reinit (NOT live set_pixformat, which is unreliable).
//  AI is paused while relaying, so the switch is safe.
// ============================================================

#include <Arduino.h>
#include "esp_camera.h"
#include "img_converters.h"

// --- PINS (AI-THINKER ESP32-CAM) ---
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM       5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// --- device mode (single source of truth; only loop() changes it) ---
enum DeviceMode { MODE_AI, MODE_UPLOADING, MODE_RELAY };
DeviceMode g_mode = MODE_AI;

// Generic camera init. Returns true on success.
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
  config.xclk_freq_hz = 10000000;          // 10 MHz (stable)
  config.pixel_format = fmt;
  config.frame_size   = size;
  config.jpeg_quality = jpegQ;             // only used when fmt == PIXFORMAT_JPEG
  config.fb_count     = 2;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAM] init failed: 0x%x\n", err);
    return false;
  }
  return true;
}

// RGB565 QVGA for the AI classifier.
inline bool setup_camera_ai()     { return setup_camera(PIXFORMAT_RGB565, FRAMESIZE_QVGA, 12); }
// Hardware JPEG VGA for the live relay (sensor encodes -> no software frame2jpg).
inline bool setup_camera_stream() { return setup_camera(PIXFORMAT_JPEG,   FRAMESIZE_VGA,  12); }

// Switch camera mode safely (deinit + reinit). Quiesce producers before calling.
inline bool switch_camera_to_ai()     { esp_camera_deinit(); return setup_camera_ai(); }
inline bool switch_camera_to_stream() { esp_camera_deinit(); return setup_camera_stream(); }

// Grab one JPEG frame. Caller must free(*jpg_buf).
// Fast path when the sensor is already in JPEG mode; else software-encode RGB565.
inline bool eagleeye_grab_jpeg(uint8_t **jpg_buf, size_t *jpg_len) {
  *jpg_buf = NULL; *jpg_len = 0;
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) return false;

  if (fb->format == PIXFORMAT_JPEG) {               // hardware JPEG -> copy out
    uint8_t *buf = (uint8_t *)malloc(fb->len);
    if (!buf) { esp_camera_fb_return(fb); return false; }
    memcpy(buf, fb->buf, fb->len);
    *jpg_buf = buf; *jpg_len = fb->len;
    esp_camera_fb_return(fb);
    return true;
  }

  uint8_t *buf = NULL; size_t len = 0;              // RGB565 -> software JPEG (q25)
  bool ok = frame2jpg(fb, 25, &buf, &len);
  esp_camera_fb_return(fb);
  if (!ok || !buf) return false;
  *jpg_buf = buf; *jpg_len = len;
  return true;
}

#endif // EAGLEEYE_CAMERA_H
