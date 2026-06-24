# EagleEye Cloud — PlatformIO Quick Start

Run these from **this folder** (it contains `platformio.ini`), or from anywhere
by adding `-d C:\fyp-eagle-eye\firmware\eagleeye-cloud-pio` to the command.

## Commands

```bash
pio run                                # compile only
pio run -t upload                      # compile + flash
pio run -t upload --upload-port COM3   # flash to a specific port
pio run -t clean                       # delete .pio build cache (forces clean rebuild)
pio device list                        # see which COM ports exist
eemon                                  # serial monitor (COM3, DTR/RTS fix)
```

## Typical cycle

```bash
cd C:\fyp-eagle-eye\firmware\eagleeye-cloud-pio
pio run -t upload --upload-port COM3   # build + flash
eemon                                  # watch output  (Ctrl+C to quit)
```

## Notes

- **Close `eemon` / any serial monitor before flashing** — only one program can
  own COM3 at a time (else "Could not open COM3").
- `eemon COM5` monitors a different port; `eemon` defaults to COM3.
- Omitting `--upload-port` lets PlatformIO auto-detect (fine with one board plugged in).
- First build of a fresh project downloads the toolchain (a few minutes); after
  that it's cached and fast.
- All libraries are vendored in `lib/` (incl. the `eagleeye_vision` ESP-NN engine) —
  nothing is installed system-wide.
