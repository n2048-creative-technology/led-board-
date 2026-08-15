# Electronics — `otherworlds-v2`

KiCad 9 project for the LED driver board: a XIAO ESP32C3 carrier that buffers
its eight data outputs to 5 V and hands them to eight 24 V LED segments.

Open [`otherworlds-v2.kicad_pro`](otherworlds-v2.kicad_pro). Rendered exports of
the schematic and layers live in [`../images/schematic/`](../images/schematic)
and are regenerated with `bash ../scripts-tools/export-kicad.sh`.

| | |
|---|---|
| Size | 98.7 × 90.9 mm, 1.6 mm, 2 layer |
| Mounting | 4 × M4 plated holes (H1–H4) |
| Assembly | Through-hole throughout — hand-solderable |
| Input | 24 V via Wago 734-132 (J19) |
| Logic supply | DC-DC buck module on J15–J18, 24 V → 5 V |

## Signal path

Eight identical channels:

```
XIAO Dn ─► SN74AHCT125N (J3 for D1-D4, J4 for D5-D8) ─► 220 Ω (Rn) ─► LED connector pin 2
```

AHCT logic runs from 5 V and accepts 3.3 V as a valid high, so it both level
shifts and buffers: the strip sees a full 5 V edge instead of the XIAO's
marginal 3.3 V. The series resistor damps reflections and sits at the driver
end of the line.

+24 V runs from J19 straight to pin 3 of every LED connector. It never enters
the logic side of the board.

## Connector map

Traced through the netlist of the committed schematic:

| Connector | J7 (1) | J8 (2) | J9 (3) | J10 (4) | J11 (5) | J12 (6) | J13 (7) | J14 (8) |
|---|---|---|---|---|---|---|---|---|
| Net | L1 | L2 | L3 | L4 | L5 | L6 | L7 | L8 |
| Resistor | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 |
| Buffer | J3 | J3 | J3 | J3 | J4 | J4 | J4 | J4 |
| XIAO pin | D1 | D2 | **D4** | **D3** | D5 | D6 | **D8** | **D7** |
| GPIO | 3 | 4 | 6 | 5 | 7 | 21 | 8 | 20 |

J9/J10 and J13/J14 are fed by crossed pairs. Harmless — the firmware drives all
eight outputs with one identical waveform — but worth knowing at the bench.

LED connectors are all **pin 1 = GND, pin 2 = data, pin 3 = +24 V**.

> ⚠️ The working copy is currently mid-edit: `D1`/`D2` appear once each and
> `D7`/`D8` three times, i.e. J3's first two inputs are labelled D7/D8 rather
> than D1/D2. In `HEAD` every label appears exactly twice. See the root
> [README](../README.md#connector-map).

Other headers:

| Ref | Purpose |
|---|---|
| J1 / J2 | XIAO ESP32C3, 1×7 each |
| J15–J18 | Buck module: J18/J17 = 24 V in, J16/J15 = 5 V out |
| J19 | 24 V input, Wago cage clamp |
| J20 | Breakout of the three unused pins: D0, D9, D10 |

⚠️ D0/GPIO2 and D9/GPIO9 on J20 are **strapping pins**. Anything wired there can
stop the board booting — read
[../firmware/docs/xiao-esp32c3-pinout.md](../firmware/docs/xiao-esp32c3-pinout.md)
first.

## Fabrication

[`production/`](production) holds the JLCPCB fabrication-toolkit output:
[`otherworlds-v2.zip`](production/otherworlds-v2.zip) (gerbers),
[`bom.csv`](production/bom.csv), [`positions.csv`](production/positions.csv),
[`designators.csv`](production/designators.csv) and an IPC netlist. Settings are
in [`fabrication-toolkit-options.json`](fabrication-toolkit-options.json).

Everything is through-hole, so the BOM carries no LCSC part numbers — it is a
hand-assembly list, not an assembly-service one.

## Sizing the supply

Work from the strip's rating, not from the firmware's estimate: the firmware's
milliamp figures model a 5 V strip, while these segments run at 24 V. Take the
strip's W/m × total length ÷ 24 V, add margin, and fuse the input. Inject at
both ends of each segment.

Details, and what the firmware's budget number actually controls, in the root
[README](../README.md#power).
