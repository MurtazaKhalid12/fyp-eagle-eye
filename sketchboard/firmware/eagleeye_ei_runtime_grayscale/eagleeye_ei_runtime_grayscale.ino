/*
 * EagleEye — Edge Impulse runtime sketch (GREYSCALE)
 * ESP32-CAM AI Thinker, greyscale human detector.
 *
 * Feeds the model 1-channel GREYSCALE input (matches a greyscale EI library).
 * Input shape is read from the installed library's model_metadata.h, so it
 * adapts to whatever greyscale model is installed (current: 80x80 tiny CNN).
 *
 * Setup:
 *   1. Install a greyscale EI library — fastest via the model-swap script:
 *        python tools/edge_impulse/swap_ei_model.py \
 *          third_party/ei_arduino_library_gray80_tinycnn_reg_espnn.zip
 *      (or Arduino IDE > Add .ZIP Library… for a full install)
 *   2. Board: AI Thinker ESP32-CAM, PSRAM: Enabled,
 *      Partition: Huge APP (3MB No OTA / 1MB SPIFFS), CPU: 240 MHz.
 *   3. Flash. Serial 115200.
 *
 * Debug commands over the serial monitor:
 *   's' toggle per-frame grey mean/range stats
 *   'd' dump the next WxH greyscale buffer as base64
 */

#include <final_inferencing.h>

#include <Arduino.h>
#include "esp_camera.h"
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

#define INFER_INTERVAL_MS 200

static bool g_print_stats = true;
static bool g_dump_next   = false;

// One byte per pixel (greyscale).
static uint8_t gray_buffer[EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT];

static const char B64_TABLE[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static void b64_dump(const uint8_t* buf, size_t len) {
    char chunk[5] = {0};
    size_t i = 0;
    while (i + 3 <= len) {
        uint32_t v = ((uint32_t)buf[i] << 16) | ((uint32_t)buf[i + 1] << 8) | buf[i + 2];
        chunk[0] = B64_TABLE[(v >> 18) & 0x3F];
        chunk[1] = B64_TABLE[(v >> 12) & 0x3F];
        chunk[2] = B64_TABLE[(v >> 6)  & 0x3F];
        chunk[3] = B64_TABLE[v & 0x3F];
        Serial.print(chunk);
        i += 3;
    }
    if (i < len) {
        uint32_t v = (uint32_t)buf[i] << 16;
        if (i + 1 < len) v |= (uint32_t)buf[i + 1] << 8;
        chunk[0] = B64_TABLE[(v >> 18) & 0x3F];
        chunk[1] = B64_TABLE[(v >> 12) & 0x3F];
        chunk[2] = (i + 1 < len) ? B64_TABLE[(v >> 6) & 0x3F] : '=';
        chunk[3] = '=';
        Serial.print(chunk);
    }
    Serial.println();
}

// Center-crop the QVGA RGB565 frame to a square and resize to the model input,
// converting each pixel to luminance (greyscale) in the process.
static void rgb565_to_gray_resize_crop(const uint8_t* src, int src_w, int src_h,
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
            // OV2640 RGB565: byte 0 = HIGH byte (RRRRRGGG), byte 1 = LOW byte (GGGBBBBB).
            uint16_t pix = (src[idx] << 8) | src[idx + 1];
            uint8_t r = (pix >> 11) & 0x1F;
            uint8_t g = (pix >> 5)  & 0x3F;
            uint8_t b = pix & 0x1F;
            r = (r << 3) | (r >> 2);
            g = (g << 2) | (g >> 4);
            b = (b << 3) | (b >> 2);
            // Rec.601 luminance.
            uint8_t gray = (uint8_t)((r * 77 + g * 150 + b * 29) >> 8);
            dst[y * dst_w + x] = gray;
        }
    }
}

// Edge Impulse greyscale models pull pixels as packed 0xVVVVVV floats
// (the gray value replicated into all three channels).
static int ei_get_data_cb(size_t offset, size_t length, float* out_ptr) {
    for (size_t i = 0; i < length; i++) {
        uint8_t v = gray_buffer[offset + i];
        out_ptr[i] = (float)((v << 16) | (v << 8) | v);
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
    cam.fb_count = 1;
    cam.fb_location = CAMERA_FB_IN_PSRAM;   // frame buffer in PSRAM (capacity)
    cam.grab_mode = CAMERA_GRAB_LATEST;
    if (esp_camera_init(&cam) != ESP_OK) return false;

    sensor_t* s = esp_camera_sensor_get();
    if (s) {
        s->set_whitebal(s, 1);
        s->set_awb_gain(s, 1);
        s->set_wb_mode(s, 0);
        s->set_exposure_ctrl(s, 1);
        s->set_aec2(s, 1);
        s->set_ae_level(s, 2);
        s->set_aec_value(s, 600);
        s->set_gain_ctrl(s, 1);
        s->set_agc_gain(s, 0);
        s->set_gainceiling(s, (gainceiling_t)4);
        s->set_bpc(s, 0);
        s->set_wpc(s, 1);
        s->set_raw_gma(s, 1);
        s->set_lenc(s, 1);
        s->set_dcw(s, 1);
        s->set_saturation(s, 0);
        s->set_brightness(s, 0);
        s->set_contrast(s, 0);
    }

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

    Serial.println("\n=== EagleEye EI Runtime GREYSCALE ===");
    Serial.printf("[model] project %d deploy v%d | input %dx%d GREY | NN input %d\n",
                  (int)EI_CLASSIFIER_PROJECT_ID,
                  (int)EI_CLASSIFIER_PROJECT_DEPLOY_VERSION,
                  EI_CLASSIFIER_INPUT_WIDTH,
                  EI_CLASSIFIER_INPUT_HEIGHT,
                  (int)EI_CLASSIFIER_NN_INPUT_FRAME_SIZE);
#if EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN
    Serial.println("[build] ESP-NN: ENABLED");
#else
    Serial.println("[build] ESP-NN: DISABLED");
#endif

    pinMode(4, OUTPUT);
    digitalWrite(4, LOW);

    if (!camera_init()) {
        Serial.println("[ERR] Camera init failed");
        while (1) delay(1000);
    }
    Serial.println("[OK] Camera QVGA RGB565 -> greyscale");
    Serial.println("Commands: 's' stats toggle, 'd' dump frame (base64 grey)\n");
}

void loop() {
    while (Serial.available()) {
        char c = Serial.read();
        if      (c == 's') { g_print_stats = !g_print_stats;
                             Serial.printf("[dbg] stats=%d\n", (int)g_print_stats); }
        else if (c == 'd') { g_dump_next = true;
                             Serial.println("[dbg] will dump next frame as base64 greyscale"); }
    }

    static uint32_t last = 0;
    if (millis() - last < INFER_INTERVAL_MS) { delay(5); return; }
    last = millis();

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) return;

    uint32_t t_pre = millis();
    rgb565_to_gray_resize_crop(fb->buf, fb->width, fb->height,
                               gray_buffer,
                               EI_CLASSIFIER_INPUT_WIDTH,
                               EI_CLASSIFIER_INPUT_HEIGHT);
    esp_camera_fb_return(fb);
    uint32_t pre_ms = millis() - t_pre;

    if (g_print_stats) {
        const size_t n_pix = (size_t)EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
        uint32_t sum = 0;
        uint8_t lo = 255, hi = 0;
        for (size_t i = 0; i < n_pix; i++) {
            uint8_t v = gray_buffer[i];
            sum += v;
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }
        Serial.printf("grey stats: mean=%lu range=%u..%u\n",
                      (unsigned long)(sum / n_pix), lo, hi);
    }

    if (g_dump_next) {
        g_dump_next = false;
        const size_t total = (size_t)EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
        Serial.printf("DUMP_BEGIN %d %d\n", (int)EI_CLASSIFIER_INPUT_WIDTH, (int)EI_CLASSIFIER_INPUT_HEIGHT);
        b64_dump(gray_buffer, total);
        Serial.println("DUMP_END");
    }

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
