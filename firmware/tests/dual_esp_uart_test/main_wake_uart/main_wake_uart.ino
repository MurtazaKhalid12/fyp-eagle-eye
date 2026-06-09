/*
 * ============================================================
 *  EagleEye — DUAL-ESP32 TEST :: MAIN-side simulator
 * ============================================================
 *  Runs on the PRIMARY ESP32-CAM (AI Thinker) — a TEST STUB, NOT eagleeye-main.
 *  The camera/AI is faked so we can validate wake + UART + servo-command alone.
 *  Role:
 *    - (optionally) deep-sleep; get woken when HELPER sends a UART byte
 *      (its TX pulls our RX/GPIO14 LOW -> ext0 wake-on-low)
 *    - UART handshake with HELPER
 *    - PRETEND the camera AI confirms a human
 *    - tell HELPER "MOVE", wait for "DONE"
 *
 *  Pins are camera-safe, so they carry straight into eagleeye-main later:
 *    GPIO14 = UART2 RX  AND  ext0 wake  (one wire does both)
 *    GPIO15 = UART2 TX
 *  Serial debug @ 115200.
 * ============================================================
 */
#include "esp_sleep.h"
#include "driver/rtc_io.h"

// ---------- MAIN PINS ----------
#define PIN_LINK_RX   GPIO_NUM_14   // UART2 RX  AND  ext0 wake  <- HELPER TX (GPIO2)
#define PIN_LINK_TX   15            // UART2 TX -> HELPER RX (GPIO13)

#define TEST_DEEP_SLEEP 0           // 0 = stay awake (bring-up FIRST) | 1 = real deep-sleep wake test
#define AI_SIM_MS       3000        // pretend the camera AI takes this long
#define LINK_BAUD       9600

HardwareSerial Link(2);

void runDetectionCycle() {
  Serial.println("[MAIN] triggered. -> READY");
  Link.println("READY");

  String evt = ""; unsigned long t0 = millis();
  while (millis() - t0 < 2000) { if (Link.available()) { evt = Link.readStringUntil('\n'); evt.trim(); break; } }
  Serial.printf("[MAIN] event from helper = '%s'\n", evt.c_str());

  // ----- SIMULATED camera AI (swap for the real v7.16 result on integration) -----
  Serial.printf("[MAIN] running (fake) AI for %d ms...\n", AI_SIM_MS);
  delay(AI_SIM_MS);
  bool human = true;                // TEST: always confirm

  if (human) {
    Serial.println("[MAIN] HUMAN confirmed -> MOVE");
    Link.println("MOVE");
    String r = ""; unsigned long t1 = millis();
    while (millis() - t1 < 5000) { if (Link.available()) { r = Link.readStringUntil('\n'); r.trim(); break; } }
    Serial.printf("[MAIN] helper replied: '%s'\n", r.c_str());
  } else {
    Serial.println("[MAIN] no human this cycle.");
  }
}

void goToSleep() {
  Serial.println("[MAIN] -> deep sleep (wake when helper sends UART on GPIO14)\n");
  delay(50);
  // wake on RX line going LOW (UART start bit). GPIO14 is RTC-capable.
  rtc_gpio_pullup_en(PIN_LINK_RX);          // idle-high so we don't false-wake
  rtc_gpio_pulldown_dis(PIN_LINK_RX);
  esp_sleep_enable_ext0_wakeup(PIN_LINK_RX, 0);   // 0 = wake on LOW
  esp_deep_sleep_start();                          // reboots into setup() on wake
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Link.begin(LINK_BAUD, SERIAL_8N1, PIN_LINK_RX, PIN_LINK_TX);

  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  Serial.printf("\n[MAIN] boot. wake_cause=%d (%s)\n", (int)cause,
                cause == ESP_SLEEP_WAKEUP_EXT0 ? "EXT0 = helper woke us" : "power-on / reset");

#if TEST_DEEP_SLEEP
  runDetectionCycle();
  goToSleep();
#else
  Serial.println("[MAIN] STAY-AWAKE test mode. Waiting for UART from helper...");
#endif
}

void loop() {
#if !TEST_DEEP_SLEEP
  static bool busy = false;
  if (!busy && Link.available()) {        // helper sent something (WAKE/EVENT)
    busy = true;
    runDetectionCycle();
    Serial.println("[MAIN] cycle done (sleep disabled). waiting again...\n");
    delay(500);
    while (Link.available()) Link.read(); // flush leftovers
    busy = false;
  }
#endif
}
