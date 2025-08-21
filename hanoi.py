# ---------------------------------------------------------------------------
# hanoi.py — Tower of Hanoi (launcher-compatible)
# CircuitPython 9.x / Adafruit MacroPad (128×64 mono OLED)
# Written by Iain Bennett — 2025
#
# Implements the classic Tower of Hanoi puzzle as a self-contained module
# compatible with a Merlin/MacroPad launcher environment.
#
# Features:
#   • Full Tower of Hanoi logic with disk counts selectable 3–7.
#   • Monochrome 128×64 OLED graphics (black background, white pegs/disks).
#   • Minimal HUD with move count and disk count.
#   • Colorful MacroPad NeoPixel feedback:
#       - Column 0 keys (K0,K3,K6) → Red (dim/med/bright states).
#       - Column 1 keys (K1,K4,K7) → Green.
#       - Column 2 keys (K2,K5,K8) → Blue.
#       - K9 → Yellow (New Game) — pulses when puzzle is solved.
#       - K10 → Cyan (Change disk count).
#       - K11 → Unused (off).
#   • Audio feedback via MacroPad speaker using pad.play_tone():
#       - Selecting/moving disks → short tones.
#       - Invalid move → error tone.
#       - New game / disk cycle → short tones.
#       - Victory melody when solved.
#
# Controls:
#   • Keys 0–8: Select and move disks by column.
#       - Press a column key once to select its top disk.
#       - Press destination column to attempt a move.
#   • K9: Start a new game (same disk count).
#   • K10: Cycle disk count (3–7), starts new game.
#   • K11: Not used.
#
# Exposed API for launcher:
#   • .group    → displayio.Group to attach to display.
#   • .new_game() → reset with current disk count.
#   • .tick(dt) → update animation (handles K9 pulsing when solved).
#   • .button(key, pressed=True) → handle key press.
#   • .button_up(key) → stub (no effect).
#   • .cleanup() → clear LEDs on exit.
#
# Notes:
#   • Defensive wrappers around bitmaptools for compatibility.
#   • Designed for 2-color display; all color feedback is via LEDs only.
# ---------------------------------------------------------------------------



import math
import displayio, terminalio
import bitmaptools
from micropython import const
try:
    from adafruit_display_text import label
    HAVE_LABEL = True
except Exception:
    HAVE_LABEL = False

# ---- Screen / layout (mono) ----
SCREEN_W, SCREEN_H = const(128), const(64)
BG_COLOR = const(0)   # black
FG_COLOR = const(1)   # white
BASE_Y   = const(62)
DISK_H   = const(4)
DEFAULT_DISKS = const(5)
MIN_DISKS = const(3)
MAX_DISKS = const(7)

# ---- Defensive wrappers ----
try:
    _HAS_FILL_REGION = hasattr(bitmaptools, "fill_region")
except Exception:
    _HAS_FILL_REGION = False

def _fallback_fill(bmp, x0, y0, w, h, color):
    try:
        x1, y1 = x0 + w, y0 + h
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                try: bmp[xx, yy] = color
                except Exception: pass
    except Exception:
        pass

def _rect_fill(bmp, x, y, w, h, color):
    if not bmp or w <= 0 or h <= 0: return
    x0 = max(0, min(SCREEN_W, int(x))); y0 = max(0, min(SCREEN_H, int(y)))
    x1 = max(0, min(SCREEN_W, int(x + w))); y1 = max(0, min(SCREEN_H, int(y + h)))
    if x1 <= x0 or y1 <= y0: return
    try:
        if _HAS_FILL_REGION: bitmaptools.fill_region(bmp, x0, y0, x1-x0, y1-y0, color)
        else: _fallback_fill(bmp, x0, y0, x1-x0, y1-y0, color)
    except Exception:
        _fallback_fill(bmp, x0, y0, x1-x0, y1-y0, color)

def _hline(bmp, x0, x1, y, color=FG_COLOR):
    if not bmp or y < 0 or y >= SCREEN_H: return
    if x0 > x1: x0, x1 = x1, x0
    x0 = max(0, int(x0)); x1 = min(SCREEN_W-1, int(x1))
    if x1 < x0: return
    _rect_fill(bmp, x0, y, x1-x0+1, 1, color)

def _vline(bmp, x, y0, y1, color=FG_COLOR):
    if not bmp or x < 0 or x >= SCREEN_W: return
    if y0 > y1: y0, y1 = y1, y0
    y0 = max(0, int(y0)); y1 = min(SCREEN_H-1, int(y1))
    if y1 < y0: return
    _rect_fill(bmp, x, y0, 1, y1-y0+1, color)


class hanoi:
    def __init__(self, launcher=None, macropad=None, **kwargs):
        # Strictly 2-color palette for mono OLED
        self.bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
        self.pal = displayio.Palette(2); self.pal[0] = 0x000000; self.pal[1] = 0xFFFFFF
        self.group = displayio.Group()
        self.group.append(displayio.TileGrid(self.bmp, pixel_shader=self.pal))

        # Bind MacroPad (for sound) and LEDs robustly
        self.pad = macropad
        self.leds = None
        # Prefer LEDs from macropad first
        for obj in (macropad, launcher):
            if obj is None: continue
            # Try common attributes
            for attr in ("pixels", "leds"):
                try:
                    candidate = getattr(obj, attr)
                    if candidate is not None:
                        self.leds = candidate
                        break
                except Exception:
                    pass
            if self.leds is not None:
                break

        # ---- LED color scheme ----
        self._COLORS_BRIGHT = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]  # R/G/B
        self._COLORS_MED    = [(128, 0, 0), (0, 128, 0), (0, 0, 128)]
        self._COLORS_DIM    = [(32, 0, 0),  (0, 32, 0),  (0, 0, 32)]
        self._LED_OFF = (0, 0, 0)
        self._LED_K9  = (255, 255, 0)   # Yellow — New game
        self._LED_K10 = (0, 255, 255)   # Cyan — Change disk count

        # Game state
        self.n = int(DEFAULT_DISKS)
        self.moves = 0
        self.selected = None
        self.solved = False
        self.stacks = [[], [], []]
        self._pulse_t = 0.0

        # HUD
        self.lbl1 = self.lbl2 = self.hud = None
        if HAVE_LABEL:
            self.lbl1 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=38)
            self.lbl2 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=50)
            self.hud  = label.Label(terminalio.FONT, text="Moves: 0  Disks: {}".format(self.n), color=0xFFFFFF, x=2, y=10)
            self.group.append(self.lbl1); self.group.append(self.lbl2); self.group.append(self.hud)

        self.new_game()

    # ---- LED show helper (handles auto_write=False) ----
    def _led_show(self):
        try:
            if self.leds and hasattr(self.leds, "show"):
                self.leds.show()
        except Exception:
            pass

    # ---- Launcher API ----
    def new_game(self):
        self.stacks = [list(range(self.n, 0, -1)), [], []]
        self.moves = 0
        self.selected = None
        self.solved = False
        self._pulse_t = 0.0
        if self.hud:
            try: self.hud.text = "Moves: 0  Disks: {}".format(self.n)
            except Exception: pass
        self._redraw()
        self._update_leds()  # sets base LED state & shows

    def tick(self, dt=0.0):
        if self.solved and self.leds:
            try:
                self._pulse_t += (dt or 0.0)
                f = 1.2  # Hz
                s = 0.5 * (math.sin(2 * math.pi * f * self._pulse_t) + 1.0)
                factor = 0.3 + 0.7 * s
                self.leds[9] = self._scale(self._LED_K9, factor)
                self._led_show()
            except Exception:
                pass

    def button(self, key, pressed=True):
        if not pressed or key < 0 or key > 11: return

        if key <= 8:
            col = key % 3
            if self.selected is None:
                if self.stacks[col]:
                    self.selected = col
                    self._beep(660, 0.04)
                    self._highlight(col)
                    self._update_leds()
            else:
                if self._try_move(self.selected, col):
                    self._beep(880, 0.06)
                else:
                    self._beep(220, 0.08)
                self.selected = None
                self._redraw()
                self._update_leds()

        elif key == 9:
            self.new_game()
            self._beep(440, 0.05)

        elif key == 10:
            self.n += 1
            if self.n > MAX_DISKS: self.n = MIN_DISKS
            self.new_game()
            self._beep(550, 0.05)

    def button_up(self, key): return

    def cleanup(self):
        if self.leds:
            try:
                self.leds.fill((0, 0, 0))
                self._led_show()
            except Exception:
                pass

    # ---- Logic ----
    def _try_move(self, src, dst):
        if src == dst or not self.stacks[src]: return False
        disk = self.stacks[src][-1]
        if self.stacks[dst] and self.stacks[dst][-1] < disk: return False
        self.stacks[src].pop(); self.stacks[dst].append(disk)
        self.moves += 1
        if self.hud:
            try: self.hud.text = "Moves: {}  Disks: {}".format(self.moves, self.n)
            except Exception: pass
        self._check_win()
        return True

    # ---- Rendering ----
    def _highlight(self, col):
        self._redraw()
        cx = 21 + col * 43
        _hline(self.bmp, cx - 10, cx + 10, 18, FG_COLOR)
        _hline(self.bmp, cx - 10, cx + 10, 22, FG_COLOR)
        _vline(self.bmp, cx - 10, 18, 22, FG_COLOR)
        _vline(self.bmp, cx + 10, 18, 22, FG_COLOR)

    def _redraw(self):
        _rect_fill(self.bmp, 0, 0, SCREEN_W, SCREEN_H, BG_COLOR)
        _rect_fill(self.bmp, 0, BASE_Y, SCREEN_W, 2, FG_COLOR)
        for i in range(3):
            x = 21 + i * 43
            _vline(self.bmp, x, 20, BASE_Y, FG_COLOR)
        for i, stack in enumerate(self.stacks):
            x = 21 + i * 43
            for level, size in enumerate(stack):
                w = 12 + size * 4
                y = BASE_Y - 2 - level * DISK_H
                _rect_fill(self.bmp, x - w // 2, y - (DISK_H - 1), w, DISK_H - 1, FG_COLOR)

    def _check_win(self):
        if not self.solved and len(self.stacks[2]) == self.n:
            self.solved = True
            if self.hud:
                try: self.hud.text = "Solved in {}!  Press K9".format(self.moves)
                except Exception: pass
            self._update_leds(win=True)
            for f, d in ((523,0.05),(659,0.05),(784,0.05),(1046,0.08)):
                self._beep(f, d)

    # ---- LED helpers ----
    def _update_leds(self, win=False):
        if not self.leds: return
        try:
            self.leds.fill(self._LED_OFF)

            # Function keys
            self.leds[9]  = self._LED_K9      # Yellow (tick() will pulse on win)
            self.leds[10] = self._LED_K10     # Cyan

            cols = (
                (0, [0, 3, 6]),  # Column 0 (Red)
                (1, [1, 4, 7]),  # Column 1 (Green)
                (2, [2, 5, 8]),  # Column 2 (Blue)
            )

            # Base dim glow per column
            for ci, keys in cols:
                for k in keys:
                    self.leds[k] = self._COLORS_DIM[ci]

            if win:
                # Celebrate: brighten all column keys
                for ci, keys in cols:
                    for k in keys:
                        self.leds[k] = self._COLORS_BRIGHT[ci]
                self._led_show()
                return

            # Selection & legal targets
            if self.selected is not None and self.stacks[self.selected]:
                for k in cols[self.selected][1]:
                    self.leds[k] = self._COLORS_BRIGHT[self.selected]
                disk = self.stacks[self.selected][-1]
                for ci, keys in cols:
                    if ci == self.selected: 
                        continue
                    if (not self.stacks[ci]) or (self.stacks[ci][-1] > disk):
                        for k in keys:
                            self.leds[k] = self._COLORS_MED[ci]
            self._led_show()
        except Exception:
            pass

    def _scale(self, rgb, factor):
        r, g, b = rgb
        return (int(r * factor), int(g * factor), int(b * factor))

    # ---- Sound ----
    def _beep(self, freq, dur):
        if not self.pad: return
        try:
            self.pad.play_tone(freq, dur)
        except Exception:
            pass