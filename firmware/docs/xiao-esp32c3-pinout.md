# Seeed XIAO ESP32C3 — pinout & GPIO notes

Sources: [Seeed XIAO ESP32C3 wiki](https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/)
and the Arduino core variant header
`~/.platformio/packages/framework-arduinoespressif32/variants/XIAO_ESP32C3/pins_arduino.h`
(both checked 2026-08-15 — they agree).

## Broken-out digital pins

The castellated edge exposes 11 digital pins plus 5V, 3V3 and GND.

| Board pin | GPIO | Alternate functions |
|---|---|---|
| D0 | GPIO2 | A0 / ADC1_CH2 — **strapping pin** |
| D1 | GPIO3 | A1 / ADC1_CH3 |
| D2 | GPIO4 | A2 / ADC1_CH4, FSPIHD, MTMS (JTAG) |
| D3 | GPIO5 | ADC2_CH0, FSPIWP, MTDI (JTAG) |
| D4 | GPIO6 | SDA, FSPICLK, MTCK (JTAG) |
| D5 | GPIO7 | SCL, FSPID, MTDO (JTAG) |
| D6 | GPIO21 | UART0 TX |
| D7 | GPIO20 | UART0 RX |
| D8 | GPIO8 | SPI SCK — **strapping pin** |
| D9 | GPIO9 | SPI MISO, BOOT button — **strapping pin** |
| D10 | GPIO10 | SPI MOSI, FSPICS0 |

There is **no user-controllable `LED_BUILTIN`** on this board — the two
on-board LEDs are power and battery-charge indicators, hardwired.

## Strapping pins: GPIO2, GPIO8, GPIO9

> **Learned the hard way, 2026-08-15.** A bring-up sketch that blinked *all*
> digital pins drove D0/GPIO2 low for 3 s out of every 6. When esptool reset
> the chip into download mode for the next upload, the running firmware was
> holding GPIO2 low at the instant boot mode was sampled → invalid boot mode →
> the ROM never started USB Serial/JTAG → the board disappeared from the USB
> bus entirely. Recovered with the BOOT-button procedure below. See
> [Recovering a board that will not enumerate](#recovering-a-board-that-will-not-enumerate).
>
> **Rule: never drive GPIO2, GPIO8 or GPIO9 low from firmware unless you have
> a specific reason.** It is not only external wiring that can strand the
> board — your own code can, and it will do it at the worst moment, because
> the host resets the chip precisely when you are trying to reflash it.

These three set the boot mode while the chip is coming out of reset. Driving
them as ordinary outputs *after* boot is perfectly fine — the risk is about
what holds them at the reset instant, whether that is your circuit **or your
firmware**:

- **GPIO9** is tied to the BOOT button with a pull-up. Held LOW at reset →
  the chip enters serial download mode instead of running your firmware.
- **GPIO8** must read HIGH at reset for a normal boot.
- **GPIO2** must read HIGH at reset for a normal boot.

A plain LED + series resistor to GND on one of these pins is enough to break
booting: the LED barely conducts below its forward voltage, so the pin settles
around ~1.8 V against the weak internal pull-up — below the ~2.5 V logic-high
threshold at 3.3 V.

Safe options when you need an indicator on D0 / D8 / D9:

1. Wire the LED **active-low**: `3V3 → LED → resistor → GPIO`. The pin sinks
   current to light it, and it presents a pull-*up* at boot.
2. Drive the LED through a MOSFET / buffer / LED-driver IC, so the GPIO only
   sees a high-impedance gate.
3. Just use the other eight pins for anything indicator-shaped.

### Which pin fails how

| Pin | Held low at reset | Severity |
|---|---|---|
| GPIO9 (D9) | Joint download boot | Benign — this is what the BOOT button does on purpose |
| GPIO8 (D8) | Blocks a normal boot | Bad, but still recoverable over USB |
| GPIO2 (D0) | **Invalid boot mode** | **Worst** — USB Serial/JTAG never comes up, board vanishes from the bus |

GPIO2 is the dangerous one: there is no button on it, and the failure removes
the very interface you would use to fix it.

## Recovering a board that will not enumerate

Symptom: no `/dev/ttyACM*`, and nothing matching VID `303a` or `2886` in
`lsusb` — the board is not on the USB bus at all.

Per [Seeed's troubleshooting notes](https://wiki.seeedstudio.com/XIAO_ESP32C3_Getting_Started/):

1. Unplug the XIAO from USB.
2. Press and **hold the BOOT button**.
3. **While still holding BOOT**, plug the USB-C cable back in.
4. Release BOOT after roughly a second.

This works no matter what is in flash, because a reset releases every GPIO
back to input before any user code runs: GPIO2 floats to its default pull-up,
the button holds GPIO9 low, and the ROM enters serial download mode. Then
reflash normally with `pio run -t upload`.

Make sure nothing is wired to D0/D8/D9 while doing this. Check with:

```bash
ls /dev/ttyACM*
lsusb | grep -iE 'espressif|303a|2886'
```

A plain RESET press is worth trying first, but it will not help if the
firmware in flash re-asserts GPIO2 low on every boot — in that case only the
BOOT procedure breaks the cycle.

## UART0 vs. the serial monitor

The board manifest sets `ARDUINO_USB_CDC_ON_BOOT=1`, so Arduino's `Serial`
is the **native USB Serial/JTAG** peripheral on the USB-C connector
(GPIO18/19, not broken out). That means D6/D7 (UART0 TX/RX) are free to use
as plain GPIO without disturbing the serial monitor.

Side effect of native USB CDC: the serial port disappears from the host on
every reset/reflash and re-enumerates a moment later. That is normal, not a
fault.

## JTAG pins

GPIO4–7 (D2–D5) double as the JTAG interface. Irrelevant while debugging over
USB Serial/JTAG, but worth knowing if you ever attach an external probe.
