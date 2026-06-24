#include "eagleeye_oled.h"

// Camera SCCB owns I2C1 — Wire (I2C0) is free for OLED
Adafruit_SSD1306 oled_display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

bool      oled_ok            = false;
OledState oled_state         = OLED_STATE_STATUS;
String    oled_model_name    = "None";
String    oled_wifi_status   = "Offline";
String    oled_mqtt_status   = "Offline";
String    oled_system_status = "Armed";
String    oled_last_event    = "Booting...";
int       oled_rssi          = -100;

// Animation state
static const char SPIN_CHARS[] = "|/-\\";
static uint8_t       g_spin       = 0;
static bool          g_invert     = false;
static float         g_score      = 0.0f;
static unsigned long g_last_anim  = 0;
static bool          g_streaming  = false;   // true while relaying video: freeze the OLED

// ── Helpers ──────────────────────────────────────────────────────────────────

// Draw n filled squares + (4-n) outline squares — WiFi/MQTT signal indicator
static void draw_dots(int x, int y, int filled) {
  for (int i = 0; i < 4; i++) {
    int bx = x + i * 7;
    if (i < filled)
      oled_display.fillRect(bx, y, 5, 5, SSD1306_WHITE);
    else
      oled_display.drawRect(bx, y, 5, 5, SSD1306_WHITE);
  }
}

static int rssi_to_bars(int rssi) {
  if (rssi >= -55) return 4;
  if (rssi >= -65) return 3;
  if (rssi >= -75) return 2;
  if (rssi >= -85) return 1;
  return 0;
}

static bool is_connected(const String& s) {
  return s == "Connected" || s == "OK";
}

// ── Main status screen ────────────────────────────────────────────────────────
//
//  ┌────────────────────────┐  y=0
//  │▓▓▓ EAGLEEYE CLOUD ▓▓▓▓│  inverted header bar
//  ├────────────────────────┤
//  │W:■■■■  M:■■■■  [ARMED]│  dots + state badge
//  │                        │
//  │Model: v7.16            │
//  ├────────────────────────┤  separator
//  │> Last event here       │
//  │                      / │  spinner bottom-right
//  └────────────────────────┘  y=63

void oled_update() {
  if (!oled_ok || oled_state != OLED_STATE_STATUS || g_streaming) return;

  oled_display.clearDisplay();

  // ── Inverted header bar ──────────────────────────────────
  oled_display.fillRect(0, 0, 128, 11, SSD1306_WHITE);
  oled_display.setTextSize(1);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setCursor(4, 2);
  oled_display.print(">> EAGLEEYE CLOUD <<");
  oled_display.setTextColor(SSD1306_WHITE);

  // ── WiFi dots ────────────────────────────────────────────
  bool wOk = is_connected(oled_wifi_status);
  bool mOk = is_connected(oled_mqtt_status);
  int  bars = wOk ? rssi_to_bars(oled_rssi) : 0;

  oled_display.setCursor(0, 14);
  oled_display.print("W:");
  draw_dots(13, 14, bars);

  // ── MQTT dots ────────────────────────────────────────────
  oled_display.setCursor(44, 14);
  oled_display.print("M:");
  draw_dots(57, 14, mOk ? 4 : 0);

  // ── State badge (right side) ─────────────────────────────
  bool armed = (oled_system_status == "Armed");
  if (armed) {
    oled_display.fillRoundRect(92, 12, 36, 11, 2, SSD1306_WHITE);
    oled_display.setTextColor(SSD1306_BLACK);
    oled_display.setCursor(95, 14);
    oled_display.print("ARMED");
    oled_display.setTextColor(SSD1306_WHITE);
  } else {
    oled_display.drawRoundRect(84, 12, 44, 11, 2, SSD1306_WHITE);
    oled_display.setCursor(87, 14);
    oled_display.print("DISARMD");
  }

  // ── Model name ───────────────────────────────────────────
  oled_display.setCursor(0, 26);
  oled_display.print("Model: ");
  String mdl = oled_model_name;
  if (mdl.length() > 10) mdl = mdl.substring(0, 10);
  oled_display.print(mdl);

  // ── Separator ────────────────────────────────────────────
  oled_display.drawFastHLine(0, 36, 128, SSD1306_WHITE);

  // ── Event log line ───────────────────────────────────────
  oled_display.setCursor(0, 40);
  oled_display.print("> ");
  oled_display.print(oled_last_event);

  // ── Spinner (bottom-right) ───────────────────────────────
  oled_display.setCursor(122, 56);
  oled_display.print(SPIN_CHARS[g_spin]);

  // ── "AI" label (bottom-left) ─────────────────────────────
  oled_display.setCursor(0, 56);
  oled_display.print("AI");

  oled_display.display();
}

// ── Alert screen (human detected) ────────────────────────────────────────────
//
//  ┌────────────────────────┐
//  │▓▓▓▓▓ !! ALERT !! ▓▓▓▓▓│  inverted banner
//  │                        │
//  │      INTRUDER!         │  size-2 text
//  │      Human: 87%        │  confidence
//  │                        │
//  │▓▓▓▓ Sending Alert ▓▓▓▓│  inverted footer
//  └────────────────────────┘
//  Flashes (invertDisplay) every 350 ms via oled_tick()

static void draw_alert_screen() {
  oled_display.clearDisplay();

  // Top inverted banner
  oled_display.fillRect(0, 0, 128, 13, SSD1306_WHITE);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setTextSize(1);
  oled_display.setCursor(22, 3);
  oled_display.print("!! ALERT !!");
  oled_display.setTextColor(SSD1306_WHITE);

  // Big INTRUDER text
  oled_display.setTextSize(2);
  oled_display.setCursor(8, 17);
  oled_display.print("INTRUDER!");

  // Confidence score
  oled_display.setTextSize(1);
  oled_display.setCursor(22, 37);
  char buf[20];
  snprintf(buf, sizeof(buf), "Human: %.0f%%", g_score * 100.0f);
  oled_display.print(buf);

  // Bottom inverted banner
  oled_display.fillRect(0, 50, 128, 14, SSD1306_WHITE);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setCursor(16, 53);
  oled_display.print("Sending Alert...");
  oled_display.setTextColor(SSD1306_WHITE);

  oled_display.display();
}

// ── Public API ────────────────────────────────────────────────────────────────

void oled_begin(const char* model_name) {
  oled_model_name = String(model_name);

  Wire.begin(OLED_SDA_PIN, OLED_CLK_PIN);
  Wire.setClock(100000);

  if (!oled_display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    if (!oled_display.begin(SSD1306_SWITCHCAPVCC, 0x3D)) {
      Serial.println("[OLED] not found (0x3C/0x3D) — disabled");
      return;
    }
    Serial.println("[OLED] found at 0x3D");
  }
  oled_ok = true;

  // ── Boot splash ──────────────────────────────────────────
  oled_display.clearDisplay();
  oled_display.setTextColor(SSD1306_WHITE);
  oled_display.setTextSize(2);
  oled_display.setCursor(16, 14);
  oled_display.print("EagleEye");
  oled_display.setCursor(34, 36);
  oled_display.print("Cloud");
  oled_display.display();
  Serial.println("[OK] OLED: Wire  SDA=GPIO15  SCL=GPIO13");
}

// Call every loop() — advances spinner and flashes alert
void oled_tick() {
  if (!oled_ok) return;
  if (g_streaming) return;             // frozen "LIVE" screen — no I2C redraws (keeps video + servo fast)
  unsigned long now = millis();

  if (oled_state == OLED_STATE_ALERT) {
    if (now - g_last_anim > 350) {
      g_last_anim = now;
      g_invert    = !g_invert;
      oled_display.invertDisplay(g_invert);
    }
  } else if (oled_state == OLED_STATE_STATUS) {
    if (now - g_last_anim > 200) {
      g_last_anim = now;
      g_spin = (g_spin + 1) % 4;
      oled_update();
    }
  }
  // OLED_STATE_FULLSCREEN: no auto-refresh — each inference frame drives the display
}

void oled_set_wifi(const char* status) {
  oled_wifi_status = String(status);
  oled_update();
}

void oled_set_mqtt(const char* status) {
  oled_mqtt_status = String(status);
  oled_update();
}

void oled_set_system(const char* status) {
  oled_system_status = String(status);
  oled_update();
}

void oled_set_rssi(int rssi) {
  oled_rssi = rssi;
  // picked up on next oled_tick() → oled_update()
}

void oled_log(const char* event) {
  oled_last_event = String(event);
  if (oled_last_event.length() > 17) oled_last_event = oled_last_event.substring(0, 17);
  if (oled_state == OLED_STATE_STATUS) oled_update();
}

void oled_show_alert(float score) {
  if (!oled_ok) return;
  g_score     = score;
  g_invert    = false;
  oled_state  = OLED_STATE_ALERT;
  oled_display.invertDisplay(false);
  draw_alert_screen();
}

void oled_clear_alert() {
  if (!oled_ok) return;
  oled_display.invertDisplay(false);
  g_invert   = false;
  oled_state = OLED_STATE_STATUS;
  oled_update();
}

// Streaming mode: draw a static "LIVE" screen ONCE, then suppress every periodic
// redraw. A full OLED frame is ~100 ms over I2C — doing it every 200 ms would
// stall Core 1's relay loop and servo-command handling, making both feel laggy.
void oled_set_streaming(bool on) {
  if (!oled_ok) return;
  g_streaming = on;
  oled_display.invertDisplay(false);
  g_invert   = false;
  oled_state = OLED_STATE_STATUS;
  if (!on) { oled_update(); return; }          // streaming ended -> live status screen

  oled_display.clearDisplay();
  // header bar
  oled_display.fillRect(0, 0, 128, 11, SSD1306_WHITE);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setTextSize(1);
  oled_display.setCursor(4, 2);
  oled_display.print(">> EAGLEEYE CLOUD <<");
  oled_display.setTextColor(SSD1306_WHITE);
  // REC dot + big LIVE
  oled_display.fillCircle(22, 31, 4, SSD1306_WHITE);
  oled_display.setTextSize(2);
  oled_display.setCursor(36, 24);
  oled_display.print("LIVE");
  // footer
  oled_display.setTextSize(1);
  oled_display.setCursor(14, 52);
  oled_display.print("Streaming video");
  oled_display.display();
}

// ── Full-screen detection states ──────────────────────────────────────────────

void oled_fullscreen_human(float score) {
  if (!oled_ok) return;
  g_score    = score;
  oled_state = OLED_STATE_FULLSCREEN;
  oled_display.invertDisplay(false);
  oled_display.clearDisplay();

  oled_display.fillRect(0, 0, 128, 13, SSD1306_WHITE);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setTextSize(1);
  oled_display.setCursor(28, 3);
  oled_display.print("!! HUMAN !!");
  oled_display.setTextColor(SSD1306_WHITE);

  oled_display.setTextSize(2);
  oled_display.setCursor(10, 17);
  oled_display.print("DETECTED!");

  oled_display.setTextSize(1);
  oled_display.setCursor(34, 38);
  char buf[20];
  snprintf(buf, sizeof(buf), "Score: %.0f%%", score * 100.0f);
  oled_display.print(buf);

  oled_display.fillRect(0, 50, 128, 14, SSD1306_WHITE);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setCursor(22, 53);
  oled_display.print("Live Detection");
  oled_display.setTextColor(SSD1306_WHITE);

  oled_display.display();
}

void oled_fullscreen_no_human() {
  if (!oled_ok) return;
  oled_state = OLED_STATE_FULLSCREEN;
  oled_display.invertDisplay(false);
  oled_display.clearDisplay();

  oled_display.setTextColor(SSD1306_WHITE);
  oled_display.setTextSize(2);
  oled_display.setCursor(16, 16);
  oled_display.print("No Human");

  oled_display.setTextSize(1);
  oled_display.setCursor(20, 50);
  oled_display.print("Monitoring...");

  oled_display.display();
}

void oled_fullscreen_scene_cleared() {
  if (!oled_ok) return;
  oled_state = OLED_STATE_FULLSCREEN;
  oled_display.invertDisplay(false);
  oled_display.clearDisplay();

  oled_display.fillRect(0, 0, 128, 13, SSD1306_WHITE);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setTextSize(1);
  oled_display.setCursor(19, 3);
  oled_display.print("SCENE CLEARED");
  oled_display.setTextColor(SSD1306_WHITE);

  oled_display.setTextSize(2);
  oled_display.setCursor(16, 19);
  oled_display.print("Re-Armed");

  oled_display.fillRect(0, 50, 128, 14, SSD1306_WHITE);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setCursor(19, 53);
  oled_display.print("Ready to Detect");
  oled_display.setTextColor(SSD1306_WHITE);

  oled_display.display();
}

void oled_fullscreen_uploading() {
  if (!oled_ok) return;
  oled_state = OLED_STATE_FULLSCREEN;
  oled_display.invertDisplay(false);
  oled_display.clearDisplay();

  oled_display.fillRect(0, 0, 128, 13, SSD1306_WHITE);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setTextSize(1);
  oled_display.setCursor(31, 3);
  oled_display.print("UPLOADING");
  oled_display.setTextColor(SSD1306_WHITE);

  oled_display.setTextSize(2);
  oled_display.setCursor(4, 24);
  oled_display.print("Sending...");

  oled_display.display();
}

void oled_fullscreen_alert_sent(float score) {
  if (!oled_ok) return;
  oled_state = OLED_STATE_FULLSCREEN;
  oled_display.invertDisplay(false);
  oled_display.clearDisplay();

  oled_display.fillRect(0, 0, 128, 13, SSD1306_WHITE);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setTextSize(1);
  oled_display.setCursor(25, 3);
  oled_display.print("ALERT SENT!");
  oled_display.setTextColor(SSD1306_WHITE);

  oled_display.setTextSize(2);
  oled_display.setCursor(28, 17);
  oled_display.print("Sent!");

  oled_display.setTextSize(1);
  oled_display.setCursor(34, 38);
  char buf[20];
  snprintf(buf, sizeof(buf), "Score: %.0f%%", score * 100.0f);
  oled_display.print(buf);

  oled_display.fillRect(0, 50, 128, 14, SSD1306_WHITE);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setCursor(10, 53);
  oled_display.print("Cloud notified!");
  oled_display.setTextColor(SSD1306_WHITE);

  oled_display.display();
}

void oled_show_sleeping() {
  if (!oled_ok) return;
  oled_display.invertDisplay(false);
  g_invert   = false;
  oled_state = OLED_STATE_STATUS;

  oled_display.clearDisplay();
  oled_display.setTextColor(SSD1306_WHITE);

  // Inverted header
  oled_display.fillRect(0, 0, 128, 11, SSD1306_WHITE);
  oled_display.setTextColor(SSD1306_BLACK);
  oled_display.setTextSize(1);
  oled_display.setCursor(4, 2);
  oled_display.print(">> EAGLEEYE CLOUD <<");
  oled_display.setTextColor(SSD1306_WHITE);

  // Big Zzz
  oled_display.setTextSize(2);
  oled_display.setCursor(22, 18);
  oled_display.print("Zzz...");

  // Footer
  oled_display.setTextSize(1);
  oled_display.drawFastHLine(0, 48, 128, SSD1306_WHITE);
  oled_display.setCursor(8, 52);
  oled_display.print("Auto-wake on motion");

  oled_display.display();
}
