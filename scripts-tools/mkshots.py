#!/usr/bin/env python3
"""Render the ESP32-served web UI in headless Chrome and capture screenshots.

The page is lifted verbatim out of firmware/src/main.cpp; only window.fetch is
replaced by a shim that reimplements the firmware's /api/* handlers (including
the integer power maths) so the UI populates exactly as it does on the board.
"""
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN = ROOT / "firmware" / "src" / "main.cpp"
HERE = pathlib.Path(__file__).parent / ".build"
OUT = ROOT / "images" / "webui"
HERE.mkdir(exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

# the page is stored as a raw string literal in the firmware
RAW = re.search(r'R"HTML\((.*?)\)HTML"', MAIN.read_text(), re.S).group(1)

CHROME = "google-chrome"

# --- firmware-equivalent mock backend --------------------------------------
MOCK = r"""
<script>
// ---- stand-in for the ESP32 HTTP API (mirrors main.cpp exactly) ----
const TOTAL_LEDS = 584, MA_PER_CHANNEL_FULL = 20, MA_PER_LED_IDLE = 1;
const DEV = Object.assign({
  on: true, ssid: 'LED-Board', pass: 'ledboard',
  r: 255, g: 255, b: 0, bp: 4000, bm: 80, fd: 4000, fe: 8, pb: 3000,
  fps: 63, phase: 'breathing'
}, __INIT__);
const clamp = (v, lo, hi) => v < lo ? lo : (v > hi ? hi : v);
function estimateMa(r, g, b) {
  const perLed = Math.floor(MA_PER_CHANNEL_FULL * (r + g + b) / 255) + MA_PER_LED_IDLE;
  return perLed * TOTAL_LEDS;
}
const atLevel = L => estimateMa(Math.floor(DEV.r * L / 255),
                                Math.floor(DEV.g * L / 255),
                                Math.floor(DEV.b * L / 255));
function hold() {
  for (let L = 255; L > 0; L--) if (atLevel(L) <= DEV.pb) return L;
  return 0;
}
function state() {
  const h = hold();
  return Object.assign({}, DEV, { hold: h, ma: atLevel(h), maFull: atLevel(255) });
}
window.fetch = (url) => {
  const u = new URL(url, 'http://4.3.2.1/');
  const q = u.searchParams;
  if (u.pathname === '/api/set') {
    const num = (k, lo, hi) => { if (q.has(k)) DEV[k] = clamp(+q.get(k), lo, hi); };
    num('r', 0, 255); num('g', 0, 255); num('b', 0, 255);
    num('bp', 200, 120000); num('bm', 0, 100);
    num('fd', 100, 120000); num('fe', 1, 73); num('pb', 100, 40000);
  } else if (u.pathname === '/api/power') {
    DEV.on = q.get('on') !== '0';
    DEV.phase = DEV.on ? 'filling' : 'emptying';
  } else if (u.pathname === '/api/fill') {
    DEV.phase = 'filling';
  }
  return Promise.resolve({ ok: true, json: () => Promise.resolve(state()) });
};
</script>
"""

# marker drawn on the colour wheel so the screenshot reads as "a colour is
# selected" -- the firmware page has no marker, this is added for the capture
# only when MARK is requested.
MARK = r"""
<script>
window.addEventListener('load', () => {
  setTimeout(() => {
    const c = document.getElementById('wheel'), x = c.getContext('2d');
    const r = __R__, g = __G__, b = __B__, R = 100;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    let h = 0;
    if (d) {
      if (mx === r) h = 60 * (((g - b) / d) % 6);
      else if (mx === g) h = 60 * ((b - r) / d + 2);
      else h = 60 * ((r - g) / d + 4);
    }
    if (h < 0) h += 360;
    const s = mx ? d / mx : 0, a = h * Math.PI / 180;
    // keep a fully saturated pick just inside the rim so the ring reads as a
    // handle rather than as a clipped artefact
    const rad = Math.min(s * R, R - 9);
    const px = R + Math.cos(a) * rad, py = R + Math.sin(a) * rad;
    x.beginPath(); x.arc(px, py, 8, 0, 6.29);
    x.strokeStyle = '#fff'; x.lineWidth = 3; x.stroke();
    x.beginPath(); x.arc(px, py, 8, 0, 6.29);
    x.strokeStyle = 'rgba(0,0,0,.55)'; x.lineWidth = 1; x.stroke();
  }, 250);
});
</script>
"""

MEASURE = r"""
<script>
window.addEventListener('load', () => setTimeout(() => {
  const cards = [...document.querySelectorAll('.card')].map(el => {
    const r = el.getBoundingClientRect();
    const h2 = el.querySelector('h2');
    return { name: h2 ? h2.textContent.trim() : 'power-button',
             x: Math.round(r.x), y: Math.round(r.y + scrollY),
             w: Math.round(r.width), h: Math.round(r.height) };
  });
  document.title = 'M' + JSON.stringify(
    { height: Math.ceil(document.body.scrollHeight), cards });
}, 600));
</script>
"""


def build(init, mark=None, measure=False):
    inject = MOCK.replace("__INIT__", json.dumps(init))
    if mark:
        inject += (MARK.replace("__R__", str(mark[0]))
                       .replace("__G__", str(mark[1]))
                       .replace("__B__", str(mark[2])))
    if measure:
        inject += MEASURE
    # the shim must exist before the page's own <script> runs
    return RAW.replace("<script>\nconst $=id=>", inject + "<script>\nconst $=id=>", 1)


def chrome(args):
    return subprocess.run([CHROME, "--headless=new", "--no-sandbox",
                           "--disable-gpu", "--hide-scrollbars",
                           "--force-device-scale-factor=2",
                           "--virtual-time-budget=3000"] + args,
                          capture_output=True, text=True)


def measure(html_path, width):
    r = chrome(["--dump-dom", f"--window-size={width},1200",
                f"file://{html_path}"])
    m = re.search(r"<title>M(\{.*?\})</title>", r.stdout, re.S)
    if not m:
        sys.exit("measure failed:\n" + r.stdout[:800] + r.stderr[:800])
    return json.loads(m.group(1))


def trim(png, pad=16, scale=2):
    """Chrome's --dump-dom pass lays out at its own default width, so its
    scrollHeight is only right for windows wider than the 520 px content box.
    Shoot tall instead and cut the uniform background off the bottom."""
    from PIL import Image
    im = Image.open(png).convert("RGB")
    bg = im.getpixel((2, im.height - 2))
    last = im.height - 1
    while last > 0:
        row = im.crop((0, last, im.width, last + 1)).getcolors(2)
        if row is None or row[0][1] != bg:
            break
        last -= 1
    im.crop((0, 0, im.width, min(im.height, last + 1 + pad * scale))).save(png)
    return last + 1


def shoot(name, init, width=560, mark=None, cards=()):
    src = HERE / f"page-{name}.html"
    src.write_text(build(init, mark=mark, measure=True))
    info = measure(src, width)
    png = OUT / f"{name}.png"
    chrome([f"--screenshot={png}", f"--window-size={width},3200",
            f"file://{src}"])
    trim(png)
    print(f"{png.name}: {width} wide")
    for want in cards:
        for c in info["cards"]:
            if c["name"].lower() == want.lower():
                crop(png, c, OUT / f"{name}-{want.lower().replace(' ', '-')}.png")
    return info


def crop(png, box, dest, scale=2, pad=10):
    from PIL import Image
    im = Image.open(png)
    x = max(0, (box["x"] - pad) * scale)
    y = max(0, (box["y"] - pad) * scale)
    w = min(im.width - x, (box["w"] + 2 * pad) * scale)
    h = min(im.height - y, (box["h"] + 2 * pad) * scale)
    im.crop((x, y, x + w, y + h)).save(dest)
    print(f"  {dest.name}: {w}x{h}")


if __name__ == "__main__":
    # 1. default state as shipped: yellow, 3 A budget, breathing
    shoot("webui-full", {}, mark=(255, 255, 0),
          cards=["power-button", "Colour", "Breathing", "Start-up fill", "Power",
                 "Access point"])
    # 2. lights off -- button flips to "Turn on", phase reports off
    shoot("webui-off", {"on": False, "phase": "off", "fps": 62},
          cards=["power-button"])
    # 3. another colour + a realistic 15 A supply, mid-fill
    shoot("webui-colour", {"r": 0, "g": 128, "b": 255, "pb": 15000,
                           "phase": "filling", "fps": 63, "bm": 55, "bp": 8000},
          mark=(0, 128, 255),
          cards=["Colour", "Power"])
    # 4. phone-width view
    shoot("webui-phone", {}, width=390, mark=(255, 255, 0))
