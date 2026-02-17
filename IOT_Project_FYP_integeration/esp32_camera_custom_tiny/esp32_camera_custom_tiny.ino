#include <Arduino.h>
#include "esp_camera.h"
#include <TensorFlowLite_ESP32.h>
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "esp_sleep.h"
#include "SD_MMC.h"
#include "driver/gpio.h"

// --- INCLUDE YOUR NEW HEADER FILE ---
#include "human_detect_model_data.h"

// --- INCLUDE IOT HEADER ---
#include "EagleEye_IoT.h"

// --- INCLUDE WEB SERVER HEADER ---
#include "camera_web_server.h"

#define CLEAR_SCENE_FRAMES 20         // ~20 consecutive "no human" frames = person left

// --- CONFIGURATION ---
// High Quality Square Crop Mode
// 1. Capture at 320x240 (QVGA)
// 2. Crop the center 240x240 to make it SQUARE (No distortion)
// 3. Resize to 48x48
// RESULT: No "squishing" distortion + sharper details.


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

// NEW RESIZE FUNCTION: Square Crop -> Resize
// Converts 320x240 (QVGA) -> Crop Center 240x240 -> Resize to 48x48
// NOTE: src is RGB565 (2 bytes per pixel)
void resize_rgb565_to_greyscale(uint8_t *src, int src_w, int src_h, int8_t *dst, int dst_w, int dst_h) {
    
    // 1. Define SQUARE crop window
    int crop_h = src_h;             // 240
    int crop_w = src_h;             // 240 (Make it square)
    int offset_x = (src_w - crop_w) / 2; // (320-240)/2 = 40 pixels offset

    for (int y = 0; y < dst_h; y++) {
        for (int x = 0; x < dst_w; x++) {
            // Map 48x48 -> 240x240 Crop
            int src_x = offset_x + (x * crop_w / dst_w);
            int src_y = (y * crop_h / dst_h);
            
            // Bounds check (just in case)
            if (src_x >= src_w) src_x = src_w - 1;
            if (src_y >= src_h) src_y = src_h - 1;

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
  delay(2000); // Wait for Serial Monitor
  Serial.begin(115200);
  Serial.println("\n\n=================================================");
  Serial.println(">>> EAGLEEYE: AI DETECTION SYSTEM <<<");
  Serial.println(">>> Greyscale Model (48x48x1) <<<");
  Serial.println(">>> MODE: High Quality Square Crop (Corrects Distortion) <<<");
  Serial.println("=================================================\n");
  
  // 3. Initialize WiFi & MQTT (from EagleEye_IoT.h)
  init_wifi_mqtt();
  
  // PRINT IP ADDRESS so user can find the stream
  Serial.print("Camera Stream Ready! Go to: http://");
  Serial.println(WiFi.localIP());
  
  // START WEB SERVER
  startCameraServer();

  // 4. Initialize Memory for TFLite
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

  // 5. Initialize Camera
  setup_camera_ai();

  // 6. Load Model
  model = tflite::GetModel(g_human_detect_model_data); 
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.println("Model Schema Error"); 
    return;
  }

  // 7. Setup Interpreter
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
  
  Serial.println("\n--- MODEL DETAILS ---");
  Serial.printf("Input Shape: %dx%dx%d\n", input->dims->data[1], input->dims->data[2], input->dims->data[3]);
  Serial.printf("Input Type: %s (1=FLOAT32, 3=UINT8, 9=INT8)\n", TfLiteTypeGetName(input->type));
  if (input->type == kTfLiteInt8) {
      Serial.printf("Input Quantization: ZeroPoint=%d, Scale=%.5f\n", input->params.zero_point, input->params.scale);
  }
  
  Serial.printf("Output Shape: %d classes\n", output->dims->data[1]);
  Serial.printf("Output Type: %s\n", TfLiteTypeGetName(output->type));
  Serial.println("---------------------\n");

  Serial.println("System Ready! Scanning for humans...\n");
}

// --- STATE TRACKING ---
static unsigned long frame_count = 0;
static unsigned long last_human_seen = 0;    // Timestamp of last human detection
static bool image_sent_this_event = false;   // Only send ONE image per intrusion
static int clear_scene_count = 0;            // Consecutive frames with no human

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

  bool human_detected = (human_score > non_human_score && human_score > 10);
  
  if (human_detected) {
    Serial.printf("[FRAME %lu] >>> HUMAN DETECTED! <<< | Score: Human=%d, Non=%d | %dms\n",
                  frame_count, human_score, non_human_score, inference_ms);
    
    last_human_seen = millis();
    clear_scene_count = 0;  // Reset clear counter
    
    // --- TRIGGER ONCE PER EVENT ---
    // Send only ONE image per intrusion event
    if (!image_sent_this_event) {
        Serial.println("========================================");
        Serial.println("   HUMAN CONFIRMED - CAPTURING IMAGE!   ");
        Serial.println("========================================");
        
        capture_and_send_image(NULL, 0, 0);
        image_sent_this_event = true;  // Don't send again until scene clears
        
        Serial.println("Image sent! Monitoring until person leaves...\n");
    }
  } else {
    // No human in this frame
    clear_scene_count++;
    
    // Print status for EVERY frame
    // if (frame_count % 10 == 0) {
      Serial.printf("[FRAME %lu] Status: %s | Score: H=%d, N=%d | AI Time: %dms\n",
                    frame_count, (human_detected ? "HUMAN" : "Monitor"), human_score, non_human_score, inference_ms);
    // }
    
    // --- SCENE CLEARED: Person has left ---
    // If we had sent an image and now see no human for CLEAR_SCENE_FRAMES
    if (image_sent_this_event && clear_scene_count >= CLEAR_SCENE_FRAMES) {
      Serial.println(">>> Scene cleared! Person has left. Re-armed for next detection.");
      image_sent_this_event = false;  // Re-arm for next person
    }
  }



  // Small delay
  delay(50);
}
