/*
 * ============================================================
 *  EagleEye — DUAL-ESP32 TEST :: HELPER board  (simplified)
 * ============================================================
 *  Runs on the SECONDARY ESP32-CAM (AI Thinker). CAMERA DISABLED.
 *  Current test setup:
 *    - ONE servo on GPIO15
 *    - NO PIR yet  -> trigger manually from the serial monitor:
 *         'p' = full flow (wake MAIN -> UART -> MAIN says MOVE -> servo moves)
 *         's' = just sweep the servo locally (test the servo wiring alone)
 *    - wakes MAIN by sending a UART byte (MAIN wakes on its RX pin / ext0)
 *
 *  Requires Arduino library: "ESP32Servo".  Serial debug @ 115200.
 *
 *  PINS (boot-safe set; GPIO0/12/16 avoided):
 *    Servo      -> GPIO15
 *    UART2 TX   -> GPIO2   -> MAIN GPIO14 (its RX + ext0 wake)
 *    UART2 RX   -> GPIO13  <- MAIN GPIO15 (its TX)
 * ============================================================
 */
#include <ESP32Servo.h>
#include <WiFi.h>

// ---------- HELPER PINS ----------
#define PIN_SERVO      15
#define PIN_LINK_TX    2     // -> MAIN GPIO14
#define PIN_LINK_RX    13    // <- MAIN GPIO15
#define PIN_CAM_PWDN   32    // AI-Thinker camera power-down (HIGH = off)

#define LINK_BAUD      9600

HardwareSerial Link(2);      // UART2 (UART0 stays free for USB debug)
Servo servo;
bool pendingEvent = false;

void disableCamera() {
  pinMode(PIN_CAM_PWDN, OUTPUT);
  digitalWrite(PIN_CAM_PWDN, HIGH);   // power the OV2640 down
}

void wakeMain() {
  Link.println("WAKE");               // a byte pulls MAIN's RX(GPIO14) LOW -> ext0 wake
  delay(600);                         // let MAIN boot + start its UART
}

void sweepServo() {
  Serial.println("[HELPER] moving servo");
  for (int a = 0; a <= 120; a += 4) { servo.write(a); delay(15); }
  delay(300);
  for (int a = 120; a >= 0; a -= 4) { servo.write(a); delay(15); }
  servo.write(0);
}

void triggerEvent(const char* why) {
  pendingEvent = true;
  Serial.printf("[HELPER] %s -> waking MAIN\n", why);
  wakeMain();
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n[HELPER] 1 servo + UART link (TEST: no PIR, camera OFF)");

  WiFi.mode(WIFI_OFF);
  disableCamera();

  ESP32PWM::allocateTimer(0);
  servo.setPeriodHertz(50);
  servo.attach(PIN_SERVO, 500, 2400);   // SG90-style 0.5–2.4 ms
  servo.write(0);

  Link.begin(LINK_BAUD, SERIAL_8N1, PIN_LINK_RX, PIN_LINK_TX);
  Serial.println("[HELPER] ready — servo rotating continuously (0<->180).");
}

void loop() {
  // --- continuous servo rotation (non-blocking sweep 0 <-> 180) ---
  static int angle = 0, step = 3;
  static unsigned long lastStep = 0;
  if (millis() - lastStep >= 20) {          // ~20 ms per step = smooth sweep
    lastStep = millis();
    angle += step;
    if (angle >= 180)    { angle = 180; step = -3; }
    else if (angle <= 0) { angle = 0;   step =  3; }
    servo.write(angle);
  }

  // still answer MAIN over UART (link stays testable)
  if (Link.available()) {
    String m = Link.readStringUntil('\n'); m.trim();
    if (m.length()) Serial.printf("[HELPER] <- MAIN: %s\n", m.c_str());
    if (m == "READY" && pendingEvent) { Link.println("EVENT:TRIGGER"); pendingEvent = false; }
    else if (m == "MOVE")             { Link.println("DONE"); }
  }
}

