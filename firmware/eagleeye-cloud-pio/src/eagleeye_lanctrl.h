#ifndef EAGLEEYE_LANCTRL_H
#define EAGLEEYE_LANCTRL_H

// ============================================================
//  EagleEye CLOUD — direct-LAN low-latency servo control
// ============================================================
//  When the phone is on the SAME Wi-Fi as the camera, the app connects to
//      ws://<device-ip>:81/
//  and streams joystick commands straight to the board with NO cloud hop —
//  typically <50 ms vs ~150-300 ms through the MQTT broker. The app falls
//  back to MQTT automatically when it can't reach the device (i.e. remote).
//
//  Commands are the SAME JSON the cloud uses:  {type:"servo", pan, tilt}.
//  We apply them instantly here (set_pan/set_tilt just move the target; the
//  smooth stepper in servos_service() does the motion), so latency is just the
//  LAN round-trip + one loop tick.
//
//  Library: "WebSockets" by Markus Sattler (Links2004) — WebSocketsServer.
//  Include AFTER eagleeye_servos.h and EagleEye_Cloud_IoT.h.
// ============================================================

#include <WebSocketsServer.h>
#include <ArduinoJson.h>

#define LANCTRL_PORT 81

WebSocketsServer lanCtrl(LANCTRL_PORT);

inline void lanctrl_event(uint8_t num, WStype_t type, uint8_t *payload, size_t len) {
  if (type == WStype_CONNECTED) { Serial.printf("[LAN] viewer %u connected\n", num); return; }
  if (type != WStype_TEXT || !payload) return;

  EE_JSON(d, 128);
  if (deserializeJson(d, payload, len)) return;
  if (strcmp(d["type"] | "", "servo") != 0) return;

  // Missing axis (-1) leaves that servo where it is. Legacy {angle} -> pan.
  int pan  = d["pan"]  | (d["angle"] | -1);
  int tilt = d["tilt"] | -1;
  if (pan  >= 0) set_pan(pan);          // applied instantly; stepper does the motion
  if (tilt >= 0) set_tilt(tilt);
  g_last_cmd_ms = millis();             // keep the loop in its fast (AI-paused) window
}

inline void lanctrl_begin() {
  lanCtrl.begin();
  lanCtrl.onEvent(lanctrl_event);
  Serial.printf("[LAN] servo control on ws://%s:%d/\n",
                WiFi.localIP().toString().c_str(), LANCTRL_PORT);
}

// Cheap, non-blocking — call every loop iteration.
inline void lanctrl_service() { lanCtrl.loop(); }

#endif // EAGLEEYE_LANCTRL_H
