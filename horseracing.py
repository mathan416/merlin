# ---------------------------------------------------------------------------
# horseracing.py — VFD-style Horseracing (Merlin Launcher compatible)
# ---------------------------------------------------------------------------
# A minimalist horse racing game styled after old VFD (vacuum fluorescent
# display) handhelds. Designed for the Merlin Launcher on Adafruit MacroPad
# with CircuitPython 9.x (128×64 monochrome OLED).
# Written by Iain Bennett — 2025
#
# Core Features
#   • Five racing lanes with pixel horses advancing toward a finish line
#   • Title → Bet → Run → Result game loop
#   • Player chooses a lane (bet) before the race starts
#   • Horses move with randomized step sizes for tension and variety
#   • Winner is announced with OLED text + LED highlight
#
# Display & HUD
#   • Static background shows lanes + dotted finish line
#   • Foreground bitmap (transparent zero) draws horses so the track remains visible
#   • Centered text prompts guide the player at each state:
#       - Title screen with logo
#       - Bet prompt with K0–K4 selectable
#       - Run with clean track view
#       - Winner announcement at finish
#
# LED Feedback
#   • BET phase: K0–K4 glow dim blue, selected lane bright blue, K11 green to start
#   • RUN phase: LEDs fade by race placement (1st = bright, last = dim)
#   • RESULT phase: Winner’s lane lit green
#   • TITLE: LEDs off
#
# Implementation Notes
#   • Foreground palette index 0 = TRANSPARENT so background lanes stay visible
#   • Incremental erase/draw logic keeps horses smooth without redrawing full screen
#   • _LedSmooth ensures flicker-free LEDs (rate-limited .show)
#   • Lightweight state machine (TITLE → BET → RUN → RESULT)
#
# Controls (MacroPad)
#   K0–K4 = Select horse lane (bet)
#   K11   = Start race (after a bet is chosen)
#   Any key at RESULT → Reset to title
#
# Assets / Deps
#   • MerlinChrome.bmp (optional logo, shown only at title)
#   • adafruit_display_text.label (HUD prompts)
#   • bitmaptools (optional; autodetected for fill/erase)
# ---------------------------------------------------------------------------
__all__ = ["horseracing"]

import time, random
import displayio, terminalio
from micropython import const
try:
    import bitmaptools
    _HAS_BT = True
except Exception:
    _HAS_BT = False

try:
    from adafruit_display_text import label
    _HAVE_LABEL = True
except Exception:
    _HAVE_LABEL = False

# ---------- Screen / Layout ----------
SCREEN_W, SCREEN_H = const(128), const(64)
PROMPT_Y1, PROMPT_Y2 = const(40), const(53)

LANES = const(5)
LANE_H = const(9)
LANE_BASE_Y = const(14)  # y of first lane line
HORSE_W, HORSE_H = const(4), const(3)
HORSE_DY = const(4)      # horse is drawn y-4..y-2

START_X = const(8)
FINISH_X = const(110)

STEP_MIN, STEP_MAX = 0.55, 1.85

STATE_TITLE, STATE_BET, STATE_RUN, STATE_RESULT = 0, 1, 2, 3

# ---------- Helpers ----------
def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)

def _clear_partial(bmp, x, y, w, h):
    if w <= 0 or h <= 0: return
    x2, y2 = x + w - 1, y + h - 1
    if x2 < 0 or y2 < 0 or x >= SCREEN_W or y >= SCREEN_H: return
    x0 = _clamp(x, 0, SCREEN_W - 1)
    y0 = _clamp(y, 0, SCREEN_H - 1)
    x1 = _clamp(x2, 0, SCREEN_W - 1)
    y1 = _clamp(y2, 0, SCREEN_H - 1)
    if x1 < x0 or y1 < y0: return
    if _HAS_BT:
        try:
            bitmaptools.fill_region(bmp, x0, y0, (x1 - x0 + 1), (y1 - y0 + 1), 0)
            return
        except Exception:
            pass
    for yy in range(y0, y1 + 1):
        for xx in range(x0, x1 + 1):
            bmp[xx, yy] = 0

def _fill_partial(bmp, x, y, w, h, c=1):
    if w <= 0 or h <= 0: return
    x2, y2 = x + w - 1, y + h - 1
    if x2 < 0 or y2 < 0 or x >= SCREEN_W or y >= SCREEN_H: return
    x0 = _clamp(x, 0, SCREEN_W - 1)
    y0 = _clamp(y, 0, SCREEN_H - 1)
    x1 = _clamp(x2, 0, SCREEN_W - 1)
    y1 = _clamp(y2, 0, SCREEN_H - 1)
    if x1 < x0 or y1 < y0: return
    if _HAS_BT:
        try:
            bitmaptools.fill_region(bmp, x0, y0, (x1 - x0 + 1), (y1 - y0 + 1), c)
            return
        except Exception:
            pass
    for yy in range(y0, y1 + 1):
        for xx in range(x0, x1 + 1):
            bmp[xx, yy] = c

def _hline(bmp, x0, x1, y, c=1):
    if y < 0 or y >= SCREEN_H: return
    if x0 > x1: x0, x1 = x1, x0
    x0 = _clamp(x0, 0, SCREEN_W - 1)
    x1 = _clamp(x1, 0, SCREEN_W - 1)
    if x1 < x0: return
    if _HAS_BT:
        try:
            bitmaptools.fill_region(bmp, x0, y, (x1 - x0 + 1), 1, c)
            return
        except Exception:
            pass
    for x in range(x0, x1 + 1): bmp[x, y] = c

def _vline(bmp, x, y0, y1, c=1):
    if x < 0 or x >= SCREEN_W: return
    if y0 > y1: y0, y1 = y1, y0
    y0 = _clamp(y0, 0, SCREEN_H - 1)
    y1 = _clamp(y1, 0, SCREEN_H - 1)
    if y1 < y0: return
    if _HAS_BT:
        try:
            bitmaptools.fill_region(bmp, x, y0, 1, (y1 - y0 + 1), c)
            return
        except Exception:
            pass
    for y in range(y0, y1 + 1): bmp[x, y] = c

def _scale_color(rgb, k):
    r = ((rgb >> 16) & 0xFF); g = ((rgb >> 8) & 0xFF); b = (rgb & 0xFF)
    return (int(r*k)<<16) | (int(g*k)<<8) | int(b*k)

def _make_bitmap_layer(transparent_zero=False):
    bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
    pal = displayio.Palette(2)
    pal[0] = 0x000000
    pal[1] = 0xFFFFFF
    if transparent_zero:
        try:
            pal.make_transparent(0)
        except Exception:
            try:
                pal[0] = 0
            except Exception:
                pass
    tile = displayio.TileGrid(bmp, pixel_shader=pal)
    return bmp, tile

# ---------- LEDs ----------
class _LedSmooth:
    def __init__(self, macropad, limit_hz=30):
        self.ok = bool(macropad and hasattr(macropad, "pixels"))
        self.px = macropad.pixels if self.ok else None
        self.buf = [0x000000]*12
        self._last = self.buf[:]
        self._last_show = 0.0
        self._min_dt = 1.0/float(limit_hz if limit_hz>0 else 30)
        if self.ok:
            try:
                if hasattr(self.px, "auto_write"):
                    self._saved_auto = self.px.auto_write
                    self.px.auto_write = False
                else:
                    self._saved_auto = True
                self.px.brightness = 0.30
                for i in range(12): self.px[i] = 0x000000
                try: self.px.show()
                except Exception: pass
            except Exception:
                self.ok = False
    def set(self, i, color):
        if self.ok and 0 <= i < 12: self.buf[i] = int(color) & 0xFFFFFF
    def fill(self, color):
        if self.ok:
            c = int(color) & 0xFFFFFF
            for i in range(12): self.buf[i] = c
    def show(self, now=None):
        if not self.ok: return
        import time as _t
        t = now if (now is not None) else _t.monotonic()
        if (t - self._last_show) < self._min_dt: return
        changed = False
        for i, c in enumerate(self.buf):
            if c != self._last[i]:
                self.px[i] = c; self._last[i] = c; changed = True
        if changed:
            try: self.px.show()
            except Exception: pass
        self._last_show = t
    def off(self):
        if not self.ok: return
        for i in range(12): self.buf[i] = 0x000000; self._last[i] = 0x111111
        self.show()
    def restore(self):
        if self.ok and hasattr(self.px, "auto_write"):
            try: self.px.auto_write = getattr(self, "_saved_auto", True)
            except Exception: pass

# ---------- Main Game ----------
class horseracing:
    __slots__ = ("macropad","group",
                 "_logo_tile",
                 "bg_bmp","bg_tile",
                 "fg_bmp","fg_tile",
                 "lbl1","lbl2",
                 "led","state","bet",
                 "pos","prev_pos","winner",
                 "_last_step","_last_tick_t")

    def __init__(self, macropad=None, *_tones, **_kwargs):
        self.macropad = macropad
        self.group = displayio.Group()

        # Bottom: Merlin chrome (title only)
        self._logo_tile = None
        try:
            obmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile = displayio.TileGrid(obmp, pixel_shader=getattr(obmp, "pixel_shader", displayio.ColorConverter()))
            self.group.append(tile)
            self._logo_tile = tile
        except Exception:
            self._logo_tile = None

        # Background (track/finish) and foreground (horses)
        self.bg_bmp, self.bg_tile = _make_bitmap_layer(transparent_zero=False)  # opaque bg
        self.fg_bmp, self.fg_tile = _make_bitmap_layer(transparent_zero=True)   # transparent zero on FG
        self.group.append(self.bg_tile)
        self.group.append(self.fg_tile)

        # Labels (centered)
        self.lbl1 = self.lbl2 = None
        if _HAVE_LABEL:
            self.lbl1 = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
            self.lbl2 = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
            self.lbl1.anchor_point = (0.5, 0.5)
            self.lbl2.anchor_point = (0.5, 0.5)
            self.lbl1.anchored_position = (SCREEN_W//2, PROMPT_Y1)
            self.lbl2.anchored_position = (SCREEN_W//2, PROMPT_Y2)
            self.group.append(self.lbl1)
            self.group.append(self.lbl2)

        self.led = _LedSmooth(self.macropad, limit_hz=30)
        self.new_game()

    # ----- UI helpers -----
    def _set_layers_visible_for_state(self):
        if self._logo_tile:
            self._logo_tile.hidden = not (self.state == STATE_TITLE)
        self.bg_tile.hidden = (self.state == STATE_TITLE)
        self.fg_tile.hidden = (self.state == STATE_TITLE)

    def _set_labels(self, t1="", t2=""):
        if not _HAVE_LABEL: return
        self.lbl1.text = t1 or ""
        self.lbl2.text = t2 or ""
        self.lbl1.anchored_position = (SCREEN_W//2, PROMPT_Y1)
        self.lbl2.anchored_position = (SCREEN_W//2, PROMPT_Y2)

    # ----- Drawing -----
    def _render_track_bg(self):
        _clear_partial(self.bg_bmp, 0, 0, SCREEN_W, SCREEN_H)
        # Lane lines (static)
        for i in range(LANES):
            y = LANE_BASE_Y + i * LANE_H
            _hline(self.bg_bmp, 0, SCREEN_W-1, y, 1)
        # Finish line posts (dotted, static)
        y_start = LANE_BASE_Y - 2
        y_end = LANE_BASE_Y + LANES * LANE_H
        for yy in range(y_start, y_end + 1, 2):
            _vline(self.bg_bmp, FINISH_X, yy, yy, 1)

    def _erase_horse_at(self, lane_idx, x):
        y_line = LANE_BASE_Y + lane_idx * LANE_H
        y0 = y_line - HORSE_DY
        _clear_partial(self.fg_bmp, x, y0, HORSE_W, HORSE_H)

    def _draw_horse_at(self, lane_idx, x):
        y_line = LANE_BASE_Y + lane_idx * LANE_H
        y0 = y_line - HORSE_DY
        _fill_partial(self.fg_bmp, x, y0, HORSE_W, HORSE_H, 1)

    def _initial_draw_for_state(self):
        self._set_layers_visible_for_state()

        if self.state in (STATE_BET, STATE_RUN, STATE_RESULT):
            self._render_track_bg()
        else:
            _clear_partial(self.bg_bmp, 0, 0, SCREEN_W, SCREEN_H)
            _clear_partial(self.fg_bmp, 0, 0, SCREEN_W, SCREEN_H)

        if self.state == STATE_TITLE:
            self._set_labels("Horseracing", "Press to begin")
        elif self.state == STATE_BET:
            self._set_labels("", "Select lane  •  K11 start")
            _clear_partial(self.fg_bmp, 0, 0, SCREEN_W, SCREEN_H)
            for i in range(LANES):
                self._draw_horse_at(i, int(self.pos[i]))
        elif self.state == STATE_RUN:
            self._set_labels("", "")
            _clear_partial(self.fg_bmp, 0, 0, SCREEN_W, SCREEN_H)
            for i in range(LANES):
                self._draw_horse_at(i, int(self.pos[i]))
        else:
            self._set_labels("", "")

    # ----- Sound (uses MacroPad play_tone(freq, duration)) -----
    def _tone(self, f, d=0.06):
        if self.macropad and hasattr(self.macropad, "play_tone"):
            try: self.macropad.play_tone(int(f), float(d))
            except Exception: pass

    def _melody(self, notes):
        # notes: list of (freq, duration)
        if not (self.macropad and hasattr(self.macropad, "play_tone")):
            return
        for f, d in notes:
            try: self.macropad.play_tone(int(f), float(d))
            except Exception: pass

    def _hoof_tick(self, lane_idx):
        # Light, short tick per lane; slight pitch stagger for variety
        base = 480 + 28 * lane_idx
        jitter = (-10, 0, 10)[lane_idx % 3]
        self._tone(base + jitter, 0.028)

    # ----- LEDs -----
    def _draw_leds(self):
        self.led.fill(0x000000)

        if self.state == STATE_BET:
            # K0..K4 dim blue; selected bright; K11 green to start
            dim_blue = _scale_color(0x0080FF, 0.25)
            for i in range(LANES):
                self.led.set(i, dim_blue)
            if self.bet is not None:
                self.led.set(self.bet, _scale_color(0x0080FF, 0.75))
            self.led.set(11, 0x00FF00)

        elif self.state == STATE_RUN:
            # Fade LEDs by placement
            order = sorted(range(LANES), key=lambda idx: self.pos[idx], reverse=True)
            ranks = [0]*LANES
            rank = 0
            for n, idx in enumerate(order):
                if n > 0 and self.pos[idx] < self.pos[order[n-1]] - 1e-6:
                    rank = n
                ranks[idx] = rank
            rank_to_k = [1.00, 0.75, 0.55, 0.35, 0.20]
            for i in range(LANES):
                r = ranks[i]
                if r >= len(rank_to_k): r = len(rank_to_k) - 1
                k = rank_to_k[r]
                self.led.set(i, _scale_color(0x0080FF, k))

        elif self.state == STATE_RESULT:
            if self.winner is not None:
                self.led.set(self.winner, 0x00FF00)

        self.led.show()

    # ----- Game Flow -----
    def new_game(self, mode=None):
        self.state = STATE_TITLE
        self.bet = None
        self.pos = [START_X * 1.0 for _ in range(LANES)]
        self.prev_pos = self.pos[:]
        self.winner = None
        self._last_step = 0.0
        self._last_tick_t = [0.0 for _ in range(LANES)]  # per-lane hoof-tick rate-limit
        self._initial_draw_for_state()
        self._draw_leds()

    def tick(self, dt=0.016):
        if self.state != STATE_RUN:
            self._draw_leds()
            return

        now = time.monotonic()
        if now - self._last_step < 0.05:
            self._draw_leds()
            return
        self._last_step = now

        for i in range(LANES):
            old_x = int(self.prev_pos[i])
            step = random.uniform(STEP_MIN, STEP_MAX) * random.uniform(0.8, 1.25)
            self.pos[i] += step
            if self.pos[i] >= FINISH_X - HORSE_W:
                self.pos[i] = FINISH_X - HORSE_W
            new_x = int(self.pos[i])

            if new_x != old_x:
                # hoof tick (rate-limited per lane to avoid chatter)
                if (now - self._last_tick_t[i]) > 0.06:
                    self._hoof_tick(i)
                    self._last_tick_t[i] = now

                self._erase_horse_at(i, old_x)
                if new_x > old_x:
                    _clear_partial(self.fg_bmp, old_x + HORSE_W, LANE_BASE_Y + i*LANE_H - HORSE_DY, 1, HORSE_H)
                else:
                    _clear_partial(self.fg_bmp, new_x, LANE_BASE_Y + i*LANE_H - HORSE_DY, 1, HORSE_H)
                self._draw_horse_at(i, new_x)
                self.prev_pos[i] = float(new_x)

        for i in range(LANES):
            if self.pos[i] >= FINISH_X - HORSE_W:
                self.winner = i
                self.state = STATE_RESULT
                self._set_labels("", "Winner: Lane {}".format(self.winner + 1))
                self._draw_leds()
                # Win jingle (short and cheerful)
                self._melody([(523, 0.08), (659, 0.09), (784, 0.12)])
                return

        self._draw_leds()

    def button(self, key, pressed=True):
        if not pressed: return
        if self.state == STATE_TITLE:
            self.state = STATE_BET
            self._initial_draw_for_state()
            self._draw_leds()
            self._tone(330, 0.06)
            return

        if self.state == STATE_BET:
            if 0 <= key < LANES:
                self.bet = key
                self._tone(392, 0.05)
                self._draw_leds()
            else:
                if self.bet is not None:
                    self.state = STATE_RUN
                    self.pos = [START_X * 1.0 for _ in range(LANES)]
                    self.prev_pos = [START_X * 1.0 for _ in range(LANES)]
                    self.winner = None
                    self._last_tick_t = [0.0 for _ in range(LANES)]
                    self._initial_draw_for_state()
                    self._draw_leds()
                    # Gate “go!” blip
                    self._tone(440, 0.09)
        elif self.state == STATE_RESULT:
            self._tone(247, 0.07)
            self.new_game()

    def cleanup(self):
        try:
            self.led.off()
            self.led.restore()
        except Exception:
            pass