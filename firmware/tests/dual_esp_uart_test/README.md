# Dual-ESP32 UART test rig (PIR + wake + 2 servos)

Standalone test for the two-board EagleEye design — **does not touch `eagleeye-main`**.

- **HELPER** (secondary ESP32-CAM, **camera OFF**) → `helper_pir_servo/` — PIR, 2 servos, UART, wakes main.
- **MAIN** (primary ESP32-CAM) → `main_wake_uart/` — *test stub* that fakes the camera AI.

Both are 3.3 V logic → **UART wires connect directly, no level shifter.**

## Why these pins
On the AI-Thinker, the camera + PSRAM eat almost everything. The only **boot-safe free
GPIOs are `13, 14, 15, 2, 4`**. Avoid: `GPIO0` (cam clock), **`GPIO16` (PSRAM — not usable)**,
`GPIO12` (boot-voltage strap, can't idle high), `GPIO1/3` (USB serial = debug).
That's 5 pins, so the **wake is folded into the UART** (main wakes on its RX pin) — no
separate wake wire. Result: **2 signal wires + ground** between the boards.

## ESP32-CAM #1 — HELPER (servo board), camera DISABLED
**Current simplified test: ONE servo, NO PIR (trigger from the serial monitor).**
| Signal | GPIO | Note |
|---|---|---|
| Servo signal | **15** | PWM (one servo for now) |
| UART2 TX → main | **2** | to main GPIO14 |
| UART2 RX ← main | **13** | from main GPIO15 |
| Camera | **off** | firmware never inits it + drives PWDN(GPIO32) high |
| PIR | — | not connected yet → trigger with `s`/`p` in the monitor |

## ESP32-CAM #2 — MAIN (AI board), camera ENABLED (in the real pipeline)
| Signal | GPIO | Note |
|---|---|---|
| UART2 RX **+ ext0 wake** | **14** | one pin does both; wake-on-LOW (UART start bit). Same pin eagleeye-main already uses. |
| UART2 TX → helper | **15** | to helper GPIO13 |

## Wiring — 2 signal wires + common ground
```
   HELPER ESP32-CAM                         MAIN ESP32-CAM
   GPIO2  (UART TX) ────────────────────►   GPIO14 (UART RX + ext0 wake)
   GPIO13 (UART RX) ◄────────────────────   GPIO15 (UART TX)
   GND ───────────────── common ───────────  GND      <-- MANDATORY
```
UART is cross-over: each board's **TX → the other's RX**. The helper sending any byte
pulls main's GPIO14 LOW → wakes it from deep sleep.

```
   Servo (one, SG90 etc.)
   signal -> HELPER GPIO15
   VCC    -> EXTERNAL 5V  (NOT the ESP 3V3!)
   GND    -> common GND
   (PIR not connected yet)
```

## Power & wiring notes
- **Common ground between both ESP32s is mandatory** (UART + wake need it).
- **Servos on a separate 5 V supply** with current headroom; tie its GND to the common GND;
  add a **470–1000 µF cap** across servo 5 V/GND. Never run servos off the 3V3 pin.
- **PIR HC-SR501:** 5 V in, OUT is 3.3 V (safe). Set the hold-time pot short for testing.
- Optional: add a **10 kΩ pull-up from GPIO14 to 3V3** on the main so it can't false-wake if
  the helper is unpowered. (The firmware also enables the internal RTC pull-up.)
- **Flashing the helper:** if upload fails, briefly unplug the wire on **GPIO2**.

## Test procedure (in order)
1. Install the **ESP32Servo** library. Board = AI Thinker ESP32-CAM, 115200 serial.
2. Flash `helper_pir_servo` → helper, `main_wake_uart` → main. Open both serial monitors.
3. **Servo alone first:** in the helper monitor type **`s`** → the servo should sweep.
   Confirms servo wiring + power before involving the link.
4. **Full flow** (`main_wake_uart` ships with `TEST_DEEP_SLEEP 0`). Type **`p`**. Expect:
   - HELPER: `manual -> waking MAIN`
   - MAIN: `triggered -> READY` … `event = 'EVENT:TRIGGER'` … `HUMAN confirmed -> MOVE`
   - HELPER: `moving servo` (servo sweeps) → `DONE`; MAIN: `helper replied: 'DONE'`
   → proves **UART both ways + servo**.
5. **Deep-sleep wake:** set `TEST_DEEP_SLEEP 1`, re-flash main. It sleeps; type `p` on helper →
   main prints `wake_cause … EXT0` and runs the cycle, then sleeps again.
6. (Later) add the PIR on a free pin (e.g. GPIO4) and call `triggerEvent("PIR")` from it.

## Troubleshooting
- **No/garbled UART:** TX↔RX not crossed, baud mismatch, or **no common GND**.
- **Main never wakes:** helper TX not on main GPIO14, GND not shared, or main stuck awake
  (line held low). Confirm idle line is HIGH.
- **Servos jitter / resets:** servos on 3V3 or no shared GND → external 5 V + cap.

## Integration later
Replace the **fake AI** block in `main_wake_uart` with the real `eagleeye-main` v7.16 result
(`human_score >= threshold`), keeping the same messages (`READY`/`EVENT:PIR`/`MOVE`/`DONE`).
GPIO14/15 are camera-safe, so the helper sketch and wiring stay exactly as-is.
