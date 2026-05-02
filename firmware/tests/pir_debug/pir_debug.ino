/*
 * PIR Sensor Debugging Script for ESP32-CAM (HW-416B / SR501)
 * 
 * WIRING:
 * 1. PIR VCC -> ESP32-CAM 5V
 * 2. PIR GND -> ESP32-CAM GND
 * 3. PIR OUT -> ESP32-CAM GPIO 14 (or try GPIO 13 if 14 fails)
 * 
 * IMPORTANT PIR SETTINGS (The Orange Knobs):
 * - TIME DELAY Knob (Txx): Turn fully COUNTER-CLOCKWISE (minimum delay, ~3s)
 * - SENSITIVITY Knob (Sxx): Turn to the MIDDLE (medium range)
 */

#include <Arduino.h>
#include "SD_MMC.h"
#include "driver/gpio.h"

// Define the pin the PIR is connected to
#define PIR_PIN 14 // IF THIS FAILS, TRY CHANGING TO 13

// LED definitions for visual feedback
#define ONBOARD_LED 33 // The little red/blue LED on the back 
#define FLASH_LED 4    // The bright front flash LED (optional use)

void setup() {
  Serial.begin(115200);
  delay(2000); // Wait for serial monitor to connect

  Serial.println("\n----------------------------------");
  Serial.println("   PIR SENSOR DEBUGGING SCRIPT    ");
  Serial.println("----------------------------------");

  // 1. MUST disable SD card because it shares pins (14, 15, 2, 4, 12, 13)
  SD_MMC.end();
  gpio_reset_pin(GPIO_NUM_2);
  gpio_reset_pin(GPIO_NUM_4);
  gpio_reset_pin(GPIO_NUM_12);
  gpio_reset_pin(GPIO_NUM_13);
  gpio_reset_pin(GPIO_NUM_14);
  gpio_reset_pin(GPIO_NUM_15);
  Serial.println("[OK] Disabled SD Card to free pins.");

  // 2. Setup LEDs to visualize motion
  pinMode(ONBOARD_LED, OUTPUT);
  digitalWrite(ONBOARD_LED, HIGH); // HIGH = OFF for this specific LED, LOW = ON
  
  pinMode(FLASH_LED, OUTPUT);
  digitalWrite(FLASH_LED, LOW); // LOW = OFF

  // 3. Setup PIR Input
  // Some sensors need a pulldown to keep them from floating when inactive
  pinMode(PIR_PIN, INPUT_PULLDOWN); 
  
  Serial.printf("[OK] PIR Pin set to GPIO %d\n", PIR_PIN);
  Serial.println("\n[WAIT] PIR sensors need 30-60 seconds to 'warm up' upon power up.");
  Serial.println("       Please do NOT move in front of it right now.");
  Serial.println("----------------------------------\n");
}

int last_pir_state = -1;

void loop() {
  // Read the PIR sensor
  int current_pir_state = digitalRead(PIR_PIN);

  // If the state changed, print it!
  if (current_pir_state != last_pir_state) {
    if (current_pir_state == HIGH) {
      Serial.println(">>> 🔴 MOTION DETECTED! (PIR is HIGH) <<<");
      digitalWrite(ONBOARD_LED, LOW);  // Turn ON small LED
    } else {
      Serial.println(">>> ⚪ Motion Stopped (PIR is LOW) <<<");
      digitalWrite(ONBOARD_LED, HIGH); // Turn OFF small LED
    }
    last_pir_state = current_pir_state;
  }

  delay(50); // Small delay to prevent spamming
}
