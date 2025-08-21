# beat_trainer.py — Beat Trainer (Merlin Launcher Compatible)
#
# Interactive rhythm-training game for Adafruit MacroPad RP2040
# (CircuitPython 9.x). Players tap MacroPad keys in time with
# visual and audio beats. Supports practice and scored modes,
# pattern selector, difficulty levels, and automatic 32-bar song
# length with per-beat judging.
#
# Author: Iain Bennett — 2025
#
# ---------------------------------------------------------------------
# Hardware:
# - Adafruit MacroPad RP2040 (12 keys, rotary encoder, 128×64 mono OLED)
#
# Launcher Compatibility:
# - Exits on encoder single-press (no double-press handling required).
# - K0–K11 key events forwarded from launcher.
#
# Key Mapping (settings modes: ATTRACT, PAUSE, RESULTS):
# - K0 / K2 : BPM – / +
# - K1      : Mode toggle (practice ↔ scored)
# - K3 / K5 : Difficulty – / +
# - K6 / K8 : Pattern – / +
# - K11     : Start / Resume (green) or Pause (red in PLAY)
#
# Key Mapping (play mode: PLAY):
# - K0–K10  : Tap inputs
# - K11     : Pause
#
# Game Flow:
# - ATTRACT → Start (K11) → PLAY → automatic end after 32 bars → RESULTS
# - Difficulty adjusts hit-window tolerance.
# - Patterns selectable (Quarter, Half, Whole, Offbeats, Shuffle, Clave 3-2, Clave 2-3).
# - LEDs provide beat cues, legends in settings, and tap-feedback colors.
# - OLED shows mode, BPM, pattern, difficulty, combo, and score.
#
# Implementation Notes:
# - Uses displayio + bitmaptools with defensive wrappers (_rect_fill, _hline, _vline).
# - Layered bitmaps for lane + playhead to minimize redraw cost.
# - Per-beat judging; adaptive hit windows scale with BPM but never shrink below
#   minimum absolute values.
# - Audio via MacroPad.play_tone().
# - LEDs fade automatically in play; legend colors are steady in settings.

import time
import displayio, terminalio
import bitmaptools
from micropython import const
try:
    from adafruit_display_text import label
    HAVE_LABEL = True
except Exception:
    HAVE_LABEL = False

# ---------- Constants & Tunables ----------
SCREEN_W, SCREEN_H = const(128), const(64)
BG, FG = const(0), const(1)

# Keys (launcher forwards 0..11)
# Final mapping:
# K0/K2: BPM -/+      K1: Mode toggle
# K3/K5: Diff -/+     K6/K8: Pattern -/+
# K11: Start/Resume (settings) or Pause (play)
K_DEC_BPM, K_TOGGLE_MODE, K_INC_BPM = 0, 1, 2
K_DEC_DIFF, K_INC_DIFF              = 3, 5
K_PREV_PATTERN, K_NEXT_PATTERN      = 6, 8
K_START_PAUSE                       = 11  # moved from 8 -> 11

DEFAULT_BPM = const(90)
MIN_BPM, MAX_BPM = const(60), const(180)
DIFFS = ("Easy", "Normal", "Hard")

HIT_WINDOWS_ABS = {  # minimum absolute window (seconds)
    "Easy":   0.110,
    "Normal": 0.075,
    "Hard":   0.050,
}
HIT_WINDOWS_FRAC = {  # fraction of seconds-per-beat (spb)
    "Easy":   0.080,   # 8% of a beat
    "Normal": 0.060,   # 6% of a beat
    "Hard":   0.045,   # 4.5% of a beat
}

SONG_MEASURES      = const(12)  # 12 bars, 4/4 -> 128 beats
BEATS_PER_MEASURE  = const(4)

# LED behavior
LED_FADE_MS        = const(140)  # time-based fade to near-zero
PIXEL_BRIGHTNESS   = 0.35

# --- LED color scheme (set USE_COLOR=False for brightness-only look) ---
USE_COLOR         = True
FEEDBACK_MS       = const(160)  # judgement tint hold
# Settings-mode legend colors
COL_BPM           = (0,   120, 255)  # blue
COL_DIFF          = (200, 0,   200)  # magenta
COL_PAT           = (0,   200, 200)  # cyan
COL_MODE          = (255, 170, 0)    # amber
COL_START         = (0,   255, 0)    # green
COL_PAUSE         = (255, 0,   0)    # red (K11 while paused)
# Play-mode colors
COLOR_BEAT        = (255, 255, 255)  # white
COLOR_BEAT_ACCENT = (255, 235, 180)  # warm white
COLOR_PERFECT     = (0,   255, 0)
COLOR_GOOD        = (64,  210, 0)
COLOR_OKAY        = (160, 160, 0)
COLOR_MISS        = (255, 40,  0)

def _scale_rgb(rgb, level):
    if level <= 0: return (0,0,0)
    if not USE_COLOR: return (level, level, level)
    r,g,b = rgb
    return ((r*level)//255, (g*level)//255, (b*level)//255)

# ---------- Defensive bitmap helpers ----------
def _clamp(v, lo, hi):
    if v < lo: return lo
    if v > hi: return hi
    return v

def _rect_fill(bmp, x, y, w, h, c):
    if w <= 0 or h <= 0: return
    x = _clamp(x, 0, SCREEN_W)
    y = _clamp(y, 0, SCREEN_H)
    w = _clamp(w, 0, SCREEN_W - x)
    h = _clamp(h, 0, SCREEN_H - y)
    if w <= 0 or h <= 0: return
    try:
        bitmaptools.fill_region(bmp, x, y, w, h, c)
    except Exception:
        x1, y1 = x + w, y + h
        for yy in range(y, y1):
            try:
                bitmaptools.fill_region(bmp, x, yy, w, 1, c)
            except Exception:
                for xx in range(x, x1):
                    try: bmp[xx, yy] = c
                    except Exception: pass

def _hline(bmp, x0, x1, y, c=FG):
    if y < 0 or y >= SCREEN_H: return
    if x0 > x1: x0, x1 = x1, x0
    x0 = _clamp(x0, 0, SCREEN_W - 1)
    x1 = _clamp(x1, 0, SCREEN_W - 1)
    _rect_fill(bmp, x0, y, (x1 - x0) + 1, 1, c)

def _vline(bmp, x, y0, y1, c=FG):
    if x < 0 or x >= SCREEN_W: return
    if y0 > y1: y0, y1 = y1, y0
    y0 = _clamp(y0, 0, SCREEN_H - 1)
    y1 = _clamp(y1, 0, SCREEN_H - 1)
    _rect_fill(bmp, x, y0, 1, (y1 - y0) + 1, c)

def _clear(bmp):
    _rect_fill(bmp, 0, 0, SCREEN_W, SCREEN_H, BG)

def _label(text, x, y):
    if not HAVE_LABEL: return None
    t = label.Label(terminalio.FONT, text=text, color=0xFFFFFF)
    t.x, t.y = x, y
    return t

# ---------- Pattern system ----------
#def _pat_quarter(measure, beat, idx):  return 0.00, (beat == 0)
#def _pat_offbeats(measure, beat, idx): return 0.50, False
#def _pat_shuffle(measure, beat, idx):  return (0.00 if (idx % 2 == 0) else 0.66), (beat == 0 and (idx % 2 == 0))

def _pat_quarter(measure, beat, idx):
    # One click per beat, accent on beat 1 of each bar
    return 0.00, (beat == 0)

def _pat_half(measure, beat, idx):
    # Click on beats 1 and 3 (i.e., every 2 beats)
    if beat % 2 == 0:                 # beats 0 and 2 (1 and 3 in counting)
        return 0.00, (beat == 0)
    return None                        # silence on other beats

def _pat_whole(measure, beat, idx):
    # Click only on beat 1 of each bar
    if beat == 0:
        return 0.00, True
    return None

def _pat_offbeats(measure, beat, idx):
    # Quarter "offbeats": click on beats 2 and 4 only.
    # (No eighth-note "&" clicks.)
    if beat in (1, 3):               # beats 2 and 4 in 1–4 counting
        return 0.00, False
    return None

def _pat_shuffle(measure, beat, idx):
    # Quarter "shuffle" feel: still quarter-aligned clicks, but
    # stronger accents on 1 and 3 to imply swing without 8th notes.
    return 0.00, (beat in (0, 2))    # accent on beats 1 & 3

def _pat_clave32(measure, beat, idx):
    # Simplified quarter-grid 3–2 clave over two bars (5 strokes):
    # Bar 1 (3): beats 1, 2, 4
    # Bar 2 (2): beats 2, 3
    m2 = measure % 2
    if m2 == 0:
        if beat in (0, 1, 3):
            return 0.00, (beat == 0)  # accent first stroke of the bar
    else:
        if beat in (1, 2):
            return 0.00, (beat == 1)
    return None

def _pat_clave23(measure, beat, idx):
    # Simplified quarter-grid 2–3 clave over two bars (5 strokes):
    # Bar 1 (2): beats 2, 3
    # Bar 2 (3): beats 1, 2, 4
    m2 = measure % 2
    if m2 == 0:
        if beat in (1, 2):
            return 0.00, (beat == 1)
    else:
        if beat in (0, 1, 3):
            return 0.00, (beat == 0)
    return None

PATTERNS = [
    ("Quarter (4/4)", _pat_quarter),
    ("Half",          _pat_half),
    ("Whole",         _pat_whole),
    ("Offbeats",      _pat_offbeats),
    ("Shuffle",       _pat_shuffle),
    ("Clave 3–2",     _pat_clave32),
    ("Clave 2–3",     _pat_clave23),
]

# ---------- Game Class ----------
class beat_trainer:
    # Use launcher default: encoder single-press exits. (No double-press opt-in.)
    # supports_double_encoder_exit omitted intentionally.

    def __init__(self, macropad=None, tones=None, **kwargs):
        self._mac = macropad
        self._pixels = getattr(macropad, "pixels", None) if macropad else None
        if self._pixels:
            try: self._pixels.brightness = PIXEL_BRIGHTNESS
            except Exception: pass

        # Display surface (layered for speed)
        self.bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
        self.pal = displayio.Palette(2); self.pal[BG]=0x000000; self.pal[FG]=0xFFFFFF
        self.bg_tile = displayio.TileGrid(self.bmp, pixel_shader=self.pal)

        # Lane (static) + Playhead (movable) sub-layers
        self.lane_bmp = None
        self.lane_tile = None
        self.ph_bmp = None
        self.ph_tile = None

        self.group = displayio.Group()
        self.group.append(self.bg_tile)

        # Text
        self._show_logo = True
        self.line1 = _label("", 2, 11)
        self.line2 = _label("", 2, 24)
        self.line3 = _label("", 2, 34)
        self.hud   = _label("", 2, 58)
        for t in (self.line1, self.line2, self.line3, self.hud):
            if t: self.group.append(t)

        # Runtime
        self.mode = "practice"  # "practice" | "scored"
        self.bpm = DEFAULT_BPM
        self.diff = "Normal"
        self.state = "ATTRACT"
        self._spb = 60.0 / self.bpm

        self.beat_index = -1
        self.song_beats = int(SONG_MEASURES * BEATS_PER_MEASURE)  # 128 beats
        self._song_start = None
        self._last_beat_sched = None
        self._pending_taps = []       # (t, key)
        self._score_p1 = 0
        self._combo_p1 = 0
        self._last_judgement = ""

        # LEDs (single-target scheme + settings legend)
        self._led_level = [0]*12           # 0..255
        self._led_color = [(0,0,0)]*12     # RGB
        self._last_led_update = time.monotonic()
        self._last_beat_led = 0
        self._feedback_until = 0.0

        # Text throttle
        self._next_text_update = 0.0  # next allowed non-forced text refresh

        # Pattern selector
        self._pat_idx = 0  # index in PATTERNS

    # ----- Launcher API -----
    def new_game(self):
        self.mode = "practice"
        self.bpm = DEFAULT_BPM
        self.diff = "Normal"
        self.state = "ATTRACT"
        self._spb = 60.0 / self.bpm
        self.beat_index = -1
        self._song_start = None
        self._last_beat_sched = None
        self._pending_taps.clear()
        self._score_p1 = 0
        self._combo_p1 = 0
        self._last_judgement = ""
        self._led_level = [0]*12
        self._led_color = [(0,0,0)]*12
        self._last_led_update = time.monotonic()
        self._last_beat_led = 0
        self._feedback_until = 0.0
        self._layout_static()
        self._update_text(force=True)
        self._render_settings_legend()  # show legend immediately
        self._pixels_show()

    def tick(self):
        now = time.monotonic()

        if self.state == "PLAY":
            self._advance_song(now)
            self._resolve_taps(now)

        self._decay_leds(now)
        # Throttle passive text refreshes to ~10 Hz
        if now >= self._next_text_update:
            self._update_text(force=False)
            self._next_text_update = now + 0.10  # 100 ms

    def button(self, key):
        if key < 0 or key > 11: return
        now = time.monotonic()

        if self.state == "PLAY":
            # GAME MODE — K0..K10 are taps; K11 pauses
            if key == K_START_PAUSE:
                self.state = "PAUSE"
                self._render_settings_legend()  # show legend with K11 red
                self._update_text(force=True)
            elif key <= 10:
                self._pending_taps.append((now, key))
            return

        # SETTINGS MODE (ATTRACT/PAUSE/RESULTS)
        if key == K_DEC_BPM:
            self._set_bpm(self.bpm - 5)
        elif key == K_INC_BPM:
            self._set_bpm(self.bpm + 5)
        elif key == K_DEC_DIFF:
            self._cycle_diff(-1)
        elif key == K_INC_DIFF:
            self._cycle_diff(+1)
        elif key == K_PREV_PATTERN:
            self._pat_idx = (self._pat_idx - 1) % len(PATTERNS)
        elif key == K_NEXT_PATTERN:
            self._pat_idx = (self._pat_idx + 1) % len(PATTERNS)
        elif key == K_TOGGLE_MODE:
            self.mode = "scored" if self.mode == "practice" else "practice"
        elif key == K_START_PAUSE:
            # Start or resume
            if self.state in ("ATTRACT", "RESULTS", "PAUSE"):
                self._start_song()
                self.state = "PLAY"

        # Refresh legend after any settings change
        self._render_settings_legend()
        self._update_text(force=True)

    def button_up(self, key):
        return

    # Encoder single press exits to the menu (launcher default). No handling needed here.
    def encoder_button(self, down):
        return

    def cleanup(self):
        self._all_leds(0)

    # ----- Internals -----
    def _layout_static(self):
        # Background clear + header line
        _clear(self.bmp)
        if self._show_logo:
            _hline(self.bmp, 0, SCREEN_W-1, 18, FG)

        # Build the static lane as its own bitmap/tilegrid (draw once)
        x0, y0, w, h = 6, 44, SCREEN_W-12, 6
        self.lane_bmp = displayio.Bitmap(w, h+1, 2)  # include bottom border line
        self.lane_tile = displayio.TileGrid(self.lane_bmp, pixel_shader=self.pal, x=x0, y=y0)

        # Clear to BG
        _rect_fill(self.lane_bmp, 0, 0, w, h, BG)
        # Vertical marks every 4 steps (16 steps across)
        steps = 16
        stepx = w // steps
        for i in range(0, steps+1, 4):
            _vline(self.lane_bmp, i*stepx, 0, h-1, FG)
        _hline(self.lane_bmp, 0, w-1, h, FG)  # bottom line

        # Playhead as a small separate bitmap we just move horizontally
        self.ph_bmp = displayio.Bitmap(stepx, h, 2)
        # Fill the playhead block once
        _rect_fill(self.ph_bmp, 0, 0, stepx, h, FG)
        self.ph_tile = displayio.TileGrid(self.ph_bmp, pixel_shader=self.pal, x=x0, y=y0)

        # Insert lane + playhead just above background, below text
        self.group.insert(1, self.lane_tile)
        self.group.insert(2, self.ph_tile)

        # Cache lane geometry
        self._lane = (x0, y0, w, h, steps, stepx)

    def _update_text(self, force=False):
        if not HAVE_LABEL: return
        def set_text(lbl, s):
            if lbl and (force or lbl.text != s):
                lbl.text = s

        pat_name = PATTERNS[self._pat_idx][0]
        mode_name = "PRACTICE" if self.mode == "practice" else "SCORED"

        if self.state == "ATTRACT":
            set_text(self.line1, f"Mode:{mode_name} BPM:{self.bpm}")
            set_text(self.line3, f"Pat: {pat_name}")
            set_text(self.line2, f"Diff: {self.diff}")
        elif self.state == "PLAY":
            set_text(self.line1, f"BPM:{self.bpm}")
            set_text(self.line3, f"{self._last_judgement}")
            set_text(self.line2, f"Diff: {self.diff}")
        elif self.state == "PAUSE":
            set_text(self.line1, f"PAUSED BPM:{self.bpm}")
            set_text(self.line3, f"Pat: {pat_name}")
            set_text(self.line2, f"Diff: {self.diff}")
        else:  # RESULTS
            set_text(self.line1, f"SCORE: {self._score_p1}")
            set_text(self.line2, "")
            set_text(self.line3, "")

        # HUD bottom line
        if self.state in ("PLAY", "PAUSE"):
            bi = max(self.beat_index, 0)
            measure = (bi // BEATS_PER_MEASURE) + 1
            beat_in_measure = (bi % BEATS_PER_MEASURE) + 1
            hud = f"M{measure}/{SONG_MEASURES}  Beat {beat_in_measure}/4  Combo:{self._combo_p1}"
        else:
            hud = ""
        set_text(self.hud, hud)

    def _set_bpm(self, new_bpm):
        self.bpm = max(MIN_BPM, min(MAX_BPM, int(new_bpm)))
        self._spb = 60.0 / self.bpm
        if self.state == "PLAY" and self._song_start is not None:
            now = time.monotonic()
            phase = (now - self._song_start) % self._spb
            self._song_start = now - phase
        self._update_text(force=True)

    def _cycle_diff(self, step):
        i = DIFFS.index(self.diff)
        self.diff = DIFFS[(i + step) % len(DIFFS)]
        self._update_text(force=True)

    def _start_song(self):
        self.beat_index = -1
        self._song_start = time.monotonic()
        self._last_beat_sched = None
        self._pending_taps.clear()
        self._score_p1 = 0
        self._combo_p1 = 0
        self._last_judgement = ""
        self._clear_ring()
        self._update_text(force=True)

    def _advance_song(self, now):
        elapsed = now - self._song_start
        idx = int(elapsed / self._spb)

        # 12-bar end condition (128 beats at 4/4)
        if idx >= self.song_beats:
            # Clamp HUD/playhead to final position and stop
            final_idx = (self._lane[4] - 1) if self._lane else (self.song_beats - 1)  # steps-1
            self._draw_playhead(final_idx)
            self.state = "RESULTS"
            self._render_settings_legend()
            self._update_text(force=True)
            return

        if idx != self.beat_index:
            self.beat_index = idx
            measure = idx // BEATS_PER_MEASURE
            beat    = idx %  BEATS_PER_MEASURE

            # Ask the active pattern what to do on this beat.
            # It may return:
            #   - None  → no click on this beat
            #   - (off_frac, accent) where 0.0 <= off_frac < 1.0
            pat_fn = PATTERNS[self._pat_idx][1]
            res = pat_fn(measure, beat, idx)

            if res is None:
                # No click scheduled for this beat
                self._last_beat_sched = None
            else:
                off_frac, accent = res
                if off_frac is None:
                    self._last_beat_sched = None
                else:
                    # Schedule the click at beat-start + fractional offset
                    if off_frac < 0.0:   off_frac = 0.0
                    if off_frac > 0.99:  off_frac = 0.99
                    off = self._spb * off_frac
                    self._last_beat_sched = self._song_start + idx*self._spb + off
                    self._flash_on_beat(idx, accent)

            self._last_judgement = ""
            # Immediate text refresh at beat boundaries keeps feel snappy
            self._update_text(force=True)

        # Playhead always moves each logical beat
        self._draw_playhead(idx)

    def _draw_playhead(self, idx):
        # Just move the small playhead tilegrid horizontally
        if not self.ph_tile or not self.lane_tile: return
        x0, y0, w, h, steps, stepx = self._lane
        ph = (idx % steps)
        px = x0 + ph*stepx
        self.ph_tile.x = px
        # no bitmap drawing here; movement only → very fast

    def _flash_on_beat(self, idx, accent=False):
        # Single-target: clear ring first
        for i in range(12):
            self._led_level[i] = 0
            self._led_color[i] = (0,0,0)
        led = idx % 12
        self._last_beat_led = led
        # Beat color
        self._led_color[led] = (COLOR_BEAT_ACCENT if accent else COLOR_BEAT)
        self._led_level[led] = 255
        self._last_led_update = time.monotonic()
        self._feedback_until = 0.0
        self._pixels_show()

        # Click
        if self._mac and hasattr(self._mac, "play_tone"):
            try:
                base = 440
                freq = int(base * (1.334)) if accent else int(base * (0.943))
                dur  = 0.045 if accent else 0.030
                self._mac.play_tone(freq, dur)
            except Exception:
                pass

    def _get_hit_window(self):
        base = HIT_WINDOWS_ABS[self.diff]
        frac = self._spb * HIT_WINDOWS_FRAC[self.diff]
        return base if base > frac else frac

    def _resolve_taps(self, now):
        sched = self._last_beat_sched
        if sched is None:
            self._pending_taps.clear()
            return

        hit_window = self._get_hit_window()
        judged = False
        next_pending = []
        for (t, key) in self._pending_taps:
            dt = t - sched
            adt = abs(dt)
            if adt <= hit_window:
                perfect_thr = hit_window * 0.40
                good_thr    = hit_window * 0.75
                if adt <= perfect_thr:
                    self._judge("Perfect", +150)
                elif adt <= good_thr:
                    self._judge("Good", +80)
                else:
                    self._judge("Okay", +40)
                judged = True
            else:
                next_pending.append((t, key))
        self._pending_taps = next_pending

        if not judged:
            phase = (now - sched) / self._spb
            if phase > 0.55:
                self._judge("Miss", -50, combo_break=True)

    def _judge(self, word, points, combo_break=False):
        # Practice mode can ignore penalties
        if self.mode == "practice" and points < 0:
            points = 0
            combo_break = False
            if word == "Miss":
                word = "OK"

        self._score_p1 += points
        self._combo_p1 = (self._combo_p1 + 1) if points > 0 else (0 if combo_break else max(0, self._combo_p1 - 1))
        self._last_judgement = word

        # Feedback on current target LED only
        led = self._last_beat_led
        if points > 0:
            if word == "Perfect":
                rgb = COLOR_PERFECT; boost = 255
            elif word == "Good":
                rgb = COLOR_GOOD;    boost = 220
            else:
                rgb = COLOR_OKAY;    boost = 190
        else:
            rgb = COLOR_MISS;        boost = 200

        self._led_color[led] = rgb
        if self._led_level[led] < boost:
            self._led_level[led] = boost
        self._feedback_until = time.monotonic() + (FEEDBACK_MS / 1000.0)
        self._last_led_update = time.monotonic()
        self._pixels_show()

    # --- LEDs ---
    def _render_settings_legend(self):
        # Clear everything
        for i in range(12):
            self._led_level[i] = 0
            self._led_color[i] = (0,0,0)
        # Map legends
        self._set_led(0, COL_BPM, 160)    # BPM -
        self._set_led(2, COL_BPM, 160)    # BPM +
        self._set_led(1, COL_MODE, 170)   # Mode toggle
        self._set_led(3, COL_DIFF, 150)   # Diff -
        self._set_led(5, COL_DIFF, 150)   # Diff +
        self._set_led(6, COL_PAT,  150)   # Pattern -
        self._set_led(8, COL_PAT,  150)   # Pattern +
        # Start/Resume (or Pause indicator if paused)
        if self.state == "PAUSE":
            self._set_led(11, COL_PAUSE, 220)  # red
        else:
            self._set_led(11, COL_START, 200)  # green
        self._last_led_update = time.monotonic()
        self._feedback_until = 0.0
        self._pixels_show()

    def _clear_ring(self):
        for i in range(12):
            self._led_level[i] = 0
            self._led_color[i] = (0,0,0)
        self._pixels_show()

    def _set_led(self, idx, rgb, level):
        if 0 <= idx < 12:
            self._led_color[idx] = rgb
            self._led_level[idx] = level

    def _decay_leds(self, now):
        dt_ms = int((now - self._last_led_update) * 1000.0)
        if dt_ms <= 0:
            return
        self._last_led_update = now
        if self.state != "PLAY":
            # In settings modes, keep legend steady (no decay)
            self._pixels_show()
            return
        if LED_FADE_MS <= 0:
            changed = False
            for i in range(12):
                if self._led_level[i] != 0:
                    self._led_level[i] = 0; changed = True
            if changed: self._pixels_show()
            return
        dec = int(255 * (dt_ms / float(LED_FADE_MS)))
        if dec <= 0: return
        changed = False
        for i in range(12):
            if self._led_level[i] > 0:
                nl = self._led_level[i] - dec
                if nl < 0: nl = 0
                if nl != self._led_level[i]:
                    self._led_level[i] = nl
                    changed = True

        if self._feedback_until and now >= self._feedback_until:
            self._feedback_until = 0.0
            led = self._last_beat_led
            if self._led_level[led] > 0:
                self._led_color[led] = COLOR_BEAT
            changed = True

        if changed:
            self._pixels_show()

    def _all_leds(self, val):
        if not self._pixels: return
        if isinstance(val, int) and val == 0:
            for i in range(12): self._pixels[i] = 0
        else:
            for i in range(12): self._pixels[i] = val
        self._pixels_show()

    def _pixels_show(self):
        if not self._pixels: return
        for i in range(12):
            r,g,b = _scale_rgb(self._led_color[i], self._led_level[i])
            self._pixels[i] = (r << 16) | (g << 8) | b
        try: self._pixels.show()
        except Exception: pass