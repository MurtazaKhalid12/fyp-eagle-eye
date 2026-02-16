#ifndef EAGLEEYE_IOT_H
#define EAGLEEYE_IOT_H

#include <WiFi.h>
#include <PubSubClient.h>
#include <libb64/cencode.h>
#include "esp_camera.h"
#include "img_converters.h"

// --- CONFIGURATION ---
#include "secrets.h" 

// Ensure these are defined in secrets.h
// const char* ssid_iot = "YOUR_WIFI_SSID";
// const char* password_iot = "YOUR_WIFI_PASSWORD";
// const char* mqtt_server_iot = "broker.hivemq.com";

const char* mqtt_topic_image = "eagleeye/camera/image";

WiFiClient espClient;
PubSubClient client(espClient);

// --- FLASHLIGHT CONFIGURATION ---
#define FLASH_GPIO_NUM 4  // AI Thinker ESP32-CAM flash LED pin

// --- HELPER FOR BASE64 ---
String msg_base64_encode(uint8_t *data, size_t len) {
  base64_encodestate _state;
  base64_init_encodestate(&_state);
  
  // Allocate buffer (approx 1.33x size + padding)
  int encoded_len = ((len + 2) / 3 * 4) + 1;
  char * encoded_data = (char *)malloc(encoded_len);
  
  if (!encoded_data) return "";
  
  int cnt = base64_encode_block((const char*)data, len, encoded_data, &_state);
  cnt += base64_encode_blockend(encoded_data + cnt, &_state);
  encoded_data[cnt] = '\0';
  
  String result = String(encoded_data);
  free(encoded_data);
  return result;
}

// --- MQTT RECONNECT ---
void mqtt_reconnect() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");
    if (client.connect("ESP32CameraClient")) {
      Serial.println("connected");
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}

// --- SETUP WIFI & MQTT ---
void init_wifi_mqtt() {
    WiFi.begin(ssid_iot, password_iot);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nWiFi connected");
    Serial.print("Connecting to MQTT Broker at: ");
    Serial.println(mqtt_server_iot);
    client.setServer(mqtt_server_iot, 1883);
    client.setBufferSize(51200); // 50KB buffer for COLOR JPEG images
    
    // Initialize flashlight pin
    pinMode(FLASH_GPIO_NUM, OUTPUT);
    digitalWrite(FLASH_GPIO_NUM, LOW);  // Start with flashlight OFF
    Serial.println("Flashlight initialized (GPIO 4)");
}

// --- KEEP ALIVE ---
void update_mqtt() {
    client.loop();
}

// --- MAIN UPLOAD LOGIC ---
// Camera is in RGB565 mode permanently (greyscale conversion done in software for AI).
// Capture RGB565 frame -> convert to COLOR JPEG -> send via MQTT
void capture_and_send_image(uint8_t *img_buf, int w, int h) {
    Serial.println("Human detected! Capturing COLOR image for upload...");
    
    // TURN ON FLASHLIGHT for better image quality
    digitalWrite(FLASH_GPIO_NUM, HIGH);
    Serial.println("Flashlight ON");
    delay(300); // Let flash and auto-exposure stabilize
    
    // Flush 1 frame so next capture has proper flash exposure
    camera_fb_t *temp = esp_camera_fb_get();
    if (temp) esp_camera_fb_return(temp);
    delay(100);
    
    // Capture a fresh COLOR RGB565 frame with flash ON
    camera_fb_t *fb = esp_camera_fb_get();
    
    // TURN OFF FLASHLIGHT immediately after capture
    digitalWrite(FLASH_GPIO_NUM, LOW);
    Serial.println("Flashlight OFF");
    
    if (!fb) {
        Serial.println("Camera capture failed for upload!");
        return;
    }
    
    Serial.printf("Captured RGB565 frame: %dx%d, %d bytes\n", fb->width, fb->height, fb->len);
    
    // Convert RGB565 to COLOR JPEG in software
    uint8_t *jpg_buf = NULL;
    size_t jpg_len = 0;
    bool converted = fmt2jpg(fb->buf, fb->len, fb->width, fb->height,
                             PIXFORMAT_RGB565, 85, &jpg_buf, &jpg_len);
    
    // Release the camera frame buffer immediately
    esp_camera_fb_return(fb);
    
    if (!converted || !jpg_buf) {
        Serial.println("JPEG conversion failed!");
        if (jpg_buf) free(jpg_buf);
        return;
    }
    
    Serial.printf("COLOR JPEG encoded: %d bytes\n", jpg_len);
    
    // Connect to MQTT if not connected
    if (!client.connected()) mqtt_reconnect();
    
    // Publish the COLOR JPEG image
    if (client.beginPublish(mqtt_topic_image, jpg_len, false)) {
        client.write(jpg_buf, jpg_len);
        client.endPublish();
        Serial.println("COLOR Image sent to Broker!");
    } else {
        Serial.println("MQTT Publish Failed (Check Buffer Size)");
    }
    
    // Free the JPEG buffer (allocated by fmt2jpg)
    free(jpg_buf);
    
    Serial.println("Upload complete!");
}

#endif




