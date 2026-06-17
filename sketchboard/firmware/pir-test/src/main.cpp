#include <Arduino.h>

#define PIR_PIN       2     // GPIO2 — matches eagleeye-cloud-v2
#define WARMUP_MS     60000 // PIR needs ~60s to settle after power-on
#define DEBOUNCE_MS   2000  // signal must hold HIGH this long to count as real motion

void setup() {
    Serial.begin(115200);
    pinMode(PIR_PIN, INPUT);

    Serial.println("Warming up PIR — please wait 60 seconds...");
    unsigned long start = millis();
    while (millis() - start < WARMUP_MS) {
        Serial.printf("  %lu s remaining\n", (WARMUP_MS - (millis() - start)) / 1000);
        delay(5000);
    }
    Serial.println("PIR ready.");
}

void loop() {
    if (digitalRead(PIR_PIN) == HIGH) {
        // debounce: confirm signal stays HIGH for DEBOUNCE_MS
        unsigned long triggered = millis();
        bool held = true;
        while (millis() - triggered < DEBOUNCE_MS) {
            if (digitalRead(PIR_PIN) == LOW) { held = false; break; }
            delay(50);
        }
        if (held) {
            Serial.println("human detected");
        }
    } else {
        Serial.println("no human");
    }
    delay(500);
}
