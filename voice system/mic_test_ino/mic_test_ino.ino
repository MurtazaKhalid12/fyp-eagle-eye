/*
 * ============================================================
 *  EagleEye Voice — I2S MIC TEST (hear the mic on your laptop)
 *  Arduino IDE sketch version (.ino)
 * ============================================================
 *  Flash this to the AUDIO ESP32 (+ I2S mic). It connects to Wi-Fi and
 *  serves a tiny web page. Open the printed URL in your LAPTOP browser,
 *  press "Start Listening", and SPEAK into the mic — you should hear
 *  yourself from the laptop speaker (~1-2 s latency is normal).
 *
 *  If you hear your voice => the mic + wiring + I2S are working.
 *  The Serial Monitor also prints a live [mic] level so you can verify
 *  even without the browser.
 *
 *  MIC WIRING (same as the voice project):
 *    BCK/SCK -> GPIO13 | WS/LRCL -> GPIO14 | SD/DOUT -> GPIO15
 *    VDD -> 3V3 | GND -> GND | L/R -> GND (selects LEFT channel)
 *
 *  ARDUINO IDE SETUP:
 *    - Board: "AI Thinker ESP32-CAM" (or your audio ESP32 board)
 *    - Tools > PSRAM: Enabled  (equivalent to -DBOARD_HAS_PSRAM)
 *    - Upload Speed: 115200 (more reliable on CH340)
 *    - Bare ESP32-CAM upload: jumper GPIO0 -> GND, press RESET while it
 *      says "Connecting...", then remove the jumper and RESET to run.
 * ============================================================
 */
#include <WiFi.h>
#include <WebServer.h>
#include "driver/i2s.h"

// ====== EDIT THESE to your network ======
const char* WIFI_SSID = "DESKTOP-Q7922V6 8377";
const char* WIFI_PASS = "12345678";

// ====== I2S mic config (matches the voice project) ======
#define I2S_PORT_NUM  I2S_NUM_1
#define I2S_SCK_PIN   15      // BCK
#define I2S_WS_PIN    13      // WS / LRCL
#define I2S_SD_PIN    14      // DOUT (mic data into ESP)
#define SAMPLE_RATE   16000
#define MIC_GAIN      8       // software volume boost for LISTENING (lower if distorted, raise if too quiet)

WebServer server(80);

const char PAGE[] PROGMEM = R"HTML(
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ESP32 Mic Test</title>
<style>body{font-family:sans-serif;background:#0f172a;color:#e2e8f0;text-align:center;padding:24px}
button{font-size:18px;padding:14px 22px;border:0;border-radius:12px;background:#22c55e;color:#03210f;font-weight:700}
small{color:#94a3b8}audio{margin-top:16px}</style></head>
<body><h2>EagleEye - Mic Test</h2>
<p>Press the button, then SPEAK into the mic.<br>You should hear yourself from this device's speaker.</p>
<button onclick="var a=document.getElementById('a');a.src='/audio';a.play()">Start Listening</button>
<br><audio id="a" controls></audio>
<p><small>~1-2s latency is normal. If you hear your voice, the mic works.</small></p>
</body></html>
)HTML";

static void i2sInit() {
  i2s_config_t cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = (i2s_bits_per_sample_t)16,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_I2S,
    .intr_alloc_flags = 0,
    .dma_buf_count = 8,
    .dma_buf_len = 512,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = -1,
  };
  i2s_pin_config_t pins = {
    .bck_io_num = I2S_SCK_PIN,
    .ws_io_num  = I2S_WS_PIN,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num  = I2S_SD_PIN,
  };
  i2s_driver_install(I2S_PORT_NUM, &cfg, 0, NULL);
  i2s_set_pin(I2S_PORT_NUM, &pins);
  i2s_zero_dma_buffer(I2S_PORT_NUM);
}

// Stream a "never-ending" WAV header so the browser plays continuously.
static void writeWavHeader(WiFiClient &c) {
  const uint32_t dataLen   = 0xFFFFFFFFu - 64;
  const uint32_t srate     = SAMPLE_RATE;
  const uint16_t bits = 16, ch = 1;
  const uint32_t byteRate  = srate * ch * bits / 8;
  const uint16_t blockAlign= ch * bits / 8;
  const uint32_t chunk = dataLen + 36, sub1 = 16;
  const uint16_t fmt = 1;
  uint8_t h[44];
  memcpy(h, "RIFF", 4);     memcpy(h + 4, &chunk, 4);  memcpy(h + 8, "WAVE", 4);
  memcpy(h + 12, "fmt ", 4); memcpy(h + 16, &sub1, 4);  memcpy(h + 20, &fmt, 2);
  memcpy(h + 22, &ch, 2);    memcpy(h + 24, &srate, 4); memcpy(h + 28, &byteRate, 4);
  memcpy(h + 32, &blockAlign, 2); memcpy(h + 34, &bits, 2);
  memcpy(h + 36, "data", 4); memcpy(h + 40, &dataLen, 4);
  c.write(h, 44);
}

static void handleRoot() { server.send_P(200, "text/html", PAGE); }

static void handleAudio() {
  WiFiClient c = server.client();
  if (!c) return;
  c.print("HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n");
  writeWavHeader(c);
  int16_t buf[256];
  size_t br;
  while (c.connected()) {
    if (i2s_read(I2S_PORT_NUM, buf, sizeof(buf), &br, pdMS_TO_TICKS(100)) == ESP_OK && br) {
      int n = br / 2;
      for (int i = 0; i < n; i++) {
        int32_t v = (int32_t)buf[i] * MIC_GAIN;
        if (v > 32767) v = 32767; else if (v < -32768) v = -32768;
        buf[i] = (int16_t)v;
      }
      c.write((uint8_t *)buf, br);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n[MIC TEST] booting");
  i2sInit();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[WiFi] connecting to %s", WIFI_SSID);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 30000) { delay(400); Serial.print("."); }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(">>> OPEN THIS IN YOUR LAPTOP BROWSER:  http://");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("[WiFi] FAILED - check WIFI_SSID / WIFI_PASS");
  }

  server.on("/", handleRoot);
  server.on("/audio", handleAudio);
  server.begin();
}

void loop() {
  server.handleClient();

  // Live mic level on Serial (works even without the browser).
  static uint32_t last = 0;
  if (millis() - last > 500) {
    last = millis();
    int16_t s[256];
    size_t br;
    if (i2s_read(I2S_PORT_NUM, s, sizeof(s), &br, 0) == ESP_OK && br) {
      long sum = 0; int n = br / 2;
      for (int i = 0; i < n; i++) sum += abs(s[i]);
      Serial.printf("[mic] level=%ld  (speak -> should rise)\n", n ? sum / n : 0);
    }
  }
}
