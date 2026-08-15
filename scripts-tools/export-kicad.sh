#!/usr/bin/env bash
# Export the KiCad project into images/schematic/ for the README.
#
# kicad-cli ships inside the KiCad snap as `kicad.kicad-cli`; a distro install
# provides plain `kicad-cli`. Note the snap cannot write outside $HOME, so this
# always writes into the repo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCH="$ROOT/electronics/otherworlds-v2.kicad_sch"
PCB="$ROOT/electronics/otherworlds-v2.kicad_pcb"
OUT="$ROOT/images/schematic"

CLI=$(command -v kicad-cli || command -v kicad.kicad-cli) || {
  echo "kicad-cli not found (try: snap install kicad)" >&2; exit 1; }

mkdir -p "$OUT"

"$CLI" sch export svg --no-background-color --exclude-drawing-sheet -o "$OUT" "$SCH"
"$CLI" sch export pdf -o "$OUT/otherworlds-v2.pdf" "$SCH"

"$CLI" pcb export svg --layers F.Cu,F.Silkscreen,F.Mask,Edge.Cuts \
  --page-size-mode 2 --exclude-drawing-sheet -o "$OUT/pcb-front.svg" "$PCB"
"$CLI" pcb export svg --layers B.Cu,B.Silkscreen,Edge.Cuts \
  --page-size-mode 2 --exclude-drawing-sheet --mirror -o "$OUT/pcb-back.svg" "$PCB"

# The 3D render is KiCad's own, committed alongside the project.
cp "$ROOT/electronics/otherworlds-v2.jpg" "$OUT/pcb-3d-render.jpg"

echo "exported to $OUT"
ls -1 "$OUT"
