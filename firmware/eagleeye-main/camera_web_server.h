#ifndef CAMERA_WEB_SERVER_H
#define CAMERA_WEB_SERVER_H

#include "esp_http_server.h"
#include "esp_timer.h"
#include "esp_camera.h"
#include "img_converters.h"
#include <Arduino.h>

#define PART_BOUNDARY "123456789000000000000987654321"

static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

extern bool is_streaming;

httpd_handle_t stream_httpd = NULL;

static esp_err_t stream_handler(httpd_req_t *req){
  camera_fb_t * fb = NULL;
  esp_err_t res = ESP_OK;
  size_t _jpg_buf_len = 0;
  uint8_t * _jpg_buf = NULL;
  char * part_buf[64];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if(res != ESP_OK){
    return res;
  }

  is_streaming = true;
  Serial.println(">>> LIVE STREAM STARTED: AI Paused <<<");

  while(true){
    fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      res = ESP_FAIL;
    } else {
      // We know the camera is in RGB565 mode for the AI
      // So we MUST convert to JPEG for the browser
      if(fb->format != PIXFORMAT_JPEG){
        bool jpeg_converted = frame2jpg(fb, 80, &_jpg_buf, &_jpg_buf_len); // 80% quality
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
    
    if(res == ESP_OK){
      size_t hlen = snprintf((char *)part_buf, 64, _STREAM_PART, _jpg_buf_len);
      res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
    }
    if(res == ESP_OK){
      res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
    }
    if(res == ESP_OK){
      res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    }
    
    // Cleanup
    if(fb){
      esp_camera_fb_return(fb);
      fb = NULL;
      _jpg_buf = NULL;
    } else if(_jpg_buf){
      free(_jpg_buf);
      _jpg_buf = NULL;
    }
    
    if(res != ESP_OK){
      break;
    }
    
    // IMPORTANT: Yield to allow the AI Task to run!
    // A delay of 100ms gives ~10 FPS max stream, leaving CPU time for AI.
    vTaskDelay(100 / portTICK_PERIOD_MS); 
  }
  
  is_streaming = false;
  Serial.println(">>> LIVE STREAM ENDED: AI Resumed <<<");
  return res;
}

// One JPEG frame (malloc). Caller must free(*jpg_buf). false if MJPEG / is active or camera error.
inline bool eagleeye_grab_jpeg(uint8_t **jpg_buf, size_t *jpg_len) {
  if (is_streaming) {
    return false;
  }
  *jpg_buf = NULL;
  *jpg_len = 0;

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    return false;
  }

  if (fb->format != PIXFORMAT_JPEG) {
    uint8_t *buf = NULL;
    size_t len = 0;
    bool ok = frame2jpg(fb, 40, &buf, &len);
    esp_camera_fb_return(fb);
    if (!ok || !buf) {
      return false;
    }
    *jpg_buf = buf;
    *jpg_len = len;
    return true;
  }

  size_t len = fb->len;
  uint8_t *buf = (uint8_t *)malloc(len);
  if (!buf) {
    esp_camera_fb_return(fb);
    return false;
  }
  memcpy(buf, fb->buf, len);
  esp_camera_fb_return(fb);
  *jpg_buf = buf;
  *jpg_len = len;
  return true;
}

// Single JPEG for mobile apps (HTTP fallback; WebSocket is preferred in app)
static esp_err_t capture_handler(httpd_req_t *req) {
  if (is_streaming) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_send(req, "MJPEG stream active", HTTPD_RESP_USE_STRLEN);
  }

  uint8_t *jpg_buf = NULL;
  size_t jpg_len = 0;
  if (!eagleeye_grab_jpeg(&jpg_buf, &jpg_len)) {
    httpd_resp_set_status(req, "500 Internal Server Error");
    return httpd_resp_send(req, "Camera capture failed", HTTPD_RESP_USE_STRLEN);
  }

  httpd_resp_set_type(req, "image/jpeg");
  esp_err_t res = httpd_resp_send(req, (const char *)jpg_buf, jpg_len);
  free(jpg_buf);
  return res;
}

void startCameraServer(){
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;

  httpd_uri_t stream_uri = {
    .uri       = "/",
    .method    = HTTP_GET,
    .handler   = stream_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t capture_uri = {
    .uri       = "/capture",
    .method    = HTTP_GET,
    .handler   = capture_handler,
    .user_ctx  = NULL
  };

  Serial.printf("Starting web server on port: '%d'\n", config.server_port);
  if (httpd_start(&stream_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &stream_uri);
    httpd_register_uri_handler(stream_httpd, &capture_uri);
    Serial.println("HTTP: GET /  (MJPEG), GET /capture (single JPEG)");
  }
}

#endif
