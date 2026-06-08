/*
 * ============================================================
 *  EAGLEEYE — AI-Assisted Hard Negative Capturer (WiFi Mode)
 *  ESP32-CAM AI Thinker
 *
 *  - Core 1: Camera capture + WebSocket video broadcast (~15 FPS)
 *  - Core 0: TFLite inference (runs in parallel, never blocks video)
 *
 *  Latency: retraining RGB->grayscale does NOT fix ~3 s Invoke(); use
 *  MicroMutableOpResolver (below). For EI v6.1 grayscale + serial timing,
 *  flash sketchboard/firmware/hard_negative_capturer/ instead.
 *  - Web UI: Shows live AI scores + capture buttons
 *  - Captures go to Python receiver via HTTP POST
 * ============================================================
 */

#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"
#include <WebSocketsServer.h>
#include <HTTPClient.h>
#include <TensorFlowLite_ESP32.h>
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "human_detect_model_data_v1_0_baseline.h"

// ============================================================
//  CONFIG — Edit these!
// ============================================================
const char* WIFI_SSID     = "DESKTOP-Q7922V6 8377";
const char* WIFI_PASSWORD = "12345678";
const char* PC_RECEIVER   = "http://192.168.137.1:8000/save"; // Python script

// ============================================================
//  CAMERA PINS (AI Thinker)
// ============================================================
#define PWDN_GPIO_NUM  32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM   0
#define SIOD_GPIO_NUM  26
#define SIOC_GPIO_NUM  27
#define Y9_GPIO_NUM    35
#define Y8_GPIO_NUM    34
#define Y7_GPIO_NUM    39
#define Y6_GPIO_NUM    36
#define Y5_GPIO_NUM    21
#define Y4_GPIO_NUM    19
#define Y3_GPIO_NUM    18
#define Y2_GPIO_NUM     5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM  23
#define PCLK_GPIO_NUM  22

// ============================================================
//  MODEL CONFIG (must match eagleeye-main)
// ============================================================
#define IMG_W           48
#define IMG_H           48
#define TENSOR_ARENA_KB 200

// ============================================================
//  GLOBALS
// ============================================================
// TFLite
tflite::MicroErrorReporter micro_error_reporter;
tflite::ErrorReporter*     error_reporter = &micro_error_reporter;
const tflite::Model*       tfl_model      = nullptr;
tflite::MicroInterpreter*  interpreter    = nullptr;
TfLiteTensor*              tfl_input      = nullptr;
TfLiteTensor*              tfl_output     = nullptr;
uint8_t*                   tensor_arena   = nullptr;

// Shared AI results (written by Core 0, read by Core 1 for UI)
volatile int8_t  g_human_score    = 0;
volatile int8_t  g_nonhuman_score = 0;
volatile bool    g_is_human       = false;
volatile bool    g_ai_busy        = false;

// Servers
httpd_handle_t   ctrl_httpd = NULL;
WebSocketsServer wsServer(81);

// FreeRTOS
TaskHandle_t aiTaskHandle = NULL;

// ============================================================
//  IMAGE PROCESSING  (same as eagleeye-main)
// ============================================================
void resize_rgb565_to_greyscale(uint8_t *src, int src_w, int src_h, int8_t *dst, int dst_w, int dst_h) {
    int crop_h = src_h;
    int crop_w = src_h;
    int offset_x = (src_w - crop_w) / 2;

    for (int y = 0; y < dst_h; y++) {
        for (int x = 0; x < dst_w; x++) {
            int src_x = offset_x + (x * crop_w / dst_w);
            int src_y = (y * crop_h / dst_h);
            
            if (src_x >= src_w) src_x = src_w - 1;
            if (src_y >= src_h) src_y = src_h - 1;

            int src_idx = (src_y * src_w + src_x) * 2;
            uint16_t pixel = (src[src_idx] << 8) | src[src_idx + 1];
            
            uint8_t r = (pixel >> 11) & 0x1F;
            uint8_t g = (pixel >> 5) & 0x3F;
            uint8_t b = pixel & 0x1F;
            
            r = (r << 3) | (r >> 2);
            g = (g << 2) | (g >> 4);
            b = (b << 3) | (b >> 2);
            
            uint8_t gray = (uint8_t)((r * 77 + g * 150 + b * 29) >> 8);
            
            dst[y * dst_w + x] = (int8_t)(gray - 128);
        }
    }
}

// ============================================================
//  SERIAL CAPTURE HANDLER
// ============================================================
void captureImagesSerial(int count) {
    Serial.printf("Capturing %d hard negative images in burst mode...\n", count);
    for (int i = 0; i < count; i++) {
        camera_fb_t* fb = esp_camera_fb_get();
        if (!fb) { Serial.println("Failed to get FB"); delay(100); continue; }
        
        uint8_t* jpg = nullptr; size_t jlen = 0;
        bool ok = frame2jpg(fb, 85, &jpg, &jlen);
        esp_camera_fb_return(fb);
        
        if (ok) {
            HTTPClient http;
            // Sending to Python receiver as 'nonhuman'
            String url = String(PC_RECEIVER) + "?label=nonhuman";
            http.begin(url);
            http.addHeader("Content-Type", "image/jpeg");
            int code = http.POST(jpg, jlen);
            free(jpg);
            http.end();
            if (code > 0) {
                Serial.printf("Captured %d/%d (Code %d)\n", i+1, count, code);
            } else {
                Serial.printf("Upload failed for image %d/%d\n", i+1, count);
            }
        }
        delay(250); // Small delay between captures
    }
    Serial.println("Burst capture complete.");
}

// ============================================================
//  AI TASK  (Core 0 — never blocks the video stream on Core 1)
// ============================================================
void aiTask(void*) {
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);   // sleep until frame ready
        
        uint32_t start_time = millis(); // Start timer
        
        if (interpreter->Invoke() == kTfLiteOk) {
            uint32_t end_time = millis(); // End timer
            
            g_human_score    = tfl_output->data.int8[0];
            g_nonhuman_score = tfl_output->data.int8[1];
            g_is_human       = (g_human_score > g_nonhuman_score && g_human_score > 10);
            
            // Print the exact inference time to the Serial Monitor
            Serial.printf("AI Inference Time: %u ms | H: %d, N: %d\n", 
                          (end_time - start_time), g_human_score, g_nonhuman_score);
        } else {
            Serial.println("AI Inference Failed!");
        }
        g_ai_busy = false;
    }
}

// ============================================================
//  WEB UI
// ============================================================
static const char INDEX_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EagleEye — Hard Negative Capturer</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',sans-serif;background:#0d0d0d;color:#eee;display:flex;flex-direction:column;align-items:center;padding:24px 16px;gap:20px}
  h1{font-size:1.3rem;letter-spacing:.05em;color:#7fdbff}
  #cam{position:relative;border-radius:10px;overflow:hidden;border:2px solid #2a2a2a;background:#111}
  #cam img{display:block;max-width:min(480px,100vw - 32px)}
  #hud{position:absolute;top:8px;left:8px;background:rgba(0,0,0,.72);padding:6px 10px;border-radius:6px;font-size:.85rem;line-height:1.6;font-family:monospace}
  .human-color{color:#7fdbff} .non-color{color:#ff7f7f} .ok{color:#4dff91} .no{color:#aaa}
  .btns{display:flex;gap:12px;flex-wrap:wrap;justify-content:center}
  button{padding:14px 28px;font-size:1rem;font-weight:700;border:none;border-radius:8px;cursor:pointer;transition:filter .15s}
  button:hover{filter:brightness(1.15)} button:active{filter:brightness(.85)}
  .b-human{background:#1a6b35;color:#fff} .b-non{background:#7a2020;color:#fff}
  #msg{font-size:.9rem;color:#aaa;min-height:1.2em;text-align:center}
</style>
</head>
<body>
<h1>⚡ EagleEye — Hard Negative Capturer</h1>
<div id="cam">
  <img id="frame" alt="stream">
  <div id="hud">
    <span class="human-color">Human</span>: <span id="hs">—</span><br>
    <span class="non-color">NonHuman</span>: <span id="ns">—</span><br>
    AI: <strong id="pred" class="no">—</strong>
  </div>
</div>
<div class="btns" style="align-items:center;">
  <div style="display:flex; align-items:center; gap:8px; background:#222; padding:10px; border-radius:8px;">
    <span>Burst Qty:</span>
    <input type="number" id="qty" value="10" min="1" max="100" style="width:60px; padding:6px; text-align:center; border-radius:4px; border:none; font-weight:bold; font-size:1rem;">
  </div>
  <button class="b-human" onclick="capBurst('human')">✅ Capture Human</button>
  <button class="b-non"   onclick="capBurst('nonhuman')">❌ Capture NonHuman</button>
</div>
<div id="msg">Connecting...</div>
<script>
const frameEl = document.getElementById('frame');
const hsEl    = document.getElementById('hs');
const nsEl    = document.getElementById('ns');
const predEl  = document.getElementById('pred');
const msgEl   = document.getElementById('msg');
const qtyEl   = document.getElementById('qty');

// WebSocket stream on port 81
const ws = new WebSocket('ws://' + location.hostname + ':81/');
ws.binaryType = 'blob';
ws.onopen  = () => msgEl.textContent = 'Stream connected!';
ws.onclose = () => msgEl.textContent = 'Stream disconnected — refresh page.';
ws.onmessage = e => {
  const url = URL.createObjectURL(e.data);
  frameEl.onload = () => URL.revokeObjectURL(url);
  frameEl.src = url;
};

// Poll AI prediction from port 80
const poll = async () => {
  try {
    const r = await fetch('/ai');
    const d = await r.json();
    hsEl.textContent = d.h;
    nsEl.textContent = d.n;
    predEl.textContent   = d.human ? 'HUMAN' : 'no human';
    predEl.className     = d.human ? 'ok' : 'no';
  } catch(_) {}
};
setInterval(poll, 400);

// Burst Capture button
const capBurst = async label => {
  const qty = parseInt(qtyEl.value) || 1;
  msgEl.textContent = `Starting burst capture of ${qty}...`;
  let successCount = 0;
  
  for(let i=1; i<=qty; i++) {
    msgEl.textContent = `Saving ${label} image ${i} of ${qty}...`;
    try {
      const r = await fetch('/capture?label=' + label);
      if(!r.ok) throw new Error('Failed');
      successCount++;
    } catch(e) {
      console.log(`Failed on image ${i}, continuing...`);
    }
    // Delay 600ms to give ESP32 camera and web server time to breathe
    await new Promise(res => setTimeout(res, 600));
  }
  msgEl.textContent = `✅ Burst finished! Successfully saved ${successCount}/${qty} images.`;
};
</script>
</body>
</html>
)rawliteral";

// ============================================================
//  HTTP HANDLERS (Port 80)
// ============================================================
static esp_err_t h_index(httpd_req_t* req) {
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, INDEX_HTML, sizeof(INDEX_HTML) - 1);
}

static esp_err_t h_ai(httpd_req_t* req) {
    char buf[80];
    snprintf(buf, sizeof(buf),
             "{\"h\":%d,\"n\":%d,\"human\":%s}",
             (int)g_human_score, (int)g_nonhuman_score,
             g_is_human ? "true" : "false");
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    return httpd_resp_send(req, buf, strlen(buf));
}

static esp_err_t h_capture(httpd_req_t* req) {
    // Parse label from query string
    char qs[64] = {0};
    char label[32] = "unknown";
    if (httpd_req_get_url_query_str(req, qs, sizeof(qs)) == ESP_OK)
        httpd_query_key_value(qs, "label", label, sizeof(label));

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { httpd_resp_send_500(req); return ESP_FAIL; }

    // High-quality JPEG for the dataset
    uint8_t* jpg = nullptr; size_t jlen = 0;
    bool ok = frame2jpg(fb, 85, &jpg, &jlen);
    esp_camera_fb_return(fb);

    if (!ok) { httpd_resp_send_500(req); return ESP_FAIL; }

    HTTPClient http;
    String url = String(PC_RECEIVER) + "?label=" + label;
    http.begin(url);
    http.addHeader("Content-Type", "image/jpeg");
    int code = http.POST(jpg, jlen);
    free(jpg);
    http.end();

    const char* reply = (code > 0) ? "Saved!" : "Upload failed — is Python script running?";
    httpd_resp_send(req, reply, HTTPD_RESP_USE_STRLEN);
    return ESP_OK;
}

void startCtrlServer() {
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.server_port = 80;
    cfg.ctrl_port   = 32768;
    if (httpd_start(&ctrl_httpd, &cfg) == ESP_OK) {
        httpd_uri_t u1 = {"/",        HTTP_GET, h_index,   nullptr};
        httpd_uri_t u2 = {"/ai",      HTTP_GET, h_ai,      nullptr};
        httpd_uri_t u3 = {"/capture", HTTP_GET, h_capture, nullptr};
        httpd_register_uri_handler(ctrl_httpd, &u1);
        httpd_register_uri_handler(ctrl_httpd, &u2);
        httpd_register_uri_handler(ctrl_httpd, &u3);
        Serial.println("[OK] HTTP server on port 80");
    }
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
    Serial.begin(115200);
    setCpuFrequencyMhz(240);
    Serial.println("\n\n=== EagleEye Hard Negative Capturer (WiFi) ===");

    // Flash LED off
    pinMode(4, OUTPUT); digitalWrite(4, LOW);

    // --- WiFi (Started BEFORE camera to prevent EV-VSYNC-OVF frame drops) ---
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(true);
    delay(100);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("[..] WiFi");
    while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
    Serial.printf("\n[OK] WiFi connected — http://%s\n", WiFi.localIP().toString().c_str());

    // --- Camera ---
    camera_config_t cam;
    cam.ledc_channel = LEDC_CHANNEL_0; cam.ledc_timer = LEDC_TIMER_0;
    cam.pin_d0=Y2_GPIO_NUM; cam.pin_d1=Y3_GPIO_NUM; cam.pin_d2=Y4_GPIO_NUM;
    cam.pin_d3=Y5_GPIO_NUM; cam.pin_d4=Y6_GPIO_NUM; cam.pin_d5=Y7_GPIO_NUM;
    cam.pin_d6=Y8_GPIO_NUM; cam.pin_d7=Y9_GPIO_NUM;
    cam.pin_xclk=XCLK_GPIO_NUM; cam.pin_pclk=PCLK_GPIO_NUM;
    cam.pin_vsync=VSYNC_GPIO_NUM; cam.pin_href=HREF_GPIO_NUM;
    cam.pin_sscb_sda=SIOD_GPIO_NUM; cam.pin_sscb_scl=SIOC_GPIO_NUM;
    cam.pin_pwdn=PWDN_GPIO_NUM; cam.pin_reset=RESET_GPIO_NUM;
    cam.xclk_freq_hz = 20000000;
    cam.pixel_format = PIXFORMAT_RGB565;
    cam.frame_size   = FRAMESIZE_QVGA;   // 320x240
    cam.jpeg_quality = 12;
    cam.fb_count     = 2;
    if (esp_camera_init(&cam) != ESP_OK) {
        Serial.println("[ERR] Camera init failed!"); while(1) delay(1000);
    }
    Serial.println("[OK] Camera: RGB565 QVGA");

    // --- TFLite ---
    tensor_arena = psramFound()
        ? (uint8_t*)ps_malloc(TENSOR_ARENA_KB * 1024)
        : (uint8_t*)malloc(TENSOR_ARENA_KB * 1024);
    if (!tensor_arena) { Serial.println("[ERR] No memory!"); while(1); }

    tfl_model = tflite::GetModel(g_human_detect_model_data_v1_0_baseline);
    // AllOpsResolver caused ~3 s Invoke() on ESP32; register only what v1 uses
    static tflite::MicroMutableOpResolver<6> resolver;
    resolver.AddConv2D();
    resolver.AddMaxPool2D();
    resolver.AddFullyConnected();
    resolver.AddReshape();
    resolver.AddSoftmax();
    static tflite::MicroInterpreter interp(tfl_model, resolver,
                                           tensor_arena, TENSOR_ARENA_KB * 1024,
                                           error_reporter);
    interpreter = &interp;
    interpreter->AllocateTensors();
    tfl_input  = interpreter->input(0);
    tfl_output = interpreter->output(0);
    Serial.println("[OK] TFLite ready");

    // --- Servers ---
    startCtrlServer();
    wsServer.begin();
    Serial.println("[OK] WebSocket stream on port 81");

    // --- AI task on Core 0 ---
    xTaskCreatePinnedToCore(aiTask, "AI", 8192, nullptr, 1, &aiTaskHandle, 0);
    Serial.println("[OK] AI task on Core 0");
    Serial.println("=== Ready ===\n");
}

// ============================================================
//  LOOP  (Core 1 — camera capture + WS broadcast)
// ============================================================
void loop() {
    wsServer.loop();
    
    // Check for Serial Burst Capture Commands
    if (Serial.available()) {
        String input = Serial.readStringUntil('\n');
        input.trim();
        int count = input.toInt();
        if (count > 0) {
            captureImagesSerial(count);
        }
    }

    static uint32_t last = 0;
    if (millis() - last < 66) { delay(2); return; }   // cap ~15 FPS
    last = millis();

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) return;

    // Kick AI on Core 0 (non-blocking — skip if still busy)
    if (!g_ai_busy) {
        g_ai_busy = true;
        resize_rgb565_to_greyscale(fb->buf, fb->width, fb->height,
                                tfl_input->data.int8, IMG_W, IMG_H);
        xTaskNotifyGive(aiTaskHandle);
    }

    // Broadcast JPEG over WebSocket only if someone is watching
    if (wsServer.connectedClients() > 0) {
        uint8_t* jpg = nullptr; size_t jlen = 0;
        if (frame2jpg(fb, 30, &jpg, &jlen)) {          // quality 30 = tiny packets
            wsServer.broadcastBIN(jpg, jlen);
            free(jpg);
        }
    }

    esp_camera_fb_return(fb);
}
