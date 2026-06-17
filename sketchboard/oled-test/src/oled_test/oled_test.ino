/*
 * EagleEye — OLED test sketch
 * SSD1306 0.96"  I2C
 *   SCL (CLK)  -> GPIO 13
 *   SDA (DATA) -> GPIO 15
 *   VCC        -> 3.3 V
 *   GND        -> GND
 */

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define OLED_SDA     15
#define OLED_SCL     13
#define SCREEN_W    128
#define SCREEN_H     64
#define OLED_ADDR  0x3C   // try 0x3D if this doesn't work

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== OLED test ===");

  Wire.begin(OLED_SDA, OLED_SCL);

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("[ERR] SSD1306 not found — check wiring / address");
    while (1) delay(1000);
  }

  // --- screen 1: banner ---
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(2);
  display.setCursor(10, 4);
  display.println("EagleEye");

  display.setTextSize(1);
  display.setCursor(20, 26);
  display.println("OLED  OK");

  display.setCursor(8, 40);
  display.println("SCL=13  SDA=15");

  display.setCursor(28, 52);
  display.println("SSD1306 0.96\"");

  display.display();
  Serial.println("[OK] OLED initialised");
}

void loop() {
  // blink bottom-right pixel so you can tell the loop is running
  static bool on = false;
  display.drawPixel(127, 63, on ? SSD1306_WHITE : SSD1306_BLACK);
  display.display();
  on = !on;
  delay(500);
}
