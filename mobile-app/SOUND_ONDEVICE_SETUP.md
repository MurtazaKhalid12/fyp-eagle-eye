# On-device Sound Detection (no server)

The **Sound** tab now runs the footsteps / glass-break / background detector
**entirely on the phone** — no Flask server, no laptop, no IP, no firewall.

```
mic PCM 16 kHz mono
   → assets/models/yamnet_embed.tflite   (15600 samples → 1024-d embedding)
   → assets/models/head_int8.tflite      (1024 → softmax: background, footsteps, glass)
   → live bars (EMA-smoothed, ~2×/sec)
```

This is the **same** YAMNet + trained-head pipeline the server used, exported to
two TFLite files. Verified in Python to reproduce the server's predictions
(background/footsteps/glass all ≈0.996 on the test clips).

## ⚠️ Requires a custom dev build (NOT Expo Go)

On-device TFLite + raw-PCM capture are native modules, so **Expo Go cannot run
this** — you build the app once. After that it works offline, laptop off.

### Native modules added
- `react-native-fast-tflite` (+ `react-native-nitro-modules`) — runs the `.tflite` models
- `react-native-live-audio-stream` — raw 16 kHz PCM from the mic

### Files changed/added
- `app.json` — added the `react-native-fast-tflite` plugin + iOS mic usage string
- `metro.config.js` — added `tflite` to `assetExts` so the models bundle
- `assets/models/yamnet_embed.tflite`, `assets/models/head_int8.tflite` — the models
- `src/screens/SoundTestScreen.js` — rewritten for on-device inference (no `fetch`)
- `src/config/soundTestConfig.js` — now unused (server URL); safe to delete

## Build & run (Android, recommended)

Needs **Android Studio / SDK + JDK 17** and a phone in USB debugging mode (or an emulator).

```bash
cd C:\fyp-eagle-eye\mobile-app
npx expo prebuild --clean        # generates the native android/ project
npx expo run:android             # builds + installs the dev build on the phone
```

Then just open the app → **Sound** tab → tap the mic. Make footstep/knock or
glass-clink sounds; the bars react live, all on-device. (Internet/laptop can be off.)

> iOS: `npx expo run:ios` (needs a Mac + Xcode). `react-native-live-audio-stream`
> is Android-first; on iOS confirm it streams 16 kHz — otherwise swap the capture
> lib (see Troubleshooting).

## Re-generating the models (optional)
The TFLite files are already bundled. To rebuild them from the trained head:
```bash
cd "C:\fyp-eagle-eye\voice system\training"
python quantize.py                       # (re)creates out/head_int8.tflite
python export_yamnet_embed_tflite.py     # creates out/yamnet_embed.tflite + sanity-checks the chain
# then copy both into mobile-app/assets/models/
```

## Troubleshooting
- **Build fails on a Nitro / new-architecture error:** set `"newArchEnabled": true`
  in `app.json` and re-run `npx expo prebuild --clean && npx expo run:android`.
  (Reanimated 4 in this project also prefers the new architecture, so this is usually safe.)
- **`Cannot find module 'react-native-fast-tflite'` / native crash in Expo Go:**
  you're still on Expo Go. You must use the dev build from `npx expo run:android`.
- **Bars stay flat / no permission prompt:** grant the microphone permission in
  Android settings for the app, then restart the Sound screen.
- **Everything reads "background":** the mic source may be over-processed —
  in `SoundTestScreen.js` the capture uses `audioSource: 1` (raw MIC); try `6`
  (VOICE_RECOGNITION) or `9` (UNPROCESSED) if your device supports it.
- **Models won't load (`require` of .tflite fails):** confirm `metro.config.js`
  has `tflite` in `assetExts`, then restart Metro with `npx expo start -c`.
