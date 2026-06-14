/*
 * ============================================================
 *  EAGLEEYE — LOCAL model firmware, RGB (PlatformIO, self-contained)
 *  ESP32-CAM AI Thinker · 96x96 RGB human / nonhuman detector + live web view
 *
 *  Fully in-folder build: the TFLM + ESP-NN engine lives in
 *  lib/final_inferencing/ (PlatformIO auto-adds it to the include path —
 *  no Arduino "Add .ZIP Library", nothing installed system-wide). The model
 *  (src/model_data.h, g_model[]) is the RGB v7.16 detector copied from
 *  eagleeye-cloud-pio (eagleeye_vision / EI project "EagleEye 1000575"). The
 *  Edge Impulse SDK is used ONLY as the int8 runtime, because it bundles
 *  ESP-NN (hardware-accelerated int8 kernels).
 *
 *  Build:  pio run            (compile)
 *          pio run -t upload   (flash)     pio device monitor -b 115200
 *  Board:  AI Thinker ESP32-CAM · PSRAM Enabled · Huge APP · 240 MHz.
 *
 *  Input convention (MUST match the model): RGB888 0..255 (3 channels) ->
 *  normalise /255 -> quantise with the model's own input scale/zero-point
 *  (1/255, -128). Output softmax order: [0]=human, [1]=nonhuman.
 * ============================================================
 */

#include <Arduino.h>
#include <final_inferencing.h>   // EI SDK = our TFLM + ESP-NN runtime (from lib/)
#include "edge-impulse-sdk/tensorflow/lite/micro/micro_interpreter.h"
#include "edge-impulse-sdk/tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "edge-impulse-sdk/tensorflow/lite/schema/schema_generated.h"

#include <math.h>
#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "model_data.h"          // g_model[], g_model_len  (our local int8 model)
#include "eagleeye_webserver.h"  // Wi-Fi live MJPEG view + detection status server

// ============================================================
//  CAMERA PINS (AI Thinker ESP32-CAM)
// ============================================================
#define PWDN_GPIO_NUM  32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM   0
#define SIOD_GPIO_NUM  26
#define SIOC_GPIO_NUM  27
#define Y9_GPIO_NUM    35
#define Y8_GPIO_NUM    34
#define Y7_GPIO_NUM    39
#define Y6_GPIO_NUM    36
#define Y5_GPIO_NUM    21
#define Y4_GPIO_NUM    19
#define Y3_GPIO_NUM    18
#define Y2_GPIO_NUM     5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM  23
#define PCLK_GPIO_NUM  22

#define IMG_W 96
#define IMG_H 96
#define HUMAN_THRESHOLD 0.65f    // matches EI project threshold (0.65)

namespace {
const tflite::Model*      model = nullptr;
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor*             input = nullptr;
TfLiteTensor*             output = nullptr;
constexpr int             kArenaSize = 160 * 1024;   // model arena ~135 KB
uint8_t*                  tensor_arena = nullptr;
}

// Centre-square crop of the QVGA frame, then nearest-neighbour resize to
// 96x96 RGB888 (3 bytes/pixel) — matches the RGB model's input.
static void rgb565_to_rgb888_resize_crop(const uint8_t* src, int src_w, int src_h,
                                         uint8_t* dst, int dst_w, int dst_h) {
    int crop_w = src_h;
    int offset_x = (src_w - crop_w) / 2;
    for (int y = 0; y < dst_h; y++) {
        for (int x = 0; x < dst_w; x++) {
            int sx = offset_x + (x * crop_w / dst_w);
            int sy = (y * src_h / dst_h);
            if (sx >= src_w) sx = src_w - 1;
            if (sy >= src_h) sy = src_h - 1;
            int idx = (sy * src_w + sx) * 2;
            uint16_t pix = (src[idx] << 8) | src[idx + 1];
            uint8_t r = (pix >> 11) & 0x1F;
            uint8_t g = (pix >> 5)  & 0x3F;
            uint8_t b = pix & 0x1F;
            r = (r << 3) | (r >> 2);
            g = (g << 2) | (g >> 4);
            b = (b << 3) | (b >> 2);
            int di = (y * dst_w + x) * 3;     // 3 bytes/pixel RGB888
            dst[di] = r; dst[di + 1] = g; dst[di + 2] = b;
        }
    }
}

static bool camera_init() {
    camera_config_t cam = {};
    cam.ledc_channel = LEDC_CHANNEL_0; cam.ledc_timer = LEDC_TIMER_0;
    cam.pin_d0 = Y2_GPIO_NUM; cam.pin_d1 = Y3_GPIO_NUM; cam.pin_d2 = Y4_GPIO_NUM; cam.pin_d3 = Y5_GPIO_NUM;
    cam.pin_d4 = Y6_GPIO_NUM; cam.pin_d5 = Y7_GPIO_NUM; cam.pin_d6 = Y8_GPIO_NUM; cam.pin_d7 = Y9_GPIO_NUM;
    cam.pin_xclk = XCLK_GPIO_NUM; cam.pin_pclk = PCLK_GPIO_NUM;
    cam.pin_vsync = VSYNC_GPIO_NUM; cam.pin_href = HREF_GPIO_NUM;
    cam.pin_sscb_sda = SIOD_GPIO_NUM; cam.pin_sscb_scl = SIOC_GPIO_NUM;
    cam.pin_pwdn = PWDN_GPIO_NUM; cam.pin_reset = RESET_GPIO_NUM;
    cam.xclk_freq_hz = 20000000;
    cam.pixel_format = PIXFORMAT_RGB565;
    cam.frame_size = FRAMESIZE_QVGA;
    cam.fb_count = 2;
    cam.fb_location = CAMERA_FB_IN_PSRAM;
    cam.grab_mode = CAMERA_GRAB_LATEST;
    if (esp_camera_init(&cam) != ESP_OK) return false;
    sensor_t* s = esp_camera_sensor_get();
    if (s) {
        s->set_whitebal(s, 1); s->set_awb_gain(s, 1); s->set_wb_mode(s, 0);
        s->set_exposure_ctrl(s, 1); s->set_aec2(s, 1); s->set_ae_level(s, 2);
        s->set_gain_ctrl(s, 1); s->set_raw_gma(s, 1); s->set_lenc(s, 1);
    }
    for (int i = 0; i < 8; i++) { camera_fb_t* w = esp_camera_fb_get(); if (w) esp_camera_fb_return(w); delay(60); }
    return true;
}

// ── Detection state shared with the web server (eagleeye_webserver.h) ───────
volatile bool     g_isHuman       = false;
volatile float    g_humanScore    = 0.0f;
volatile float    g_nonhumanScore = 1.0f;
volatile uint32_t g_inferMs       = 0;

// Classify one RGB565 camera frame (-> RGB888 -> int8 -> model) and publish the
// result into the globals above. Called per streamed frame by the web server.
void infer_on_frame(camera_fb_t* fb) {
    static uint8_t rgb[IMG_W * IMG_H * 3];   // 3 channels (RGB888)
    rgb565_to_rgb888_resize_crop(fb->buf, fb->width, fb->height, rgb, IMG_W, IMG_H);

    const float in_scale = input->params.scale ? input->params.scale : 1.0f;
    const int   in_zp    = input->params.zero_point;
    const int   n = IMG_W * IMG_H * 3;
    for (int i = 0; i < n; i++) {
        float norm = (float)rgb[i] / 255.0f;
        int q = (int)lroundf(norm / in_scale) + in_zp;
        if (q < -128) q = -128;
        if (q > 127)  q = 127;
        input->data.int8[i] = (int8_t)q;
    }

    uint32_t t0 = millis();
    if (interpreter->Invoke() != kTfLiteOk) { Serial.println("Invoke failed"); return; }
    g_inferMs = millis() - t0;

    const float osc = output->params.scale;
    const int   ozp = output->params.zero_point;
    float human    = ((int)output->data.int8[0] - ozp) * osc;  // index 0 = human
    float nonhuman = ((int)output->data.int8[1] - ozp) * osc;  // index 1 = nonhuman
    g_humanScore    = human;
    g_nonhumanScore = nonhuman;
    g_isHuman       = (human >= HUMAN_THRESHOLD && human > nonhuman);
}

void setup() {
    Serial.begin(115200);
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
    setCpuFrequencyMhz(240);
    Serial.println("\n=== EagleEye LOCAL (PlatformIO · TFLM + ESP-NN) ===");
#if EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN
    Serial.println("[build] ESP-NN: ENABLED");
#else
    Serial.println("[build] ESP-NN: DISABLED (slow)");
#endif

    Serial.printf("[heap] free internal=%u  free PSRAM=%u\n",
                  (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                  (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));

    bool arena_psram = false;
    tensor_arena = (uint8_t*)heap_caps_malloc(kArenaSize, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!tensor_arena) {
        tensor_arena = (uint8_t*)heap_caps_malloc(kArenaSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        arena_psram = true;
    }
    if (!tensor_arena) { Serial.println("[ERR] arena alloc failed"); while (1) delay(1000); }
    Serial.printf("[arena] %d KB in %s\n", kArenaSize / 1024,
                  arena_psram ? "PSRAM (SLOW — reduce kArenaSize)" : "internal SRAM (fast)");

    model = tflite::GetModel(g_model);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        Serial.printf("[ERR] model schema %lu != %d\n",
                      (unsigned long)model->version(), TFLITE_SCHEMA_VERSION);
        while (1) delay(1000);
    }

    // Ops used by the EI-faithful CNN + dynamic-reshape extras.
    static tflite::MicroMutableOpResolver<10> resolver;
    resolver.AddConv2D();
    resolver.AddMaxPool2D();
    resolver.AddReshape();
    resolver.AddFullyConnected();
    resolver.AddSoftmax();
    resolver.AddQuantize();
    resolver.AddDequantize();
    resolver.AddShape();
    resolver.AddStridedSlice();
    resolver.AddPack();

    static tflite::MicroInterpreter static_interp(model, resolver, tensor_arena, kArenaSize, nullptr, nullptr);
    interpreter = &static_interp;
    if (interpreter->AllocateTensors(true) != kTfLiteOk) {
        Serial.println("[ERR] AllocateTensors failed (raise kArenaSize?)");
        while (1) delay(1000);
    }
    input = interpreter->input(0);
    output = interpreter->output(0);
    Serial.printf("[OK] input %dx%dx%d scale=%.6f zp=%d | arena used %u\n",
                  input->dims->data[1], input->dims->data[2], input->dims->data[3],
                  input->params.scale, input->params.zero_point,
                  (unsigned)interpreter->arena_used_bytes());

    if (!camera_init()) { Serial.println("[ERR] camera init failed"); while (1) delay(1000); }
    Serial.println("[OK] camera ready\n");

    web_begin();   // Wi-Fi + live MJPEG view + detection status server
}

void loop() {
    // Inference runs inside the live-stream handler (one camera owner). Here we
    // just echo the latest detection to serial once a second.
    Serial.printf("%-9s | Human %.3f  NonHuman %.3f | %lu ms%s\n",
                  g_isHuman ? "HUMAN" : "no human", g_humanScore, g_nonhumanScore,
                  (unsigned long)g_inferMs,
                  (g_inferMs == 0) ? "   (open the live page to start detection)" : "");
    delay(1000);
}
