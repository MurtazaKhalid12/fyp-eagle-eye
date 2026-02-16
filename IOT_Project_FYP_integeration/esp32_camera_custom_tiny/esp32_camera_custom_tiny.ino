#include <Arduino.h>
#include "esp_camera.h"
#include <TensorFlowLite_ESP32.h>
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"

// --- INCLUDE YOUR NEW HEADER FILE ---
#include "human_detect_model_data.h"

// --- INCLUDE IOT HEADER ---
#include "EagleEye_IoT.h"

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

// --- MODEL CONFIGURATION ---
#define IMG_WIDTH 48
#define IMG_HEIGHT 48
#define IMG_CHANNELS 1    // GRAYSCALE model (much faster!)
#define TENSOR_ARENA_SIZE 100 * 1024 

// --- GLOBALS ---
tflite::MicroErrorReporter micro_error_reporter;
tflite::ErrorReporter* error_reporter = &micro_error_reporter;
const tflite::Model* model = nullptr;
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;
uint8_t* tensor_arena = nullptr;

// --- CAMERA SETUP (RGB565 permanently - works reliably on ESP32-CAM) ---
void setup_camera_ai() {
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
  config.pixel_format = PIXFORMAT_RGB565; // RGB565 (reliable on OV2640)
  config.frame_size = FRAMESIZE_QVGA;    // 320x240
  config.jpeg_quality = 12;
  config.fb_count = 2;                    // Double buffer in PSRAM

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("Camera Init Failed");
    return;
  }
  Serial.println("Camera initialized: RGB565 QVGA (320x240) - software greyscale for AI");
}

// --- RESIZE RGB565 -> GREYSCALE (320x240 -> 48x48x1) ---
// Captures in RGB565 (reliable) but converts to greyscale for the model
void resize_rgb565_to_greyscale(uint8_t *src, int src_w, int src_h, int8_t *dst, int dst_w, int dst_h) {
    for (int y = 0; y < dst_h; y++) {
        for (int x = 0; x < dst_w; x++) {
            int src_x = x * src_w / dst_w;
            int src_y = y * src_h / dst_h;
            
            // Get RGB565 pixel (2 bytes)
            int src_idx = (src_y * src_w + src_x) * 2;
            uint16_t pixel = (src[src_idx] << 8) | src[src_idx + 1];
            
            // Extract RGB from RGB565
            uint8_t r = (pixel >> 11) & 0x1F;
            uint8_t g = (pixel >> 5) & 0x3F;
            uint8_t b = pixel & 0x1F;
            
            // Scale to 8-bit
            r = (r << 3) | (r >> 2);
            g = (g << 2) | (g >> 4);
            b = (b << 3) | (b >> 2);
            
            // Convert to greyscale using luminance formula
            uint8_t gray = (uint8_t)((r * 77 + g * 150 + b * 29) >> 8);
            
            // Normalize for TFLite int8: 0..255 -> -128..127
            dst[y * dst_w + x] = (int8_t)(gray - 128);
        }
    }
}

void setup() {
  // 1. Initialize Serial
  delay(3000); // Wait for Serial Monitor
  Serial.begin(115200);
  Serial.println("\n\n=================================================");
  Serial.println(">>> TINY GRAYSCALE MODEL (48x48x1) FAST MODE <<<");
  Serial.println(">>> Optimized for Speed on ESP32 <<<");
  Serial.println("=================================================\n");

  // 2. Initialize WiFi & MQTT (from EagleEye_IoT.h)
  init_wifi_mqtt();

  // 3. Initialize Memory for TFLite
  if (psramFound()) {
      tensor_arena = (uint8_t*)ps_malloc(TENSOR_ARENA_SIZE);
      Serial.printf("PSRAM found! Free: %d bytes\n", ESP.getFreePsram());
  } else {
      tensor_arena = (uint8_t*)malloc(TENSOR_ARENA_SIZE);
  }

  if (tensor_arena == nullptr) {
    Serial.println("Memory Alloc Failed");
    return;
  }

  // 4. Initialize Camera (GRAYSCALE mode)
  setup_camera_ai();

  // 5. Load Model
  model = tflite::GetModel(g_human_detect_model_data); 
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.println("Model Schema Error"); 
    return;
  }

  // 6. Setup Interpreter
  static tflite::AllOpsResolver resolver;
  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, TENSOR_ARENA_SIZE, error_reporter);
  interpreter = &static_interpreter;

  if (interpreter->AllocateTensors() != kTfLiteOk) {
    Serial.println("Allocate Tensors Failed");
    return;
  }

  input = interpreter->input(0);
  output = interpreter->output(0);
  
  Serial.printf("Model input: %dx%dx%d (int8)\n", IMG_WIDTH, IMG_HEIGHT, IMG_CHANNELS);
  Serial.println("System Ready! GRAYSCALE mode - Listening for targets...");
}

// --- FRAME COUNTER FOR PERIODIC STATUS ---
static unsigned long frame_count = 0;

void loop() {
  // 1. Maintain MQTT Connection
  update_mqtt();

  // 2. Capture RGB565 Frame (always color - reliable on OV2640)
  camera_fb_t * fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[ERROR] Camera capture failed!");
    delay(100);
    return;
  }

  // 3. Convert RGB565 -> Greyscale and resize 320x240 -> 48x48x1 for model
  resize_rgb565_to_greyscale(fb->buf, fb->width, fb->height, input->data.int8, IMG_WIDTH, IMG_HEIGHT);
  esp_camera_fb_return(fb); // Release buffer immediately

  // 4. Run Inference
  long t1 = millis();
  TfLiteStatus status = interpreter->Invoke();
  long t2 = millis();
  long inference_ms = t2 - t1;

  if (status != kTfLiteOk) {
    Serial.println("[ERROR] Inference Failed!");
    return;
  }

  // 5. Get Results
  int8_t human_score = output->data.int8[0];
  int8_t non_human_score = output->data.int8[1];
  
  frame_count++;

  // 6. ALWAYS print detection status (continuous monitoring)
  // THRESHOLD: > 10 in int8 range [-128..127]
  // Non-human scores typically: -40 to -110 (well below threshold)
  // Human scores typically: +48 to +94 (well above threshold)
  // Gap between classes is ~91 points, threshold at 10 gives safe margin
  bool human_detected = (human_score > non_human_score && human_score > 10);
  
  if (human_detected) {
    Serial.printf("[FRAME %lu] >>> HUMAN DETECTED! <<< | Score: Human=%d, Non=%d | %dms\n",
                  frame_count, human_score, non_human_score, inference_ms);
  } else {
    Serial.printf("[FRAME %lu]     No Human           | Score: Human=%d, Non=%d | %dms\n",
                  frame_count, human_score, non_human_score, inference_ms);
  }

  // 7. Capture & Send Image ONLY when human detected (with cooldown)
  static unsigned long last_trigger = 0;
  
  if (human_detected) {
      if (millis() - last_trigger > 5000) {  // 5 second cooldown
          Serial.println("========================================");
          Serial.println("   CAPTURING IMAGE FOR UPLOAD!          ");
          Serial.println("========================================");
          
          // Captures frame -> converts to JPEG -> sends via MQTT
          capture_and_send_image(NULL, 0, 0);
          
          last_trigger = millis();
          Serial.println("Resuming continuous detection...\n");
      }
  }

  // Small delay to avoid flooding Serial too fast
  delay(50);
}
