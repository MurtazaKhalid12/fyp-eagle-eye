#ifndef EAGLEEYE_OLED_H
#define EAGLEEYE_OLED_H

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT  64
#define OLED_RESET     -1
// I2C0 (Wire) — camera SCCB owns I2C1 internally
#define OLED_SDA_PIN   15
#define OLED_CLK_PIN   13

// Display states
typedef enum {
  OLED_STATE_STATUS,   // normal operation
  OLED_STATE_ALERT,    // human detected — flashing
} OledState;

extern Adafruit_SSD1306 oled_display;
extern bool      oled_ok;
extern OledState oled_state;

extern String oled_model_name;
extern String oled_wifi_status;
extern String oled_mqtt_status;
extern String oled_system_status;
extern String oled_last_event;
extern int    oled_rssi;

void oled_begin(const char* model_name);
void oled_update();
void oled_tick();                       // call every loop() — drives spinner + alert flash
void oled_set_wifi(const char* status);
void oled_set_mqtt(const char* status);
void oled_set_system(const char* status);
void oled_set_rssi(int rssi);           // call with WiFi.RSSI() to show signal bars
void oled_log(const char* event);
void oled_show_alert(float score);      // dramatic full-screen intruder display
void oled_clear_alert();                // return to status screen
void oled_show_sleeping();

#endif // EAGLEEYE_OLED_H
