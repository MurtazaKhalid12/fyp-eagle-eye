/*
 * EagleEye — Edge Impulse runtime sketch (RGB)
 * ESP32-CAM AI Thinker, RGB human detector.
 *
 * Input shape comes from the installed EI library's model_metadata.h
 * (currently the v12 deployment: 96x96 MobileNetV2 0.1 transfer learning).
 *
 * Uses the FULL Edge Impulse Arduino library (ESP-NN + run_classifier).
 *
 * Setup:
 *   1. Arduino IDE > Sketch > Include Library > Add .ZIP Library…
 *      pick: third_party/ei_arduino_library_v7_rgb96_mobilenetv2.zip
 *   2. Board: AI Thinker ESP32-CAM, PSRAM: Enabled,
 *      Partition: Huge APP (3MB No OTA / 1MB SPIFFS), CPU: 240 MHz.
 *   3. Flash. Serial 115200.
 *
 * OV2640 RGB565: each pixel is stored big-endian within the 16-bit word
 * (byte 0 = high byte = `RRRRRGGG`, byte 1 = low byte = `GGGBBBBB`).
 * That matches Espressif's own `fmt2rgb888` which reads `hb = src[0]`.
 *
 * Debug commands over the serial monitor:
 *   's' toggle per-frame R/G/B mean/range
 *   'd' dump the next 96x96x3 RGB888 buffer as base64 (decode it with
 *       tools/diag/decode_esp32_frame.py and run the same TFLite model)
 *   'b' toggle BGR<->RGB swap inside ei_get_data_cb (sanity test)
 */

#include <final_inferencing.h>

#include <Arduino.h>
#include "esp_camera.h"
#include "edge-impulse-sdk/dsp/image/image.hpp"
#include "edge-impulse-sdk/tensorflow/lite/micro/micro_interpreter.h"
#include "edge-impulse-sdk/tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "edge-impulse-sdk/tensorflow/lite/schema/schema_generated.h"
#include "tflite-model/tflite_learn_1000575_3.h"
#include "esp_heap_caps.h"
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

// Debug controls — set via serial commands at runtime:
//   's' -> toggle per-frame R/G/B mean stats
//   'd' -> dump the next 96x96x3 buffer as base64 over serial
//   'b' -> toggle BGR<->RGB packing in ei_get_data_cb (sanity test)
static bool g_print_stats = true;
static bool g_dump_next  = false;
static bool g_swap_rb    = false;
static bool g_direct_tflm = true;

static uint8_t rgb_buffer[EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT * 3];

static tflite::MicroInterpreter* g_direct_interpreter = nullptr;
static TfLiteTensor* g_direct_input = nullptr;
static TfLiteTensor* g_direct_output = nullptr;
static uint8_t* g_direct_arena = nullptr;

static bool direct_tflm_init() {
    if (g_direct_interpreter) return true;

    const tflite::Model* model = tflite::GetModel(tflite_learn_1000575_3);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        Serial.printf("[direct] model schema %d != supported %d\n",
                      model->version(), TFLITE_SCHEMA_VERSION);
        return false;
    }

    static tflite::MicroMutableOpResolver<6> resolver;
    resolver.AddAdd();
    resolver.AddConv2D();
    resolver.AddDepthwiseConv2D();
    resolver.AddFullyConnected();
    resolver.AddReshape();
    resolver.AddSoftmax();

    g_direct_arena = (uint8_t*)heap_caps_malloc(
        EI_CLASSIFIER_TFLITE_LEARN_1000575_3_ARENA_SIZE,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!g_direct_arena) {
        g_direct_arena = (uint8_t*)heap_caps_malloc(
            EI_CLASSIFIER_TFLITE_LEARN_1000575_3_ARENA_SIZE,
            MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    }
    if (!g_direct_arena) {
        Serial.printf("[direct] arena alloc failed (%u bytes)\n",
                      (unsigned)EI_CLASSIFIER_TFLITE_LEARN_1000575_3_ARENA_SIZE);
        return false;
    }

    g_direct_interpreter = new tflite::MicroInterpreter(
        model,
        resolver,
        g_direct_arena,
        EI_CLASSIFIER_TFLITE_LEARN_1000575_3_ARENA_SIZE,
        nullptr,
        nullptr);

    if (g_direct_interpreter->AllocateTensors(true) != kTfLiteOk) {
        Serial.println("[direct] AllocateTensors failed");
        return false;
    }

    g_direct_input = g_direct_interpreter->input(0);
    g_direct_output = g_direct_interpreter->output(0);

    Serial.printf("[direct] input type=%d bytes=%u scale=%.9f zp=%d\n",
                  (int)g_direct_input->type,
                  (unsigned)g_direct_input->bytes,
                  g_direct_input->params.scale,
                  g_direct_input->params.zero_point);
    Serial.printf("[direct] output type=%d bytes=%u scale=%.9f zp=%d\n",
                  (int)g_direct_output->type,
                  (unsigned)g_direct_output->bytes,
                  g_direct_output->params.scale,
                  g_direct_output->params.zero_point);

    return true;
}

static bool run_direct_tflm(float* out_human, float* out_nonhuman,
                            int8_t* out_raw0, int8_t* out_raw1,
                            uint32_t* out_ms) {
    if (!direct_tflm_init()) return false;
    if (!g_direct_input || !g_direct_output || g_direct_input->type != kTfLiteInt8) {
        Serial.println("[direct] unexpected tensor type");
        return false;
    }

    const size_t n_pix = (size_t)EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
    if (g_direct_input->bytes < n_pix * 3) {
        Serial.printf("[direct] input too small: %u < %u\n",
                      (unsigned)g_direct_input->bytes, (unsigned)(n_pix * 3));
        return false;
    }

    // This exactly matches the PC-side test and EI's quantized fast path:
    // input scale=1/255, zero_point=-128, so uint8 pixel P becomes P-128.
    for (size_t i = 0; i < n_pix; i++) {
        uint8_t r = rgb_buffer[i * 3 + 0];
        uint8_t g = rgb_buffer[i * 3 + 1];
        uint8_t b = rgb_buffer[i * 3 + 2];
        if (g_swap_rb) {
            uint8_t t = r; r = b; b = t;
        }
        g_direct_input->data.int8[i * 3 + 0] = (int8_t)((int)r - 128);
        g_direct_input->data.int8[i * 3 + 1] = (int8_t)((int)g - 128);
        g_direct_input->data.int8[i * 3 + 2] = (int8_t)((int)b - 128);
    }

    uint32_t t0 = millis();
    if (g_direct_interpreter->Invoke() != kTfLiteOk) {
        Serial.println("[direct] Invoke failed");
        return false;
    }
    if (out_ms) *out_ms = millis() - t0;

    int8_t raw0 = g_direct_output->data.int8[0];
    int8_t raw1 = g_direct_output->data.int8[1];
    if (out_raw0) *out_raw0 = raw0;
    if (out_raw1) *out_raw1 = raw1;

    float scale = g_direct_output->params.scale;
    int zp = g_direct_output->params.zero_point;
    if (out_human) *out_human = ((float)raw0 - (float)zp) * scale;
    if (out_nonhuman) *out_nonhuman = ((float)raw1 - (float)zp) * scale;
    return true;
}

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
            // OV2640 RGB565: byte 0 = HIGH byte (RRRRRGGG), byte 1 = LOW byte
            // (GGGBBBBB). Matches Espressif's fmt2rgb888 which reads `hb = src[0]`.
            uint16_t pix = (src[idx] << 8) | src[idx + 1];
            uint8_t r = (pix >> 11) & 0x1F;
            uint8_t g = (pix >> 5)  & 0x3F;
            uint8_t b = pix & 0x1F;
            r = (r << 3) | (r >> 2);
            g = (g << 2) | (g >> 4);
            b = (b << 3) | (b >> 2);
            int di = (y * dst_w + x) * 3;
            dst[di]     = r;
            dst[di + 1] = g;
            dst[di + 2] = b;
        }
    }
}

static int ei_get_data_cb(size_t offset, size_t length, float* out_ptr) {
    for (size_t i = 0; i < length; i++) {
        size_t pix_idx = (offset + i) * 3;
        uint8_t r = rgb_buffer[pix_idx];
        uint8_t g = rgb_buffer[pix_idx + 1];
        uint8_t b = rgb_buffer[pix_idx + 2];
        if (g_swap_rb) {
            // sanity-test the BGR<->RGB hypothesis
            uint8_t t = r; r = b; b = t;
        }
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
    // fb_count=1 + GRAB_LATEST avoids the "cam_hal: EV-EOF-OVF" overflow that
    // happens because each inference holds the frame buffer for ~640 ms.
    cam.fb_count = 1;
    cam.fb_location = CAMERA_FB_IN_PSRAM;
    cam.grab_mode = CAMERA_GRAB_LATEST;
    if (esp_camera_init(&cam) != ESP_OK) return false;

    // CRITICAL: OV2640 in raw RGB565 mode does NOT auto-engage the ISP.
    // Without this block the green channel runs ~50% high (Bayer is RGGB),
    // and a transfer-learning model trained on JPEG-pipeline output cannot
    // recognise the result as "human".
    sensor_t* s = esp_camera_sensor_get();
    if (s) {
        s->set_whitebal(s, 1);        // auto white balance ON
        s->set_awb_gain(s, 1);        // AWB gain ON
        s->set_wb_mode(s, 0);         // mode 0 = auto
        s->set_exposure_ctrl(s, 1);   // AEC ON
        s->set_aec2(s, 1);            // AEC2 (DSP-level) ON
        s->set_ae_level(s, 2);        // +2 EV — your live frames were ~33% darker than training
        s->set_aec_value(s, 600);
        s->set_gain_ctrl(s, 1);       // AGC ON
        s->set_agc_gain(s, 0);
        s->set_gainceiling(s, (gainceiling_t)4);  // allow more gain in low light
        s->set_bpc(s, 0);
        s->set_wpc(s, 1);
        s->set_raw_gma(s, 1);         // gamma correction ON (very important)
        s->set_lenc(s, 1);            // lens correction
        s->set_dcw(s, 1);
        s->set_saturation(s, 0);
        s->set_brightness(s, 0);
        s->set_contrast(s, 0);
    }

    // Let the ISP / AWB converge before any frame leaves the cam.
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

    Serial.println("\n=== EagleEye EI Runtime RGB ===");
    Serial.printf("[model] project %d deploy v%d\n",
                  (int)EI_CLASSIFIER_PROJECT_ID,
                  (int)EI_CLASSIFIER_PROJECT_DEPLOY_VERSION);
    Serial.printf("[model] EI input %dx%d RGB | raw pixels %d | NN input %d\n",
                  EI_CLASSIFIER_INPUT_WIDTH,
                  EI_CLASSIFIER_INPUT_HEIGHT,
                  (int)EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE,
                  (int)EI_CLASSIFIER_NN_INPUT_FRAME_SIZE);
    Serial.printf("[model] label count %d\n", (int)EI_CLASSIFIER_LABEL_COUNT);
    for (int i = 0; i < (int)EI_CLASSIFIER_LABEL_COUNT; i++) {
        Serial.printf("[model]   class[%d] = %s\n", i, ei_classifier_inferencing_categories[i]);
    }
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
    Serial.println("[OK] Camera QVGA RGB565");
    Serial.println("Commands: 's' stats toggle, 'd' dump frame (base64), 'b' BGR swap toggle, 'm' direct TFLM toggle\n");
}

void loop() {
    // Handle serial debug commands
    while (Serial.available()) {
        char c = Serial.read();
        if      (c == 's') { g_print_stats = !g_print_stats;
                             Serial.printf("[dbg] stats=%d\n", (int)g_print_stats); }
        else if (c == 'd') { g_dump_next = true;
                             Serial.println("[dbg] will dump next frame as base64 RGB888"); }
        else if (c == 'b') { g_swap_rb = !g_swap_rb;
                             Serial.printf("[dbg] swap_rb=%d\n", (int)g_swap_rb); }
        else if (c == 'm') { g_direct_tflm = !g_direct_tflm;
                             Serial.printf("[dbg] direct_tflm=%d\n", (int)g_direct_tflm); }
    }

    static uint32_t last = 0;
    if (millis() - last < INFER_INTERVAL_MS) { delay(5); return; }
    last = millis();

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) return;

    uint32_t t_pre = millis();
    rgb565_to_rgb888_resize_crop(fb->buf, fb->width, fb->height,
                                 rgb_buffer,
                                 EI_CLASSIFIER_INPUT_WIDTH,
                                 EI_CLASSIFIER_INPUT_HEIGHT);
    esp_camera_fb_return(fb);
    uint32_t pre_ms = millis() - t_pre;

    if (g_print_stats) {
        const size_t n_pix = (size_t)EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
        uint32_t sum_r = 0, sum_g = 0, sum_b = 0;
        uint8_t min_r = 255, min_g = 255, min_b = 255;
        uint8_t max_r = 0,   max_g = 0,   max_b = 0;
        for (size_t i = 0; i < n_pix; i++) {
            uint8_t r = rgb_buffer[i * 3 + 0];
            uint8_t g = rgb_buffer[i * 3 + 1];
            uint8_t b = rgb_buffer[i * 3 + 2];
            sum_r += r; sum_g += g; sum_b += b;
            if (r < min_r) min_r = r; if (r > max_r) max_r = r;
            if (g < min_g) min_g = g; if (g > max_g) max_g = g;
            if (b < min_b) min_b = b; if (b > max_b) max_b = b;
        }
        Serial.printf("rgb stats: meanR=%lu meanG=%lu meanB=%lu  rangeR=%u..%u rangeG=%u..%u rangeB=%u..%u\n",
                      (unsigned long)(sum_r / n_pix),
                      (unsigned long)(sum_g / n_pix),
                      (unsigned long)(sum_b / n_pix),
                      min_r, max_r, min_g, max_g, min_b, max_b);
    }

    if (g_dump_next) {
        g_dump_next = false;
        const size_t total = (size_t)EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT * 3;
        Serial.printf("DUMP_BEGIN %d %d\n", (int)EI_CLASSIFIER_INPUT_WIDTH, (int)EI_CLASSIFIER_INPUT_HEIGHT);
        b64_dump(rgb_buffer, total);
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
    Serial.println("[EI run_classifier]");

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

    if (g_direct_tflm) {
        float direct_h = 0.0f;
        float direct_n = 0.0f;
        int8_t raw0 = 0;
        int8_t raw1 = 0;
        uint32_t direct_ms = 0;
        if (run_direct_tflm(&direct_h, &direct_n, &raw0, &raw1, &direct_ms)) {
            Serial.printf("[direct TFLM] invoke %lu ms | raw=[%d,%d]\n",
                          (unsigned long)direct_ms, (int)raw0, (int)raw1);
            Serial.printf("  human: %.3f\n", direct_h);
            Serial.printf("  nonhuman: %.3f\n", direct_n);
            Serial.println(direct_h > direct_n ? "Direct: Human detected" : "Direct: Not detected");
        }
    }
}
