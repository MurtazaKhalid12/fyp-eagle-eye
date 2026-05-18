/*
 * EagleEye — Hard Negative Capturer (Serial-only)
 * ESP32-CAM: 48x48 grayscale human vs nonhuman
 * Serial 115200: "Human detected" / "Not detected"
 *
 * Model switch (edit before flash):
 *   USE_EDGE_IMPULSE_MODEL 0  -> v2.1 local INT8 (~100-200 ms invoke)  [default]
 *   USE_EDGE_IMPULSE_MODEL 1  -> EI v6.1 (~2200 ms on TensorFlowLite_ESP32, no ESP-NN)
 */

#include <Arduino.h>
#include "esp_camera.h"
#include <TensorFlowLite_ESP32.h>
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// 0 = fast in-house v2.1 | 1 = Edge Impulse v6.1 (slow on bare TFLite Micro)
#ifndef USE_EDGE_IMPULSE_MODEL
#define USE_EDGE_IMPULSE_MODEL  0
#endif

#if USE_EDGE_IMPULSE_MODEL
#include "human_detect_model_data.h"
#define MODEL_TAG "EI v6.1 grayscale (expect ~2.2s invoke)"
#else
#include "human_detect_model_data_v2_1.h"
#define MODEL_TAG "v2.1 hard-negative 90+ (expect ~100-200ms invoke)"
#endif

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

#define IMG_W           48
#define IMG_H           48
#define IMG_C           1
#define TENSOR_ARENA_KB 200
#define LABEL_HUMAN     0
#define LABEL_NONHUMAN  1

#define INFER_INTERVAL_MS  200
#define REPORT_TIMING      1

// Only print when class changes (reduces Serial load)
#define REPORT_ON_CHANGE   0

tflite::MicroErrorReporter micro_error_reporter;
tflite::ErrorReporter* error_reporter = &micro_error_reporter;
const tflite::Model* tfl_model = nullptr;
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* tfl_input = nullptr;
TfLiteTensor* tfl_output = nullptr;
uint8_t* tensor_arena = nullptr;

#if USE_EDGE_IMPULSE_MODEL
static tflite::MicroMutableOpResolver<6> resolver;
#else
static tflite::AllOpsResolver resolver;
#endif

void resize_rgb565_to_grayscale_int8(uint8_t* src, int src_w, int src_h,
                                     int8_t* dst, int dst_w, int dst_h) {
    int crop_w = src_h;
    int offset_x = (src_w - crop_w) / 2;

    for (int y = 0; y < dst_h; y++) {
        for (int x = 0; x < dst_w; x++) {
            int src_x = offset_x + (x * crop_w / dst_w);
            int src_y = (y * src_h / dst_h);
            if (src_x >= src_w) src_x = src_w - 1;
            if (src_y >= src_h) src_y = src_h - 1;

            int src_idx = (src_y * src_w + src_x) * 2;
            uint16_t pixel = (src[src_idx] << 8) | src[src_idx + 1];

            uint8_t r = (pixel >> 11) & 0x1F;
            uint8_t g = (pixel >> 5) & 0x3F;
            uint8_t b = pixel & 0x1F;
            r = (r << 3) | (r >> 2);
            g = (g << 2) | (g >> 4);
            b = (b << 3) | (b >> 2);

            uint8_t gray = (uint8_t)((r * 77 + g * 150 + b * 29) >> 8);
            dst[y * dst_w + x] = (int8_t)(gray - 128);
        }
    }
}

bool run_inference(bool* out_human, uint32_t* out_invoke_ms) {
    uint32_t t0 = millis();
    if (interpreter->Invoke() != kTfLiteOk) {
        Serial.println("[ERR] Inference failed");
        return false;
    }
    if (out_invoke_ms) *out_invoke_ms = millis() - t0;

    int8_t h = tfl_output->data.int8[LABEL_HUMAN];
    int8_t n = tfl_output->data.int8[LABEL_NONHUMAN];
    *out_human = (h > n);
    return true;
}

void report_detection(bool is_human) {
    Serial.println(is_human ? "Human detected" : "Not detected");
}

void setup() {
    Serial.begin(115200);
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
    setCpuFrequencyMhz(240);

    Serial.println("\n=== EagleEye Serial Detector ===");
    Serial.println("[build] sketchboard/firmware/hard_negative_capturer");
    Serial.printf("[model] %s\n", MODEL_TAG);

    pinMode(4, OUTPUT);
    digitalWrite(4, LOW);

    camera_config_t cam = {};
    cam.ledc_channel = LEDC_CHANNEL_0;
    cam.ledc_timer = LEDC_TIMER_0;
    cam.pin_d0 = Y2_GPIO_NUM;
    cam.pin_d1 = Y3_GPIO_NUM;
    cam.pin_d2 = Y4_GPIO_NUM;
    cam.pin_d3 = Y5_GPIO_NUM;
    cam.pin_d4 = Y6_GPIO_NUM;
    cam.pin_d5 = Y7_GPIO_NUM;
    cam.pin_d6 = Y8_GPIO_NUM;
    cam.pin_d7 = Y9_GPIO_NUM;
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
    if (esp_camera_init(&cam) != ESP_OK) {
        Serial.println("[ERR] Camera init failed");
        while (1) delay(1000);
    }
    Serial.println("[OK] Camera QVGA RGB565");

    tensor_arena = psramFound()
        ? (uint8_t*)ps_malloc(TENSOR_ARENA_KB * 1024)
        : (uint8_t*)malloc(TENSOR_ARENA_KB * 1024);
    if (!tensor_arena) {
        Serial.println("[ERR] No PSRAM/RAM for tensor arena");
        while (1) delay(1000);
    }

    tfl_model = tflite::GetModel(g_human_detect_model_data);
    if (tfl_model->version() != TFLITE_SCHEMA_VERSION) {
        Serial.println("[ERR] Model schema mismatch");
        while (1) delay(1000);
    }

#if USE_EDGE_IMPULSE_MODEL
    resolver.AddConv2D();
    resolver.AddMaxPool2D();
    resolver.AddFullyConnected();
    resolver.AddReshape();
    resolver.AddRelu();
#endif

    static tflite::MicroInterpreter static_interp(
        tfl_model, resolver, tensor_arena, TENSOR_ARENA_KB * 1024, error_reporter);
    interpreter = &static_interp;

    if (interpreter->AllocateTensors() != kTfLiteOk) {
        Serial.println("[ERR] AllocateTensors failed");
        while (1) delay(1000);
    }

    tfl_input = interpreter->input(0);
    tfl_output = interpreter->output(0);
    if (tfl_input->bytes != IMG_W * IMG_H * IMG_C) {
        Serial.printf("[ERR] Input %d bytes, expected %d\n",
                      tfl_input->bytes, IMG_W * IMG_H * IMG_C);
        while (1) delay(1000);
    }

    Serial.printf("[OK] PSRAM: %s | arena %d KB\n",
                  psramFound() ? "yes" : "no", TENSOR_ARENA_KB);
    Serial.printf("[OK] Weights %u bytes | input %dx%dx%d\n",
                  (unsigned)g_human_detect_model_data_len, IMG_W, IMG_H, IMG_C);

    memset(tfl_input->data.int8, 0, tfl_input->bytes);
    uint32_t warm_ms = 0;
    bool dummy = false;
    run_inference(&dummy, &warm_ms);
    Serial.printf("[OK] Warmup invoke: %lu ms\n", (unsigned long)warm_ms);
#if USE_EDGE_IMPULSE_MODEL
    Serial.println("[note] EI on TensorFlowLite_ESP32 uses slow reference conv (~2s).");
    Serial.println("       For fast EI use Studio Arduino export (ESP-NN), or set");
    Serial.println("       USE_EDGE_IMPULSE_MODEL to 0 for v2.1 local model.");
#endif
    Serial.println("Watching...\n");
}

void loop() {
    static uint32_t last_infer = 0;
    if (millis() - last_infer < INFER_INTERVAL_MS) {
        delay(5);
        return;
    }
    last_infer = millis();

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) return;

    uint32_t t_preprocess = millis();
    resize_rgb565_to_grayscale_int8(
        fb->buf, fb->width, fb->height, tfl_input->data.int8, IMG_W, IMG_H);
    esp_camera_fb_return(fb);
    uint32_t preprocess_ms = millis() - t_preprocess;

    bool is_human = false;
    uint32_t invoke_ms = 0;
    if (run_inference(&is_human, &invoke_ms)) {
#if REPORT_TIMING
        Serial.printf("timing: preprocess %lu ms | invoke %lu ms | total %lu ms\n",
                      (unsigned long)preprocess_ms,
                      (unsigned long)invoke_ms,
                      (unsigned long)(preprocess_ms + invoke_ms));
#endif
#if REPORT_ON_CHANGE
        static int last = -1;
        int cur = is_human ? 1 : 0;
        if (cur != last) {
            report_detection(is_human);
            last = cur;
        }
#else
        report_detection(is_human);
#endif
    }
}
