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

// =====================================================
//  CONFIGURATION
// =====================================================

// --- PIR SENSOR ---
#define PIR_PIN GPIO_NUM_14           // PIR OUT connected to GPIO 14 (RTC_GPIO16)

// --- DEEP SLEEP TIMING ---
#define SCAN_DURATION_MS     15000    // 15s: AI scanning window after PIR wake-up
#define EXTENDED_SCAN_MS     30000    // 30s: Extra scanning after human confirmed
#define MIN_SLEEP_SECONDS    5        // Minimum sleep to avoid rapid wake cycling
#define ARMED_CHECK_TIMEOUT  5000     // 5s: Max wait for armed status from MQTT

// --- AI DETECTION ---
#define CLEAR_SCENE_FRAMES   20       // ~20 consecutive "no human" frames = person left

// --- CAMERA RESOLUTION ---
// High Quality Square Crop Mode:
// 1. Capture at 320x240 (QVGA)
// 2. Crop center 240x240 (no distortion)
// 3. Resize to 48x48 for AI

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
#define IMG_CHANNELS 1    // GRAYSCALE model
#define TENSOR_ARENA_SIZE 100 * 1024 

// =====================================================
//  GLOBALS
// =====================================================
tflite::MicroErrorReporter micro_error_reporter;
tflite::ErrorReporter* error_reporter = &micro_error_reporter;
const tflite::Model* model = nullptr;
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;
uint8_t* tensor_arena = nullptr;

// --- STATE ---
unsigned long wake_time = 0;          // millis() when we woke up
unsigned long scan_deadline = 0;      // When to stop scanning and sleep
unsigned long frame_count = 0;
bool human_confirmed = false;         // Have we confirmed a human this cycle?
bool image_sent_this_event = false;   // Only send ONE image per intrusion
int clear_scene_count = 0;            // Consecutive frames with no human

// =====================================================
//  CAMERA SETUP (RGB565 permanently)
// =====================================================
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
    Serial.println("[ERROR] Camera Init Failed!");
    return;
  }
  Serial.println("[OK] Camera: RGB565 QVGA (320x240) - greyscale AI");
}

// =====================================================
//  IMAGE PROCESSING: Square Crop → Resize → Greyscale
// =====================================================
// Converts 320x240 (QVGA) → Crop Center 240x240 → Resize to 48x48
void resize_rgb565_to_greyscale(uint8_t *src, int src_w, int src_h, int8_t *dst, int dst_w, int dst_h) {
    // 1. Define SQUARE crop window
    int crop_h = src_h;             // 240
    int crop_w = src_h;             // 240 (Make it square)
    int offset_x = (src_w - crop_w) / 2; // (320-240)/2 = 40 pixels offset

    for (int y = 0; y < dst_h; y++) {
        for (int x = 0; x < dst_w; x++) {
            // Map 48x48 → 240x240 Crop
            int src_x = offset_x + (x * crop_w / dst_w);
            int src_y = (y * crop_h / dst_h);
            
            // Bounds check
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
            
            // Normalize for TFLite int8: 0..255 → -128..127
            dst[y * dst_w + x] = (int8_t)(gray - 128);
        }
    }
}

// =====================================================
//  DEEP SLEEP FUNCTION
// =====================================================
void enter_deep_sleep() {
    Serial.println("\n========================================");
    Serial.println("   ENTERING DEEP SLEEP");
    Serial.printf("   Awake for: %lu seconds\n", (millis() - wake_time) / 1000);
    Serial.printf("   Frames processed: %lu\n", frame_count);
    Serial.println("   Waiting for PIR trigger on GPIO 14...");
    Serial.println("========================================\n");
    
    // Disconnect WiFi & MQTT cleanly
    client.disconnect();
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    
    // Deinit camera to prevent power drain
    esp_camera_deinit();
    
    // Configure wake-up source: PIR on GPIO 14 going HIGH
    esp_sleep_enable_ext0_wakeup(PIR_PIN, 1);  // 1 = wake on HIGH
    
    // Small delay so serial messages flush
    delay(100);
    
    // Enter deep sleep — system reboots on wake
    esp_deep_sleep_start();
    
    // Code never reaches here
}

// =====================================================
//  SETUP (Runs on every wake-up from deep sleep)
// =====================================================
void setup() {
  delay(500);
  Serial.begin(115200);
  
  // Record wake time
  wake_time = millis();
  
  // --- Check why we woke up ---
  esp_sleep_wakeup_cause_t wakeup_reason = esp_sleep_get_wakeup_cause();
  
  Serial.println("\n\n=================================================");
  Serial.println(">>> EAGLEEYE: AI SURVEILLANCE SYSTEM <<<");
  Serial.println(">>> PIR + Deep Sleep Mode <<<");
  Serial.println(">>> Greyscale Model (48x48x1) <<<");
  Serial.println("=================================================");
  
  switch(wakeup_reason) {
    case ESP_SLEEP_WAKEUP_EXT0:
      Serial.println(">>> WAKE REASON: PIR Motion Detected! <<<");
      break;
    case ESP_SLEEP_WAKEUP_TIMER:
      Serial.println(">>> WAKE REASON: Timer <<<");
      break;
    default:
      Serial.println(">>> WAKE REASON: Power-on / Reset <<<");
      break;
  }
  Serial.println("=================================================\n");

  // --- FREE GPIO 14 from SD Card ---
  // ESP32-CAM shares GPIO 14 with SD card. We must disable SD first.
  SD_MMC.end();
  gpio_reset_pin(GPIO_NUM_2);
  gpio_reset_pin(GPIO_NUM_12);
  gpio_reset_pin(GPIO_NUM_13);
  gpio_reset_pin(GPIO_NUM_14);
  gpio_reset_pin(GPIO_NUM_15);
  Serial.println("[OK] SD Card disabled - GPIO 14 freed for PIR");
  
  // Turn off flash LED initially
  pinMode(4, OUTPUT);
  digitalWrite(4, LOW);
  
  // Configure PIR pin as input (to read current state)
  pinMode(PIR_PIN, INPUT);

  // --- Initialize WiFi & MQTT ---
  Serial.println("[...] Connecting to WiFi & MQTT...");
  init_wifi_mqtt();
  Serial.printf("[OK] WiFi connected! IP: %s\n", WiFi.localIP().toString().c_str());

  // --- Wait briefly for MQTT to receive retained armed status ---
  Serial.println("[...] Checking system armed status...");
  unsigned long mqtt_wait_start = millis();
  while (millis() - mqtt_wait_start < ARMED_CHECK_TIMEOUT) {
    update_mqtt();
    delay(100);
  }
  
  // Check if system is disarmed
  if (!is_system_armed) {
    Serial.println(">>> SYSTEM IS DISARMED — Going back to sleep <<<");
    enter_deep_sleep();
    return;  // Never reached
  }
  Serial.println("[OK] System is ARMED — Starting detection");

  // --- Initialize TFLite Memory ---
  if (psramFound()) {
      tensor_arena = (uint8_t*)ps_malloc(TENSOR_ARENA_SIZE);
      Serial.printf("[OK] PSRAM found! Free: %d bytes\n", ESP.getFreePsram());
  } else {
      tensor_arena = (uint8_t*)malloc(TENSOR_ARENA_SIZE);
  }

  if (tensor_arena == nullptr) {
    Serial.println("[ERROR] Memory allocation failed!");
    enter_deep_sleep();
    return;
  }

  // --- Initialize Camera ---
  setup_camera_ai();

  // --- Load TFLite Model ---
  model = tflite::GetModel(g_human_detect_model_data); 
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.println("[ERROR] Model schema mismatch!");
    enter_deep_sleep();
    return;
  }

  // --- Setup Interpreter ---
  static tflite::AllOpsResolver resolver;
  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, TENSOR_ARENA_SIZE, error_reporter);
  interpreter = &static_interpreter;

  if (interpreter->AllocateTensors() != kTfLiteOk) {
    Serial.println("[ERROR] Allocate Tensors Failed!");
    enter_deep_sleep();
    return;
  }

  input = interpreter->input(0);
  output = interpreter->output(0);
  
  Serial.println("\n--- MODEL DETAILS ---");
  Serial.printf("Input Shape: %dx%dx%d\n", input->dims->data[1], input->dims->data[2], input->dims->data[3]);
  Serial.printf("Input Type: %s\n", TfLiteTypeGetName(input->type));
  Serial.printf("Output Shape: %d classes\n", output->dims->data[1]);
  Serial.println("---------------------\n");

  // --- Set scanning deadline ---
  scan_deadline = millis() + SCAN_DURATION_MS;
  
  Serial.println("========================================");
  Serial.printf("   AI SCANNING FOR %d SECONDS\n", SCAN_DURATION_MS / 1000);
  Serial.println("   Looking for humans...");
  Serial.println("========================================\n");
}

// =====================================================
//  MAIN LOOP (AI Detection + Smart Sleep)
// =====================================================
void loop() {
  // 1. Maintain MQTT Connection
  update_mqtt();
  
  // 2. Check if system was disarmed remotely while scanning
  if (!is_system_armed) {
    Serial.println(">>> DISARMED remotely — Going to sleep <<<");
    enter_deep_sleep();
    return;
  }

  // 3. Check if scan window has expired
  if (millis() > scan_deadline) {
    if (human_confirmed) {
      Serial.println(">>> Extended scan complete — Going to sleep <<<");
    } else {
      Serial.println(">>> No human found (false alarm) — Going to sleep <<<");
    }
    enter_deep_sleep();
    return;
  }

  // 4. Capture RGB565 Frame
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[ERROR] Camera capture failed!");
    delay(100);
    return;
  }

  // 5. Convert RGB565 → Greyscale and resize for model
  resize_rgb565_to_greyscale(fb->buf, fb->width, fb->height, input->data.int8, IMG_WIDTH, IMG_HEIGHT);
  esp_camera_fb_return(fb);

  // 6. Run Inference
  long t1 = millis();
  TfLiteStatus status = interpreter->Invoke();
  long inference_ms = millis() - t1;

  if (status != kTfLiteOk) {
    Serial.println("[ERROR] Inference Failed!");
    return;
  }

  // 7. Get Results
  int8_t human_score = output->data.int8[0];
  int8_t non_human_score = output->data.int8[1];
  frame_count++;

  bool human_detected = (human_score > non_human_score && human_score > 10);
  
  // Time remaining in scan window
  long time_left = (scan_deadline - millis()) / 1000;

  if (human_detected) {
    Serial.printf("[FRAME %lu] >>> HUMAN! <<< | H=%d N=%d | %dms | %lds left\n",
                  frame_count, human_score, non_human_score, inference_ms, time_left);
    
    clear_scene_count = 0;
    
    if (!image_sent_this_event) {
      Serial.println("========================================");
      Serial.println("   HUMAN CONFIRMED — CAPTURING IMAGE!");
      Serial.println("========================================");
      
      capture_and_send_image(NULL, 0, 0);
      image_sent_this_event = true;
      human_confirmed = true;
      
      // EXTEND the scan window — keep watching
      scan_deadline = millis() + EXTENDED_SCAN_MS;
      Serial.printf(">>> Extending scan by %d seconds <<<\n", EXTENDED_SCAN_MS / 1000);
    }
  } else {
    // No human in this frame
    clear_scene_count++;
    
    Serial.printf("[FRAME %lu] Monitor | H=%d N=%d | %dms | %lds left\n",
                  frame_count, human_score, non_human_score, inference_ms, time_left);
    
    // Scene cleared: person has left
    if (image_sent_this_event && clear_scene_count >= CLEAR_SCENE_FRAMES) {
      Serial.println(">>> Scene cleared! Person left — Going to sleep <<<");
      enter_deep_sleep();
      return;
    }
  }

  // Small delay between frames
  delay(50);
}
