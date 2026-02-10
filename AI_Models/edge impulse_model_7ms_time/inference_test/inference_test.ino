/*
 * Edge Impulse + DumbDisplay Integration
 * 
 * - Uses Edge Impulse EON Compiler for FAST Inference (~0.7s)
 * - Uses DumbDisplay for Visual Feedback
 * - UPDATED: Swaps bytes (Big Endian -> Little Endian) to fix colors!
 */

#include <Person_Detection_3_inferencing.h>
#include "esp_camera.h"

// --- DumbDisplay Setup ---
#define BLUETOOTH "ESP32BT" 
#include "esp32dumbdisplay.h"
DumbDisplay dumbdisplay(new DDBluetoothSerialIO(BLUETOOTH));

GraphicalDDLayer* detectImageLayer;
GraphicalDDLayer* personImageLayer;
LcdDDLayer* statusLayer;
const char* imageName = "esp32cam_rgb";

// --- Camera Pins (AI-Thinker ESP32-CAM) ---
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

// Allocate memory for the model
uint8_t *snapshot_buf; 
uint32_t snapshot_buf_size;

// Callback function to provide data to the classifier
static int raw_feature_get_data(size_t offset, size_t length, float *out_ptr) {
    // The DSP block expects ONE float per pixel, containing packed RGB (0xRRGGBB).
    // We have RGB565 (2 bytes per pixel).
    // NOTE: We have already swapped bytes to Little Endian in the loop()!
    
    size_t pixel_ix = offset; 
    for (size_t i = 0; i < length; i++) {
        // Read 2 bytes (Little Endian now)
        uint8_t b_low = snapshot_buf[(pixel_ix + i) * 2];
        uint8_t b_high = snapshot_buf[(pixel_ix + i) * 2 + 1];
        uint16_t pixel = (b_high << 8) | b_low; 

        // Extract RGB (5-6-5)
        uint8_t r = ((pixel >> 11) & 0x1F);
        uint8_t g = ((pixel >> 5) & 0x3F);
        uint8_t b = (pixel & 0x1F);

        // Scale to 8-bit (0-255)
        r = (r * 255) / 31;
        g = (g * 255) / 63;
        b = (b * 255) / 31;

        // Pack into integer: 0x00RRGGBB
        uint32_t pixel_rgb = (r << 16) | (g << 8) | b;
        
        // Cast to float (Edge Impulse expects this)
        out_ptr[i] = (float)pixel_rgb;
    }
    return 0;
}

void setup() {
    Serial.begin(115200);
    Serial.println("\n\n=== Edge Impulse + DumbDisplay (Byte Swap Fix) ===");

    // 1. Initialize Camera
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
    config.xclk_freq_hz = 20000000;
    
    // TRUE COLOR MODE
    config.pixel_format = PIXFORMAT_RGB565; 
    config.frame_size = FRAMESIZE_96X96; 
    config.jpeg_quality = 12;
    config.fb_count = 1;

    if (esp_camera_init(&config) != ESP_OK) {
        Serial.println("Camera init failed!");
        return;
    }
    
    // Allocate buffer: 96 * 96 * 2 bytes (for RGB565)
    snapshot_buf_size = 96 * 96 * 2; 
    snapshot_buf = (uint8_t*)malloc(snapshot_buf_size);
    
    Serial.println("Camera initialized.");

    // 2. Initialize DumbDisplay
    Serial.println("Creating DumbDisplay layers...");
    detectImageLayer = dumbdisplay.createGraphicalLayer(96, 96);
    detectImageLayer->padding(3);
    detectImageLayer->border(3, DD_COLOR_blue, "round");
    detectImageLayer->backgroundColor(DD_COLOR_blue);
    detectImageLayer->enableFeedback("fl"); // Enable click feedback

    statusLayer = dumbdisplay.createLcdLayer(16, 4);
    statusLayer->padding(5);
    statusLayer->clear();
    statusLayer->writeCenteredLine("Ready!", 1);
    statusLayer->writeCenteredLine("Tap to Detect", 2);

    personImageLayer = dumbdisplay.createGraphicalLayer(96, 96);
    personImageLayer->padding(3);
    personImageLayer->border(3, DD_COLOR_blue, "round");
    personImageLayer->backgroundColor(DD_COLOR_blue);

    dumbdisplay.configAutoPin(DD_AP_VERT);
}

void loop() {
    // Keep DD connection alive and check for any feedback (optional)
    detectImageLayer->getFeedback();
    
    // CONTINUOUS LOOP: No "if (feedback)" check anymore
    {
        Serial.println("\n--- Starting Capture ---");
        statusLayer->clear();
        statusLayer->writeCenteredLine("Capturing...", 1);

        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) {
            Serial.println("Camera capture failed");
            statusLayer->writeCenteredLine("Cam Error", 1);
            return;
        }

        if (fb->len > snapshot_buf_size) {
             Serial.printf("Error: Frame size %d > Buffer %d\n", fb->len, snapshot_buf_size);
             esp_camera_fb_return(fb);
             return;
        }
        
        // COPY AND SWAP BYTES (Big Endian -> Little Endian)
        // This fixes the "Psychedelic" colors
        for (size_t i = 0; i < fb->len; i += 2) {
            snapshot_buf[i] = fb->buf[i+1];     // Low byte
            snapshot_buf[i+1] = fb->buf[i];     // High byte
        }
        
        esp_camera_fb_return(fb);

        // Show Image on Phone
        // Now that bytes are swapped, it should look correct on the phone
        detectImageLayer->cachePixelImage16(imageName, (const uint16_t*)snapshot_buf, 96, 96);
        detectImageLayer->drawImageFileFit(imageName);

        // Run Inference
        statusLayer->writeCenteredLine("Inferencing...", 1);
        signal_t signal;
        signal.total_length = EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE; 
        signal.get_data = &raw_feature_get_data;

        Serial.println("Running Inference...");
        unsigned long start_time = millis();
        
        ei_impulse_result_t result = { 0 };
        EI_IMPULSE_ERROR res = run_classifier(&signal, &result, false);
        
        unsigned long duration = millis() - start_time;

        if (res != EI_IMPULSE_OK) {
            Serial.printf("ERR: %d\n", res);
            statusLayer->writeCenteredLine("Inf Error", 1);
            return;
        }

        Serial.printf("Time: %lu ms\n", duration);
        
        // Find top prediction
        float person_score = 0;
        
        for (size_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
            Serial.printf("  %s: %.5f\n", result.classification[i].label, result.classification[i].value);
            if (strcmp(result.classification[i].label, "person") == 0) {
                person_score = result.classification[i].value;
            }
        }

        // Update Status Layer
        statusLayer->clear();
        // CHANGED: Threshold lowered to 10% (0.10) as requested
        if (person_score > 0.10) {
            statusLayer->pixelColor("darkgreen");
            statusLayer->writeCenteredLine("PERSON!", 0);
            personImageLayer->backgroundColor("green");
        } else {
            statusLayer->pixelColor("darkred");
            statusLayer->writeCenteredLine("No Person", 0);
            personImageLayer->backgroundColor("red");
        }
        statusLayer->writeLine(String("Score: ") + String((int)(person_score * 100)) + "%", 2);
        statusLayer->writeLine(String("Time: ") + String(duration) + "ms", 3);
        
        // Also show result on the second image layer
        personImageLayer->drawImageFileFit(imageName);
    }
    
    // Keep DD connection alive
    dumbdisplay.writeComment(""); 
    delay(100);
}
