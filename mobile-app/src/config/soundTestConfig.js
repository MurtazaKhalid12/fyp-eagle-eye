// ============================================================
//  SOUND TEST (TEMPORARY / REMOVABLE)
// ============================================================
//  Points the in-app Sound Test screen at the local model server
//  (voice system/webtest/app.py, YAMNet + head).
//
//  Set this to the LAPTOP IP on the SAME network as the phone, + port 5000.
//    - Phone on the laptop's Mobile Hotspot  -> use the hotspot gateway IP
//      (Windows ICS is always 192.168.137.1). <-- current setup.
//    - Phone on the same Wi-Fi router as the laptop's Ethernet/Wi-Fi
//      -> use that adapter's IPv4 from `ipconfig` (e.g. 192.168.1.88).
//  NOTE: the laptop's Ethernet IP (192.168.1.88) is on a DIFFERENT subnet than
//  the hotspot, so the phone cannot reach it — that caused the all-zero bars.
//
//  To REMOVE the whole sound-test feature later, delete:
//    - this file
//    - src/screens/SoundTestScreen.js
//    - the 2 lines marked "SOUND TEST (removable)" in App.js
// ============================================================
export const SOUND_SERVER_URL = "http://192.168.1.88:5000";
