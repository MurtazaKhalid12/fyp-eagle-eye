#include "eagleeye_pir.h"

bool last_pir_state = false;

void pir_begin() {
  pinMode(PIR_PIN, INPUT);
  Serial.println("[OK] PIR: Pin=GPIO2");
}

bool pir_motion_detected() {
  bool state = (digitalRead(PIR_PIN) == HIGH);
  if (state != last_pir_state) {
    last_pir_state = state;
    if (state) {
      Serial.println("[PIR] Motion Detected!");
      return true;
    } else {
      Serial.println("[PIR] Motion Ended");
    }
  }
  return false;
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
