#include <Arduino.h>
#include "esp_camera.h"
#include <TensorFlowLite_ESP32.h>
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"

// INCLUDE YOUR NEW HEADER FILE
#include "human_detect_model_data.h"

// --- PINS (AI THINKER) ---
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

// --- FAST CONFIGURATION ---
#define IMG_WIDTH 48  // Back to 48x48 for speed
#define IMG_HEIGHT 48

// 120KB is enough for 48x48
#define TENSOR_ARENA_SIZE 120 * 1024 

// --- GLOBALS ---
tflite::MicroErrorReporter micro_error_reporter;
tflite::ErrorReporter* error_reporter = &micro_error_reporter;
const tflite::Model* model = nullptr;
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;
uint8_t* tensor_arena = nullptr;

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
  config.xclk_freq_hz = 10000000; // 10MHz stable
  config.pixel_format = PIXFORMAT_GRAYSCALE; 
  config.frame_size = FRAMESIZE_QQVGA; // 160x120
  config.jpeg_quality = 12;
  config.fb_count = 1;

  if(psramFound()){ config.fb_count = 2; } 

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("❌ Camera Init Failed");
    return;
  }
}

// 160x120 -> 48x48
void resize_image(uint8_t *src, int src_w, int src_h, int8_t *dst, int dst_w, int dst_h) {
    for (int y = 0; y < dst_h; y++) {
        for (int x = 0; x < dst_w; x++) {
            int src_x = x * src_w / dst_w;
            int src_y = y * src_h / dst_h;
            uint8_t pixel = src[src_y * src_w + src_x];
            dst[y * dst_w + x] = (int8_t)(pixel - 128); // Signed INT8
        }
    }
}

void setup() {
  delay(2000); 
  Serial.begin(115200);
  Serial.println("\n🔥 SYSTEM STARTING (48x48 Fast Mode)");

  if (psramFound()) {
      tensor_arena = (uint8_t*)ps_malloc(TENSOR_ARENA_SIZE);
  } else {
      tensor_arena = (uint8_t*)malloc(TENSOR_ARENA_SIZE);
  }

  if (tensor_arena == nullptr) {
    Serial.println("❌ Memory Alloc Failed");
    return;
  }

  setup_camera();

  // Load Model
  model = tflite::GetModel(g_human_detect_model_data); 
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.println("❌ Model Schema Error"); 
    return;
  }

  static tflite::AllOpsResolver resolver;
  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, TENSOR_ARENA_SIZE, error_reporter);
  interpreter = &static_interpreter;

  if (interpreter->AllocateTensors() != kTfLiteOk) {
    Serial.println("❌ Allocate Tensors Failed");
    return;
  }

  input = interpreter->input(0);
  output = interpreter->output(0);
  
  Serial.println("✅ Ready! Expected < 500ms latency.");
}

void loop() {
  camera_fb_t * fb = esp_camera_fb_get();
  if (!fb) return;

  // Convert & Resize
  resize_image(fb->buf, fb->width, fb->height, input->data.int8, IMG_WIDTH, IMG_HEIGHT);
  esp_camera_fb_return(fb);

  // Measure Latency
  long t1 = millis();
  TfLiteStatus status = interpreter->Invoke();
  long t2 = millis();

  if (status != kTfLiteOk) {
    Serial.println("Inference Error");
    return;
  }

  int8_t human = output->data.int8[0];
  int8_t non = output->data.int8[1];

  Serial.print("⏱️ "); Serial.print(t2 - t1); Serial.print("ms | ");
  Serial.print("Score: "); Serial.print(human);
  
  if (human > non) Serial.println(" -> 🙋 HUMAN");
  else Serial.println(" -> .");
}