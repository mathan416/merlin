# spin_the_bottle.py — Spin the Bottle
# CircuitPython 9.x — Merlin Launcher Compatible (Adafruit MacroPad RP2040)
# Written by Iain Bennett — 2025
#
# OVERVIEW
# ────────────────────────────────────────────────
# A modern Merlin Fusion take on the classic party game.
# Ten “seats” are arranged around the MacroPad’s 12-key layout, with idle
# rainbow-drifting LEDs and toggleable participation. Players can spin the
# bottle with K4 or K7, and suspense builds with acceleration, random
# deceleration, and even an optional “Blind Mode” where the LEDs black out
# during the spin.
#
# GAMEPLAY
# ────────────────────────────────────────────────
# • Toggle seats: tap a key (excluded = dim white, included = rainbow).
# • Spin:
#     – K4 short press → start spin
#     – K7 press       → start spin
#     – K4 long press  → toggle Blind Mode
# • Spin phases: acceleration → cruise → random deceleration → land.
# • Winner reveal:
#     – First: big “K#” for 3 seconds
#     – Then: small “Winner: K#” with replay/toggle prompts
# • Sounds: ticking tones speed with the spin; final “ding” marks the winner.
#
# FEATURES
# ────────────────────────────────────────────────
# • Launcher-compatible API: .group, .new_game(), .tick(),
#   .button(), .button_up(), .cleanup().
# • Idle rainbow drift animation across participating seats.
# • Trail LED effect during spin (bright → dim tail).
# • Blind Mode hides LEDs during spin for added suspense.
# • Defensive cleanup: clears LEDs, tones, and display safely before exit.
# • Optional MerlinChrome.bmp logo overlay if present.
#
# NOTES
# ────────────────────────────────────────────────
# • Uses const for hardware-safe literal ints.
# • Bitmaptools drawing is wrapped in defensive clamps and fallbacks.
# • Written for resilience: hardware/firmware errors degrade gracefully.

import math, time, random
import displayio, terminalio
import bitmaptools
from micropython import const
try:
    from adafruit_display_text import label
    HAVE_LABEL = True
except Exception:
    HAVE_LABEL = False

# ---------- Literal-int consts ONLY ----------
SCREEN_W    = const(128)
SCREEN_H    = const(64)
BG          = const(0)
FG          = const(1)

SHOW_LOGO   = True  # bool is fine as a plain variable

PROMPT_Y1   = const(38)
PROMPT_Y2   = const(50)

# Keys
PARTY_KEYS = (0, 1, 2, 5, 8, 11, 10, 9, 6, 3)  # K0→K1→K2→K5→K8→K11→K10→K9→K6→K3→loop
NUM_SEATS  = len(PARTY_KEYS)
K_START_A  = const(4)   # K4 -> start + long-press blind toggle
K_START_B  = const(7)   # K7 -> start

# Spin dynamics
ACCEL_STEPS     = const(24)
MIN_STEP_MS     = const(40)
MAX_STEP_MS     = const(180)
DECEL_RANDOM_MS = (600, 1400)

# LED levels
DIM_EXCLUDED    = const(8)
DIM_INCLUDED    = const(40)

# Idle rainbow drift
IDLE_HUE_STEP   = const(1)
IDLE_TICK_MS    = const(50)

# Long-press
LONG_PRESS_SEC  = 1.0

# Sound (play_tone uses seconds)
WINNER_FREQ     = 784
TICK_MIN_FREQ   = 400
TICK_RANGE      = 800
TICK_DUR_SEC    = 0.01
DING_DUR_SEC    = 0.28

# ---------- Defensive bitmaptools helpers ----------
def _clamp(val, lo, hi):
    if val < lo: return lo
    if val > hi: return hi
    return val

def _hline(bmp, x0, x1, y, color):
    if not bmp: return
    try:
        W, H = bmp.width, bmp.height
    except Exception:
        return
    if y < 0 or y >= H: return
    if x0 > x1: x0, x1 = x1, x0
    x0 = _clamp(x0, 0, W - 1)
    x1 = _clamp(x1, 0, W - 1)
    try:
        bitmaptools.draw_line(bmp, x0, y, x1, y, color)
    except Exception:
        for x in range(x0, x1 + 1):
            try: bmp[x, y] = color
            except Exception: pass

def _vline(bmp, x, y0, y1, color):
    if not bmp: return
    try:
        W, H = bmp.width, bmp.height
    except Exception:
        return
    if x < 0 or x >= W: return
    if y0 > y1: y0, y1 = y1, y0
    y0 = _clamp(y0, 0, H - 1)
    y1 = _clamp(y1, 0, H - 1)
    try:
        bitmaptools.draw_line(bmp, x, y0, x, y1, color)
    except Exception:
        for y in range(y0, y1 + 1):
            try: bmp[x, y] = color
            except Exception: pass

def _rect_fill(bmp, x, y, w, h, color):
    if not bmp: return
    try:
        W, H = bmp.width, bmp.height
    except Exception:
        return
    if w <= 0 or h <= 0: return
    x0 = _clamp(x,     0, W)
    y0 = _clamp(y,     0, H)
    x1 = _clamp(x + w, 0, W)
    y1 = _clamp(y + h, 0, H)
    if x1 <= x0 or y1 <= y0: return
    try:
        bitmaptools.fill_region(bmp, x0, y0, x1 - x0, y1 - y0, color)
    except Exception:
        for yy in range(y0, y1):
            _hline(bmp, x0, x1 - 1, yy, color)

def clear(bmp):
    _rect_fill(bmp, 0, 0, getattr(bmp, "width", 0), getattr(bmp, "height", 0), BG)

# HSV->RGB (0..255)
def hsv_to_rgb(h, s=255, v=255):
    h = h & 0xFF
    i = h // 43
    f = (h - 43*i) * 6
    p = (v * (255 - s)) // 255
    q = (v * (255 - (s * f)//256)) // 255
    t = (v * (255 - (s * (255 - f))//256)) // 255
    if i == 0:   r,g,b = v, t, p
    elif i == 1: r,g,b = q, v, p
    elif i == 2: r,g,b = p, v, t
    elif i == 3: r,g,b = p, q, v
    elif i == 4: r,g,b = t, p, v
    else:        r,g,b = v, p, q
    return (int(r), int(g), int(b))

# ---------- LED helper ----------
class LedDriver:
    def __init__(self, pixels, party_keys):
        self.pixels = pixels
        self.have   = pixels is not None
        self.party  = tuple(party_keys)
        self.shadow = [(0,0,0)] * 12
        # (removed stray self.result_ready_at)

    def _apply(self):
        if not self.have: return
        for i, c in enumerate(self.shadow):
            self.pixels[i] = c
        try: self.pixels.show()
        except Exception: pass

    def idle_map(self, colors_rgb, participating_mask):
        for i in range(12): self.shadow[i] = (0,0,0)
        for si, key in enumerate(self.party):
            if participating_mask[si]:
                r,g,b = colors_rgb[si]
                self.shadow[key] = ((r*DIM_INCLUDED)//255,
                                    (g*DIM_INCLUDED)//255,
                                    (b*DIM_INCLUDED)//255)
            else:
                self.shadow[key] = (DIM_EXCLUDED, DIM_EXCLUDED, DIM_EXCLUDED)
        self.shadow[K_START_A] = (6,6,6)
        self.shadow[K_START_B] = (6,6,6)
        self._apply()

    def trail_map(self, colors_rgb, participating_mask, curr_seat, bright=255):
        self.idle_map(colors_rgb, participating_mask)
        if bright < 1: bright = 1
        if bright > 255: bright = 255
        key_now   = self.party[curr_seat]
        key_prev1 = self.party[(curr_seat - 1) % NUM_SEATS]
        key_prev2 = self.party[(curr_seat - 2) % NUM_SEATS]
        def scale(rgb, s):
            r = (rgb[0] * s) // 255
            g = (rgb[1] * s) // 255
            b = (rgb[2] * s) // 255
            return ((r * bright) // 255, (g * bright) // 255, (b * bright) // 255)
        self.shadow[key_now]   = scale(colors_rgb[curr_seat], 255)
        self.shadow[key_prev1] = scale(colors_rgb[(curr_seat-1) % NUM_SEATS], 120)
        self.shadow[key_prev2] = scale(colors_rgb[(curr_seat-2) % NUM_SEATS],  60)
        self._apply()

    def celebrate(self, colors_rgb, participating_mask, curr_seat, bright=255):
        self.idle_map(colors_rgb, participating_mask)
        if bright < 1: bright = 1
        if bright > 255: bright = 255
        key_now = self.party[curr_seat]
        r,g,b = colors_rgb[curr_seat]
        self.shadow[key_now] = ((r * bright)//255, (g * bright)//255, (b * bright)//255)
        self._apply()

    def blackout(self):
        if not self.have: return
        for i in range(12): self.pixels[i] = (0,0,0)
        try: self.pixels.show()
        except Exception: pass

# ---------- Game ----------
class spin_bottle:
    NAME = "Spin the Bottle"
    supports_double_encoder_exit = False

    def __init__(self, macropad=None, *args, **kwargs):
        self.macropad = macropad
        self.pixels   = getattr(macropad, "pixels", None) if macropad else None

        # Canvas
        self.bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
        self.pal = displayio.Palette(2); self.pal[BG] = 0x000000; self.pal[FG] = 0xFFFFFF
        self.tg  = displayio.TileGrid(self.bmp, pixel_shader=self.pal)
        self.group = displayio.Group()
        self.group.append(self.tg)

        # Merlin logo (above canvas so it’s visible)
        if SHOW_LOGO:
            try:
                logo = displayio.OnDiskBitmap("MerlinChrome.bmp")
                tile = displayio.TileGrid(
                    logo, pixel_shader=getattr(logo, "pixel_shader", displayio.ColorConverter())
                )
                self.group.append(tile)
            except Exception:
                pass

        self._make_labels()

        self.key_to_seat = {k:i for i,k in enumerate(PARTY_KEYS)}
        self.seat_to_key = list(PARTY_KEYS)

        self.leds = LedDriver(self.pixels, PARTY_KEYS)

        # Rainbow
        self.base_hues   = [int(i*(256//NUM_SEATS)) for i in range(NUM_SEATS)]
        self.hue_offset  = 0
        self.last_idle_ms = 0

        # State
        self.participating = [True]*NUM_SEATS
        self.state = "idle"
        self.curr_seat = 0
        self.step_ms = MAX_STEP_MS
        self.accel_count = 0
        self.decel_until = 0.0
        self.results = []
        self.rng = random

        # Winner reveal timer init (needed for reveal->result)
        self.result_ready_at = 0.0

        # Options
        self.blind_mode = False
        self.k4_down_at = None

    def new_game(self):
        self.state = "idle"
        self.results.clear()
        self.curr_seat = 0
        self.step_ms = MAX_STEP_MS
        self.accel_count = 0
        self.decel_until = 0.0
        self.hue_offset = 0
        self.last_idle_ms = int(time.monotonic()*1000)
        self.blind_mode = False
        self.k4_down_at = None
        self.result_ready_at = 0.0
        self._draw_all()
        self._led_idle()

    def tick(self):
        now = time.monotonic()
        now_ms = int(now*1000)

        if self.state == "idle":
            if (now_ms - self.last_idle_ms) >= IDLE_TICK_MS:
                self.hue_offset = (self.hue_offset + IDLE_HUE_STEP) & 0xFF
                self._led_idle()
                self.last_idle_ms = now_ms
            if self.k4_down_at and (now - self.k4_down_at) >= LONG_PRESS_SEC:
                self.blind_mode = not self.blind_mode
                self.k4_down_at = None
                self._draw_all()
                self._led_idle()

        elif self.state == "reveal":
            # after 3 sec, switch to small “Winner: K#” message
            if now >= self.result_ready_at:
                self.state = "result"
                self._draw_all()

        elif self.state == "spinning":
            if now >= self.next_step_at:
                self._advance_pointer()
                if self.accel_count < ACCEL_STEPS:
                    t = self.accel_count / float(ACCEL_STEPS)
                    self.step_ms = int(MAX_STEP_MS - (MAX_STEP_MS - MIN_STEP_MS)*t)
                    self.accel_count += 1
                elif now >= self.decel_until:
                    self.step_ms = min(MAX_STEP_MS, int(self.step_ms * 1.10))
                    if self.step_ms >= MAX_STEP_MS - 5 and self.participating[self.curr_seat]:
                        self._land(self.curr_seat)
                        return
                self.next_step_at = now + (self.step_ms / 1000.0)

    def button(self, key):
        if key in (K_START_A, K_START_B):
            if self.state == "idle":
                if key == K_START_A:
                    # K4: arm long-press; don't start yet
                    self.k4_down_at = time.monotonic()
                else:
                    # K7: immediate spin
                    self.results.clear()
                    self._begin_spin()
            elif self.state == "spinning":
                self.decel_until = time.monotonic()
            elif self.state in ("result", "reveal"):
                self.results.clear()
                self._begin_spin()
            return

        if self.state in ("idle", "result") and key in self.key_to_seat:
            si = self.key_to_seat[key]
            self.participating[si] = not self.participating[si]
            if not any(self.participating):
                self.participating[si] = True
            self.results = [r for r in self.results if self.participating[r]]
            self._draw_all()
            self._led_idle()

    def button_up(self, key):
        if key == K_START_A:
            # If we released before long-press threshold AND still idle → short press = spin
            if self.state == "idle" and self.k4_down_at is not None:
                if (time.monotonic() - self.k4_down_at) < LONG_PRESS_SEC:
                    self.results.clear()
                    self._begin_spin()
            self.k4_down_at = None

    def cleanup(self):
        # Reset timers/state that could keep logic alive
        self.result_ready_at = 0.0
        self.k4_down_at = None

        # Kill LEDs (defensive)
        try:
            self.leds.blackout()
        except Exception:
            pass

        # Stop any lingering tone if the platform supports it
        try:
            stop = getattr(self.macropad, "stop_tone", None)
            if callable(stop):
                stop()
        except Exception:
            pass

        # Clear UI text & canvas, but keep the display group intact for the launcher
        try:
            clear(self.bmp)
        except Exception:
            pass
        if HAVE_LABEL:
            try:
                self.label1.text = ""
                self.label2.text = ""
                self.big_label.text = ""
            except Exception:
                pass

    # ----- internals -----
    def _make_labels(self):
        self.label1 = None; self.label2 = None; self.big_label = None
        if HAVE_LABEL:
            self.label1 = label.Label(
                terminalio.FONT, text="", color=0xFFFFFF, scale=1,
                anchored_position=(SCREEN_W//2, PROMPT_Y1), anchor_point=(0.5, 0.0)
            )
            self.label2 = label.Label(
                terminalio.FONT, text="", color=0xFFFFFF, scale=1,
                anchored_position=(SCREEN_W//2, PROMPT_Y2), anchor_point=(0.5, 0.0)
            )
            self.big_label = label.Label(
                terminalio.FONT, text="", color=0xFFFFFF, scale=2,
                anchored_position=(SCREEN_W//2, 56), anchor_point=(0.5, 1.0)
            )
            self.group.append(self.label1)
            self.group.append(self.label2)
            self.group.append(self.big_label)

    def _prompt(self, t1, t2):
        if HAVE_LABEL:
            self.label1.text = t1
            self.label2.text = t2

    def _draw_all(self):
        clear(self.bmp)

        if self.state == "idle":
            blind = " [BLIND]" if self.blind_mode else ""
            self._prompt("Spin the Bottle"+blind, "Spin   Toggle")
            if HAVE_LABEL: self.big_label.text = ""
        elif self.state == "spinning":
            self._prompt("Spinning...", "Slam stop")
            if HAVE_LABEL: self.big_label.text = ""
        elif self.state == "reveal":
            # Big K# only, no small text
            k = self.seat_to_key[self.results[0]]
            if HAVE_LABEL:
                self.label1.text = ""
                self.label2.text = ""
                self.big_label.text = f"K{k}"
        else:  # "result"
            # Small “Winner: K#” message; big text cleared
            k = self.seat_to_key[self.results[0]]
            self._prompt("Winner:", f"K{k}  Spin   Toggle")
            if HAVE_LABEL: self.big_label.text = ""

    def _colors_for_idle(self):
        return [hsv_to_rgb((h0 + self.hue_offset) & 0xFF, 255, 255) for h0 in self.base_hues]

    def _led_idle(self):
        self.leds.idle_map(self._colors_for_idle(), self.participating)

    def _begin_spin(self):
        if not any(self.participating):
            self.participating = [True]*NUM_SEATS
        self.state = "spinning"
        if not self.participating[self.curr_seat]:
            self.curr_seat = self._next_active(self.curr_seat)
        self.accel_count = 0
        self.step_ms = MAX_STEP_MS
        now = time.monotonic()
        self.next_step_at = now + (self.step_ms/1000.0)
        self.decel_until = now + (ACCEL_STEPS*self.step_ms/1000.0) + \
                           self.rng.uniform(DECEL_RANDOM_MS[0]/1000.0, DECEL_RANDOM_MS[1]/1000.0)
        self._draw_all()

    def _advance_pointer(self):
        self.curr_seat = (self.curr_seat + 1) % NUM_SEATS
        self._draw_all()

        denom = (MAX_STEP_MS - MIN_STEP_MS)
        speed_factor = (MAX_STEP_MS - self.step_ms) / denom if denom else 0.0
        if speed_factor < 0: speed_factor = 0.0
        if speed_factor > 1: speed_factor = 1.0
        spin_bright = 100 + int(155 * speed_factor)

        if not self.blind_mode:
            self.leds.trail_map(self._colors_for_idle(), self.participating, self.curr_seat, bright=spin_bright)
        else:
            self.leds.blackout()

        if self.macropad:
            try:
                freq = TICK_MIN_FREQ + int(TICK_RANGE * speed_factor)
                self.macropad.play_tone(freq, TICK_DUR_SEC)
            except Exception:
                pass

    def _land(self, seat_idx):
        if not self.participating[seat_idx]:
            seat_idx = self._next_active(seat_idx)

        self.curr_seat = seat_idx
        self.results = [seat_idx]

        colors = self._colors_for_idle()
        if not self.blind_mode:
            for ramp in (180, 220, 255):
                self.leds.blackout(); time.sleep(0.08)
                self.leds.celebrate(colors, self.participating, seat_idx, bright=ramp); time.sleep(0.12)
        self.leds.celebrate(colors, self.participating, seat_idx, bright=255)
        if self.macropad:
            try: self.macropad.play_tone(WINNER_FREQ, DING_DUR_SEC)
            except Exception: pass

        # Show ONLY the big K# for 3 seconds
        self.state = "reveal"
        self.result_ready_at = time.monotonic() + 3.0
        self._draw_all()

    def _next_active(self, start):
        j = (start + 1) % NUM_SEATS
        for _ in range(NUM_SEATS):
            if self.participating[j]:
                return j
            j = (j + 1) % NUM_SEATS
        return start