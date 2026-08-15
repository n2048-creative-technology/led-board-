#!/usr/bin/env python3
"""Crop a KiCad SVG export to its drawing.

kicad-cli plots onto the full sheet, so an A4 export is mostly empty margin and
the drawing renders tiny in a README. Chrome measures the real content box with
getBBox(); this rewrites viewBox/width/height to it, losing nothing.

    python3 scripts-tools/tighten-svg.py images/schematic/*.svg
"""
import json
import pathlib
import re
import subprocess
import sys

PAD_FRACTION = 0.015  # breathing room, as a fraction of the content's long side


def measure(svg_path: pathlib.Path):
    """Return the union bbox of the SVG's drawable content, in user units."""
    html = svg_path.parent / f".{svg_path.stem}.measure.html"
    html.write_text(
        "<body style='margin:0'>" + svg_path.read_text() + """
<script>
window.addEventListener('load', () => setTimeout(() => {
  const svg = document.querySelector('svg');
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const el of svg.querySelectorAll('*')) {
    if (!el.getBBox || !(el instanceof SVGGraphicsElement)) continue;
    let b; try { b = el.getBBox(); } catch (e) { continue }
    if (!b.width && !b.height) continue;
    x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y);
    x1 = Math.max(x1, b.x + b.width); y1 = Math.max(y1, b.y + b.height);
  }
  document.title = 'M' + JSON.stringify({x0, y0, x1, y1});
}, 300));
</script></body>""")
    try:
        r = subprocess.run(
            ["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
             "--virtual-time-budget=3000", "--window-size=1400,1000",
             "--dump-dom", f"file://{html.resolve()}"],
            capture_output=True, text=True)
        m = re.search(r"<title>M(\{.*?\})</title>", r.stdout, re.S)
        return json.loads(m.group(1)) if m else None
    finally:
        html.unlink(missing_ok=True)


def tighten(svg_path: pathlib.Path) -> bool:
    text = svg_path.read_text()
    head = re.search(r"<svg\b[^>]*>", text, re.S)
    if not head or 'viewBox="' not in head.group(0):
        print(f"  {svg_path.name}: no viewBox, skipped")
        return False

    b = measure(svg_path)
    if not b or b["x1"] <= b["x0"]:
        print(f"  {svg_path.name}: could not measure, left as is")
        return False

    pad = max(b["x1"] - b["x0"], b["y1"] - b["y0"]) * PAD_FRACTION
    x, y = b["x0"] - pad, b["y0"] - pad
    w, h = (b["x1"] - b["x0"]) + 2 * pad, (b["y1"] - b["y0"]) + 2 * pad

    # keep the unit suffix (mm) that KiCad puts on width/height
    unit = (re.search(r'width="[\d.]+(\w*)"', head.group(0)) or [None, ""])[1] \
        if re.search(r'width="[\d.]+(\w*)"', head.group(0)) else ""
    new = head.group(0)
    new = re.sub(r'width="[^"]*"', f'width="{w:.4f}{unit}"', new, count=1)
    new = re.sub(r'height="[^"]*"', f'height="{h:.4f}{unit}"', new, count=1)
    new = re.sub(r'viewBox="[^"]*"', f'viewBox="{x:.4f} {y:.4f} {w:.4f} {h:.4f}"',
                 new, count=1)
    svg_path.write_text(text[:head.start()] + new + text[head.end():])
    print(f"  {svg_path.name}: {w:.1f} x {h:.1f}{unit}")
    return True


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        tighten(pathlib.Path(arg))
