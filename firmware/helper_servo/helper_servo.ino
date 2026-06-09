/*
 * ============================================================
 *  EagleEye — HELPER board (servo pan controller)   [production]
 * ============================================================
 *  Runs on the SECONDARY ESP32-CAM (AI Thinker). CAMERA DISABLED.
 *  Job: drive ONE servo as a smooth camera-pan head, commanded from the
 *  mobile app via the MAIN board over UART.
 *
 *  Commands received on UART (one per line, '\n'-terminated):
 *    ANGLE:N   -> move SMOOTHLY to absolute angle N (0..180)   [app slider]
 *    LEFT      -> nudge smoothly by -STEP deg
 *    RIGHT     -> nudge smoothly by +STEP deg
 *    CENTER    -> smooth move to 90 deg
 *    HUMAN     -> a gentle smooth sweep (legacy auto-detect alert)
 *
 *  "Smooth" = a NON-BLOCKING stepper eases the servo toward its target a couple
 *  of degrees per tick, instead of jumping — clean pan, and the UART is never
 *  stalled, so commands take effect immediately (low latency).
 *
 *  Requires Arduino library: "ESP32Servo".  Serial debug @ 115200.
 *  Manual test from the monitor:  'a'=left  'd'=right  'c'=center  'p'=sweep
 *
 *  WIRING (this feature needs just 1 data wire + ground):
 *    MAIN GPIO15 (TX) ──► HELPER GPIO13 (RX)
 *    MAIN GND ───────────  HELPER GND
 *    Servo: signal -> HELPER GPIO15,  VCC -> external 5V,  GND -> common
 * ============================================================
 */
#include <ESP32Servo.h>
#include <WiFi.h>

// ---------- HELPER PINS ----------
#define PIN_SERVO      15
#define PIN_LINK_RX    13    // <- MAIN GPIO15 (TX)
#define PIN_LINK_TX    2     // -> MAIN (optional reply; unused by main)
#define PIN_CAM_PWDN   32    // camera power-down (HIGH = off)
#define LINK_BAUD      9600

// ---------- MOTION TUNING ----------
// Lower STEP_MS / higher STEP_DEG = faster & snappier; raise STEP_MS = slower & silkier.
// 2 deg / 8 ms ~= 250 deg/s : smooth but keeps up with a finger drag (low delay).
#define STEP_MS        8     // ms between micro-steps
#define STEP_DEG       2     // deg moved per micro-step
#define NUDGE_STEP     15    // deg per LEFT/RIGHT nudge

HardwareSerial Link(2);      // UART2
Servo servo;
int currentAngle = 90;       // where the head physically is right now
int targetAngle  = 90;       // where we're easing toward
unsigned long lastStepMs = 0;

// Tiny waypoint queue — only used for the multi-stop HUMAN alert sweep.
#define QMAX 8
int  wpQueue[QMAX];
int  wpHead = 0, wpTail = 0;
void wpClear() { wpHead = wpTail = 0; }
void wpPush(int a) { int n = (wpTail + 1) % QMAX; if (n != wpHead) { wpQueue[wpTail] = a; wpTail = n; } }
bool wpEmpty() { return wpHead == wpTail; }
int  wpPop()   { int a = wpQueue[wpHead]; wpHead = (wpHead + 1) % QMAX; return a; }

int clampAngle(int a) { if (a < 0) a = 0; if (a > 180) a = 180; return a; }

void disableCamera() {
  pinMode(PIN_CAM_PWDN, OUTPUT);
  digitalWrite(PIN_CAM_PWDN, HIGH);
}

// Set an immediate target (slider / nudge). Abandons any queued sweep so the
// head simply follows the newest command — this is what makes dragging feel live.
void setTarget(int a) {
  wpClear();
  targetAngle = clampAngle(a);
}

// Gentle multi-stop alert sweep (legacy auto-detect HUMAN command).
void alertSweep() {
  wpClear();
  targetAngle = 150;
  wpPush(30);
  wpPush(90);
}

// NON-BLOCKING stepper: ease currentAngle toward targetAngle. Call every loop.
void serviceServo() {
  unsigned long now = millis();
  if (now - lastStepMs < STEP_MS) return;
  lastStepMs = now;

  if (currentAngle != targetAngle) {
    if (currentAngle < targetAngle) { currentAngle += STEP_DEG; if (currentAngle > targetAngle) currentAngle = targetAngle; }
    else                            { currentAngle -= STEP_DEG; if (currentAngle < targetAngle) currentAngle = targetAngle; }
    servo.write(currentAngle);
  } else if (!wpEmpty()) {
    targetAngle = wpPop();                    // reached a waypoint -> go to the next
  }
}

void handleCommand(const String& m) {
  if      (m.startsWith("ANGLE:")) setTarget(m.substring(6).toInt());
  else if (m == "LEFT")            setTarget(targetAngle - NUDGE_STEP);
  else if (m == "RIGHT")           setTarget(targetAngle + NUDGE_STEP);
  else if (m == "CENTER")          setTarget(90);
  else if (m == "HUMAN" || m == "MOVE") alertSweep();
  else return;                                // unknown -> ignore (no ack)
  Link.println("DONE");                       // optional ack (main ignores)
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n[HELPER] smooth servo pan (camera OFF) — waiting for app/MAIN commands");

  WiFi.mode(WIFI_OFF);
  disableCamera();

  ESP32PWM::allocateTimer(0);
  servo.setPeriodHertz(50);
  servo.attach(PIN_SERVO, 500, 2400);        // SG90-style
  servo.write(currentAngle);                 // start centered (90)

  Link.begin(LINK_BAUD, SERIAL_8N1, PIN_LINK_RX, PIN_LINK_TX);
  Link.setTimeout(20);                        // don't let a partial line stall the stepper
  Serial.println("[HELPER] ready.  (monitor: a=left d=right c=center p=sweep)");
}

void loop() {
  serviceServo();                             // non-blocking smooth motion (runs constantly)

  // command from MAIN (forwarded from the app)
  if (Link.available()) {
    String m = Link.readStringUntil('\n'); m.trim();
    if (m.length()) {
      Serial.printf("[HELPER] <- %s\n", m.c_str());
      handleCommand(m);
    }
  }

  // manual test triggers from the USB serial monitor
  if (Serial.available()) {
    char c = Serial.read();
    if      (c == 'a' || c == 'A') setTarget(targetAngle - NUDGE_STEP);
    else if (c == 'd' || c == 'D') setTarget(targetAngle + NUDGE_STEP);
    else if (c == 'c' || c == 'C') setTarget(90);
    else if (c == 'p' || c == 'P') alertSweep();
  }
}
