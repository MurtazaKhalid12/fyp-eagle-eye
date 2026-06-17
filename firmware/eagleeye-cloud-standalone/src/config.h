#ifndef EAGLEEYE_CONFIG_H
#define EAGLEEYE_CONFIG_H

// ============================================================
//  EagleEye CLOUD — credentials & feature flags
//  Edit the DEV_* values below before flashing.
// ============================================================

#define FW_VERSION            "1.0.0-cloud"

// ---- feature flags ----
#define ENABLE_PROVISIONING   0
#define ENABLE_OTA            1
#define TLS_INSECURE          1
#define STREAM_AUTOSTART      0

// ---- Wi-Fi ----
#define DEV_DEVICE_ID         "cam-01"
#define DEV_WIFI_SSID         "DESKTOP-Q7922V6 8377"
#define DEV_WIFI_PASS         "12345678"

// ---- HiveMQ Cloud (TLS 8883) ----
#define DEV_MQTT_HOST         "659fb17dced44921898bdfaa347fb042.s1.eu.hivemq.cloud"
#define DEV_MQTT_PORT         8883
#define DEV_MQTT_USER         "dev-cam-01"
#define DEV_MQTT_PASS         "Common@321"

// ---- Cloudinary ----
#define DEV_CLD_CLOUD         "dsq74osj5"
#define DEV_CLD_PRESET        "eagleeye_unsigned"
#define DEV_CLD_FOLDER        "eagleeye_intrusions"

// ---- Cloud Function URLs (leave "" to skip) ----
#define DEV_INGEST_URL        ""
#define DEV_TOKEN_URL         ""

// ---- Firebase RTDB host (no https://, no trailing /) ----
#define DEV_FIREBASE_DB       "fyproject-2d3f6-default-rtdb.firebaseio.com"

// ---- Relay server ----
#define DEV_RELAY_HOST        "lean-guppy-28.murtazakhalid12.deno.net"
#define DEV_RELAY_PORT        443

#endif // EAGLEEYE_CONFIG_H
