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
    client.setServer(mqtt_server_iot, 1883);
    client.setBufferSize(20480); // 20KB buffer for raw binary JPEG
    
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
void capture_and_send_image(uint8_t *img_buf, int w, int h) {
    Serial.println("Human detected! Capturing HIGH-QUALITY image...");
    
    // TURN ON FLASHLIGHT for better image quality
    digitalWrite(FLASH_GPIO_NUM, HIGH);
    Serial.println("Flashlight ON");
    
    // IMPORTANT: Temporarily switch camera to JPEG mode for high-quality capture
    sensor_t * s = esp_camera_sensor_get();
    s->set_framesize(s, FRAMESIZE_SVGA);  // 800x600 for excellent quality
    s->set_quality(s, 8);  // JPEG quality 8 (very high quality, 0-63 scale)
    
    // Delay to let camera adjust and flashlight stabilize
    delay(200);
    
    // Capture a FRESH high-resolution JPEG with flashlight
    camera_fb_t *fb = esp_camera_fb_get();
    
    // TURN OFF FLASHLIGHT immediately after capture
    digitalWrite(FLASH_GPIO_NUM, LOW);
    Serial.println("Flashlight OFF");
    
    if (!fb) {
        Serial.println("Camera capture failed for upload");
        // Restore settings for AI
        s->set_framesize(s, FRAMESIZE_VGA);
        s->set_quality(s, 12);
        return;
    }
    
    Serial.printf("Captured HIGH-QUALITY image: %d bytes (should be 30-100KB)\n", fb->len);
    
    // Connect to MQTT if not connected
    if (!client.connected()) mqtt_reconnect();
    
    // Publish the high-quality JPEG directly
    if (client.beginPublish(mqtt_topic_image, fb->len, false)) {
        client.write(fb->buf, fb->len);
        client.endPublish();
        Serial.println("HIGH-QUALITY Image sent to Broker!");
    } else {
        Serial.println("MQTT Publish Failed (Check Buffer Size)");
    }
    
    // Return the frame buffer to free memory
    esp_camera_fb_return(fb);
    
    // Restore camera settings for AI inference
    s->set_framesize(s, FRAMESIZE_VGA);
    s->set_quality(s, 12);
    delay(100);
}

#endif
