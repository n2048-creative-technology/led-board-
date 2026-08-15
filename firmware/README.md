# LED board

Firmware for a Seeed **XIAO ESP32C3** driving addressable RGB LED strips.

Current behaviour, across **8 identical strip segments** (73 LEDs each, 584
total) on D1–D8:

1. **FILL** — every segment fades up to bright yellow, LED by LED from the
   first to the last, with a soft leading edge. All 8 segments run this in
   parallel and in step.
2. **BREATHE** — once full, brightness breathes between 100% and 80% of the
   held level, forever.

## Wi-Fi control

The board raises its own access point with a captive portal, so it can be
controlled from a phone with no app and no internet.

| | |
|---|---|
| SSID | `LED-Board` |
| Password | `ledboard` |
| Address | http://4.3.2.1/ |

Join the network and the "sign in" sheet should open the UI automatically; if
not, browse to the address. Everything on the page is inline — no CDN is
reachable on an AP, so the colour wheel is drawn on a `<canvas>` rather than
pulled from a library.

The UI offers:

- **On / off** — turning off runs the fill animation **backwards**, so the
  LEDs withdraw in exactly the reverse order they arrived: the last LED to
  light is the first to go dark. Pressing the button mid-sweep picks up at the
  matching front position rather than snapping, so it stays smooth even if you
  change your mind halfway.
- **Colour** — an HSV wheel (drag to pick), R/G/B sliders, a hex field, and
  the OS-native colour picker. All four stay in sync.
- **Breathing** — cycle period (0.5–20 s) and floor (0–100%). A floor of 100%
  holds steady with no breathing.
- **Start-up fill** — duration, leading-edge softness in LEDs, and a *Replay
  fill* button to watch it again without a reboot.
- **Power** — the budget in mA, with live feedback on the resulting hold level
  and estimated draw. The limiter accounts for the *current colour*: red uses
  one channel, yellow two, white three, so the achievable brightness changes
  as you pick.
- **Access point** — editable network name and password. Applying restarts the
  radio, so you will be disconnected and must rejoin with the new details.

### You cannot lock yourself out of the AP

Credentials are validated server-side before being stored (SSID 1–32 chars,
password empty for an open network or 8–63 chars — a 1–7 char password is
rejected, since no AP will start with one). On top of that, if a stored pair
ever fails to bring the AP up, the board falls back to `LED-Board` /
`ledboard` by itself. Recovering never requires reflashing over USB.

Changes apply live (debounced ~60 ms). **Save to board** writes them to NVS so
they survive a power cycle; without saving, the board reverts to defaults on
reboot.

### HTTP API

Handy for scripting or an external controller:

| Endpoint | Purpose |
|---|---|
| `GET /api/state` | Current settings, hold level, estimated mA, fps, phase |
| `GET /api/set?r=&g=&b=&bp=&bm=&fd=&fe=&pb=` | Set any subset; returns new state |
| `GET /api/power?on=0\|1` | Turn off (reverse withdraw) or on (fill) |
| `GET /api/ap?ssid=&pass=` | Change AP credentials; 400 if invalid |
| `GET /api/fill` | Restart the fill animation |
| `GET /api/save` | Persist current settings to NVS |

`phase` reports `filling`, `breathing`, `emptying` or `off`.

All values are clamped server-side, so out-of-range input is safe.

Wi-Fi does not disturb the LED output — the strips are driven by the RMT
peripheral in hardware, and the frame rate stayed at 62 fps with the AP
running.

## ⚠️ Power: yellow at this scale is expensive

584 LEDs, and **yellow lights two channels per LED**. Full-brightness yellow
across all segments is an estimated **~24 A at 5 V (~120 W)**.

The firmware includes a limiter (Adafruit NeoPixel has no power management of
its own) that computes the brightest yellow fitting `POWER_BUDGET_MA` and
holds there. At the placeholder **3000 mA** it settles on level **31/255 —
about 12% of full**, which is not "bright" by any reasonable reading.

**Set `POWER_BUDGET_MA` in [src/main.cpp](src/main.cpp) to what your supply
actually delivers.** Roughly what each budget buys:

| PSU budget | Hold level | Fraction of full |
|---|---|---|
| 3 A (placeholder) | 31/255 | ~12% |
| 10 A | ~106/255 | ~42% |
| 15 A | ~160/255 | ~63% |
| 20 A | ~213/255 | ~84% |
| 24 A+ | 255/255 | 100% |

Injecting power at both ends of each segment (and mid-run for long ones) is
also worth planning — 24 A does not travel far down a strip's copper without
a visible voltage drop and a colour shift toward red.

## Driving 8 outputs from a 2-channel chip

The ESP32-C3 has only **2 RMT TX channels**, which rules out both obvious
approaches:

| Approach | Result |
|---|---|
| FastLED 3.10.3, 8 controllers | ❌ `no free tx channels`, then a Guru Meditation panic. FastLED pins one RMT channel per controller for its lifetime — hard limit of 2 strips. Its `README_WORKER_POOL.md` describes transparent N>K sharing, but **that implementation is not in the source**. |
| Adafruit NeoPixel, 8 instances | ⚠️ Works — it re-binds a single channel per pin on each show — but the teardown/setup cost measured **3 fps** at 8×73 LEDs. |
| **1 RMT channel + GPIO matrix fan-out** | ✅ **63 fps.** What this firmware does. |

The working approach transmits **one** strip's worth of data on one RMT
channel bound to GPIO3, then uses the GPIO matrix
(`esp_rom_gpio_connect_out_signal`) to route that same output signal to the
other seven pins. Every segment gets an identical, hardware-timed waveform,
and a frame costs one transmission (~2.2 ms) rather than eight.

**The trade-off:** all 8 segments necessarily show the *same* content. That is
exactly what this blue pulse wants. If independent per-segment animation is
ever needed, the options are:

- **2 independent strips** via FastLED (the chip's real RMT limit), or
- **8 independent strips** via a parallel bit-bang driver, computing an 8-bit
  GPIO mask per bit period — all eight pins live in one 32-bit output
  register, so this is feasible but needs cycle-accurate timing work, or
- **a chip with more RMT channels** — ESP32-S3 has 4, original ESP32 has 8.

## Hardware

| | |
|---|---|
| Board | Seeed Studio XIAO ESP32C3 (`seeed_xiao_esp32c3`) |
| MCU | ESP32-C3, single-core RISC-V @ 160 MHz, 4 MB flash |
| Platform | pioarduino `espressif32` 54.03.20 — Arduino core 3.2.0, ESP-IDF 5.4 |
| LED library | Adafruit NeoPixel 1.15.5 |
| Strip | WS281x RGB, 800 kHz, colour order **GBR** |
| Segments | 8 × 73 LEDs = 584 total |
| Data pins | D1–D8 = GPIO 3, 4, 5, 6, 7, 21, 20, 8 |
| Serial | Native USB Serial/JTAG, 115200 baud |

Strip parameters (WS281x / GBR / 73) were taken from a WLED configuration
confirmed working on this exact hardware — worth keeping as the reference if
anything regresses.

> **There is no GPIO22 on the ESP32-C3** — its GPIO range is 0–21. D7 is
> **GPIO20** (UART0 RX), which is what the seventh segment uses.

Full pin map and GPIO caveats: [docs/xiao-esp32c3-pinout.md](docs/xiao-esp32c3-pinout.md).

D1/GPIO3 is deliberately chosen: it is **not** a strapping pin, so an attached
strip cannot interfere with boot the way D0/D8/D9 could.

## Wiring

```
XIAO D1 (GPIO3) ──[ 330Ω ]──► DIN   (strip data input — follow the arrows)
XIAO GND ───────────────────── GND  (must be common with the strip PSU)
Strip +V ◄───────────────────  strip power supply (5 V or 12 V — see below)
                               1000 µF across +V/GND at the injection point
```

Five things that actually matter:

1. **Logic level.** WS2812-family chips want `VIH ≈ 0.7 × VDD`, i.e. ~3.5 V on
   a 5 V strip. The XIAO outputs 3.3 V, which is *marginal*. It often works on
   a short lead and fails intermittently on a long one. Robust fixes: a
   74AHCT125/74HCT245 level shifter, or drop the strip supply to ~4.3–4.5 V
   with a series diode so 3.3 V clears the threshold.
2. **Series resistor.** 220–470 Ω on the data line, placed close to the XIAO
   pin, damps reflections.
3. **Bulk capacitor.** 1000 µF electrolytic across the strip's +V/GND at the
   power injection point absorbs switch-on inrush.
4. **Common ground.** The XIAO ground and the strip PSU ground must be tied
   together, or the data signal has no reference.
5. **Power budget.** The XIAO's `5V` pin is just USB VBUS passthrough — the
   whole USB port budget is 500 mA and the board itself eats into that. That
   is roughly 8 LEDs at full white. Anything longer needs its own supply.
   **If the strip is 12 V, it must have its own PSU — never feed 12 V into the
   XIAO.**

The firmware also enforces a software ceiling via
`FastLED.setMaxPowerInVoltsAndMilliamps(5, 500)`, which scales brightness down
automatically rather than browning out. Raise `POWER_MILLIAMPS` in
[src/main.cpp](src/main.cpp) once the strip runs off a dedicated supply.

## Configuration

All in the header block of [src/main.cpp](src/main.cpp):

| Constant | Default | Meaning |
|---|---|---|
| `LED_DATA_PIN` | `D1` | Strip data pin (GPIO3) |
| `LED_CHIPSET` | `SM16703` | FastLED driver — 300/600/300 ns, ~833 kHz |
| `COLOR_ORDER` | `GRB` | Byte order the strip expects |
| `NUM_LEDS` | `30` | Number of control ICs, **not** LED packages |
| `PULSE_PERIOD_MS` | `3000` | One full fade-up + fade-down cycle |
| `PULSE_MAX_BRIGHTNESS` | `200` | Peak of the pulse, 0–255 |

### If the strip is not an SM16703

`LED_CHIPSET` is a single token — swap it for `WS2812B` (250/625/375 ns, the
usual 5 V 5050 strip), `UCS1903` (500/1500/500 ns, 400 kHz), or `SK6812`.
Symptom of a wrong chipset is flicker or garbled colours down the strip.

### If the colours are wrong

`COLOR_ORDER` is the culprit. The boot self-test makes this trivial to
diagnose — it lights the strip red, then green, then blue, announcing each on
serial. If "BLUE" shows green, swap the last two letters of `COLOR_ORDER`;
common variants are `GRB`, `RGB`, and `BRG`.

## Build, flash, monitor

```bash
pio run                    # build
pio run -t upload          # build + flash
pio device monitor         # 115200 baud
```

## Testing

The firmware self-reports over serial, so it can be validated with no strip
attached — FastLED will happily clock data into thin air. Expected output:

```
XIAO ESP32C3 - FastLED blue pulse
FastLED 3.10.3 | chipset SM16703 | order GRB
Data pin D1 = GPIO3 | 30 LEDs | pulse period 3000 ms
Power limit 5 V / 500 mA
Colour-order self-test (RED, GREEN, BLUE):
  self-test: strip should be RED
  self-test: strip should be GREEN
  self-test: strip should be BLUE
  if those colours were wrong, change COLOR_ORDER in main.cpp
Pulsing blue.
[    1234 ms] blue level  87/255 | 60 fps | ~102 mA
```

The per-second heartbeat reports the current blue level, the achieved frame
rate, and FastLED's own estimate of unscaled strip current — useful for
sanity-checking the power budget before committing to a strip length.

### Verification status

| Step | Status |
|---|---|
| Builds for `seeed_xiao_esp32c3` | ✅ RAM 4.0%, flash 23.2% |
| Flashed and run on hardware | ⏳ pending — board not on USB at time of writing |

The earlier all-pin blink sketch *was* flashed and verified on this board
(2026-08-15, `/dev/ttyACM0`); the FastLED version has not yet been.

## Notes

- **RMT channels.** The ESP32-C3 has only **2 RMT TX channels**, so FastLED
  can drive at most 2 parallel strips on this chip. One strip is comfortable.
- **RMT4 vs RMT5.** ESP-IDF 5.x selects FastLED's RMT5 backend automatically.
  The two backends cannot coexist in one sketch — IDF panics at boot if both
  try to initialise.
- **No `LED_BUILTIN`.** The XIAO ESP32C3's on-board LEDs are power and
  battery-charge indicators, hardwired.
- **USB CDC.** `Serial` is the native USB Serial/JTAG port, so the serial
  device disappears and re-enumerates on every reset/reflash. That is normal.

## Layout

```
src/     firmware sources
include/ headers
lib/     project-private libraries
test/    unit tests
docs/    datasheets, pinouts, reference notes
```

`kicad/`, `openscad/`, `3d-models/` and `images/` to be added as the board and
enclosure work starts.
