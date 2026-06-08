#include <Arduino.h>
#include "esp_camera.h"
#include "esp_heap_caps.h"
#include <TensorFlowLite_ESP32.h>
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"

// Include our locally-generated model header
#include "human_detect_model_data.h"

// =====================================================
//  CAMERA PINS (AI THINKER ESP32-CAM)
// =====================================================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// =====================================================
//  MODEL CONFIGURATION
// =====================================================
#define IMG_WIDTH 96
#define IMG_HEIGHT 96
#define TENSOR_ARENA_SIZE 90 * 1024  // 90KB fits in fast internal SRAM (our tiny model needs ~30KB)

// =====================================================
//  TFLITE GLOBALS
// =====================================================
tflite::MicroErrorReporter micro_error_reporter;
tflite::ErrorReporter* error_reporter = &micro_error_reporter;
const tflite::Model* model = nullptr;
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;
uint8_t* tensor_arena = nullptr;

unsigned long frame_count = 0;

// =====================================================
//  CAMERA SETUP
// =====================================================
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
  config.xclk_freq_hz = 10000000;        // 10MHz stable
  config.pixel_format = PIXFORMAT_RGB565; // OV2640 native RGB565 format
  config.frame_size = FRAMESIZE_QVGA;    // 320x240 QVGA
  config.jpeg_quality = 12;
  config.fb_count = 1;                   // Use single buffer to save memory

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("[ERROR] Camera Initialization Failed!");
    return;
  }
  
  // Converge White Balance and Auto Exposure
  sensor_t* s = esp_camera_sensor_get();
  if (s) {
    s->set_whitebal(s, 1);        // Auto white balance ON
    s->set_exposure_ctrl(s, 1);   // Auto exposure control ON
    s->set_gain_ctrl(s, 1);       // Auto gain control ON
  }
  
  for (int i = 0; i < 8; i++) {
    camera_fb_t* warm = esp_camera_fb_get();
    if (warm) esp_camera_fb_return(warm);
    delay(50);
  }
  
  Serial.println("[OK] Camera Initialized: RGB565 QVGA (320x240)");
}

// =====================================================
//  IMAGE PREPROCESSING (RGB565 center-square-crop, grayscale & resize)
// =====================================================
// Converts 320x240 RGB565 -> 240x240 Crop -> 96x96 Grayscale and quantizes it dynamically
void preprocess_frame(uint8_t *src, int src_w, int src_h, int8_t *dst, int dst_w, int dst_h, float scale, int zero_point) {
    int crop_h = src_h;             // 240
    int crop_w = src_h;             // 240
    int offset_x = (src_w - crop_w) / 2; // (320-240)/2 = 40 pixels offset

    for (int y = 0; y < dst_h; y++) {
        for (int x = 0; x < dst_w; x++) {
            // Map 96x96 destination index to 240x240 source crop window
            int src_x = offset_x + (x * crop_w / dst_w);
            int src_y = (y * crop_h / dst_h);
            
            // Bounds check
            if (src_x >= src_w) src_x = src_w - 1;
            if (src_y >= src_h) src_y = src_h - 1;

            // Get RGB565 pixel bytes
            int src_idx = (src_y * src_w + src_x) * 2;
            uint16_t pixel = (src[src_idx] << 8) | src[src_idx + 1];
            
            // Extract R, G, B channels
            uint8_t r = (pixel >> 11) & 0x1F;
            uint8_t g = (pixel >> 5) & 0x3F;
            uint8_t b = pixel & 0x1F;
            
            // Scale up to 8-bit [0, 255]
            r = (r << 3) | (r >> 2);
            g = (g << 2) | (g >> 4);
            b = (b << 3) | (b >> 2);
            
            // Convert to grayscale using standard luminance formula
            uint8_t gray = (uint8_t)((r * 77 + g * 150 + b * 29) >> 8);
            
            // Quantize raw grayscale [0, 255] directly based on TFLite quantization parameters.
            // Since the model's graph contains a Rescaling layer, the input expects raw pixel floats.
            int dst_idx = y * dst_w + x;
            dst[dst_idx] = (int8_t)constrain(round((float)gray / scale + zero_point), -128, 127);
        }
    }
}

// =====================================================
//  SETUP
// =====================================================
void setup() {
  // Force CPU frequency to maximum 240MHz for faster execution
  setCpuFrequencyMhz(240);
  
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n=== EAGLEEYE LOCAL MOBILENET V1 INFERENCE ===");
  Serial.printf("CPU Frequency: %d MHz\n", getCpuFrequencyMhz());
  
  // Allocate memory for Tensor Arena in fast internal SRAM (avoiding PSRAM latency)
  tensor_arena = (uint8_t*)heap_caps_malloc(TENSOR_ARENA_SIZE, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (tensor_arena != nullptr) {
      Serial.printf("[OK] Tensor Arena allocated in fast internal SRAM: %d bytes\n", TENSOR_ARENA_SIZE);
  } else {
      Serial.println("[WARNING] Failed to allocate in internal SRAM, trying normal malloc...");
      tensor_arena = (uint8_t*)malloc(TENSOR_ARENA_SIZE);
      if (tensor_arena != nullptr) {
          Serial.printf("[OK] Tensor Arena allocated in standard RAM: %d bytes\n", TENSOR_ARENA_SIZE);
      } else if (psramFound()) {
          Serial.println("[WARNING] Standard RAM allocation failed, falling back to slow PSRAM...");
          tensor_arena = (uint8_t*)ps_malloc(TENSOR_ARENA_SIZE);
      }
  }

  if (tensor_arena == nullptr) {
    Serial.println("[ERROR] Memory allocation for Tensor Arena failed!");
    while(true) { delay(1000); }
  }

  // Initialize Camera
  setup_camera();

  // Load model from generated array
  model = tflite::GetModel(g_human_detect_model_data);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.printf("[ERROR] Model schema version %d does not match TFLite runtime schema %d!\n", 
                  model->version(), TFLITE_SCHEMA_VERSION);
    while(true) { delay(1000); }
  }

  // Set up interpreter
  static tflite::AllOpsResolver resolver;
  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, TENSOR_ARENA_SIZE, error_reporter);
  interpreter = &static_interpreter;

  if (interpreter->AllocateTensors() != kTfLiteOk) {
    Serial.println("[ERROR] TFLite Allocate Tensors failed!");
    while(true) { delay(1000); }
  }

  input = interpreter->input(0);
  output = interpreter->output(0);
  
  Serial.println("\n--- Model Load Successful ---");
  Serial.printf("Input Shape:  %dx%dx%d\n", input->dims->data[1], input->dims->data[2], input->dims->data[3]);
  Serial.printf("Input Type:   %s\n", TfLiteTypeGetName(input->type));
  Serial.printf("Input Scale:  %.6f, ZeroPoint: %d\n", input->params.scale, input->params.zero_point);
  Serial.printf("Output Shape: %d classes\n", output->dims->data[1]);
  Serial.printf("Output Type:  %s\n", TfLiteTypeGetName(output->type));
  Serial.printf("Output Scale: %.6f, ZeroPoint: %d\n", output->params.scale, output->params.zero_point);
  Serial.println("-----------------------------\n");
}

// =====================================================
//  MAIN LOOP
// =====================================================
void loop() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[ERROR] Camera capture failed!");
    delay(500);
    return;
  }
  
  unsigned long start_pre = millis();
  
  // Crop, resize and dynamically quantize into 1-channel input tensor
  preprocess_frame(
      fb->buf, fb->width, fb->height, 
      input->data.int8, 
      IMG_WIDTH, IMG_HEIGHT, 
      input->params.scale, input->params.zero_point
  );
  
  unsigned long pre_ms = millis() - start_pre;
  esp_camera_fb_return(fb); // Release camera buffer immediately
  
  // Run inference
  unsigned long start_infer = millis();
  TfLiteStatus status = interpreter->Invoke();
  unsigned long infer_ms = millis() - start_infer;
  
  if (status != kTfLiteOk) {
    Serial.println("[ERROR] Inference invocation failed!");
    delay(500);
    return;
  }
  
  frame_count++;
  
  // Dequantize output tensor to get float probabilities
  float out_scale = output->params.scale;
  int out_zp = output->params.zero_point;
  
  // Class 0 = Humans, Class 1 = NonHuman (alphabetical order)
  float score_human    = (output->data.int8[0] - out_zp) * out_scale;
  float score_nonhuman = (output->data.int8[1] - out_zp) * out_scale;
  
  Serial.printf("[FRAME %lu] Preprocess: %lu ms | Inference: %lu ms | Human: %.3f, NonHuman: %.3f -> ", 
                frame_count, pre_ms, infer_ms, score_human, score_nonhuman);
                
  if (score_human > score_nonhuman && score_human > 0.5f) {
    Serial.println("HUMAN DETECTED!");
  } else {
    Serial.println("Not detected");
  }
  
  // Maintain a stable frame rate for continuous monitoring
  delay(150);
}
