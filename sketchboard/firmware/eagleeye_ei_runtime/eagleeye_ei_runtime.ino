/*
 * EagleEye — Edge Impulse runtime sketch (Option A)
 * ESP32-CAM AI Thinker, 96x96 RGB human detector
 * Model: rgb96_mobilenetv1 (no ESP-NN), 2 classes (human / nonhuman)
 *
 * Feeds the model TRUE RGB (3-channel) input — the QVGA RGB565 frame is
 * centre-cropped and resized to 96x96, keeping real R/G/B per pixel.
 *
 * Uses the FULL Edge Impulse Arduino library and run_classifier().
 *
 * Setup (fast model swap — no full library re-add / no minutes-long recompile):
 *   1. Make sure the final_inferencing library is installed once (Add .ZIP Library).
 *   2. Swap in just the model files for this model:
 *        python tools/edge_impulse/swap_ei_model.py \
 *          third_party/ei_arduino_library_rgb96_mobilenetv1_no_espnn.zip
 *      This replaces only src/model-parameters, src/tflite-model and
 *      ei_classifier_config.h, leaving the cached edge-impulse-sdk untouched
 *      so Arduino recompiles in seconds.
 *   3. In Arduino IDE just press Compile/Upload (do NOT re-Add the .ZIP).
 *
 * Serial @115200 prints both the EI timing line and a final
 *   "Human detected" / "Not detected"
 */

// EI library folder is "final_inferencing" (rgb96_mobilenetv1 model swapped in)
#include <final_inferencing.h>

#include <Arduino.h>
#include "esp_camera.h"
#include "edge-impulse-sdk/dsp/image/image.hpp"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

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

#define CAM_W 320
#define CAM_H 240

#define INFER_INTERVAL_MS 200

// Three bytes per pixel (R,G,B), interleaved.
static uint8_t rgb_buffer[EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT * 3];

static void rgb565_to_rgb_resize_crop(const uint8_t* src, int src_w, int src_h,
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
            // OV2640 RGB565: byte 0 = HIGH byte (RRRRRGGG), byte 1 = LOW byte
            // (GGGBBBBB). Matches Espressif's fmt2rgb888 which reads `hb = src[0]`.
            uint16_t pix = (src[idx] << 8) | src[idx + 1];
            uint8_t r = (pix >> 11) & 0x1F;
            uint8_t g = (pix >> 5) & 0x3F;
            uint8_t b = pix & 0x1F;
            r = (r << 3) | (r >> 2);
            g = (g << 2) | (g >> 4);
            b = (b << 3) | (b >> 2);
            int o = (y * dst_w + x) * 3;
            dst[o]     = r;
            dst[o + 1] = g;
            dst[o + 2] = b;
        }
    }
}

// EI RGB image models pull one packed 0xRRGGBB float per pixel; offset/length
// are in pixels, so index the interleaved RGB buffer 3 bytes at a time.
static int ei_get_data_cb(size_t offset, size_t length, float* out_ptr) {
    for (size_t i = 0; i < length; i++) {
        const uint8_t* p = &rgb_buffer[(offset + i) * 3];
        out_ptr[i] = (float)((p[0] << 16) | (p[1] << 8) | p[2]);
    }
    return 0;
}

static bool camera_init() {
    camera_config_t cam = {};
    cam.ledc_channel = LEDC_CHANNEL_0;
    cam.ledc_timer = LEDC_TIMER_0;
    cam.pin_d0 = Y2_GPIO_NUM;  cam.pin_d1 = Y3_GPIO_NUM;
    cam.pin_d2 = Y4_GPIO_NUM;  cam.pin_d3 = Y5_GPIO_NUM;
    cam.pin_d4 = Y6_GPIO_NUM;  cam.pin_d5 = Y7_GPIO_NUM;
    cam.pin_d6 = Y8_GPIO_NUM;  cam.pin_d7 = Y9_GPIO_NUM;
    cam.pin_xclk = XCLK_GPIO_NUM;
    cam.pin_pclk = PCLK_GPIO_NUM;
    cam.pin_vsync = VSYNC_GPIO_NUM;
    cam.pin_href = HREF_GPIO_NUM;
    cam.pin_sscb_sda = SIOD_GPIO_NUM;
    cam.pin_sscb_scl = SIOC_GPIO_NUM;
    cam.pin_pwdn = PWDN_GPIO_NUM;
    cam.pin_reset = RESET_GPIO_NUM;
    cam.xclk_freq_hz = 20000000;
    cam.pixel_format = PIXFORMAT_RGB565;
    cam.frame_size = FRAMESIZE_QVGA;
    cam.fb_count = 2;
    return esp_camera_init(&cam) == ESP_OK;
}

void setup() {
    Serial.begin(115200);
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
    setCpuFrequencyMhz(240);

    Serial.println("\n=== EagleEye EI Runtime (Option A: run_classifier + ESP-NN) ===");
    Serial.printf("[model] EI input %dx%d, label count %d\n",
                  EI_CLASSIFIER_INPUT_WIDTH,
                  EI_CLASSIFIER_INPUT_HEIGHT,
                  (int)EI_CLASSIFIER_LABEL_COUNT);

    pinMode(4, OUTPUT);
    digitalWrite(4, LOW);

    if (!camera_init()) {
        Serial.println("[ERR] Camera init failed");
        while (1) delay(1000);
    }
    Serial.println("[OK] Camera QVGA RGB565");

    if (EI_CLASSIFIER_INPUT_WIDTH != 96 || EI_CLASSIFIER_INPUT_HEIGHT != 96) {
        Serial.printf("[WARN] Library expects %dx%d, sketch is tuned for 96x96\n",
                      EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT);
    }

    Serial.println("Watching...\n");
}

void loop() {
    static uint32_t last = 0;
    if (millis() - last < INFER_INTERVAL_MS) { delay(5); return; }
    last = millis();

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) return;

    uint32_t t_pre = millis();
    rgb565_to_rgb_resize_crop(fb->buf, fb->width, fb->height,
                              rgb_buffer,
                              EI_CLASSIFIER_INPUT_WIDTH,
                              EI_CLASSIFIER_INPUT_HEIGHT);
    esp_camera_fb_return(fb);
    uint32_t pre_ms = millis() - t_pre;

    ei::signal_t signal;
    signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
    signal.get_data = &ei_get_data_cb;

    ei_impulse_result_t result = {};
    EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
    if (err != EI_IMPULSE_OK) {
        Serial.printf("[ERR] run_classifier %d\n", (int)err);
        return;
    }

    Serial.printf("timing: preprocess %lu ms | DSP %d ms | classification %d ms | total %lu ms\n",
                  (unsigned long)pre_ms,
                  result.timing.dsp,
                  result.timing.classification,
                  (unsigned long)(pre_ms + result.timing.dsp + result.timing.classification));

    float human_score = 0.0f;
    float nonhuman_score = 0.0f;
    for (uint16_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
        const char* lbl = ei_classifier_inferencing_categories[i];
        float v = result.classification[i].value;
        Serial.printf("  %s: %.3f\n", lbl, v);
        if (strcmp(lbl, "human") == 0)        human_score = v;
        else if (strcmp(lbl, "nonhuman") == 0) nonhuman_score = v;
    }

    Serial.println(human_score > nonhuman_score ? "Human detected" : "Not detected");
}
