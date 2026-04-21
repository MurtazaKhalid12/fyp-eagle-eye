/*
 * PIR Sensor Test (HW-416B) - Simple callback style
 * 
 * Wiring:
 *   HW-416B VCC  -> 5V
 *   HW-416B GND  -> GND
 *   HW-416B OUT  -> GPIO 14
 */

#include "SD_MMC.h"
#include "driver/gpio.h"

#define PIR_PIN 14

void setup() {
  Serial.begin(115200);
  delay(2000);

  // --- DISABLE SD CARD to free GPIO 2, 4, 12, 13, 14, 15 ---
  SD_MMC.end();
  gpio_reset_pin(GPIO_NUM_2);
  gpio_reset_pin(GPIO_NUM_4);
  gpio_reset_pin(GPIO_NUM_12);
  gpio_reset_pin(GPIO_NUM_13);
  gpio_reset_pin(GPIO_NUM_14);
  gpio_reset_pin(GPIO_NUM_15);
  Serial.println("SD Card disabled - all GPIOs freed!");

  // Turn off flash LED
  pinMode(4, OUTPUT);
  digitalWrite(4, LOW);

  // Configure PIR pin
  pinMode(PIR_PIN, INPUT);

  Serial.println("\nPIR Sensor Initialized (Waiting for stabilization...)");
  Serial.println("GPIO 14 | Don't move near sensor for 60 seconds!\n");
}

bool lastMotion = false;

void loop() {
  bool motion = digitalRead(PIR_PIN);

  // Motion started
  if (motion && !lastMotion) {
    Serial.println("Motion Detected!");
  }

  // Motion stopped
  if (!motion && lastMotion) {
    Serial.println("Motion Stopped.");
  }

  lastMotion = motion;
  delay(100);
}
