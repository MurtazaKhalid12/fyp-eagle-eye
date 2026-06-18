#ifndef EAGLEEYE_PIR_H
#define EAGLEEYE_PIR_H

#include <Arduino.h>
#include "esp_sleep.h"

#define PIR_PIN 2

void pir_begin();

// Configure GPIO2 as ext0 wakeup source (call just before esp_deep_sleep_start)
void pir_configure_wakeup();

// True if this boot was triggered by the PIR (ext0 wakeup on GPIO2)
bool pir_is_wakeup_source();

#endif // EAGLEEYE_PIR_H
