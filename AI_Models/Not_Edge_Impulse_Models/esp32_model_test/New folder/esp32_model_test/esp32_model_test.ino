#include <Arduino.h>
#include "esp_camera.h"
#include <TensorFlowLite_ESP32.h>
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"

// INCLUDE YOUR NEW HEADER FILE
// INCLUDE YOUR NEW HEADER FILE
#include "human_detect_model_data.h"

// --- WIFI & WEB SERVER ---
#include <WiFi.h>
#include "esp_http_server.h"
#include "img_converters.h"

// --- CREDENTIALS ---
const char* ssid = "DESKTOP-Q7922V6 8377";
const char* password = "Z0@361z3";

// --- WEB SERVER GLOBALS ---
httpd_handle_t stream_httpd = NULL;

// --- STREAM HANDLER ---
// Standard MJPEG Stream Handler
static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t * fb = NULL;
  esp_err_t res = ESP_OK;
  size_t _jpg_buf_len = 0;
  uint8_t * _jpg_buf = NULL;
  char * part_buf[64];
  static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=123456789000000000000987654321";
  static const char* _STREAM_BOUNDARY = "\r\n--123456789000000000000987654321\r\n";
  static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if (res != ESP_OK) return res;

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      res = ESP_FAIL;
    } else {
        // Even though we capture in GRAYSCALE for AI efficiency,
        // Grayscale JPEGs display fine in browsers.
        if(fb->format != PIXFORMAT_JPEG){
            bool jpeg_converted = frame2jpg(fb, 80, &_jpg_buf, &_jpg_buf_len);
            esp_camera_fb_return(fb);
            fb = NULL;
            if(!jpeg_converted){
                Serial.println("JPEG compression failed");
                res = ESP_FAIL;
            }
        } else {
            _jpg_buf_len = fb->len;
            _jpg_buf = fb->buf;
        }
    }

    if (res == ESP_OK) {
      size_t hlen = snprintf((char *)part_buf, 64, _STREAM_PART, _jpg_buf_len);
      res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    }

    if (fb) {
      esp_camera_fb_return(fb);
      fb = NULL;
      _jpg_buf = NULL;
    } else if (_jpg_buf) {
      free(_jpg_buf);
      _jpg_buf = NULL;
    }

    if (res != ESP_OK) break;
    
    // IMPORTANT: Allow AI loop to run on the other core or sharing time
    // For this simple test, we are blocking inside the stream handler.
    // NOTE: This will PAUSE AI detection while you are watching the stream.
    // To have both running simultaneously requires FreeRTOS tasks.
    // For now, this is a "View Mode". Close tab to resume high-speed AI.
    vTaskDelay(20 / portTICK_PERIOD_MS); 
  }
  return res;
}

void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  httpd_uri_t stream_uri = {
    .uri       = "/",
    .method    = HTTP_GET,
    .handler   = stream_handler,
    .user_ctx  = NULL
  };
  if (httpd_start(&stream_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &stream_uri);
  }
}


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
#define IMG_WIDTH 48
#define IMG_HEIGHT 48

// --- CONFIGURATION ---
// EXPERIMENT: Use High Quality Square Crop
// 1. Capture at 320x240 (QVGA) instead of 160x120 (QQVGA) for more detail.
// 2. Crop the center 240x240 to make it SQUARE.
// 3. Resize to 48x48.
// RESULT: No "squishing" distortion (people look like people) + sharper details.


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
  config.frame_size = FRAMESIZE_QVGA; // 320x240 (Better detection than 160x120)
  config.jpeg_quality = 12;
  config.fb_count = 1;

  if(psramFound()){ config.fb_count = 2; } 

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("❌ Camera Init Failed");
    return;
  }
}

// NEW RESIZE FUNCTION: Square Crop -> Resize
// Converts 320x240 (QVGA) -> Crop Center 240x240 -> Resize to 48x48
void resize_image(uint8_t *src, int src_w, int src_h, int8_t *dst, int dst_w, int dst_h) {
    
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

            // Get pixel from QVGA source
            uint8_t pixel = src[src_y * src_w + src_x];
            
            // Normalize
            dst[y * dst_w + x] = (int8_t)(pixel - 128); 
        }
    }
}

void setup() {
  delay(2000); 
  Serial.begin(115200);
  Serial.println("\n🔥 SYSTEM STARTING (DQVGA Square Crop Mode)");
  Serial.println(">>> MODE: High Quality Square Crop (Corrects Distortion) <<<");

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

  // --- WIFI SETUP ---
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi Connected!");
  Serial.print("🎥 Stream Ready: http://");
  Serial.println(WiFi.localIP());

  // --- START SERVER ---
  startCameraServer();

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