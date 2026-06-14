# EagleEye Cloud — PlatformIO (self-contained)

A PlatformIO port of [`firmware/eagleeye-cloud`](../eagleeye-cloud) — the ESP32-CAM
cloud firmware (Wi-Fi + MQTT + HTTPS upload + WebSocket relay + servos + on-device
human detection). **Everything is in this folder**: all libraries are vendored in
`lib/`, nothing is installed into Arduino's global `libraries/`. The original
Arduino sketch is left untouched.

## Layout

```
eagleeye-cloud-pio/
  platformio.ini          board + build config
  src/                    the firmware (copied from firmware/eagleeye-cloud)
    eagleeye-cloud.ino     main sketch (PlatformIO preprocesses .ino like Arduino IDE)
    *.h, config.h          all the firmware modules + your config (git-ignored)
  lib/                    vendored libraries (auto-added to the include path)
    eagleeye_inferencing/  EagleEye v7.16 detector engine — ESP-NN enabled
    ArduinoJson/ ESP32Servo/ PubSubClient/ WebSockets/
  .gitignore             ignores .pio/ and src/config.h (secrets)
```

PlatformIO adds every `lib/<name>/` to the include path automatically, so
`#include <eagleeye_inferencing.h>` / `<ArduinoJson.h>` / … all resolve from this
folder — no global install (the thing Arduino IDE can't do for in-folder libs).

## Build / flash / monitor

```bash
pio run                 # compile
pio run -t upload       # flash (add --upload-port COMx if needed)
pio device monitor -b 115200
```

Pinned to `espressif32@6.5.0` = arduino-esp32 2.0.14 (matches the Arduino IDE setup).

## Notes

- `src/config.h` was copied from the original (it holds Wi-Fi / MQTT / Cloudinary
  secrets) and is **git-ignored** here. Edit it for your deployment.
- `WiFiManager` is only compiled when `ENABLE_PROVISIONING=1` in `src/config.h`.
  It's not vendored (you don't have it installed and it's off by default); to use
  provisioning, add `lib_deps = tzapu/WiFiManager` to `platformio.ini`.
- To change board options (PSRAM, partition, CPU), edit `platformio.ini` — not GUI
  menus.
