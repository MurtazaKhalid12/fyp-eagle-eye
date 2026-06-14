#ifndef EAGLEEYE_SERVOS_H
#define EAGLEEYE_SERVOS_H

// ============================================================
//  EagleEye CLOUD — TWO servos (pan + tilt) on the MAIN board
// ============================================================
//  Two servos driven directly on the main ESP32-CAM:
//    PAN  signal -> GPIO 15
//    TILT signal -> GPIO 14
//    Servo VCC   -> external 5 V  (NOT the ESP pins)
//    Servo GND   -> common GND (shared with the ESP)
//
//  Non-blocking smooth stepper so panning/tilting is smooth and the AI/MQTT
//  loop is never stalled. Uses LEDC timers 1..3 (the camera owns timer 0), so
//  call servos_begin() AFTER the camera is initialised.
//
//  NOTE: GPIO14/15 are also the SD-MMC pins. The CLOUD build uploads to the
//  cloud (Cloudinary) and does NOT use the SD card, so the pins are free.
//
//  Requires the Arduino library "ESP32Servo".
// ============================================================

#include <Arduino.h>
#include <ESP32Servo.h>

#define SERVO_PAN_PIN   15
#define SERVO_TILT_PIN  14
#define SERVO_STEP_MS   5     // ms between micro-steps (lower = snappier)
#define SERVO_STEP_DEG  1     // 1° micro-steps = smoother motion (~200°/s slew)

Servo servoPan;
Servo servoTilt;
int panCur  = 90, panTgt  = 90;
int tiltCur = 90, tiltTgt = 90;
unsigned long servoLastStep = 0;

static inline int servo_clamp(int a) { if (a < 0) a = 0; if (a > 180) a = 180; return a; }

inline void servos_begin() {
  ESP32PWM::allocateTimer(1);            // camera uses timer 0 — keep servos off it
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);
  servoPan.setPeriodHertz(50);
  servoPan.attach(SERVO_PAN_PIN, 500, 2400);    // SG90-style
  servoPan.write(panCur);                       // start centered
  servoTilt.setPeriodHertz(50);
  servoTilt.attach(SERVO_TILT_PIN, 500, 2400);  // SG90-style
  servoTilt.write(tiltCur);                      // start centered
  Serial.println("[OK] servos: PAN=GPIO15  TILT=GPIO14");
}

inline void set_pan(int a)  { panTgt  = servo_clamp(a); }
inline void set_tilt(int a) { tiltTgt = servo_clamp(a); }

// Non-blocking smooth stepper for BOTH servos — call every loop iteration.
inline void servos_service() {
  unsigned long now = millis();
  if (now - servoLastStep < SERVO_STEP_MS) return;
  servoLastStep = now;
  if (panCur != panTgt) {
    if (panCur < panTgt) { panCur += SERVO_STEP_DEG; if (panCur > panTgt) panCur = panTgt; }
    else                 { panCur -= SERVO_STEP_DEG; if (panCur < panTgt) panCur = panTgt; }
    servoPan.write(panCur);
  }
  if (tiltCur != tiltTgt) {
    if (tiltCur < tiltTgt) { tiltCur += SERVO_STEP_DEG; if (tiltCur > tiltTgt) tiltCur = tiltTgt; }
    else                   { tiltCur -= SERVO_STEP_DEG; if (tiltCur < tiltTgt) tiltCur = tiltTgt; }
    servoTilt.write(tiltCur);
  }
}

#endif // EAGLEEYE_SERVOS_H
