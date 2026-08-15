/*
 * LED board - yellow fade-in, breathing hold, and a Wi-Fi control UI
 *
 * Seeed XIAO ESP32C3 driving 8 identical addressable RGB strip segments
 * through a level shifter.
 *
 * Sequence on power-up:
 *   1. FILL    - every segment fades up to the chosen colour, LED by LED from
 *                the first to the last, with a soft leading edge. All 8
 *                segments run this in parallel and in step.
 *   2. BREATHE - once full, brightness breathes between 100% and a settable
 *                floor, forever.
 *
 * The board also raises a Wi-Fi access point with a captive portal, so colour
 * and timing can be changed from a phone with no app and no internet. See
 * AP_SSID / AP_PASSWORD below. Settings persist in NVS.
 *
 * Strip settings come from a WLED configuration confirmed working on this
 * hardware:
 *   LED type     WS281x RGB (800 kHz)
 *   Colour order GBR
 *   Length       73 per segment
 *   Data GPIO    3  (segment 1)
 *
 * Output order follows the board's D1..D8 pins:
 *   seg 1 = D1 = GPIO3     seg 5 = D5 = GPIO7
 *   seg 2 = D2 = GPIO4     seg 6 = D6 = GPIO21
 *   seg 3 = D3 = GPIO5     seg 7 = D7 = GPIO20
 *   seg 4 = D4 = GPIO6     seg 8 = D8 = GPIO8
 *
 * There is no GPIO22 on the ESP32-C3 - its GPIO range is 0..21. D7 is GPIO20.
 *
 * ---------------------------------------------------------------------------
 * HOW 8 OUTPUTS ARE DRIVEN
 * ---------------------------------------------------------------------------
 * The ESP32-C3 has only 2 RMT TX channels:
 *   - FastLED 3.10.3 pins one RMT channel per controller for its lifetime, so
 *     8 strips fails with "no free tx channels" and then panics. Its
 *     README_WORKER_POOL.md describes transparent sharing, but that code is
 *     not actually in the source. Hard limit: 2 strips.
 *   - Adafruit NeoPixel with 8 instances works (it re-binds one channel per
 *     pin per show) but measured only 3 fps at 8 x 73 LEDs.
 *
 * So: ONE RMT channel transmits ONE segment's worth of data, and the GPIO
 * matrix routes that same signal to all 8 pins at once. Identical,
 * hardware-timed waveform on every segment, one transmission per frame.
 * Measured 63 fps. The segments are electrically the same signal, so they can
 * only ever show the same thing - which is what this effect wants.
 */

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>

#include "esp_rom_gpio.h"
#include "driver/gpio.h"
#include "soc/gpio_struct.h"

// ---------------------------------------------------------------------------
// Strip wiring - compile-time, matches the hardware
// ---------------------------------------------------------------------------

#define PIXEL_TYPE (NEO_GBR + NEO_KHZ800)
#define LEDS_PER_STRIP 73
#define NUM_STRIPS 8
#define MASTER_PIN 3

static const uint8_t STRIP_PINS[NUM_STRIPS] = {3, 4, 5, 6, 7, 21, 20, 8};

#define TOTAL_LEDS (LEDS_PER_STRIP * NUM_STRIPS)

static Adafruit_NeoPixel strip(LEDS_PER_STRIP, MASTER_PIN, PIXEL_TYPE);

// ---------------------------------------------------------------------------
// Access point
// ---------------------------------------------------------------------------

// Factory defaults. The live values are editable from the UI and stored in
// NVS; these are what the board falls back to if the stored pair will not
// bring an AP up, so that a bad edit can never lock you out.
static const char *AP_SSID_DEFAULT = "LED-Board";
// WPA2 needs 8-63 characters. Empty means an open network.
static const char *AP_PASS_DEFAULT = "ledboard";

static String apSsid = AP_SSID_DEFAULT;
static String apPass = AP_PASS_DEFAULT;

// Set when the UI changes credentials: the HTTP response is sent first, then
// the AP restarts a moment later, so the browser is not cut off mid-reply.
static uint32_t apRestartAtMs = 0;

// Fixed AP address. 4.3.2.1 is memorable and is what WLED uses.
static const IPAddress AP_IP(4, 3, 2, 1);
static const IPAddress AP_MASK(255, 255, 255, 0);

static DNSServer dnsServer;
static WebServer server(80);
static Preferences prefs;

// ---------------------------------------------------------------------------
// Runtime settings - all changeable from the UI, all persisted to NVS
// ---------------------------------------------------------------------------

struct Settings {
  bool on;                     // lights on/off, animated in and out
  uint8_t r, g, b;             // target colour at full brightness
  uint32_t breathePeriodMs;    // one full 100% -> floor -> 100% cycle
  uint8_t breatheMinPercent;   // floor of the breath
  uint32_t fillDurationMs;     // first LED to last; also the withdraw time
  uint16_t fillEdgeLeds;       // softness of the fill's leading edge
  uint32_t powerBudgetMa;      // see the power note below
};

// Defaults: the bright yellow this started as.
static Settings cfg = {
    .on = true,
    .r = 255,
    .g = 255,
    .b = 0,
    .breathePeriodMs = 4000,
    .breatheMinPercent = 80,
    .fillDurationMs = 4000,
    .fillEdgeLeds = 8,
    .powerBudgetMa = 3000,
};

// ---------------------------------------------------------------------------
// POWER
// ---------------------------------------------------------------------------
//
// 584 LEDs. A colour lighting two channels (yellow, cyan, magenta) costs
// roughly twice a single-channel colour; white costs three times. Full-
// brightness yellow across all segments is an estimated ~24 A at 5 V.
//
// Adafruit NeoPixel has no power management, so the limiter below finds the
// brightest scaling of the chosen colour that fits powerBudgetMa. SET THAT TO
// WHAT THE PSU ACTUALLY DELIVERS - it is now editable from the web UI, which
// makes it easy to set optimistically. It is an estimate, not a measurement.
static const uint32_t MA_PER_CHANNEL_FULL = 20;  // one channel, full, per LED
static const uint32_t MA_PER_LED_IDLE = 1;       // controller IC idle draw

static const uint16_t FRAME_INTERVAL_MS = 16;

// ---------------------------------------------------------------------------

// FILL and EMPTY share one renderer: EMPTY is literally the fill animation
// played backwards, so the LEDs withdraw in exactly the reverse order they
// arrived - the last LED to light is the first to go dark.
enum Phase { PHASE_FILL, PHASE_BREATHE, PHASE_EMPTY, PHASE_OFF };

static Phase phase = PHASE_FILL;
static uint32_t phaseStartMs = 0;
static uint32_t lastFrameMs = 0;
static uint32_t lastReportMs = 0;
static uint32_t frameCount = 0;
static uint32_t measuredFps = 0;
static uint8_t holdLevel = 255;
static uint8_t currentLevel = 0;

// --- persistence ------------------------------------------------------------

static void loadSettings() {
  // Opened read-WRITE rather than read-only: on a board that has never saved,
  // a read-only open of a missing namespace logs a scary "nvs_open failed:
  // NOT_FOUND". Read-write creates it quietly and the getters still fall back
  // to the defaults passed in.
  prefs.begin("ledboard", false);
  cfg.on = prefs.getBool("on", cfg.on);
  // isKey() guards keep Preferences from logging "nvs_get_str ... NOT_FOUND"
  // on a board that has not stored credentials yet. The defaults already hold.
  if (prefs.isKey("ssid")) {
    apSsid = prefs.getString("ssid", apSsid);
  }
  if (prefs.isKey("pass")) {
    apPass = prefs.getString("pass", apPass);
  }
  cfg.r = prefs.getUChar("r", cfg.r);
  cfg.g = prefs.getUChar("g", cfg.g);
  cfg.b = prefs.getUChar("b", cfg.b);
  cfg.breathePeriodMs = prefs.getULong("bp", cfg.breathePeriodMs);
  cfg.breatheMinPercent = prefs.getUChar("bm", cfg.breatheMinPercent);
  cfg.fillDurationMs = prefs.getULong("fd", cfg.fillDurationMs);
  cfg.fillEdgeLeds = prefs.getUShort("fe", cfg.fillEdgeLeds);
  cfg.powerBudgetMa = prefs.getULong("pb", cfg.powerBudgetMa);
  prefs.end();
}

static void saveSettings() {
  prefs.begin("ledboard", false);
  prefs.putBool("on", cfg.on);
  prefs.putUChar("r", cfg.r);
  prefs.putUChar("g", cfg.g);
  prefs.putUChar("b", cfg.b);
  prefs.putULong("bp", cfg.breathePeriodMs);
  prefs.putUChar("bm", cfg.breatheMinPercent);
  prefs.putULong("fd", cfg.fillDurationMs);
  prefs.putUShort("fe", cfg.fillEdgeLeds);
  prefs.putULong("pb", cfg.powerBudgetMa);
  prefs.end();
}

// --- power ------------------------------------------------------------------

static uint32_t estimateMilliamps(uint8_t r, uint8_t g, uint8_t b) {
  const uint32_t sum = (uint32_t)r + g + b;
  const uint32_t perLed = (MA_PER_CHANNEL_FULL * sum) / 255 + MA_PER_LED_IDLE;
  return perLed * (uint32_t)TOTAL_LEDS;
}

static uint32_t estimateAtLevel(uint8_t level) {
  return estimateMilliamps((uint8_t)(((uint16_t)cfg.r * level) / 255),
                           (uint8_t)(((uint16_t)cfg.g * level) / 255),
                           (uint8_t)(((uint16_t)cfg.b * level) / 255));
}

static uint8_t computeHoldLevel() {
  for (uint16_t level = 255; level > 0; level--) {
    if (estimateAtLevel((uint8_t)level) <= cfg.powerBudgetMa) {
      return (uint8_t)level;
    }
  }
  return 0;
}

static uint32_t colorAt(uint8_t level) {
  return strip.Color((uint8_t)(((uint16_t)cfg.r * level) / 255),
                     (uint8_t)(((uint16_t)cfg.g * level) / 255),
                     (uint8_t)(((uint16_t)cfg.b * level) / 255));
}

// --- rendering --------------------------------------------------------------

// Smoothstep 3t^2 - 2t^3 over an 8-bit triangle. Eases at both ends, which is
// what makes the breath read as breathing rather than a sawtooth.
static uint8_t breatheWave(uint8_t phase8) {
  uint16_t tri = (phase8 < 128) ? (uint16_t)phase8 * 2 : (uint16_t)(255 - phase8) * 2;
  if (tri > 255) {
    tri = 255;
  }
  const uint32_t t = tri;
  return (uint8_t)((t * t * (765 - 2 * t)) / (255UL * 255UL));
}

static uint32_t fillTravel256() {
  const uint16_t edge = cfg.fillEdgeLeds ? cfg.fillEdgeLeds : 1;
  // The front travels past the end of the strip by `edge` so the last LED
  // reaches full exactly as the phase ends, rather than being cut off
  // mid-fade.
  return (uint32_t)(LEDS_PER_STRIP + edge) * 256;
}

// Paint the strip for a given leading-edge position, in 1/256ths of an LED.
// Everything behind the front is at holdLevel, everything ahead is dark, and
// the `edge` LEDs around it are the soft gradient.
static void renderFrontAt(uint32_t front256) {
  const uint16_t edge = cfg.fillEdgeLeds ? cfg.fillEdgeLeds : 1;
  const uint32_t edge256 = (uint32_t)edge * 256;

  for (uint16_t i = 0; i < LEDS_PER_STRIP; i++) {
    const uint32_t pos256 = (uint32_t)i * 256;
    uint8_t frac;
    if (front256 <= pos256) {
      frac = 0;
    } else if ((front256 - pos256) >= edge256) {
      frac = 255;
    } else {
      frac = (uint8_t)(((front256 - pos256) * 255) / edge256);
    }
    // Gamma-correct the fade so it ramps evenly to the eye instead of
    // spending most of its apparent brightness in the first few percent.
    const uint8_t level =
        (uint8_t)(((uint16_t)Adafruit_NeoPixel::gamma8(frac) * holdLevel) / 255);
    strip.setPixelColor(i, colorAt(level));
  }
}

// One frame of the fill (forward) or the withdraw (reverse). Returns true
// once the phase has run its course.
static bool renderSweep(uint32_t elapsed, bool reverse) {
  const uint32_t duration = cfg.fillDurationMs ? cfg.fillDurationMs : 1;
  const bool done = elapsed >= duration;
  if (done) {
    elapsed = duration;
  }

  const uint32_t travel256 = fillTravel256();
  // Reverse simply runs the front from the far end back to zero, which
  // extinguishes the last LED first and the first LED last.
  const uint32_t t = reverse ? (duration - elapsed) : elapsed;
  renderFrontAt((uint32_t)((uint64_t)t * travel256 / duration));
  return done;
}

static uint8_t renderBreathe(uint32_t now) {
  const uint32_t period = cfg.breathePeriodMs ? cfg.breathePeriodMs : 1;
  const uint8_t phase8 = (uint8_t)(((now % period) * 256UL) / period);
  const uint8_t w = breatheWave(phase8);

  const uint32_t minPct = cfg.breatheMinPercent > 100 ? 100 : cfg.breatheMinPercent;
  const uint32_t span = 100 - minPct;
  const uint32_t percent = minPct + (span * w) / 255;
  const uint8_t level = (uint8_t)((holdLevel * percent) / 100);

  strip.fill(colorAt(level));
  return level;
}

// `lower` gives the UI-facing name, otherwise a padded label for serial.
static const char *phaseLabel(bool lower) {
  switch (phase) {
    case PHASE_FILL:    return lower ? "filling"  : "FILL   ";
    case PHASE_EMPTY:   return lower ? "emptying" : "EMPTY  ";
    case PHASE_OFF:     return lower ? "off"      : "OFF    ";
    case PHASE_BREATHE:
    default:            return lower ? "breathing" : "BREATHE";
  }
}

static void restartFill() {
  phase = PHASE_FILL;
  phaseStartMs = millis();
}

// Turn the lights on or off, animating in or out. If a sweep is already
// running, the new one picks up at the matching front position instead of
// snapping - so hitting off halfway through the fill withdraws from where it
// actually got to.
static void setPower(bool on) {
  if (on == cfg.on && phase != PHASE_OFF) {
    return;
  }
  const uint32_t now = millis();
  const uint32_t duration = cfg.fillDurationMs ? cfg.fillDurationMs : 1;

  // Both sweeps use the same front position, so mirroring the elapsed time
  // (e' = duration - e) makes the hand-off seamless in either direction.
  uint32_t elapsedIn = 0;
  if (phase == PHASE_FILL || phase == PHASE_EMPTY) {
    const uint32_t e = now - phaseStartMs;
    elapsedIn = duration - (e > duration ? duration : e);
  }

  cfg.on = on;
  phase = on ? PHASE_FILL : PHASE_EMPTY;
  phaseStartMs = now - elapsedIn;
}

// --- GPIO matrix fan-out ----------------------------------------------------

static bool fanOutDataSignal() {
  const uint32_t sig = GPIO.func_out_sel_cfg[MASTER_PIN].func_sel;

  // 128 is the matrix's "plain GPIO output" escape value; at or above it no
  // peripheral drives the pin, so there is nothing to copy.
  if (sig >= 128) {
    Serial.printf("  FAN-OUT FAILED: GPIO%u has no peripheral signal (func_sel=%u)\n",
                  (unsigned)MASTER_PIN, (unsigned)sig);
    return false;
  }

  Serial.printf("  RMT signal %u on GPIO%u -> mirrored to:", (unsigned)sig,
                (unsigned)MASTER_PIN);
  for (uint8_t i = 0; i < NUM_STRIPS; i++) {
    const uint8_t pin = STRIP_PINS[i];
    if (pin == MASTER_PIN) {
      continue;
    }
    gpio_reset_pin((gpio_num_t)pin);
    gpio_set_direction((gpio_num_t)pin, GPIO_MODE_OUTPUT);
    esp_rom_gpio_connect_out_signal((gpio_num_t)pin, sig, false, false);
    Serial.printf(" GPIO%u", (unsigned)pin);
  }
  Serial.println();
  return true;
}

// --- access point -----------------------------------------------------------

// SSID must be 1-32 chars. Password must be empty (open network) or 8-63
// chars - a 1-7 char password is accepted by nothing and would leave the
// board with no AP at all, so it is rejected before it can be stored.
static bool apCredsValid(const String &ssid, const String &pass) {
  if (ssid.length() < 1 || ssid.length() > 32) {
    return false;
  }
  if (pass.length() != 0 && (pass.length() < 8 || pass.length() > 63)) {
    return false;
  }
  return true;
}

static bool startAp(const String &ssid, const String &pass) {
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_AP);
  WiFi.softAPConfig(AP_IP, AP_IP, AP_MASK);
  return (pass.length() >= 8) ? WiFi.softAP(ssid.c_str(), pass.c_str())
                              : WiFi.softAP(ssid.c_str());
}

// Bring the AP up, falling back to the factory pair if the stored one fails.
// Without this a bad SSID/password in NVS would mean reflashing over USB to
// get back in.
static bool startApWithFallback() {
  if (apCredsValid(apSsid, apPass) && startAp(apSsid, apPass)) {
    return true;
  }
  Serial.printf("AP \"%s\" failed to start - falling back to defaults\n",
                apSsid.c_str());
  apSsid = AP_SSID_DEFAULT;
  apPass = AP_PASS_DEFAULT;
  return startAp(apSsid, apPass);
}

// ---------------------------------------------------------------------------
// Web UI - one self-contained page. Nothing external is reachable on an AP,
// so all CSS and JS are inline and the colour wheel is drawn on a canvas.
// ---------------------------------------------------------------------------

static const char INDEX_HTML[] PROGMEM = R"HTML(<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>LED Board</title>
<style>
:root{--bg:#111318;--card:#1a1d24;--line:#2b3038;--fg:#e8eaed;--mut:#9aa0aa;--acc:#ffc233}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:16px;max-width:520px;margin:0 auto}
h1{font-size:19px;margin:4px 0 2px}
.sub{color:var(--mut);font-size:13px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:0 0 14px}
.wheelwrap{display:flex;gap:16px;align-items:center;flex-wrap:wrap;justify-content:center}
canvas{border-radius:50%;cursor:crosshair;touch-action:none;display:block}
#sw{width:74px;height:74px;border-radius:12px;border:1px solid var(--line);flex:none}
.row{display:flex;align-items:center;gap:10px;margin:12px 0}
.row label{width:64px;color:var(--mut);font-size:13px;flex:none}
input[type=range]{flex:1;accent-color:var(--acc);min-width:0}
input[type=number],input[type=text]{width:78px;background:#0e1015;border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:7px 8px;font:inherit;font-size:14px;flex:none}
.val{width:56px;text-align:right;color:var(--mut);font-variant-numeric:tabular-nums;font-size:13px;flex:none}
button{background:var(--acc);color:#1a1200;border:0;border-radius:9px;padding:11px 14px;font:inherit;font-weight:600;cursor:pointer}
button.sec{background:#252a33;color:var(--fg)}
button.big{width:100%;padding:16px;font-size:16px}
button.big.off{background:#252a33;color:var(--mut)}
.btns{display:flex;gap:9px;flex-wrap:wrap;margin-top:6px}
.note{font-size:12.5px;color:var(--mut);margin-top:12px;line-height:1.45}
.warn{color:#ff9f43}
.err{color:#ff6b6b}
#hex{width:104px;text-transform:uppercase}
#ssid,#pass{width:100%}
.row.stack{flex-direction:column;align-items:stretch;gap:6px}
.row.stack label{width:auto}
</style></head><body>

<h1>LED Board</h1>
<div class="sub">8 segments &times; 73 LEDs &middot; <span id="fps">-</span> fps &middot; <span id="phase">-</span></div>

<div class="card"><button id="pwr" class="big">&nbsp;</button>
<div class="note">Turning off withdraws the LEDs in reverse: the last to light is the first to go dark.</div>
</div>

<div class="card"><h2>Colour</h2>
<div class="wheelwrap">
  <canvas id="wheel" width="200" height="200"></canvas>
  <div id="sw"></div>
</div>
<div class="row"><label>R</label><input type="range" id="rS" min="0" max="255"><span class="val" id="rV">0</span></div>
<div class="row"><label>G</label><input type="range" id="gS" min="0" max="255"><span class="val" id="gV">0</span></div>
<div class="row"><label>B</label><input type="range" id="bS" min="0" max="255"><span class="val" id="bV">0</span></div>
<div class="row"><label>Hex</label><input type="text" id="hex" maxlength="7"><input type="color" id="pick"></div>
</div>

<div class="card"><h2>Breathing</h2>
<div class="row"><label>Period</label><input type="range" id="bpS" min="500" max="20000" step="100"><span class="val" id="bpV">-</span></div>
<div class="row"><label>Floor</label><input type="range" id="bmS" min="0" max="100"><span class="val" id="bmV">-</span></div>
<div class="note">Brightness cycles between the floor and 100% of the held level. A floor of 100% holds steady with no breathing.</div>
</div>

<div class="card"><h2>Start-up fill</h2>
<div class="row"><label>Duration</label><input type="range" id="fdS" min="200" max="20000" step="100"><span class="val" id="fdV">-</span></div>
<div class="row"><label>Edge</label><input type="range" id="feS" min="1" max="40"><span class="val" id="feV">-</span></div>
<div class="btns"><button class="sec" id="replay">Replay fill</button></div>
<div class="note">Edge is how many LEDs the leading fade spans. 1 is a hard wipe.</div>
</div>

<div class="card"><h2>Power</h2>
<div class="row"><label>Budget</label><input type="number" id="pb" min="100" max="40000" step="100"><span class="val">mA</span></div>
<div class="note" id="pwrnote">-</div>
<div class="note warn">This is an estimate from typical WS281x figures, not a measurement. Set it to what your supply actually delivers.</div>
</div>

<div class="card"><h2>Access point</h2>
<div class="row stack"><label>Network name</label><input type="text" id="ssid" maxlength="32"></div>
<div class="row stack"><label>Password</label><input type="text" id="pass" maxlength="63"></div>
<div class="btns"><button class="sec" id="apply">Apply &amp; restart AP</button><span class="val err" id="aperr"></span></div>
<div class="note">Password must be 8&ndash;63 characters, or empty for an open network. Applying restarts the access point, so this device will drop off and you will need to rejoin using the new details.</div>
<div class="note">If a stored pair ever fails to start, the board falls back to <b>LED-Board</b> / <b>ledboard</b> on its own, so a bad edit cannot lock you out.</div>
</div>

<div class="btns"><button id="save">Save to board</button><span class="val" id="saved"></span></div>

<script>
const $=id=>document.getElementById(id);
let S={r:255,g:255,b:0,bp:4000,bm:80,fd:4000,fe:8,pb:3000},tmr=null;

// --- colour wheel (HSV: angle = hue, radius = saturation) ---
const cv=$('wheel'),cx=cv.getContext('2d'),R=100;
(function draw(){
  const img=cx.createImageData(200,200),d=img.data;
  for(let y=0;y<200;y++)for(let x=0;x<200;x++){
    const dx=x-R,dy=y-R,dist=Math.sqrt(dx*dx+dy*dy),i=(y*200+x)*4;
    if(dist>R){d[i+3]=0;continue}
    let h=Math.atan2(dy,dx)*180/Math.PI;if(h<0)h+=360;
    const c=hsv2rgb(h,Math.min(dist/R,1),1);
    d[i]=c[0];d[i+1]=c[1];d[i+2]=c[2];d[i+3]=255;
  }
  cx.putImageData(img,0,0);
})();
function hsv2rgb(h,s,v){
  const c=v*s,x=c*(1-Math.abs((h/60)%2-1)),m=v-c;let r,g,b;
  if(h<60){r=c;g=x;b=0}else if(h<120){r=x;g=c;b=0}else if(h<180){r=0;g=c;b=x}
  else if(h<240){r=0;g=x;b=c}else if(h<300){r=x;g=0;b=c}else{r=c;g=0;b=x}
  return [Math.round((r+m)*255),Math.round((g+m)*255),Math.round((b+m)*255)];
}
function pickAt(e){
  const rect=cv.getBoundingClientRect();
  const t=e.touches?e.touches[0]:e;
  const x=(t.clientX-rect.left)*(200/rect.width)-R, y=(t.clientY-rect.top)*(200/rect.height)-R;
  const dist=Math.sqrt(x*x+y*y);
  let h=Math.atan2(y,x)*180/Math.PI;if(h<0)h+=360;
  const c=hsv2rgb(h,Math.min(dist/R,1),1);
  S.r=c[0];S.g=c[1];S.b=c[2];sync();push();
}
let drag=false;
cv.addEventListener('pointerdown',e=>{drag=true;cv.setPointerCapture(e.pointerId);pickAt(e)});
cv.addEventListener('pointermove',e=>{if(drag)pickAt(e)});
cv.addEventListener('pointerup',()=>drag=false);

// --- helpers ---
const hx=n=>n.toString(16).padStart(2,'0');
function sync(){
  $('rS').value=S.r;$('gS').value=S.g;$('bS').value=S.b;
  $('rV').textContent=S.r;$('gV').textContent=S.g;$('bV').textContent=S.b;
  const h='#'+hx(S.r)+hx(S.g)+hx(S.b);
  $('hex').value=h.toUpperCase();$('pick').value=h;$('sw').style.background=h;
  $('bpS').value=S.bp;$('bpV').textContent=(S.bp/1000).toFixed(1)+'s';
  $('bmS').value=S.bm;$('bmV').textContent=S.bm+'%';
  $('fdS').value=S.fd;$('fdV').textContent=(S.fd/1000).toFixed(1)+'s';
  $('feS').value=S.fe;$('feV').textContent=S.fe;
  $('pb').value=S.pb;
  if(document.activeElement!==$('ssid'))$('ssid').value=S.ssid||'';
  if(document.activeElement!==$('pass'))$('pass').value=S.pass||'';
  paintPwr();
}
function push(){
  clearTimeout(tmr);
  tmr=setTimeout(()=>{
    const q=`r=${S.r}&g=${S.g}&b=${S.b}&bp=${S.bp}&bm=${S.bm}&fd=${S.fd}&fe=${S.fe}&pb=${S.pb}`;
    fetch('/api/set?'+q).then(r=>r.json()).then(apply).catch(()=>{});
  },60);
}
function paintPwr(){
  const b=$('pwr');
  b.textContent=S.on?'Turn off':'Turn on';
  b.className='big'+(S.on?'':' off');
}
function apply(j){
  $('fps').textContent=j.fps;
  $('phase').textContent=j.phase;
  S.on=j.on;paintPwr();
  $('pwrnote').textContent=`Holding at ${j.hold}/255 (${Math.round(j.hold/2.55)}% of full) ≈ ${j.ma} mA. Full brightness would need ${j.maFull} mA.`;
}
$('pwr').addEventListener('click',()=>{
  S.on=!S.on;paintPwr();
  fetch('/api/power?on='+(S.on?1:0)).then(r=>r.json()).then(apply).catch(()=>{});
});
$('apply').addEventListener('click',()=>{
  const q='ssid='+encodeURIComponent($('ssid').value)+'&pass='+encodeURIComponent($('pass').value);
  $('aperr').textContent='';
  fetch('/api/ap?'+q).then(r=>r.json().then(j=>({ok:r.ok,j}))).then(({ok,j})=>{
    $('aperr').textContent=ok?'restarting…':(j.error||'invalid');
  }).catch(()=>{$('aperr').textContent='no reply'});
});
['r','g','b'].forEach(k=>$(k+'S').addEventListener('input',e=>{S[k]=+e.target.value;sync();push()}));
$('hex').addEventListener('change',e=>{
  const m=/^#?([0-9a-f]{6})$/i.exec(e.target.value.trim());
  if(!m)return sync();
  const v=parseInt(m[1],16);S.r=v>>16&255;S.g=v>>8&255;S.b=v&255;sync();push();
});
$('pick').addEventListener('input',e=>{
  const v=parseInt(e.target.value.slice(1),16);S.r=v>>16&255;S.g=v>>8&255;S.b=v&255;sync();push();
});
[['bpS','bp'],['bmS','bm'],['fdS','fd'],['feS','fe']].forEach(([id,k])=>
  $(id).addEventListener('input',e=>{S[k]=+e.target.value;sync();push()}));
$('pb').addEventListener('change',e=>{S.pb=+e.target.value||3000;sync();push()});
$('replay').addEventListener('click',()=>fetch('/api/fill'));
$('save').addEventListener('click',()=>fetch('/api/save').then(()=>{
  $('saved').textContent='saved';setTimeout(()=>$('saved').textContent='',1800);
}));

fetch('/api/state').then(r=>r.json()).then(j=>{S=j;sync();apply(j)});
setInterval(()=>fetch('/api/state').then(r=>r.json()).then(apply).catch(()=>{}),2000);
</script></body></html>)HTML";

// Minimal JSON string escaping - enough for SSIDs and passwords, which can
// legitimately contain quotes and backslashes.
static String jsonEscape(const String &s) {
  String out;
  out.reserve(s.length() + 8);
  for (size_t i = 0; i < s.length(); i++) {
    const char c = s[i];
    if (c == '"' || c == '\\') {
      out += '\\';
      out += c;
    } else if ((uint8_t)c < 0x20) {
      out += ' ';
    } else {
      out += c;
    }
  }
  return out;
}

static String stateJson() {
  String j = "{";
  j += "\"on\":" + String(cfg.on ? "true" : "false");
  j += ",\"ssid\":\"" + jsonEscape(apSsid) + "\"";
  j += ",\"pass\":\"" + jsonEscape(apPass) + "\"";
  j += ",\"r\":" + String(cfg.r);
  j += ",\"g\":" + String(cfg.g);
  j += ",\"b\":" + String(cfg.b);
  j += ",\"bp\":" + String(cfg.breathePeriodMs);
  j += ",\"bm\":" + String(cfg.breatheMinPercent);
  j += ",\"fd\":" + String(cfg.fillDurationMs);
  j += ",\"fe\":" + String(cfg.fillEdgeLeds);
  j += ",\"pb\":" + String(cfg.powerBudgetMa);
  j += ",\"hold\":" + String(holdLevel);
  j += ",\"ma\":" + String(estimateAtLevel(holdLevel));
  j += ",\"maFull\":" + String(estimateAtLevel(255));
  j += ",\"fps\":" + String(measuredFps);
  j += ",\"phase\":\"" + String(phaseLabel(true)) + "\"";
  j += "}";
  return j;
}

static uint32_t argOr(const char *name, uint32_t fallback) {
  return server.hasArg(name) ? (uint32_t)server.arg(name).toInt() : fallback;
}

static uint32_t clampU32(uint32_t v, uint32_t lo, uint32_t hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

static void handleSet() {
  cfg.r = (uint8_t)clampU32(argOr("r", cfg.r), 0, 255);
  cfg.g = (uint8_t)clampU32(argOr("g", cfg.g), 0, 255);
  cfg.b = (uint8_t)clampU32(argOr("b", cfg.b), 0, 255);
  cfg.breathePeriodMs = clampU32(argOr("bp", cfg.breathePeriodMs), 200, 120000);
  cfg.breatheMinPercent = (uint8_t)clampU32(argOr("bm", cfg.breatheMinPercent), 0, 100);
  cfg.fillDurationMs = clampU32(argOr("fd", cfg.fillDurationMs), 100, 120000);
  cfg.fillEdgeLeds = (uint16_t)clampU32(argOr("fe", cfg.fillEdgeLeds), 1, LEDS_PER_STRIP);
  cfg.powerBudgetMa = clampU32(argOr("pb", cfg.powerBudgetMa), 100, 40000);

  holdLevel = computeHoldLevel();
  server.send(200, "application/json", stateJson());
}

static void setupWeb() {
  server.on("/", []() {
    server.sendHeader("Cache-Control", "no-store");
    server.send_P(200, "text/html", INDEX_HTML);
  });
  server.on("/api/state", []() { server.send(200, "application/json", stateJson()); });
  server.on("/api/set", handleSet);
  server.on("/api/power", []() {
    if (server.hasArg("on")) {
      setPower(server.arg("on").toInt() != 0);
    }
    server.send(200, "application/json", stateJson());
  });
  server.on("/api/ap", []() {
    const String ssid = server.arg("ssid");
    const String pass = server.arg("pass");
    if (!apCredsValid(ssid, pass)) {
      server.send(400, "application/json",
                  "{\"error\":\"SSID 1-32 chars; password empty or 8-63 chars\"}");
      return;
    }
    apSsid = ssid;
    apPass = pass;
    prefs.begin("ledboard", false);
    prefs.putString("ssid", apSsid);
    prefs.putString("pass", apPass);
    prefs.end();
    // Reply first, restart the radio a moment later - otherwise the client is
    // dropped before it ever sees the response.
    server.send(200, "application/json", stateJson());
    apRestartAtMs = millis() + 400;
  });
  server.on("/api/fill", []() {
    restartFill();
    server.send(200, "application/json", stateJson());
  });
  server.on("/api/save", []() {
    saveSettings();
    server.send(200, "application/json", stateJson());
  });

  // Captive portal: send every unknown host/path to the UI so phones pop the
  // "sign in to network" sheet instead of silently deciding there is no
  // internet. Covers the Android/iOS/Windows probe URLs by catching all.
  server.onNotFound([]() {
    server.sendHeader("Location", String("http://") + AP_IP.toString() + "/", true);
    server.send(302, "text/plain", "");
  });

  server.begin();
}

// ---------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);

  uint32_t serialWaitStart = millis();
  while (!Serial && (millis() - serialWaitStart) < 2000) {
    delay(10);
  }

  Serial.println();
  Serial.println(F("XIAO ESP32C3 - LED board"));
  Serial.printf("%u segments x %u LEDs = %u total | WS281x 800 kHz, order GBR\n",
                (unsigned)NUM_STRIPS, (unsigned)LEDS_PER_STRIP,
                (unsigned)TOTAL_LEDS);
  Serial.print(F("Pins: "));
  for (uint8_t i = 0; i < NUM_STRIPS; i++) {
    Serial.printf("D%u=GPIO%u ", (unsigned)i + 1, (unsigned)STRIP_PINS[i]);
  }
  Serial.println();

  loadSettings();

  // Bind the RMT channel to MASTER_PIN, then mirror it to the other seven.
  strip.begin();
  strip.clear();
  strip.show();
  fanOutDataSignal();

  holdLevel = computeHoldLevel();
  Serial.printf("Colour %u,%u,%u | budget %u mA -> hold %u/255 (est. %u mA, full %u mA)\n",
                (unsigned)cfg.r, (unsigned)cfg.g, (unsigned)cfg.b,
                (unsigned)cfg.powerBudgetMa, (unsigned)holdLevel,
                (unsigned)estimateAtLevel(holdLevel),
                (unsigned)estimateAtLevel(255));

  // Access point + captive portal.
  if (startApWithFallback()) {
    dnsServer.setErrorReplyCode(DNSReplyCode::NoError);
    dnsServer.start(53, "*", AP_IP);
    setupWeb();
    Serial.printf("AP \"%s\" up -> http://%s/  (password: %s)\n", apSsid.c_str(),
                  AP_IP.toString().c_str(),
                  apPass.length() >= 8 ? apPass.c_str() : "<open>");
  } else {
    Serial.println(F("AP FAILED TO START - LEDs will still run"));
  }

  // Come up in whatever power state was last saved.
  if (cfg.on) {
    Serial.println(F("PHASE: FILL"));
    restartFill();
  } else {
    Serial.println(F("PHASE: OFF (saved state)"));
    phase = PHASE_OFF;
  }
  lastFrameMs = millis();
  lastReportMs = millis();
}

void loop() {
  dnsServer.processNextRequest();
  server.handleClient();

  const uint32_t now = millis();

  // Deferred AP restart, so the HTTP reply got out before the radio drops.
  if (apRestartAtMs && now >= apRestartAtMs) {
    apRestartAtMs = 0;
    Serial.printf("Restarting AP as \"%s\"...\n", apSsid.c_str());
    dnsServer.stop();
    if (startApWithFallback()) {
      dnsServer.start(53, "*", AP_IP);
      Serial.printf("AP \"%s\" up -> http://%s/  (password: %s)\n", apSsid.c_str(),
                    AP_IP.toString().c_str(),
                    apPass.length() >= 8 ? apPass.c_str() : "<open>");
    } else {
      Serial.println(F("AP RESTART FAILED"));
    }
  }

  if ((now - lastFrameMs) < FRAME_INTERVAL_MS) {
    return;
  }
  lastFrameMs = now;

  switch (phase) {
    case PHASE_FILL:
      currentLevel = holdLevel;
      if (renderSweep(now - phaseStartMs, false)) {
        phase = PHASE_BREATHE;
        phaseStartMs = now;
        Serial.println(F("PHASE: BREATHE"));
      }
      break;

    case PHASE_EMPTY:
      currentLevel = holdLevel;
      if (renderSweep(now - phaseStartMs, true)) {
        phase = PHASE_OFF;
        Serial.println(F("PHASE: OFF"));
      }
      break;

    case PHASE_OFF:
      currentLevel = 0;
      strip.clear();
      break;

    case PHASE_BREATHE:
    default:
      currentLevel = renderBreathe(now);
      break;
  }

  strip.show();
  frameCount++;

  if ((now - lastReportMs) >= 2000) {
    measuredFps = frameCount / 2;
    Serial.printf("[%8lu ms] %s | level %3u/255 | %lu fps | est. %u mA | clients %u\n",
                  (unsigned long)now, phaseLabel(false),
                  (unsigned)currentLevel, (unsigned long)measuredFps,
                  (unsigned)estimateAtLevel(currentLevel),
                  (unsigned)WiFi.softAPgetStationNum());
    lastReportMs = now;
    frameCount = 0;
  }
}
