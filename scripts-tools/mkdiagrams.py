#!/usr/bin/env python3
"""Generate the README diagrams as SVG.

The two animation diagrams are computed from the firmware's own integer maths
(renderFrontAt / breatheWave / gamma8), so they show what the strip actually
does rather than an artist's impression.
"""
import math
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "images" / "diagrams"
OUT.mkdir(parents=True, exist_ok=True)

BG   = "#ffffff"
PANE = "#f3f5f8"
LINE = "#3a4048"
MUT  = "#6b7280"
ACC  = "#e8a41f"
RED  = "#c8403a"
BLK  = "#22262c"
BLU  = "#2f6fd0"
GRN  = "#3f9142"

FONT = "font-family='DejaVu Sans, Helvetica, Arial, sans-serif'"
MONO = "font-family='DejaVu Sans Mono, Menlo, Consolas, monospace'"


def svg(w, h, body, title):
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' "
            f"viewBox='0 0 {w} {h}' role='img' aria-label='{title}'>"
            f"<title>{title}</title>"
            f"<rect width='{w}' height='{h}' fill='{BG}'/>{body}</svg>")


def box(x, y, w, h, label, sub=None, fill=PANE, stroke=LINE, r=8, lsize=14):
    s = (f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='{r}' fill='{fill}' "
         f"stroke='{stroke}' stroke-width='1.6'/>")
    cy = y + h / 2 + (0 if not sub else -7)
    s += (f"<text x='{x + w/2}' y='{cy + 5}' text-anchor='middle' {FONT} "
          f"font-size='{lsize}' font-weight='600' fill='{BLK}'>{label}</text>")
    if sub:
        s += (f"<text x='{x + w/2}' y='{cy + 23}' text-anchor='middle' {MONO} "
              f"font-size='11.5' fill='{MUT}'>{sub}</text>")
    return s


def txt(x, y, s, size=12, anchor="start", fill=BLK, mono=False, weight="400"):
    f = MONO if mono else FONT
    return (f"<text x='{x}' y='{y}' text-anchor='{anchor}' {f} font-size='{size}' "
            f"font-weight='{weight}' fill='{fill}'>{s}</text>")


def arrow(x1, y1, x2, y2, color=LINE, dash=None, width=1.8, head="a"):
    d = f" stroke-dasharray='{dash}'" if dash else ""
    return (f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='{color}' "
            f"stroke-width='{width}'{d} marker-end='url(#{head})'/>")


def defs(colors):
    m = ""
    for name, c in colors.items():
        m += (f"<marker id='{name}' viewBox='0 0 10 10' refX='9' refY='5' "
              f"markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
              f"<path d='M 0 0 L 10 5 L 0 10 z' fill='{c}'/></marker>")
    return f"<defs>{m}</defs>"


# ---------------------------------------------------------------------------
# Shared symbols
# ---------------------------------------------------------------------------
def gnd(x, y, label=None):
    """Local ground symbol -- keeps the drawing free of one long return rail."""
    s = (f"<line x1='{x}' y1='{y}' x2='{x}' y2='{y+16}' stroke='{BLK}' stroke-width='1.6'/>"
         f"<line x1='{x-15}' y1='{y+16}' x2='{x+15}' y2='{y+16}' stroke='{BLK}' stroke-width='2.6'/>"
         f"<line x1='{x-9}' y1='{y+23}' x2='{x+9}' y2='{y+23}' stroke='{BLK}' stroke-width='2.2'/>"
         f"<line x1='{x-4}' y1='{y+30}' x2='{x+4}' y2='{y+30}' stroke='{BLK}' stroke-width='1.8'/>")
    if label:
        s += txt(x, y + 46, label, 10.5, anchor="middle", fill=MUT)
    return s


def flag(x, y, label, color=RED, up=True):
    """Power flag, drawn the way the KiCad schematic labels its rails."""
    d = -1 if up else 1
    s = (f"<path d='M {x} {y} L {x} {y+d*14} M {x-7} {y+d*14} L {x} {y+d*22} "
         f"L {x+7} {y+d*14} Z' fill='none' stroke='{color}' stroke-width='1.6' "
         f"stroke-linejoin='round'/>")
    s += txt(x, y + d * 30 + (4 if up else 10), label, 11, anchor="middle",
             fill=color, mono=True, weight="600")
    return s


# ---------------------------------------------------------------------------
# 1. System overview
# ---------------------------------------------------------------------------
def system_overview():
    W, H = 1000, 680
    s = defs({"a": LINE, "ar": RED, "ay": ACC, "ab": BLU})
    s += txt(28, 34, "System overview", 17, weight="700")
    s += txt(28, 54, "One controller, one data waveform, eight identical segments", 12.5, fill=MUT)

    # phone
    s += box(28, 120, 150, 78, "Phone / laptop", "any browser")
    s += (f"<path d='M 178 159 L 246 159' stroke='{BLU}' stroke-width='1.8' "
          f"stroke-dasharray='5 4' marker-end='url(#ab)'/>")
    s += txt(212, 148, "Wi-Fi", 11, anchor="middle", fill=BLU, mono=True)

    # controller
    s += box(248, 96, 236, 300, "", fill="#eef2f7")
    s += txt(366, 122, "XIAO ESP32C3", 14.5, anchor="middle", weight="700")
    s += txt(366, 139, "on J1 / J2 headers", 11, anchor="middle", fill=MUT, mono=True)
    rows = [("SoftAP  LED-Board", "4.3.2.1  ·  WPA2"),
            ("DNS captive portal", "every host -> /"),
            ("HTTP server", "/  and  /api"),
            ("NVS settings store", "namespace ledboard"),
            ("RMT TX channel", "800 kHz  ·  1 x 73 px")]
    for i, (a, b) in enumerate(rows):
        y = 156 + i * 47
        s += (f"<rect x='266' y='{y}' width='200' height='38' rx='6' fill='{BG}' "
              f"stroke='{LINE}' stroke-width='1.1'/>")
        s += txt(276, y + 16, a, 11.5, weight="600")
        s += txt(276, y + 30, b, 10.5, fill=MUT, mono=True)
    s += (f"<rect x='266' y='391' width='200' height='34' rx='6' fill='{ACC}' "
          f"fill-opacity='.22' stroke='{ACC}' stroke-width='1.4'/>")
    s += txt(366, 406, "GPIO matrix fan-out", 11.5, anchor="middle", weight="600")
    s += txt(366, 419, "one signal -> 8 pins", 10.5, anchor="middle", fill=MUT, mono=True)

    # level shifters
    s += box(536, 150, 130, 275, "", fill=PANE)
    s += txt(601, 176, "J3  ·  J4", 13, anchor="middle", weight="700", mono=True)
    s += txt(601, 194, "2 x SN74AHCT125N", 10.5, anchor="middle", fill=MUT, mono=True)
    s += txt(601, 208, "quad buffers = 8 ch", 10.5, anchor="middle", fill=MUT)
    s += txt(601, 246, "3.3 V  ->  5 V", 12, anchor="middle", weight="600", fill=RED)
    s += (f"<line x1='556' y1='268' x2='646' y2='268' stroke='{LINE}' "
          f"stroke-width='1' stroke-dasharray='3 3'/>")
    s += txt(601, 296, "R1 - R8", 12, anchor="middle", mono=True, weight="600")
    s += txt(601, 312, "220 R in series", 10.5, anchor="middle", fill=MUT)
    s += txt(601, 356, "AHCT logic runs at 5 V,", 10.5, anchor="middle", fill=MUT)
    s += txt(601, 371, "so it accepts 3.3 V in", 10.5, anchor="middle", fill=MUT)
    s += txt(601, 386, "and drives a full 5 V out", 10.5, anchor="middle", fill=MUT)
    s += arrow(468, 408, 534, 300, ACC, head="ay")

    # segments
    pins = [("D1", 3, "J7"), ("D2", 4, "J8"), ("D3", 5, "J9"), ("D4", 6, "J10"),
            ("D5", 7, "J11"), ("D6", 21, "J12"), ("D7", 20, "J13"), ("D8", 8, "J14")]
    for i, (d, gpio, conn) in enumerate(pins):
        y = 128 + i * 38
        s += (f"<rect x='740' y='{y}' width='232' height='30' rx='6' fill='{BG}' "
              f"stroke='{LINE}' stroke-width='1.2'/>")
        s += txt(750, y + 19, f"{d}=GPIO{gpio}", 10.5, mono=True, weight="600")
        s += txt(832, y + 19, conn, 10.5, mono=True, fill=BLU, weight="600")
        s += txt(866, y + 19, f"seg {i+1}", 10.5, fill=MUT)
        for k in range(6):
            s += (f"<circle cx='{924 + k*8}' cy='{y+15}' r='2.4' fill='{ACC}' "
                  f"stroke='{ACC}' stroke-opacity='.6'/>")
        s += arrow(668, 274, 738, y + 15, ACC, width=1.2, head="ay")
    s += txt(856, 118, "8 x 73 px = 584  ·  WS281x, GBR, 800 kHz, 24 V",
             11, anchor="middle", fill=MUT)

    # power chain
    s += box(28, 470, 150, 78, "24 V PSU", "sized for the strip")
    s += arrow(178, 509, 206, 509, RED, head="ar")
    s += box(208, 486, 86, 46, "J19", "Wago", lsize=12)
    s += (f"<path d='M 294 509 L 856 509 L 856 434' stroke='{RED}' stroke-width='2.2' "
          f"fill='none' marker-end='url(#ar)'/>")
    s += txt(310, 499, "+24 V straight to pin 3 of every LED connector", 11, fill=RED)
    s += (f"<circle cx='400' cy='509' r='3.4' fill='{RED}'/>")
    s += (f"<line x1='400' y1='509' x2='400' y2='540' stroke='{RED}' stroke-width='1.8'/>")
    s += box(330, 540, 190, 54, "DC-DC buck", "24 V -> 5 V")
    s += (f"<line x1='520' y1='567' x2='556' y2='567' stroke='{RED}' stroke-width='1.8'/>")
    s += flag(556, 567, "+5 V", up=False)
    s += txt(578, 562, "XIAO J1.1  and  both buffer VCCs (pin 14)", 11, fill=RED)
    s += txt(578, 578, "a module on the J15-J18 headers, not a fitted part", 10.5, fill=MUT)
    s += (f"<line x1='425' y1='594' x2='425' y2='624' stroke='{BLK}' stroke-width='1.8'/>")
    s += (f"<line x1='103' y1='548' x2='103' y2='624' stroke='{BLK}' stroke-width='1.8'/>")
    s += (f"<path d='M 103 624 L 900 624 L 900 434' stroke='{BLK}' stroke-width='2.2' "
          f"fill='none' marker-end='url(#a)'/>")
    s += txt(470, 648, "GND — one node across PSU, board and every segment",
             11, anchor="middle", fill=MUT)
    return svg(W, H, s, "LED board system overview")


# ---------------------------------------------------------------------------
# 2. One channel of the driver board
# ---------------------------------------------------------------------------
def wiring():
    W, H = 1000, 600
    s = defs({"a": LINE, "ar": RED, "ay": ACC})
    s += txt(28, 34, "One channel of eight", 17, weight="700")
    s += txt(28, 54, "Simplified from the KiCad schematic — designators match "
                     "otherworlds-v2.kicad_sch", 12.5, fill=MUT)

    # +24 V rail
    s += (f"<line x1='336' y1='118' x2='946' y2='118' stroke='{RED}' stroke-width='2.2'/>")
    s += txt(336, 104, "+24 V", 11.5, fill=RED, mono=True, weight="600")

    # XIAO
    s += (f"<rect x='40' y='150' width='176' height='280' rx='10' fill='{PANE}' "
          f"stroke='{LINE}' stroke-width='1.6'/>")
    s += txt(128, 178, "XIAO ESP32C3", 13.5, anchor="middle", weight="700")
    s += txt(128, 194, "J1 / J2 headers", 10.5, anchor="middle", fill=MUT, mono=True)
    s += (f"<line x1='40' y1='204' x2='216' y2='204' stroke='{LINE}' stroke-width='1'/>")
    pins = [("D1", "GPIO3"), ("D2", "GPIO4"), ("D3", "GPIO5"), ("D4", "GPIO6"),
            ("D5", "GPIO7"), ("D6", "GPIO21"), ("D7", "GPIO20"), ("D8", "GPIO8")]
    for i, (d, g) in enumerate(pins):
        y = 226 + i * 22
        s += txt(56, y + 4, d, 11.5, mono=True, weight="600")
        s += txt(86, y + 4, g, 11, mono=True, fill=MUT)
        s += (f"<line x1='216' y1='{y}' x2='248' y2='{y}' stroke='{ACC}' stroke-width='1.6'/>")
        s += (f"<circle cx='248' cy='{y}' r='2.6' fill='{ACC}'/>")
    s += txt(56, 414, "GND", 11.5, mono=True, weight="600")
    s += (f"<path d='M 216 410 L 300 410 L 300 434' stroke='{BLK}' stroke-width='1.8' fill='none'/>")
    s += gnd(300, 434)

    # buffer J3
    s += (f"<path d='M 248 226 L 288 226 L 288 268 L 306 268' stroke='{ACC}' "
          f"stroke-width='1.6' fill='none'/>")
    s += (f"<path d='M 306 228 L 306 308 L 378 268 Z' fill='{BG}' stroke='{LINE}' "
          f"stroke-width='1.8' stroke-linejoin='round'/>")
    s += txt(318, 252, "J3", 11, mono=True, weight="600")
    s += txt(316, 286, "SN74", 8.5, mono=True, fill=MUT)
    s += txt(316, 296, "AHCT125N", 8.5, mono=True, fill=MUT)
    s += txt(300, 244, "2", 9.5, anchor="end", mono=True, fill=MUT)
    s += txt(384, 258, "3", 9.5, mono=True, fill=MUT)
    s += (f"<line x1='342' y1='228' x2='342' y2='196' stroke='{RED}' stroke-width='1.6'/>")
    s += flag(342, 196, "+5 V")
    s += txt(356, 190, "pin 14", 10, fill=MUT, mono=True)
    s += (f"<line x1='342' y1='302' x2='342' y2='330' stroke='{BLK}' stroke-width='1.6'/>")
    s += gnd(342, 330, "pin 7")
    s += txt(252, 214, "3.3 V", 10, fill=MUT)

    # R1
    s += (f"<line x1='378' y1='268' x2='406' y2='268' stroke='{ACC}' stroke-width='1.6'/>")
    zig = "M 406 268"
    for k in range(6):
        zig += f" L {412 + k*9} {260 if k % 2 == 0 else 276}"
    zig += " L 464 268"
    s += f"<path d='{zig}' fill='none' stroke='{ACC}' stroke-width='1.8'/>"
    s += txt(435, 250, "R1  220 R", 11, anchor="middle", mono=True, weight="600")
    s += (f"<line x1='464' y1='268' x2='516' y2='268' stroke='{ACC}' stroke-width='1.6' "
          f"marker-end='url(#ay)'/>")
    s += txt(490, 288, "L1", 10.5, anchor="middle", mono=True, weight="600")

    # connector J7 + segment
    s += (f"<rect x='520' y='214' width='190' height='108' rx='8' fill='{PANE}' "
          f"stroke='{LINE}' stroke-width='1.6'/>")
    s += txt(615, 238, "J7", 13, anchor="middle", weight="700", mono=True)
    s += txt(615, 254, "3-pin, to segment 1", 10.5, anchor="middle", fill=MUT)
    for i, (pin, label, col) in enumerate([("3", "+24 V", RED), ("2", "L1  data", ACC),
                                           ("1", "GND", BLK)]):
        y = 278 + i * 15
        s += txt(548, y, pin, 10.5, mono=True, fill=MUT)
        s += txt(570, y, label, 10.5, mono=True, fill=col, weight="600")
    s += (f"<line x1='560' y1='214' x2='560' y2='118' stroke='{RED}' stroke-width='1.8'/>")
    s += (f"<line x1='668' y1='322' x2='668' y2='352' stroke='{BLK}' stroke-width='1.8'/>")
    s += gnd(668, 352)
    s += arrow(712, 268, 748, 268, LINE, width=1.4)
    s += (f"<rect x='752' y='240' width='200' height='56' rx='8' fill='{BG}' "
          f"stroke='{LINE}' stroke-width='1.4'/>")
    s += txt(852, 262, "segment 1", 12, anchor="middle", weight="700")
    s += txt(852, 280, "73 px WS281x, 24 V", 10.5, anchor="middle", fill=MUT, mono=True)

    # power entry + buck
    s += box(846, 380, 116, 56, "J19", "24 V in", lsize=12)
    s += (f"<line x1='904' y1='380' x2='904' y2='118' stroke='{RED}' stroke-width='2'/>")
    s += (f"<line x1='904' y1='436' x2='904' y2='466' stroke='{BLK}' stroke-width='1.8'/>")
    s += gnd(904, 466)
    s += box(636, 380, 176, 56, "DC-DC buck", "24 V -> 5 V", lsize=12)
    s += (f"<line x1='724' y1='380' x2='724' y2='118' stroke='{RED}' stroke-width='1.8'/>")
    s += (f"<line x1='636' y1='408' x2='596' y2='408' stroke='{RED}' stroke-width='1.8'/>")
    s += flag(596, 408, "+5 V")
    s += txt(596, 456, "on J15-J18", 10, anchor="middle", fill=MUT, mono=True)
    s += (f"<line x1='724' y1='436' x2='724' y2='466' stroke='{BLK}' stroke-width='1.8'/>")
    s += gnd(724, 466)

    # the other seven channels
    s += (f"<path d='M 258 248 L 268 248 L 268 380 L 258 380' fill='none' stroke='{MUT}' "
          f"stroke-width='1.2'/>")
    s += (f"<line x1='268' y1='314' x2='268' y2='344' stroke='{MUT}' stroke-width='1.2'/>")
    s += txt(276, 348, "x 7 more", 10.5, fill=MUT, mono=True)

    notes = [
        ("D2-D8 repeat this channel", "J3 buffers D1-D4, J4 buffers D5-D8; R1-R8 feed "
         "connectors J7-J14."),
        ("The buck is a module", "it mounts on the J15-J18 single-pin headers, so it can be "
         "sized to the load."),
        ("Only the data line is shifted", "the 24 V strip power never touches the board's "
         "logic side."),
        ("Every ground symbol is one node", "PSU, board and strips share it, or the data line "
         "has no reference."),
    ]
    for i, (a, b) in enumerate(notes):
        y = 508 + i * 22
        s += (f"<circle cx='48' cy='{y-4}' r='3' fill='{ACC}'/>")
        s += txt(62, y, a, 11.5, weight="600")
        s += txt(320, y, b, 11.5, fill=MUT)
    return svg(W, H, s, "One channel of the LED driver board")


# ---------------------------------------------------------------------------
def fanout():
    W, H = 1000, 500
    s = defs({"a": LINE, "ay": ACC, "ab": BLU})
    s += txt(28, 34, "Driving 8 outputs from a 2-channel chip", 17, weight="700")
    s += txt(28, 54, "One RMT transmission per frame, mirrored onto eight pins by the GPIO matrix",
             12.5, fill=MUT)

    s += box(40, 96, 190, 84, "Frame buffer", "73 px, Adafruit NeoPixel")
    s += arrow(232, 138, 292, 138, LINE)
    s += box(294, 96, 190, 84, "RMT TX channel 0", "hardware-timed, 800 kHz")
    s += txt(389, 196, "one 2.2 ms transmission", 11, anchor="middle", fill=MUT, mono=True)

    # waveform
    d = "M 314 232"
    x = 314
    for bit in [1, 0, 1, 1, 0, 1, 0, 0, 1, 1]:
        hi = 14 if bit else 6
        d += f" L {x} 232 L {x} {232-24} L {x+hi} {232-24} L {x+hi} 232 L {x+20} 232"
        x += 20
    s += f"<path d='{d}' fill='none' stroke='{ACC}' stroke-width='1.8'/>"
    s += txt(389, 252, "WS281x bitstream", 10.5, anchor="middle", fill=MUT)

    s += (f"<path d='M 484 138 L 540 138' stroke='{ACC}' stroke-width='2' "
          f"marker-end='url(#ay)'/>")
    s += (f"<rect x='542' y='90' width='196' height='96' rx='8' fill='{ACC}' "
          f"fill-opacity='.18' stroke='{ACC}' stroke-width='1.8'/>")
    s += txt(640, 120, "GPIO matrix", 13.5, anchor="middle", weight="700")
    s += txt(640, 140, "esp_rom_gpio_connect_out_signal()", 9.5, anchor="middle", mono=True)
    s += txt(640, 162, "same func_sel routed to 8 pads", 10.5, anchor="middle", fill=MUT)

    pins = [3, 4, 5, 6, 7, 21, 20, 8]
    for i, g in enumerate(pins):
        y = 84 + i * 30
        s += (f"<rect x='808' y='{y}' width='150' height='24' rx='6' fill='{BG}' "
              f"stroke='{LINE}' stroke-width='1.2'/>")
        s += txt(822, y + 16, f"GPIO{g:<2}  seg {i+1}", 11, mono=True)
        s += arrow(740, 138, 806, y + 12, ACC, width=1.1, head="ay")

    s += txt(40, 336, "Why not the obvious approaches", 13.5, weight="700")
    rows = [("FastLED 3.10.3, 8 controllers",
             "one RMT channel held per controller  ->  \"no free tx channels\", then a panic", RED),
            ("Adafruit NeoPixel, 8 instances",
             "works — re-binds one channel per pin per show — but measured 3 fps at 8 x 73", "#b8860b"),
            ("1 RMT channel + GPIO matrix fan-out",
             "63 fps, identical hardware-timed waveform on every segment", GRN)]
    for i, (a, b, c) in enumerate(rows):
        y = 358 + i * 40
        s += (f"<rect x='40' y='{y}' width='918' height='32' rx='6' fill='{PANE}' "
              f"stroke='{LINE}' stroke-width='1'/>")
        s += (f"<rect x='40' y='{y}' width='5' height='32' rx='2' fill='{c}'/>")
        s += txt(58, y + 21, a, 11.5, weight="600")
        s += txt(330, y + 21, b, 11.5, fill=MUT)
    s += txt(40, 488, "Trade-off: the eight segments are electrically the same signal, so they always show "
                      "the same content — which is exactly what this piece wants.", 11.5, fill=BLK)
    return svg(W, H, s, "RMT channel fan-out across eight GPIOs")


# ---------------------------------------------------------------------------
# 4. Animation, computed from the firmware maths
# ---------------------------------------------------------------------------
GAMMA8 = [int(math.pow(i / 255.0, 2.6) * 255.0 + 0.5) for i in range(256)]
LEDS = 73


def strip_levels(front256, edge=8, hold=255):
    """renderFrontAt() from main.cpp, verbatim integer maths."""
    edge256 = edge * 256
    out = []
    for i in range(LEDS):
        pos256 = i * 256
        if front256 <= pos256:
            frac = 0
        elif (front256 - pos256) >= edge256:
            frac = 255
        else:
            frac = ((front256 - pos256) * 255) // edge256
        out.append((GAMMA8[frac] * hold) // 255)
    return out


def breathe_wave(phase8):
    """breatheWave() from main.cpp."""
    tri = phase8 * 2 if phase8 < 128 else (255 - phase8) * 2
    tri = min(tri, 255)
    t = tri
    return (t * t * (765 - 2 * t)) // (255 * 255)


def animation():
    W, H = 1000, 620
    s = defs({"a": LINE, "ay": ACC})
    s += txt(28, 34, "Animation", 17, weight="700")
    s += txt(28, 54, "Pixel levels below are computed with the firmware's own integer maths "
                     "(edge = 8 LEDs, gamma 2.6)", 12.5, fill=MUT)

    # --- phase machine
    ph = [("FILL", "front sweeps 0 -> end", ACC), ("BREATHE", "hold, floor..100%", GRN),
          ("EMPTY", "fill played backwards", BLU), ("OFF", "dark", MUT)]
    for i, (name, sub, c) in enumerate(ph):
        x = 40 + i * 240
        s += (f"<rect x='{x}' y='84' width='196' height='54' rx='8' fill='{BG}' "
              f"stroke='{c}' stroke-width='1.8'/>")
        s += txt(x + 98, 108, name, 13, anchor="middle", weight="700", mono=True)
        s += txt(x + 98, 126, sub, 10.5, anchor="middle", fill=MUT)
        if i < 3:
            s += arrow(x + 198, 111, x + 238, 111, LINE, width=1.4)
    s += txt(276, 76, "fill complete", 10, anchor="middle", fill=MUT)
    s += txt(516, 76, "power off", 10, anchor="middle", fill=MUT)
    s += txt(756, 76, "sweep complete", 10, anchor="middle", fill=MUT)
    s += (f"<path d='M 916 138 C 916 170, 40 170, 40 140' fill='none' stroke='{LINE}' "
          f"stroke-width='1.4' stroke-dasharray='4 4' marker-end='url(#a)'/>")
    s += txt(478, 172, "power on", 10.5, anchor="middle", fill=MUT)

    # --- fill snapshots
    s += txt(40, 218, "FILL — leading edge travelling along one segment", 13, weight="700")
    travel = (LEDS + 8) * 256
    for k, frac in enumerate([0.15, 0.35, 0.55, 0.75, 1.0]):
        y = 240 + k * 38
        front = int(travel * frac)
        lv = strip_levels(front)
        s += txt(40, y + 16, f"t = {frac*100:>3.0f}%", 11, mono=True, fill=MUT)
        for i, level in enumerate(lv):
            op = level / 255
            s += (f"<rect x='{116 + i*11.6:.1f}' y='{y}' width='9.6' height='20' rx='2' "
                  f"fill='{ACC}' fill-opacity='{op:.3f}' stroke='{LINE}' "
                  f"stroke-opacity='.18' stroke-width='.6'/>")
    s += txt(116, 438, "LED 1", 10, fill=MUT, mono=True)
    s += txt(963, 438, "LED 73", 10, anchor="end", fill=MUT, mono=True)
    s += txt(540, 456, "EMPTY is this same renderer run backwards — the last LED to light "
                       "is the first to go dark.", 11.5, anchor="middle", fill=MUT)

    # --- breathe curve
    s += txt(40, 500, "BREATHE — smoothstep over a triangle (floor 80%, period 4 s)", 13, weight="700")
    x0, y0, w, h = 116, 516, 700, 78
    s += (f"<rect x='{x0}' y='{y0}' width='{w}' height='{h}' fill='{PANE}' "
          f"stroke='{LINE}' stroke-width='1'/>")
    floor = 80
    pts = []
    for p in range(257):
        phase8 = p % 256
        pct = floor + (100 - floor) * breathe_wave(phase8) / 255
        x = x0 + w * p / 256
        y = y0 + h - (pct - 70) / 30 * h
        pts.append(f"{x:.1f},{y:.1f}")
    s += f"<polyline points='{' '.join(pts)}' fill='none' stroke='{GRN}' stroke-width='2.2'/>"
    s += (f"<line x1='{x0}' y1='{y0}' x2='{x0+w}' y2='{y0}' stroke='{MUT}' "
          f"stroke-width='.8' stroke-dasharray='3 3'/>")
    s += txt(x0 - 8, y0 + 5, "100%", 10.5, anchor="end", fill=MUT, mono=True)
    s += (f"<line x1='{x0}' y1='{y0+h*2/3}' x2='{x0+w}' y2='{y0+h*2/3}' stroke='{MUT}' "
          f"stroke-width='.8' stroke-dasharray='3 3'/>")
    s += txt(x0 - 8, y0 + h*2/3 + 4, "80%", 10.5, anchor="end", fill=MUT, mono=True)
    s += txt(x0 + w/2, y0 + h + 18, "one period (0.5-20 s, settable) — of the power-limited "
                                    "hold level, not of full brightness",
             11, anchor="middle", fill=MUT)
    return svg(W, H, s, "Fill, breathe and withdraw animation")


if __name__ == "__main__":
    for name, fn in [("system-overview", system_overview), ("wiring-schematic", wiring),
                     ("rmt-fanout", fanout), ("animation", animation)]:
        p = OUT / f"{name}.svg"
        p.write_text(fn())
        print(f"{p.name}: {len(p.read_text())} bytes")
