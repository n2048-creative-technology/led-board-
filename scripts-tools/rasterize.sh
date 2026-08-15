#!/bin/bash
# accurate SVG -> PNG via Chrome (ImageMagick's internal SVG renderer drops
# fill-opacity and mis-measures text)
for f in "$@"; do
  base="${f%.svg}"
  w=$(grep -o "width='[0-9]*'" "$f" | head -1 | tr -dc 0-9)
  h=$(grep -o "height='[0-9]*'" "$f" | head -1 | tr -dc 0-9)
  cat > "$base.wrap.html" <<HTML
<body style="margin:0;background:#fff"><img src="$(basename "$f")" width="$w" height="$h"></body>
HTML
  google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 --virtual-time-budget=2000 \
    --screenshot="$base.png" --window-size="$w,$h" "file://$PWD/$base.wrap.html" 2>/dev/null
done
