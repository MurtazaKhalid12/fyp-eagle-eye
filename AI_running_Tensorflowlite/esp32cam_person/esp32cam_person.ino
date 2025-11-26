// ESP32-CAM Person Detection with TensorFlow Lite
// Fixed VSYNC overflow and FB-SIZE issues

uint8_t* sendBuffer = (uint8_t*) ps_malloc(96 * 96); // 96x96 grayscale image

#define BLUETOOTH "ESP32BT"
#define WIFI_SSID "Pixel_1548"
#define WIFI_PASSWORD "12345612"

#if defined(BLUETOOTH)
  #include "esp32dumbdisplay.h"
  DumbDisplay dumbdisplay(new DDBluetoothSerialIO(BLUETOOTH));
#else
  #include "wifidumbdisplay.h"
  DumbDisplay dumbdisplay(new DDWiFiServerIO(WIFI_SSID, WIFI_PASSWORD));
#endif

#include "esp_camera.h" 
#include <TensorFlowLite_ESP32.h>
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "person_detect_model_data.h"

class DDTFLErrorReporter : public tflite::ErrorReporter {
public:
  virtual int Report(const char* format, va_list args) {
    int len = strlen(format);
    char buffer[max(32, 2 * len)];
    vsnprintf(buffer, sizeof(buffer), format, args);
    dumbdisplay.writeComment(buffer);
    Serial.println(buffer);
    return 0;
  }
};

tflite::ErrorReporter* error_reporter = new DDTFLErrorReporter();
const tflite::Model* model = ::tflite::GetModel(g_person_detect_model_data);
const int tensor_arena_size = 81 * 1024;
uint8_t* tensor_arena;
tflite::MicroInterpreter* interpreter = NULL;
TfLiteTensor* input;
constexpr int kNumCols = 96;
constexpr int kNumRows = 96;
constexpr int kPersonIndex = 1;
constexpr int kNotAPersonIndex = 2;
const float PersonScoreThreshold = 0.6;

const char* imageName = "esp32cam_gs";
const int imageWidth = kNumCols;
const int imageHeight = kNumRows;
GraphicalDDLayer* detectImageLayer;
GraphicalDDLayer* personImageLayer;
LcdDDLayer* statusLayer;

const framesize_t FrameSize = FRAMESIZE_96X96;
const pixformat_t PixelFormat = PIXFORMAT_GRAYSCALE;
bool initialiseCamera();
camera_fb_t* captureImage(bool useFlash);
void releaseCapturedImage(camera_fb_t* fb);
bool cameraReady;
bool cameraInitialized = false;

// Camera configuration
int cameraImageBrightness = 0;
const int brightLED = 4;
const int ledFreq = 5000;
const int ledChannel = 15;
const int ledRresolution = 8;

// GPIO Pins for AI-THINKER ESP32-CAM with OV2640
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

void brightLed(byte ledBrightness) {
  ledcWrite(ledChannel, ledBrightness);
}

void setupFlashPWM() {
  ledcSetup(ledChannel, ledFreq, ledRresolution);
  ledcAttachPin(brightLED, ledChannel);
  brightLed(32);
  delay(50);
  brightLed(0);
}

bool cameraImageSettings() {
  sensor_t *s = esp_camera_sensor_get();
  if (s == NULL) {
    Serial.println("ERROR: Failed to get camera sensor");
    return false;
  }

  // Reset sensor to default settings first
  s->set_framesize(s, FrameSize);
  delay(100);

  // Basic settings for OV2640 stability
  s->set_quality(s, 10);                        // 10-63, lower is better quality
  s->set_brightness(s, 0);                      // -2 to 2
  s->set_contrast(s, 0);                        // -2 to 2
  s->set_saturation(s, 0);                      // -2 to 2
  s->set_sharpness(s, 0);                       // -2 to 2
  s->set_denoise(s, 0);                         // 0 to 8
  
  // Enable auto controls
  s->set_gain_ctrl(s, 1);                       // AGC on
  s->set_exposure_ctrl(s, 1);                   // AEC on
  s->set_awb_gain(s, 1);                        // AWB on
  s->set_whitebal(s, 1);                        // White balance on
  
  // Disable potentially problematic features
  s->set_aec2(s, 0);                            // AEC DSP off
  s->set_dcw(s, 1);                             // Downsize enable
  s->set_bpc(s, 1);                             // Black pixel correction on
  s->set_wpc(s, 1);                             // White pixel correction on
  s->set_raw_gma(s, 1);                         // Gamma correction on
  s->set_lenc(s, 1);                            // Lens correction on
  
  // Mirror and flip off
  s->set_hmirror(s, 0);
  s->set_vflip(s, 0);
  
  // Special effects off
  s->set_special_effect(s, 0);
  
  Serial.println("Camera settings applied");
  return true;
}

bool initialiseCamera() {
  // Complete camera deinit if previously initialized
  if (cameraInitialized) {
    esp_camera_deinit();
    delay(500);
  }
  
  Serial.println("Initializing camera...");

#ifdef WITH_FLASH  
  setupFlashPWM();
#endif  

  // Check for PSRAM first
  if (!psramFound()) {
    Serial.println("ERROR: PSRam not found - required!");
    error_reporter->Report("ERROR: PSRam not found - required!");
    return false;
  }
  Serial.println("PSRAM found OK");

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
  
  // CRITICAL SETTINGS for VSYNC stability
  config.xclk_freq_hz = 10000000;               // 10MHz - balanced speed
  config.pixel_format = PixelFormat;            // GRAYSCALE
  config.frame_size = FrameSize;                // 96x96
  config.jpeg_quality = 10;                     // High quality
  config.fb_count = 2;                          // Double buffering REQUIRED
  config.fb_location = CAMERA_FB_IN_PSRAM;      // Use PSRAM
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;    // Only when buffer empty - prevents overflow

  Serial.printf("Initializing camera with %dx%d grayscale...\n", kNumCols, kNumRows);

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("ERROR: Camera init failed with error 0x%x\n", err);
    error_reporter->Report("ERROR: Camera init failed with error 0x%x", err);
    return false;
  }

  cameraInitialized = true;
  Serial.println("Camera hardware initialized");

  // Apply sensor settings
  delay(200);
  if (!cameraImageSettings()) {
    Serial.println("WARNING: Failed to apply camera settings");
  }
  
  // Critical: Flush initial frames (usually corrupted/wrong size)
  Serial.println("Flushing initial frames...");
  for (int i = 0; i < 5; i++) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb) {
      Serial.printf("Frame %d: size=%d bytes (expected %d)\n", i, fb->len, kNumCols * kNumRows);
      esp_camera_fb_return(fb);
      delay(100);
    } else {
      Serial.printf("Frame %d: NULL\n", i);
      delay(100);
    }
  }

  Serial.println("Camera initialization complete!");
  return true;
}

camera_fb_t* captureImage(bool useFlash) {
  if (useFlash) brightLed(255);
  
  // Wait for camera to be ready
  delay(30);
  
  camera_fb_t *fb = NULL;
  
  // Retry logic for frame capture
  for (int retry = 0; retry < 3; retry++) {
    fb = esp_camera_fb_get();
    
    if (fb == NULL) {
      Serial.printf("Capture attempt %d failed - NULL frame\n", retry + 1);
      delay(100);
      continue;
    }
    
    // Check frame buffer validity
    if (fb->len == 0 || fb->buf == NULL) {
      Serial.printf("Capture attempt %d - invalid buffer (len=%d)\n", retry + 1, fb->len);
      esp_camera_fb_return(fb);
      fb = NULL;
      delay(100);
      continue;
    }
    
    // Check expected size for grayscale 96x96
    int expected_size = kNumCols * kNumRows;
    if (fb->len != expected_size) {
      Serial.printf("WARNING: Frame size mismatch: got %d, expected %d\n", fb->len, expected_size);
      // Don't reject - sometimes this is still usable
    }
    
    // Valid frame captured
    break;
  }
  
  if (useFlash) {
    delay(10);
    brightLed(0);
  }
  
  if (fb == NULL) {
    Serial.println("ERROR: Failed to capture frame after retries");
    error_reporter->Report("ERROR: Camera capture failed after retries");
  } else {
    Serial.printf("Frame captured: %d bytes\n", fb->len);
  }
  
  return fb;
}

void releaseCapturedImage(camera_fb_t* fb) {
  if (fb) {
    esp_camera_fb_return(fb);
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n\n=== ESP32-CAM Person Detection Starting ===");
  Serial.printf("Free heap: %d bytes\n", ESP.getFreeHeap());
  Serial.printf("PSRAM size: %d bytes\n", ESP.getPsramSize());
  Serial.printf("Free PSRAM: %d bytes\n", ESP.getFreePsram());

  // Create UI layers
  Serial.println("Creating DumbDisplay layers...");
  detectImageLayer = dumbdisplay.createGraphicalLayer(imageWidth, imageHeight);
  detectImageLayer->padding(3);
  detectImageLayer->border(3, DD_COLOR_blue, "round");
  detectImageLayer->backgroundColor(DD_COLOR_blue);
  detectImageLayer->enableFeedback("fl");

  statusLayer = dumbdisplay.createLcdLayer(16, 4);
  statusLayer->padding(5);
  statusLayer->clear();
  statusLayer->writeCenteredLine("Initializing...", 1);

  personImageLayer = dumbdisplay.createGraphicalLayer(imageWidth, imageHeight);
  personImageLayer->padding(3);
  personImageLayer->border(3, DD_COLOR_blue, "round");
  personImageLayer->backgroundColor(DD_COLOR_blue);

  dumbdisplay.configAutoPin(DD_AP_VERT);
  Serial.println("DumbDisplay layers created");

  // Initialize TensorFlow Lite
  Serial.println("Initializing TensorFlow Lite...");
  dumbdisplay.writeComment(String("Preparing TFLite model v") + model->version());

  if (model->version() != TFLITE_SCHEMA_VERSION) {
    String msg = String("ERROR: Model schema v") + model->version() + 
                 " not supported (need v" + TFLITE_SCHEMA_VERSION + ")";
    error_reporter->Report(msg.c_str());
    Serial.println(msg);
    statusLayer->clear();
    statusLayer->pixelColor("red");
    statusLayer->writeCenteredLine("Model Error!", 1);
    return;
  }

  tensor_arena = (uint8_t *) heap_caps_malloc(tensor_arena_size, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (tensor_arena == NULL) {
    error_reporter->Report("ERROR: heap_caps_malloc() failed");
    Serial.println("ERROR: Failed to allocate tensor arena");
    statusLayer->clear();
    statusLayer->pixelColor("red");
    statusLayer->writeCenteredLine("Memory Error!", 1);
    return;
  }
  Serial.printf("Allocated %d bytes for tensor arena\n", tensor_arena_size);

  tflite::MicroMutableOpResolver<5>* micro_op_resolver = new tflite::MicroMutableOpResolver<5>();
  micro_op_resolver->AddAveragePool2D();
  micro_op_resolver->AddConv2D();
  micro_op_resolver->AddDepthwiseConv2D();
  micro_op_resolver->AddReshape();
  micro_op_resolver->AddSoftmax();

  interpreter = new tflite::MicroInterpreter(model, *micro_op_resolver, tensor_arena, 
                                            tensor_arena_size, error_reporter);

  TfLiteStatus allocate_status = interpreter->AllocateTensors();
  if (allocate_status != kTfLiteOk) {
    error_reporter->Report("ERROR: AllocateTensors() failed");
    Serial.println("ERROR: Failed to allocate tensors");
    statusLayer->clear();
    statusLayer->pixelColor("red");
    statusLayer->writeCenteredLine("Tensor Error!", 1);
    return;
  }

  input = interpreter->input(0);
  dumbdisplay.writeComment("TFLite model ready!");
  Serial.println("TensorFlow Lite initialized successfully");
  Serial.printf("Input tensor: %d bytes\n", input->bytes);

  // Initialize camera - CRITICAL STEP
  statusLayer->clear();
  statusLayer->writeCenteredLine("Init Camera...", 1);
  
  cameraReady = initialiseCamera(); 
  
  if (cameraReady) {
    dumbdisplay.writeComment("Camera initialized!");
    Serial.println("=== Camera Ready ===");
    statusLayer->clear();
    statusLayer->pixelColor("green");
    statusLayer->writeCenteredLine("Ready!", 1);
    statusLayer->writeCenteredLine("Tap top image", 2);
    statusLayer->writeCenteredLine("to detect", 3);
  } else {
    dumbdisplay.writeComment("ERROR: Camera init failed!");
    Serial.println("=== Camera Initialization Failed ===");
    statusLayer->clear();
    statusLayer->pixelColor("red");
    statusLayer->writeCenteredLine("Camera Error!", 1);
  }

  Serial.printf("Free heap after init: %d bytes\n", ESP.getFreeHeap());
  Serial.printf("Free PSRAM after init: %d bytes\n", ESP.getFreePsram());
}

void loop() {
  if (!cameraReady || interpreter == NULL) {
    Serial.println("ERROR: System not initialized!");
    statusLayer->clear();
    statusLayer->pixelColor("red");
    statusLayer->writeCenteredLine("Not Ready!", 1);
    delay(2000);
    return;
  }

  // Capture image with extensive error handling
  camera_fb_t* capturedImage = captureImage(false);
  if (capturedImage == NULL) {
    Serial.println("ERROR: Failed to capture image");
    delay(500);
    return;
  }

  // Validate captured image
  int expected_size = imageWidth * imageHeight;
  if (capturedImage->len != expected_size) {
    Serial.printf("WARNING: Size mismatch - got %d, expected %d\n", 
                  capturedImage->len, expected_size);
    
    // If size is too different, skip this frame
    if (abs((int)capturedImage->len - expected_size) > 100) {
      Serial.println("ERROR: Frame size too different - skipping");
      releaseCapturedImage(capturedImage);
      delay(200);
      return;
    }
  }

  // Display captured image
  detectImageLayer->cachePixelImageGS(imageName, capturedImage->buf, imageWidth, imageHeight);
  detectImageLayer->drawImageFileFit(imageName);

  // Check for user interaction (tap on image)
  const DDFeedback* feedback = detectImageLayer->getFeedback();
  if (feedback != NULL) {
    Serial.println("=== Detection Started ===");
    
    statusLayer->clear();
    statusLayer->pixelColor("red");
    statusLayer->writeCenteredLine("Detecting...", 1);
    dumbdisplay.writeComment("Running person detection...");

    // Prepare input tensor
    const uint8_t* person_data = capturedImage->buf;
    int copy_size = min((int)capturedImage->len, (int)input->bytes);
    
    for (int i = 0; i < copy_size; ++i) {
      input->data.int8[i] = person_data[i] ^ 0x80;  // Convert to signed
    }

    // Run inference
    Serial.println("Running inference...");
    long detect_start_millis = millis();
    TfLiteStatus invoke_status = interpreter->Invoke();
    long detect_taken_millis = millis() - detect_start_millis;
    
    if (invoke_status != kTfLiteOk) {
      error_reporter->Report("ERROR: Invoke failed!");
      Serial.println("ERROR: Inference failed");
      releaseCapturedImage(capturedImage);
      delay(1000);
      return;
    }

    // Process results
    TfLiteTensor* output = interpreter->output(0);
    int8_t _person_score = output->data.int8[kPersonIndex];
    int8_t _no_person_score = output->data.int8[kNotAPersonIndex];
    float person_score = (_person_score - output->params.zero_point) * output->params.scale;
    float no_person_score = (_no_person_score - output->params.zero_point) * output->params.scale;
    bool detected_person = person_score > PersonScoreThreshold;

    Serial.printf("Person score: %.3f\n", person_score);
    Serial.printf("No person score: %.3f\n", no_person_score);
    Serial.printf("Detection time: %ld ms\n", detect_taken_millis);
    Serial.printf("Result: %s\n", detected_person ? "PERSON DETECTED" : "No person");

    dumbdisplay.writeComment(String("Person: ") + String(person_score, 3));
    dumbdisplay.writeComment(String("No person: ") + String(no_person_score, 3));

    // Update display
    personImageLayer->unloadImageFile(imageName);
    if (detected_person) {
      dumbdisplay.savePixelImageGS(imageName, capturedImage->buf, imageWidth, imageHeight);
      dumbdisplay.writeComment("PERSON DETECTED - Image saved!");
      Serial.println("Image saved to phone");
    } else {
      personImageLayer->cachePixelImageGS(imageName, capturedImage->buf, imageWidth, imageHeight);
    }
    personImageLayer->drawImageFileFit(imageName);

    // Update status display
    statusLayer->clear();
    if (detected_person) {
      personImageLayer->backgroundColor("green");
      statusLayer->pixelColor("darkgreen");
      statusLayer->writeCenteredLine("PERSON!", 0);
      statusLayer->writeCenteredLine("DETECTED", 1);
    } else {
      personImageLayer->backgroundColor("gray");
      statusLayer->pixelColor("darkgray");
      statusLayer->writeCenteredLine("No Person", 0);
      statusLayer->writeCenteredLine("Detected", 1);
    }
    statusLayer->writeLine(String(" Score: ") + String((int)(100 * person_score)) + "%", 2);
    statusLayer->writeLine(String(" Time: ") + String((float)detect_taken_millis / 1000.0, 2) + "s", 3);

    Serial.println("=== Detection Complete ===\n");
    delay(1000);
  }

  releaseCapturedImage(capturedImage);
  
  // Longer delay to prevent camera buffer overflow
  delay(150);
}