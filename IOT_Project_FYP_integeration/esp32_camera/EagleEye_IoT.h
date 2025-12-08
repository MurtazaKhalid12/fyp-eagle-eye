#ifndef EAGLEEYE_IOT_H
#define EAGLEEYE_IOT_H

#include <WiFi.h>
#include <PubSubClient.h>
#include <libb64/cencode.h>
#include "esp_camera.h"
#include "img_converters.h"

// --- CONFIGURATION ---
const char* ssid_iot = "PEOPLE";
const char* password_iot = "12345678";
const char* mqtt_server_iot = "broker.hivemq.com";
const char* mqtt_topic_image = "eagleeye/camera/image";

WiFiClient espClient;
PubSubClient client(espClient);

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
}

// --- KEEP ALIVE ---
void update_mqtt() {
    client.loop();
}

// --- MAIN UPLOAD LOGIC ---
void capture_and_send_image() {
    Serial.println("Human detected! Capturing fresh frame for upload...");
    
    // 1. Capture a FRESH frame for the upload (High Quality)
    camera_fb_t * fb_upload = esp_camera_fb_get();
    if (!fb_upload) {
         Serial.println("Failed to capture upload frame");
         return;
    } 
    
    // 2. Convert raw RGB565 frame to JPEG
    uint8_t * jpeg_buf = NULL;
    size_t jpeg_len = 0;
    // fmt2jpg acts on the raw framebuffer (RGB565) directly
    bool converted = fmt2jpg(fb_upload->buf, fb_upload->len, fb_upload->width, fb_upload->height, fb_upload->format, 31, &jpeg_buf, &jpeg_len);

    if (converted) {
        // 3. Connect to MQTT if not connected
        if (!client.connected()) mqtt_reconnect();
        
        // 4. Base64 Encode
        String base64Image = msg_base64_encode(jpeg_buf, jpeg_len);

        // 5. Publish
        if (client.beginPublish(mqtt_topic_image, base64Image.length(), false)) {
            client.print(base64Image);
            client.endPublish();
            Serial.println("Image sent to Broker!");
        } else {
            Serial.println("MQTT Publish Failed (Check Buffer Size)");
        }
        free(jpeg_buf);
    } else {
        Serial.println("JPEG Compression Failed");
    }
    esp_camera_fb_return(fb_upload);
}

#endif
