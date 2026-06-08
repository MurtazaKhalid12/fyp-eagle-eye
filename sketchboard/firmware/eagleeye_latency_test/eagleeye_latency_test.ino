/*
 * ============================================================
 *  EAGLEEYE — Model Inference Latency Test (serial only)
 *  ESP32-CAM AI Thinker
 *
 *  Minimal sketch: grab a frame, run the Edge Impulse model, and print
 *    - inference latency (DSP + classification + total)
 *    - human / nonhuman scores and the verdict
 *  No WiFi, no web UI, no streaming, no capture/upload. Just model speed.
 *
 *  Library: ei_arduino_library_rgb96_mobilenetv1_a2_no_espnn.zip
 *    Arduino IDE > Sketch > Include Library > Add .ZIP Library
 *  Board: AI Thinker ESP32-CAM, PSRAM Enabled, Huge APP, 240 MHz.
 * ============================================================
 */

#include <final_inferencing.h>

#include <Arduino.h>
#include "esp_camera.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// ============================================================
//  CAMERA PINS (AI Thinker)
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

#define HUMAN_THRESHOLD 0.65f

static uint8_t rgb_buffer[EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT * 3];

// Center-crop the QVGA RGB565 frame to a square and resize to the model input,
// converting to RGB888 in the process.
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
            uint8_t g = (pix >> 5) & 0x3F;
            uint8_t b = pix & 0x1F;
            r = (r << 3) | (r >> 2);
            g = (g << 2) | (g >> 4);
            b = (b << 3) | (b >> 2);

            int di = (y * dst_w + x) * 3;
            dst[di] = r;
            dst[di + 1] = g;
            dst[di + 2] = b;
        }
    }
}

// Edge Impulse pulls pixels as packed 0xRRGGBB floats.
static int ei_get_data_cb(size_t offset, size_t length, float* out_ptr) {
    for (size_t i = 0; i < length; i++) {
        size_t pix_idx = (offset + i) * 3;
        uint8_t r = rgb_buffer[pix_idx];
        uint8_t g = rgb_buffer[pix_idx + 1];
        uint8_t b = rgb_buffer[pix_idx + 2];
        out_ptr[i] = (float)((r << 16) | (g << 8) | b);
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
    cam.fb_location = CAMERA_FB_IN_PSRAM;
    cam.grab_mode = CAMERA_GRAB_LATEST;
    if (esp_camera_init(&cam) != ESP_OK) return false;

    // Let auto-exposure / white-balance settle so scores are meaningful.
    for (int i = 0; i < 8; i++) {
        camera_fb_t* warm = esp_camera_fb_get();
        if (warm) esp_camera_fb_return(warm);
        delay(60);
    }
    return true;
}

void setup() {
    Serial.begin(115200);
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
    setCpuFrequencyMhz(240);

    if (!camera_init()) {
        Serial.println("Camera init failed");
        while (1) delay(1000);
    }

    Serial.printf("Model input %dx%d RGB | ESP-NN %s | CPU %d MHz\n",
                  EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT,
                  EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN ? "ON" : "OFF",
                  getCpuFrequencyMhz());
    Serial.println("Running inference latency test...\n");
}

void loop() {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { delay(10); return; }
    rgb565_to_rgb888_resize_crop(fb->buf, fb->width, fb->height, rgb_buffer,
                                 EI_CLASSIFIER_INPUT_WIDTH, EI_CLASSIFIER_INPUT_HEIGHT);
    esp_camera_fb_return(fb);

    ei::signal_t signal;
    signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
    signal.get_data = &ei_get_data_cb;

    ei_impulse_result_t result = {};
    uint32_t t0 = micros();
    EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
    uint32_t total_ms = (micros() - t0) / 1000;

    if (err != EI_IMPULSE_OK) {
        Serial.printf("run_classifier error %d\n", (int)err);
        delay(200);
        return;
    }

    float human = 0.0f, nonhuman = 0.0f;
    for (uint16_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
        const char* lbl = ei_classifier_inferencing_categories[i];
        float v = result.classification[i].value;
        if (strcmp(lbl, "human") == 0) human = v;
        else if (strcmp(lbl, "nonhuman") == 0) nonhuman = v;
    }
    bool isHuman = (human >= HUMAN_THRESHOLD && human > nonhuman);

    // Result + latency on one line.
    Serial.printf("%-9s | Human %.3f  NonHuman %.3f | DSP %d ms  Inference %d ms  Total %lu ms\n",
                  isHuman ? "HUMAN" : "no human",
                  human, nonhuman,
                  result.timing.dsp, result.timing.classification,
                  (unsigned long)total_ms);

    delay(50);
}
