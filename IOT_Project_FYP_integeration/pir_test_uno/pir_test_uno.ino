// PIR Sensor Test - Arduino Uno (Full Debug)
// Wiring: VCC->5V, GND->GND, OUT->Pin 7

#define PIR_PIN 7

bool lastMotion = false;
unsigned long motionCount = 0;
unsigned long highCount = 0;
unsigned long lowCount = 0;

void setup() {
  Serial.begin(9600);
  pinMode(PIR_PIN, INPUT);
  
  Serial.println("================================");
  Serial.println("  PIR DEBUG TEST - Arduino Uno");
  Serial.println("  Data Pin: 7 | Baud: 9600");
  Serial.println("================================\n");
  Serial.println("Reading raw GPIO every second...\n");
}

void loop() {
  bool motion = digitalRead(PIR_PIN);

  // Count HIGH vs LOW readings
  if (motion) highCount++;
  else lowCount++;

  // Motion started (rising edge)
  if (motion && !lastMotion) {
    motionCount++;
    Serial.print(">>> MOTION DETECTED! (#");
    Serial.print(motionCount);
    Serial.print(") at ");
    Serial.print(millis() / 1000);
    Serial.println("s");
  }

  // Motion stopped (falling edge)
  if (!motion && lastMotion) {
    Serial.print(">>> MOTION STOPPED at ");
    Serial.print(millis() / 1000);
    Serial.println("s");
  }

  // Print raw value every 2 seconds
  static unsigned long lastPrint = 0;
  if (millis() - lastPrint > 2000) {
    Serial.print("[");
    Serial.print(millis() / 1000);
    Serial.print("s] RAW Pin 7 = ");
    Serial.print(motion ? "HIGH" : "LOW");
    Serial.print(" | HIGH count: ");
    Serial.print(highCount);
    Serial.print(" | LOW count: ");
    Serial.print(lowCount);
    Serial.print(" | Triggers: ");
    Serial.println(motionCount);
    
    lastPrint = millis();
  }

  lastMotion = motion;
  delay(100);
}
