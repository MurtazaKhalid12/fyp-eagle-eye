#include <Arduino.h>
#include "esp_camera.h"
#include <TensorFlowLite_ESP32.h>
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include "human_detect_model_data.h"

// ============================================================================
// 1. PIN DEFINITIONS (AI THINKER ESP32-CAM)
// ============================================================================
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

// ============================================================================
// 2. CONFIGURATION
// ============================================================================
#define IMG_WIDTH 96
#define IMG_HEIGHT 96

// CRITICAL: A 96x96 model creates LARGE internal buffers.
// We allocate 500KB in PSRAM to prevent the "EXCVADDR" crash.
#define TENSOR_ARENA_SIZE 500 * 1024 

// ============================================================================
// 3. GLOBALS
// ============================================================================
tflite::MicroErrorReporter micro_error_reporter;
tflite::ErrorReporter* error_reporter = &micro_error_reporter;
const tflite::Model* model = nullptr;
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;

uint8_t* tensor_arena = nullptr;

// ============================================================================
// 4. CAMERA SETUP (STABILIZED)
// ============================================================================
void setup_camera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  
  // LOWER FREQUENCY TO 10MHz = MORE STABLE (Fixes Capture Failed)
  config.xclk_freq_hz = 10000000; 
  
  config.pixel_format = PIXFORMAT_GRAYSCALE; 
  config.frame_size = FRAMESIZE_QQVGA; // 160x120 -> We will resize to 96x96
  config.jpeg_quality = 12;
  config.fb_count = 1;

  if(psramFound()){
    config.fb_count = 2; // Double buffering if PSRAM exists
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("❌ Camera init failed with error 0x%x\n", err);
    return;
  }
}

// ============================================================================
// 5. PREPROCESSING (RESIZE)
// ============================================================================
// Input: 160x120 (uint8) -> Output: 96x96 (int8)
void resize_image(uint8_t *src, int src_w, int src_h, int8_t *dst, int dst_w, int dst_h) {
    for (int y = 0; y < dst_h; y++) {
        for (int x = 0; x < dst_w; x++) {
            // Nearest Neighbor Resize
            int src_x = x * src_w / dst_w;
            int src_y = y * src_h / dst_h;
            
            uint8_t pixel = src[src_y * src_w + src_x];
            
            // Normalize: 0..255 (uint8) -> -128..127 (int8)
            dst[y * dst_w + x] = (int8_t)(pixel - 128);
        }
    }
}

// ============================================================================
// 6. SETUP
// ============================================================================
void setup() {
  // CRITICAL DELAY: Give hardware 3 seconds to power up
  delay(3000); 

  Serial.begin(115200);
  while(!Serial);
  Serial.println("\n\n--- ESP32 HUMAN DETECTION (96x96) STARTING ---");

  // 1. ALLOCATE MEMORY (TENSOR ARENA)
  if (psramFound()) {
      tensor_arena = (uint8_t*)ps_malloc(TENSOR_ARENA_SIZE);
      Serial.printf("✅ Allocated %d KB in PSRAM for Tensor Arena\n", TENSOR_ARENA_SIZE/1024);
  } else {
      // Fallback
      tensor_arena = (uint8_t*)malloc(TENSOR_ARENA_SIZE);
      Serial.printf("⚠️ Allocated %d KB in DRAM for Tensor Arena (High Risk!)\n", TENSOR_ARENA_SIZE/1024);
  }

  if (tensor_arena == nullptr) {
      Serial.println("❌ ERROR: Tensor Arena Allocation Failed! Restarting...");
      delay(5000);
      ESP.restart();
  }

  // 2. SETUP CAMERA
  setup_camera();
  Serial.println("✅ Camera Initialized");

  // 3. LOAD MODEL
  model = tflite::GetModel(g_model); 
  
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    TF_LITE_REPORT_ERROR(error_reporter, "Model Schema Mismatch!");
    return;
  }
  Serial.println("✅ Model Loaded");

  // 4. INIT INTERPRETER
  static tflite::AllOpsResolver resolver;
  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, TENSOR_ARENA_SIZE, error_reporter);
  interpreter = &static_interpreter;

  // 5. ALLOCATE TENSORS (This is where it crashed before)
  Serial.println("⏳ Allocating Tensors... (This may take a moment)");
  TfLiteStatus allocate_status = interpreter->AllocateTensors();
  if (allocate_status != kTfLiteOk) {
    TF_LITE_REPORT_ERROR(error_reporter, "❌ AllocateTensors() failed!");
    return;
  }
  Serial.println("✅ Tensors Allocated");

  // 6. GET POINTERS
  input = interpreter->input(0);
  output = interpreter->output(0);
  
  Serial.print("🔍 Input Shape: [");
  Serial.print(input->dims->data[0]); Serial.print(",");
  Serial.print(input->dims->data[1]); Serial.print(",");
  Serial.print(input->dims->data[2]); Serial.print(",");
  Serial.print(input->dims->data[3]); Serial.println("]");

  Serial.println("🚀 SYSTEM READY - Starting Loop");
}

// ============================================================================
// 7. LOOP
// ============================================================================
void loop() {
  // A. CAPTURE
  camera_fb_t * fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("❌ Camera capture failed");
    return;
  }

  // B. PREPROCESS
  resize_image(fb->buf, fb->width, fb->height, input->data.int8, IMG_WIDTH, IMG_HEIGHT);
  esp_camera_fb_return(fb);

  // C. INFERENCE
  unsigned long t_start = millis();
  if (interpreter->Invoke() != kTfLiteOk) {
    Serial.println("❌ Inference Failed");
    return;
  }
  unsigned long t_end = millis();

  // D. RESULTS
  // Training typically sets: 0=Human, 1=NonHuman (or vice versa).
  // Check your confusing matrix labels to be 100% sure. 
  // We assume: Index 0 = Human.
  int8_t score_human = output->data.int8[0];
  int8_t score_non = output->data.int8[1];
  
  Serial.print("⏱️ "); Serial.print(t_end - t_start); Serial.print("ms | ");
  Serial.print("Human: "); Serial.print(score_human); 
  Serial.print(" | Non-Human: "); Serial.print(score_non);
  
  if (score_human > score_non) { 
    Serial.println(" -> 🙋 HUMAN");
  } else {
    Serial.println(" -> .");
  }
}