/*
 * ============================================================
 *  EAGLEEYE — AI-Assisted Hard Negative Capturer (WiFi + EI)
 *  ESP32-CAM AI Thinker
 *
 *  - Web UI on ESP32: live camera stream + current EI scores
 *  - Capture buttons POST JPEGs to sketchboard's Python receiver
 *  - AI uses the installed Edge Impulse Arduino library:
 *      ei_arduino_library_rgb96_mobilenetv1_a2_no_espnn.zip
 * ============================================================
 */

#include <final_inferencing.h>

#include <Arduino.h>
#include "esp_camera.h"
#include "img_converters.h"
#include <WiFi.h>
#include "esp_http_server.h"
#include <WebSocketsServer.h>
#include <HTTPClient.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// ============================================================
//  CONFIG - edit these if your WiFi / PC IP changes
// ============================================================
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* PC_RECEIVER   = "http://192.168.137.1:8000/save";

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

#define HUMAN_THRESHOLD 0.65f

static uint8_t rgb_buffer[EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT * 3];

volatile bool  g_ai_busy = false;
volatile bool  g_is_human = false;
volatile float g_human_score = 0.0f;
volatile float g_nonhuman_score = 0.0f;
volatile int   g_last_classification_ms = 0;
volatile int   g_last_dsp_ms = 0;

httpd_handle_t ctrl_httpd = NULL;
WebSocketsServer wsServer(81);
TaskHandle_t aiTaskHandle = NULL;

static void rgb565_to_rgb888_resize_crop(const uint8_t* src, int src_w, int src_h,
                                         uint8_t* dst, int dst_w, int dst_h) {
    int crop_w = src_h;
    int offset_x = (src_w - crop_w) / 2;
    for (int y = 0; y < dst_h; y++) {
        for (int x = 0; x < dst_w; x++) {
            int sx = offset_x + (x * crop_w / dst_w);
            int sy = (y * src_h / dst_h);
            if (sx >= src_w) sx = src_w - 1;
            if (sy >= src_h) sy = src_h - 1;

            int idx = (sy * src_w + sx) * 2;
            uint16_t pix = (src[idx] << 8) | src[idx + 1];
            uint8_t r = (pix >> 11) & 0x1F;
            uint8_t g = (pix >> 5) & 0x3F;
            uint8_t b = pix & 0x1F;
            r = (r << 3) | (r >> 2);
            g = (g << 2) | (g >> 4);
            b = (b << 3) | (b >> 2);

            int di = (y * dst_w + x) * 3;
            dst[di] = r;
            dst[di + 1] = g;
            dst[di + 2] = b;
        }
    }
}

static int ei_get_data_cb(size_t offset, size_t length, float* out_ptr) {
    for (size_t i = 0; i < length; i++) {
        size_t pix_idx = (offset + i) * 3;
        uint8_t r = rgb_buffer[pix_idx];
        uint8_t g = rgb_buffer[pix_idx + 1];
        uint8_t b = rgb_buffer[pix_idx + 2];
        out_ptr[i] = (float)((r << 16) | (g << 8) | b);
    }
    return 0;
}

void aiTask(void*) {
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        ei::signal_t signal;
        signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
        signal.get_data = &ei_get_data_cb;

        ei_impulse_result_t result = {};
        EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
        if (err == EI_IMPULSE_OK) {
            float human = 0.0f;
            float nonhuman = 0.0f;
            for (uint16_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
                const char* lbl = ei_classifier_inferencing_categories[i];
                float v = result.classification[i].value;
                if (strcmp(lbl, "human") == 0) human = v;
                else if (strcmp(lbl, "nonhuman") == 0) nonhuman = v;
            }

            g_human_score = human;
            g_nonhuman_score = nonhuman;
            g_is_human = (human >= HUMAN_THRESHOLD && human > nonhuman);
            g_last_dsp_ms = result.timing.dsp;
            g_last_classification_ms = result.timing.classification;

            Serial.printf("EI: human %.3f nonhuman %.3f | DSP %d ms | cls %d ms | %s\n",
                          human, nonhuman, result.timing.dsp,
                          result.timing.classification,
                          g_is_human ? "Human detected" : "Not detected");
        } else {
            Serial.printf("[ERR] run_classifier %d\n", (int)err);
        }

        g_ai_busy = false;
    }
}

static const char INDEX_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EagleEye — EI Hard Negative Capturer</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:Segoe UI,Arial,sans-serif;background:#0d0d0d;color:#eee;display:flex;flex-direction:column;align-items:center;padding:24px 16px;gap:20px}
  h1{font-size:1.25rem;letter-spacing:.04em;color:#7fdbff;text-align:center}
  #cam{position:relative;border-radius:10px;overflow:hidden;border:2px solid #2a2a2a;background:#111}
  #cam img{display:block;max-width:min(480px,100vw - 32px)}
  #hud{position:absolute;top:8px;left:8px;background:rgba(0,0,0,.72);padding:8px 10px;border-radius:6px;font-size:.85rem;line-height:1.55;font-family:Consolas,monospace}
  .human-color{color:#7fdbff}.non-color{color:#ff9f7a}.ok{color:#4dff91}.no{color:#aaa}
  .btns{display:flex;gap:12px;flex-wrap:wrap;justify-content:center;align-items:center}
  button{padding:14px 24px;font-size:1rem;font-weight:700;border:none;border-radius:8px;cursor:pointer;transition:filter .15s}
  button:hover{filter:brightness(1.15)}button:active{filter:brightness(.85)}
  .b-human{background:#1a6b35;color:#fff}.b-non{background:#7a2020;color:#fff}
  #msg{font-size:.9rem;color:#aaa;min-height:1.2em;text-align:center;max-width:720px}
  input{width:64px;padding:7px;text-align:center;border-radius:4px;border:none;font-weight:bold}
</style>
</head>
<body>
<h1>EagleEye — EI MobileNetV1 0.2 Hard Negative Capturer</h1>
<div id="cam">
  <img id="frame" alt="stream">
  <div id="hud">
    <span class="human-color">Human</span>: <span id="hs">—</span><br>
    <span class="non-color">NonHuman</span>: <span id="ns">—</span><br>
    AI: <strong id="pred" class="no">—</strong><br>
    DSP: <span id="dsp">—</span> ms | CLS: <span id="cls">—</span> ms
  </div>
</div>
<div class="btns">
  <div style="display:flex;align-items:center;gap:8px;background:#222;padding:10px;border-radius:8px;">
    <span>Burst Qty:</span>
    <input type="number" id="qty" value="5" min="1" max="100">
  </div>
  <button class="b-human" onclick="capBurst('human')">Capture Human</button>
  <button class="b-non" onclick="capBurst('nonhuman')">Capture NonHuman</button>
</div>
<div id="msg">Connecting...</div>
<script>
const frameEl = document.getElementById('frame');
const hsEl = document.getElementById('hs');
const nsEl = document.getElementById('ns');
const predEl = document.getElementById('pred');
const dspEl = document.getElementById('dsp');
const clsEl = document.getElementById('cls');
const msgEl = document.getElementById('msg');
const qtyEl = document.getElementById('qty');

const ws = new WebSocket('ws://' + location.hostname + ':81/');
ws.binaryType = 'blob';
ws.onopen = () => msgEl.textContent = 'Stream connected. Python receiver must be running on your PC.';
ws.onclose = () => msgEl.textContent = 'Stream disconnected. Refresh page.';
ws.onmessage = e => {
  const url = URL.createObjectURL(e.data);
  frameEl.onload = () => URL.revokeObjectURL(url);
  frameEl.src = url;
};

const poll = async () => {
  try {
    const r = await fetch('/ai');
    const d = await r.json();
    hsEl.textContent = Number(d.human_score).toFixed(3);
    nsEl.textContent = Number(d.nonhuman_score).toFixed(3);
    dspEl.textContent = d.dsp_ms;
    clsEl.textContent = d.classification_ms;
    predEl.textContent = d.human ? 'HUMAN' : 'no human';
    predEl.className = d.human ? 'ok' : 'no';
  } catch(_) {}
};
setInterval(poll, 500);

const capBurst = async label => {
  const qty = parseInt(qtyEl.value) || 1;
  msgEl.textContent = `Starting ${label} burst of ${qty}...`;
  let successCount = 0;
  for (let i = 1; i <= qty; i++) {
    msgEl.textContent = `Saving ${label} image ${i}/${qty}...`;
    try {
      const r = await fetch('/capture?label=' + label);
      if (!r.ok) throw new Error(await r.text());
      successCount++;
    } catch(e) {
      console.log(e);
    }
    await new Promise(res => setTimeout(res, 700));
  }
  msgEl.textContent = `Burst finished: saved ${successCount}/${qty} ${label} images.`;
};
</script>
</body>
</html>
)rawliteral";

static esp_err_t h_index(httpd_req_t* req) {
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, INDEX_HTML, sizeof(INDEX_HTML) - 1);
}

static esp_err_t h_ai(httpd_req_t* req) {
    char buf[180];
    snprintf(buf, sizeof(buf),
             "{\"human_score\":%.3f,\"nonhuman_score\":%.3f,\"human\":%s,\"dsp_ms\":%d,\"classification_ms\":%d}",
             (double)g_human_score,
             (double)g_nonhuman_score,
             g_is_human ? "true" : "false",
             (int)g_last_dsp_ms,
             (int)g_last_classification_ms);
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    return httpd_resp_send(req, buf, strlen(buf));
}

static esp_err_t h_capture(httpd_req_t* req) {
    char qs[64] = {0};
    char label[32] = "nonhuman";
    if (httpd_req_get_url_query_str(req, qs, sizeof(qs)) == ESP_OK) {
        httpd_query_key_value(qs, "label", label, sizeof(label));
    }

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }

    uint8_t* jpg = nullptr;
    size_t jlen = 0;
    bool ok = frame2jpg(fb, 85, &jpg, &jlen);
    esp_camera_fb_return(fb);
    if (!ok || !jpg) {
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }

    HTTPClient http;
    String url = String(PC_RECEIVER) + "?label=" + String(label);
    http.begin(url);
    http.addHeader("Content-Type", "image/jpeg");
    int code = http.POST(jpg, jlen);
    free(jpg);
    http.end();

    if (code > 0 && code < 400) {
        httpd_resp_send(req, "Saved", HTTPD_RESP_USE_STRLEN);
    } else {
        Serial.printf("[capture] upload failed code=%d url=%s\n", code, url.c_str());
        httpd_resp_set_status(req, "502 Bad Gateway");
        httpd_resp_send(req, "Upload failed - is Python receiver running and PC_RECEIVER correct?", HTTPD_RESP_USE_STRLEN);
    }
    return ESP_OK;
}

void startCtrlServer() {
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.server_port = 80;
    cfg.ctrl_port = 32768;
    if (httpd_start(&ctrl_httpd, &cfg) == ESP_OK) {
        httpd_uri_t u1 = {"/", HTTP_GET, h_index, nullptr};
        httpd_uri_t u2 = {"/ai", HTTP_GET, h_ai, nullptr};
        httpd_uri_t u3 = {"/capture", HTTP_GET, h_capture, nullptr};
        httpd_register_uri_handler(ctrl_httpd, &u1);
        httpd_register_uri_handler(ctrl_httpd, &u2);
        httpd_register_uri_handler(ctrl_httpd, &u3);
        Serial.println("[OK] HTTP server on port 80");
    }
}

static bool camera_init() {
    camera_config_t cam = {};
    cam.ledc_channel = LEDC_CHANNEL_0;
    cam.ledc_timer = LEDC_TIMER_0;
    cam.pin_d0 = Y2_GPIO_NUM;  cam.pin_d1 = Y3_GPIO_NUM;
    cam.pin_d2 = Y4_GPIO_NUM;  cam.pin_d3 = Y5_GPIO_NUM;
    cam.pin_d4 = Y6_GPIO_NUM;  cam.pin_d5 = Y7_GPIO_NUM;
    cam.pin_d6 = Y8_GPIO_NUM;  cam.pin_d7 = Y9_GPIO_NUM;
    cam.pin_xclk = XCLK_GPIO_NUM;
    cam.pin_pclk = PCLK_GPIO_NUM;
    cam.pin_vsync = VSYNC_GPIO_NUM;
    cam.pin_href = HREF_GPIO_NUM;
    cam.pin_sscb_sda = SIOD_GPIO_NUM;
    cam.pin_sscb_scl = SIOC_GPIO_NUM;
    cam.pin_pwdn = PWDN_GPIO_NUM;
    cam.pin_reset = RESET_GPIO_NUM;
    cam.xclk_freq_hz = 20000000;
    cam.pixel_format = PIXFORMAT_RGB565;
    cam.frame_size = FRAMESIZE_QVGA;
    cam.jpeg_quality = 12;
    cam.fb_count = 2;
    cam.fb_location = CAMERA_FB_IN_PSRAM;
    cam.grab_mode = CAMERA_GRAB_LATEST;
    if (esp_camera_init(&cam) != ESP_OK) return false;

    sensor_t* s = esp_camera_sensor_get();
    if (s) {
        s->set_whitebal(s, 1);
        s->set_awb_gain(s, 1);
        s->set_wb_mode(s, 0);
        s->set_exposure_ctrl(s, 1);
        s->set_aec2(s, 1);
        s->set_ae_level(s, 2);
        s->set_aec_value(s, 600);
        s->set_gain_ctrl(s, 1);
        s->set_agc_gain(s, 0);
        s->set_gainceiling(s, (gainceiling_t)4);
        s->set_bpc(s, 0);
        s->set_wpc(s, 1);
        s->set_raw_gma(s, 1);
        s->set_lenc(s, 1);
        s->set_dcw(s, 1);
        s->set_saturation(s, 0);
        s->set_brightness(s, 0);
        s->set_contrast(s, 0);
    }

    for (int i = 0; i < 8; i++) {
        camera_fb_t* warm = esp_camera_fb_get();
        if (warm) esp_camera_fb_return(warm);
        delay(60);
    }
    return true;
}

void setup() {
    Serial.begin(115200);
    WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
    setCpuFrequencyMhz(240);

    Serial.println("\n\n=== EagleEye Sketchboard EI Hard Negative Capturer ===");
    Serial.printf("[model] project %d deploy v%d | input %dx%d RGB\n",
                  (int)EI_CLASSIFIER_PROJECT_ID,
                  (int)EI_CLASSIFIER_PROJECT_DEPLOY_VERSION,
                  EI_CLASSIFIER_INPUT_WIDTH,
                  EI_CLASSIFIER_INPUT_HEIGHT);
#if EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN
    Serial.println("[build] ESP-NN: ENABLED");
#else
    Serial.println("[build] ESP-NN: DISABLED");
#endif

    pinMode(4, OUTPUT);
    digitalWrite(4, LOW);

    WiFi.mode(WIFI_STA);
    WiFi.disconnect(true);
    delay(100);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("[..] WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.printf("\n[OK] WiFi connected - open http://%s\n", WiFi.localIP().toString().c_str());
    Serial.printf("[OK] Python receiver: %s\n", PC_RECEIVER);

    if (!camera_init()) {
        Serial.println("[ERR] Camera init failed");
        while (1) delay(1000);
    }
    Serial.println("[OK] Camera: RGB565 QVGA");

    startCtrlServer();
    wsServer.begin();
    Serial.println("[OK] WebSocket stream on port 81");

    xTaskCreatePinnedToCore(aiTask, "EI_AI", 16384, nullptr, 1, &aiTaskHandle, 0);
    Serial.println("[OK] EI AI task on Core 0");
    Serial.println("=== Ready ===\n");
}

void loop() {
    wsServer.loop();

    static uint32_t last = 0;
    if (millis() - last < 100) {
        delay(2);
        return;
    }
    last = millis();

    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) return;

    if (!g_ai_busy) {
        g_ai_busy = true;
        rgb565_to_rgb888_resize_crop(fb->buf, fb->width, fb->height,
                                     rgb_buffer,
                                     EI_CLASSIFIER_INPUT_WIDTH,
                                     EI_CLASSIFIER_INPUT_HEIGHT);
        xTaskNotifyGive(aiTaskHandle);
    }

    if (wsServer.connectedClients() > 0) {
        uint8_t* jpg = nullptr;
        size_t jlen = 0;
        if (frame2jpg(fb, 35, &jpg, &jlen)) {
            wsServer.broadcastBIN(jpg, jlen);
            free(jpg);
        }
    }

    esp_camera_fb_return(fb);
}
