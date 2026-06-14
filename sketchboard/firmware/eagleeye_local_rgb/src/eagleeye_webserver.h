/*
 * EagleEye Local — live-view web server.
 *
 *  Port 80 : "/"        the web page (live <img> + detection banner)
 *            "/status"  JSON {human, score, nonhuman, ms} — polled by the page
 *  Port 81 : "/stream"  multipart MJPEG live video
 *
 *  Inference runs INSIDE the stream handler — one frame is grabbed, classified,
 *  and JPEG-encoded per stream tick, so there is a single camera owner (no race
 *  with loop()). Detection therefore runs whenever the live page is open.
 *
 *  Two separate httpd instances (80 + 81) run as separate FreeRTOS tasks so
 *  /status keeps answering while /stream is busy streaming.
 *
 *  Included once, by main.cpp. The detection globals + infer_on_frame() are
 *  defined in main.cpp; declared extern here.
 */
#ifndef EAGLEEYE_WEBSERVER_H
#define EAGLEEYE_WEBSERVER_H

#include <Arduino.h>
#include <WiFi.h>
#include "esp_http_server.h"
#include "esp_camera.h"
#include "img_converters.h"
#include "wifi_config.h"

// ── shared with main.cpp ────────────────────────────────────────────────────
extern volatile bool     g_isHuman;
extern volatile float    g_humanScore;
extern volatile float    g_nonhumanScore;
extern volatile uint32_t g_inferMs;
extern void infer_on_frame(camera_fb_t* fb);   // runs the model, updates the globals

static httpd_handle_t s_web    = nullptr;   // :80 page + status
static httpd_handle_t s_stream = nullptr;   // :81 mjpeg
static String         s_ip;

// ── "/" : the web page ──────────────────────────────────────────────────────
static esp_err_t index_handler(httpd_req_t* req) {
    String html =
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>EagleEye Local</title><style>"
        "body{font-family:sans-serif;margin:0;background:#111;color:#eee;text-align:center}"
        "h1{font-size:1rem;color:#888;margin:8px}"
        "#s{font-size:1.5rem;font-weight:bold;padding:14px;transition:background .2s}"
        ".hu{background:#c0392b;color:#fff}.no{background:#2c3e50}"
        "img{max-width:100%;height:auto;display:block;margin:0 auto;background:#000}"
        "</style></head><body>"
        "<h1>EagleEye — local live view</h1>"
        "<div id='s' class='no'>connecting…</div>"
        "<img src='http://" + s_ip + ":81/stream' alt='live'>"
        "<script>"
        "setInterval(function(){fetch('/status').then(function(r){return r.json();})"
        ".then(function(j){var s=document.getElementById('s');"
        "if(j.human){s.textContent='\\u26A0 HUMAN DETECTED  ('+j.score.toFixed(2)+')';s.className='hu';}"
        "else{s.textContent='no human  ('+j.score.toFixed(2)+')';s.className='no';}})"
        ".catch(function(e){});},400);"
        "</script></body></html>";
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, html.c_str(), html.length());
}

// ── "/status" : JSON detection state ────────────────────────────────────────
static esp_err_t status_handler(httpd_req_t* req) {
    char buf[160];
    int n = snprintf(buf, sizeof(buf),
        "{\"human\":%s,\"score\":%.3f,\"nonhuman\":%.3f,\"ms\":%lu}",
        g_isHuman ? "true" : "false", g_humanScore, g_nonhumanScore,
        (unsigned long)g_inferMs);
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    return httpd_resp_send(req, buf, n);
}

// ── "/stream" : MJPEG + per-frame inference ─────────────────────────────────
#define EE_BOUNDARY "eagleeyeframe"
static const char* STREAM_CT       = "multipart/x-mixed-replace;boundary=" EE_BOUNDARY;
static const char* STREAM_BOUNDARY = "\r\n--" EE_BOUNDARY "\r\n";
static const char* STREAM_PARTHDR  = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static esp_err_t stream_handler(httpd_req_t* req) {
    esp_err_t res = httpd_resp_set_type(req, STREAM_CT);
    if (res != ESP_OK) return res;
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

    char hdr[64];
    while (true) {
        camera_fb_t* fb = esp_camera_fb_get();
        if (!fb) { res = ESP_FAIL; break; }

        infer_on_frame(fb);                    // classify this frame -> globals

        uint8_t* jpg = nullptr; size_t jlen = 0;
        bool ok = frame2jpg(fb, 80, &jpg, &jlen);
        esp_camera_fb_return(fb);
        if (!ok) { res = ESP_FAIL; break; }

        res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
        if (res == ESP_OK) {
            int hl = snprintf(hdr, sizeof(hdr), STREAM_PARTHDR, (unsigned)jlen);
            res = httpd_resp_send_chunk(req, hdr, hl);
        }
        if (res == ESP_OK)
            res = httpd_resp_send_chunk(req, (const char*)jpg, jlen);
        free(jpg);
        if (res != ESP_OK) break;              // client disconnected
        delay(5);
    }
    return res;
}

static void start_servers() {
    httpd_config_t c = HTTPD_DEFAULT_CONFIG();
    c.server_port = 80; c.ctrl_port = 32768;
    if (httpd_start(&s_web, &c) == ESP_OK) {
        httpd_uri_t idx = { .uri = "/",       .method = HTTP_GET, .handler = index_handler,  .user_ctx = NULL };
        httpd_uri_t st  = { .uri = "/status", .method = HTTP_GET, .handler = status_handler, .user_ctx = NULL };
        httpd_register_uri_handler(s_web, &idx);
        httpd_register_uri_handler(s_web, &st);
    }
    httpd_config_t s = HTTPD_DEFAULT_CONFIG();
    s.server_port = 81; s.ctrl_port = 32769; s.stack_size = 8192;
    if (httpd_start(&s_stream, &s) == ESP_OK) {
        httpd_uri_t str = { .uri = "/stream", .method = HTTP_GET, .handler = stream_handler, .user_ctx = NULL };
        httpd_register_uri_handler(s_stream, &str);
    }
}

static void web_begin() {
    bool useSta = (strlen(WIFI_SSID) > 0);
    if (useSta) {
        WiFi.mode(WIFI_STA);
        WiFi.begin(WIFI_SSID, WIFI_PASS);
        Serial.printf("[wifi] joining \"%s\" ", WIFI_SSID);
        uint32_t t0 = millis();
        while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) { delay(400); Serial.print("."); }
        Serial.println();
    }
    if (useSta && WiFi.status() == WL_CONNECTED) {
        s_ip = WiFi.localIP().toString();
        Serial.printf("[wifi] STA connected -> http://%s/\n", s_ip.c_str());
    } else {
        WiFi.mode(WIFI_AP);
        WiFi.softAP(AP_SSID, AP_PASS);
        s_ip = WiFi.softAPIP().toString();
        Serial.printf("[wifi] hotspot \"%s\" (pass \"%s\") -> http://%s/\n",
                      AP_SSID, AP_PASS, s_ip.c_str());
    }
    start_servers();
    Serial.printf("[web] LIVE VIEW: http://%s/   (open this in a browser)\n", s_ip.c_str());
}

#endif  // EAGLEEYE_WEBSERVER_H
