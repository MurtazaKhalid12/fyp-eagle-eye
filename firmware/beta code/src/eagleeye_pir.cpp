#include "eagleeye_pir.h"

// PIR is WAKE-ONLY: it boots the device from deep sleep (ext0 on GPIO2 HIGH).
// No PIR value/motion is read at runtime, printed to serial, or shown on the OLED.

void pir_begin() {
  pinMode(PIR_PIN, INPUT);
  Serial.println("[OK] PIR: Pin=GPIO2 (wake-only)");
}

void pir_configure_wakeup() {
  // Wake from deep sleep when GPIO2 goes HIGH (PIR fires)
  // GPIO2 is RTC-capable so ext0 wakeup is supported
  esp_sleep_enable_ext0_wakeup(GPIO_NUM_2, 1);
  Serial.println("[PIR] ext0 wakeup configured: GPIO2 HIGH");
}

bool pir_is_wakeup_source() {
  return esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0;
}
