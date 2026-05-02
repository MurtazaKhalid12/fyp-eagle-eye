#ifndef EAGLEEYE_WS_H
#define EAGLEEYE_WS_H

// Arduino Library Manager: "WebSockets" by Markus Sattler (Links2004)
// https://github.com/Links2004/arduinoWebSockets
#include <WebSocketsServer.h>
#include "camera_web_server.h"

#define EAGLEEYE_WS_PORT 81
// Target ~18 FPS max; real rate limited by JPEG encode + Wi-Fi
#define EAGLEEYE_WS_FRAME_MS 55

static WebSocketsServer eagleeyeWs(EAGLEEYE_WS_PORT);
static uint8_t eagleeyeWsClients = 0;
static uint32_t eagleeyeWsLastSend = 0;

inline void eagleeyeWsEvent(uint8_t num, WStype_t type, uint8_t *payload, size_t length) {
  (void)payload;
  (void)length;
  switch (type) {
    case WStype_CONNECTED:
      eagleeyeWsClients++;
      Serial.printf("[WS] client #%u connected (%u online)\n", num, eagleeyeWsClients);
      break;
    case WStype_DISCONNECTED:
      if (eagleeyeWsClients) {
        eagleeyeWsClients--;
      }
      Serial.printf("[WS] client left (%u online)\n", eagleeyeWsClients);
      break;
    default:
      break;
  }
}

inline void eagleeye_ws_begin() {
  eagleeyeWs.begin();
  eagleeyeWs.onEvent(eagleeyeWsEvent);
  Serial.printf("[WS] Binary JPEG stream: ws://<cam-ip>:%u\n", EAGLEEYE_WS_PORT);
}

inline bool eagleeye_ws_has_clients() {
  return eagleeyeWsClients > 0;
}

inline void eagleeye_ws_loop() {
  eagleeyeWs.loop();
  if (!eagleeyeWsClients) {
    return;
  }
  uint32_t now = millis();
  if (now - eagleeyeWsLastSend < EAGLEEYE_WS_FRAME_MS) {
    return;
  }
  eagleeyeWsLastSend = now;

  uint8_t *jpg = nullptr;
  size_t jpg_len = 0;
  if (!eagleeye_grab_jpeg(&jpg, &jpg_len)) {
    return;
  }
  eagleeyeWs.broadcastBIN(jpg, jpg_len);
  free(jpg);
}

#endif
