#ifndef WIFI_CONFIG_H
#define WIFI_CONFIG_H

// ── How the live-view server connects ──────────────────────────────────────
//
//  • STATION (join your existing Wi-Fi):  fill WIFI_SSID / WIFI_PASS below.
//    The board prints its IP on serial; browse to http://<that-ip>/ from any
//    device on the same network (keeps your internet).
//
//  • HOTSPOT (default, no credentials): leave WIFI_SSID empty. The board makes
//    its own Wi-Fi (AP_SSID / AP_PASS). Connect your phone/PC to it, then
//    browse to http://192.168.4.1/  (that device loses internet while joined).
//
//  If STA is configured but fails to connect within ~15 s, it falls back to the
//  hotspot automatically.

#define WIFI_SSID   ""                 // <-- your Wi-Fi name (empty = use hotspot)
#define WIFI_PASS   ""                 // <-- your Wi-Fi password

#define AP_SSID     "EagleEye-RGB"     // hotspot name (RGB build)
#define AP_PASS     "eagleeye123"      // hotspot password (min 8 chars)

#endif  // WIFI_CONFIG_H
