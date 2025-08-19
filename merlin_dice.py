# ---------- Main ----------
# merlin_dice.py — Merlin Dice (CircuitPython 9.x, Merlin Launcher)

import math, time, json, gc
import displayio, bitmaptools, terminalio
from micropython import const
import random as _random

def _rand_uniform(a, b):
    try:
        return _random.uniform(a, b)
    except AttributeError:
        return a + (_random.random() * (b - a))

def _randint_inclusive(lo, hi):
    try:
        return _random.randint(lo, hi)
    except AttributeError:
        r = int(_random.random() * (hi - lo + 1)) + lo
        if r < lo: r = lo
        if r > hi: r = hi
        return r

try:
    from adafruit_display_text import label
    HAVE_LABEL = True
except Exception:
    HAVE_LABEL = False

try:
    import rainbowio
except Exception:
    rainbowio = None

# ---------- Tunables ----------
SCREEN_W, SCREEN_H = const(128), const(64)
PROMPT_Y2 = const(51)

# Keys (your mapping)
K_UP, K_LEFT, K_RIGHT, K_DOWN = 1, 3, 5, 7
K_SPIN, K_MODE = 9, 11
K_ADV = 2

# Dice bounds
MIN_SIDES, MAX_SIDES = const(2), const(20)

# Spin timing
SPIN_TIME_MIN = 0.45
SPIN_TIME_MAX = 1.10

# Files
SETTINGS_PATH = "/merlin_dice_settings.json"

# Safe math tau
TAU = getattr(math, "tau", 2.0 * math.pi)
IDLE_ANGLE = TAU * 0.125  # 45° = π/4

# Roll modes
RM_NORMAL, RM_ADV, RM_DIS = 0, 1, 2
ROLLMODE_NAMES = ("Norm", "Adv", "Dis")

# Themes (name, tuple of LED colors)
THEMES = [
    ("Medieval", (0x803000, 0xC09040, 0xFFD080)),
    ("Sci-Fi",   (0x0030A0, 0x20C0FF, 0x80F0FF)),
    ("Neon",     (0x700070, 0x00FF90, 0xFF40D0)),
    ("Runic",    (0x204020, 0x80FF80, 0xC0FFC0)),
    ("Arcade",   (0x202020, 0xFFFFFF, 0x80C0FF)),
    ("Steampunk",(0x4A2C0A, 0xC88733, 0xE6C58C)),
    ("Crystal",  (0xA0E0FF, 0xD8F7FF, 0xF0FFFF)),
    ("CyberRune",(0x00FFD8, 0x80FFEA, 0xFFFFFF)),
    ("Minimal",  (0xFFFFFF, 0xA0A0A0, 0x404040)),
]

# Quick picks
COMMON_DICE = [4, 6, 8, 10, 12, 20]

# ---------- Button mapping ----------
BUTTON_ACTIONS = {
    K_UP: "up",
    K_LEFT: "left",
    K_RIGHT: "right",
    K_DOWN: "down",
    K_SPIN: "spin",
    K_MODE: "mode",
    K_ADV: "adv",
}

# ---------- Fast surface helpers ----------
def make_surface():
    bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
    pal = displayio.Palette(2)
    pal[0] = 0x000000
    pal[1] = 0xFFFFFF
    return bmp, pal

def clear(bmp):
    try:
        bitmaptools.fill_region(bmp, 0, 0, SCREEN_W, SCREEN_H, 0)
    except Exception:
        for y in range(SCREEN_H):
            for x in range(SCREEN_W):
                bmp[x, y] = 0

def putpixel(bmp, x, y, c=1):
    if 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
        bmp[x, y] = c

def _safe_fill_region(bmp, x, y, w, h, c=1):
    if w <= 0 or h <= 0: return
    if x < 0: w += x; x = 0
    if y < 0: h += y; y = 0
    if x >= SCREEN_W or y >= SCREEN_H: return
    if x + w > SCREEN_W: w = SCREEN_W - x
    if y + h > SCREEN_H: h = SCREEN_H - y
    if w <= 0 or h <= 0: return
    try:
        bitmaptools.fill_region(bmp, int(x), int(y), int(w), int(h), int(c))
    except Exception:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                putpixel(bmp, xx, yy, c)

def _hline(bmp, x0, x1, y, c=1):
    if y < 0 or y >= SCREEN_H: return
    if x0 > x1: x0, x1 = x1, x0
    if x1 < 0 or x0 >= SCREEN_W: return
    if x0 < 0: x0 = 0
    if x1 >= SCREEN_W: x1 = SCREEN_W - 1
    _safe_fill_region(bmp, x0, y, (x1 - x0 + 1), 1, c)

def _vline(bmp, x, y0, y1, c=1):
    if x < 0 or x >= SCREEN_W: return
    if y0 > y1: y0, y1 = y1, y0
    if y1 < 0 or y0 >= SCREEN_H: return
    if y0 < 0: y0 = 0
    if y1 >= SCREEN_H: y1 = SCREEN_H - 1
    _safe_fill_region(bmp, x, y0, 1, (y1 - y0 + 1), c)

def line(bmp, x0, y0, x1, y1, c=1):
    dx = abs(x1 - x0); dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        putpixel(bmp, x0, y0, c)
        if x0 == x1 and y0 == y1: break
        e2 = 2 * err
        if e2 >= dy: err += dy; x0 += sx
        if e2 <= dx: err += dx; y0 += sy

def rect(bmp, x, y, w, h, c=1):
    if w <= 0 or h <= 0: return
    _hline(bmp, x, x + w - 1, y, c)
    _hline(bmp, x, x + w - 1, y + h - 1, c)
    _vline(bmp, x, y, y + h - 1, c)
    _vline(bmp, x + w - 1, y, y + h - 1, c)

# ---------- 3D cube wireframe ----------
CUBE_EDGES = [
    (0,1),(1,2),(2,3),(3,0),
    (4,5),(5,6),(6,7),(7,4),
    (0,4),(1,5),(2,6),(3,7),
]
CUBE_VERTS = [
    (-1,-1,-1),( 1,-1,-1),( 1, 1,-1),(-1, 1,-1),
    (-1,-1, 1),( 1,-1, 1),( 1, 1, 1),(-1, 1, 1),
]

# ---- Incremental/cropped cube drawing helpers ----
TOP_MARGIN = 1
SIDE_MARGIN = 2
BOTTOM_PAD   = 2
CONTENT_BOTTOM = PROMPT_Y2 - BOTTOM_PAD

CUBE_CLIP = (
    SIDE_MARGIN,
    TOP_MARGIN,
    SCREEN_W - 2*SIDE_MARGIN,
    max(0, CONTENT_BOTTOM - TOP_MARGIN)
)

def _clip_center():
    cx, cy, cw, ch = CUBE_CLIP
    return cx + cw // 2, cy + ch // 2

def _in_clip(x, y, clip):
    cx, cy, cw, ch = clip
    return (cx <= x < cx+cw) and (cy <= y < cy+ch)

def putpixel_clip(bmp, x, y, c, clip):
    if _in_clip(x, y, clip):
        bmp[x, y] = c

def line_clip(bmp, x0, y0, x1, y1, c, clip):
    dx = abs(x1 - x0); dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        putpixel_clip(bmp, x0, y0, c, clip)
        if x0 == x1 and y0 == y1: break
        e2 = 2 * err
        if e2 >= dy: err += dy; x0 += sx
        if e2 <= dx: err += dx; y0 += sy

def draw_cube_edges(bmp, edges, color, clip):
    for x0, y0, x1, y1 in edges:
        line_clip(bmp, x0, y0, x1, y1, color, clip)

# ---- DEMOSCENE-style projection ----
_ZOFF = 260.0
_NEAR = 30.0
_SCALE = 180.0

def _cube_halfsize():
    _, _, cw, ch = CUBE_CLIP
    # Slightly conservative factor to keep all projected edges within CUBE_CLIP
    return max(8, int(min(cw, ch) * 0.40))

def compute_cube_edges_demoscene(t):
    _S = _cube_halfsize()
    CXC, CYC = _clip_center()
    ca, sa = math.cos(t), math.sin(t)
    cb, sb = math.cos(t * 0.7 + 1.1), math.sin(t * 0.7 + 1.1)

    proj = []
    for (x, y, z) in CUBE_VERTS:
        x *= _S; y *= _S; z *= _S
        xz = x * ca - y * sa
        yz = x * sa + y * ca
        y2 = yz * cb - z * sb
        z2 = yz * sb + z * cb
        denom = z2 + _ZOFF
        if denom < _NEAR: denom = _NEAR
        d = _SCALE / denom
        px = int(CXC + xz * d)
        py = int(CYC + y2 * d)
        proj.append((px, py))
    return [(proj[a][0], proj[a][1], proj[b][0], proj[b][1]) for a, b in CUBE_EDGES]

# ---------- LED helpers (module-level) ----------
def _scale_color(color, f):
    if f <= 0: return 0
    if f >= 1: return color & 0xFFFFFF
    r = int(((color >> 16) & 0xFF) * f + 0.5)
    g = int(((color >> 8)  & 0xFF) * f + 0.5)
    b = int(( color        & 0xFF) * f + 0.5)
    if r > 255: r = 255
    if g > 255: g = 255
    if b > 255: b = 255
    return (r << 16) | (g << 8) | b

def _mix_color(c0, c1, t):
    """Linear blend between two 0xRRGGBB colors."""
    if t <= 0: return c0 & 0xFFFFFF
    if t >= 1: return c1 & 0xFFFFFF
    r0 = (c0 >> 16) & 0xFF; g0 = (c0 >> 8) & 0xFF; b0 = c0 & 0xFF
    r1 = (c1 >> 16) & 0xFF; g1 = (c1 >> 8) & 0xFF; b1 = c1 & 0xFF
    r = int(r0 + (r1 - r0) * t + 0.5)
    g = int(g0 + (g1 - g0) * t + 0.5)
    b = int(b0 + (b1 - b0) * t + 0.5)
    return (r << 16) | (g << 8) | b

# ---------- LEDs ----------
def led_wheel(n, theme_colors):
    return theme_colors[n % len(theme_colors)] if rainbowio else 0xFFFFFF

def set_leds(macropad, color=None, index=None, theme_colors=None):
    if not hasattr(macropad, "pixels"): return
    if color is not None:
        for i in range(12): macropad.pixels[i] = color
        macropad.pixels.show(); return
    if index is not None and theme_colors is not None:
        for i in range(12): macropad.pixels[i] = 0x000000
        macropad.pixels[index % 12] = led_wheel(index, theme_colors)
        macropad.pixels.show()

# ---------- Labels ----------
def make_label(text, x, y, scale=1):
    if HAVE_LABEL:
        return label.Label(terminalio.FONT, text=text, color=0xFFFFFF,
                           scale=scale, anchor_point=(0,0),
                           anchored_position=(x, y))
    return None

class merlin_dice:
    def __init__(self, macropad=None, display=None, **kwargs):
        self.macropad = macropad
        self.display = display
        self.group = displayio.Group()
        self._ang0 = 0.0
        self._ang1 = 0.0

        # Game surface
        self.bmp, self.pal = make_surface()
        self.tg = displayio.TileGrid(self.bmp, pixel_shader=self.pal)
        self.group.append(self.tg)
        gc.collect()

        # Prompts
        self.lbl_btm = make_label("", 2, PROMPT_Y2, 1)
        if self.lbl_btm: self.group.append(self.lbl_btm)

        # State
        self.sides = 20
        self.theme_idx = 0
        self.roll_mode = RM_NORMAL
        self.last_roll = None
        self.last_detail = None
        self.spinning = False
        self.spin_t0 = 0.0
        self.spin_t1 = 0.0
        self.spinner_led_idx = 0

        # Result/ack screen
        self.awaiting_ack = False

        # Incremental cube state
        self._cube_prev_edges = []  # list of (x0,y0,x1,y1)

        # LED animation state
        self._t_last = time.monotonic()
        self._led_phase = 0.0
        self._led_width = 7.0
        self._led_floor = 0.18
        self._crit_t0 = None
        self._crit_duration = 1.2
        self._crit_cycles = 2.0
        self._crit_color = 0x000000

        # Cached LED buffer for fades (fallback if hardware read is not supported)
        self._led_buf = [0x000000] * 12

        # Load settings
        self._load_settings()

        # Initial draw
        self._redraw_static()
        self._update_prompts()
        gc.collect()

        # LED UX state
        self._key_flash_until = {}
        self._result_until = 0
        self._update_leds_idle()

    # Launcher API
    def new_game(self, **kwargs):
        self.last_roll = None
        self.last_detail = None
        self.spinning = False
        self.awaiting_ack = False
        self._cube_prev_edges = []
        set_leds(self.macropad, color=0x000000)
        self._redraw_static()
        self._update_prompts()
        self._key_flash_until.clear()
        self._result_until = 0
        self._update_leds_idle()

    def cleanup(self):
        set_leds(self.macropad, color=0x000000)
        self._save_settings()

    def button(self, *args, **kwargs):
        k = None
        pressed = kwargs.get("pressed", None)

        if len(args) == 1:
            ev = args[0]
            if hasattr(ev, "key") or hasattr(ev, "key_number") or hasattr(ev, "key_id"):
                k = getattr(ev, "key", None)
                if k is None:
                    k = getattr(ev, "key_number", getattr(ev, "key_id", None))
                if pressed is None:
                    pressed = getattr(ev, "pressed", True)
            else:
                k = ev
                if pressed is None:
                    pressed = True
        elif len(args) >= 2:
            k, pressed = args[0], args[1]
        else:
            return

        pressed = bool(pressed)
        if not pressed or k is None:
            return

        action = BUTTON_ACTIONS.get(k)
        if action is None:
            return

        # If showing a result, only MODE dismisses (without changing theme)
        if self.awaiting_ack:
            if action == "spin":
                self.awaiting_ack = False
                self._flash_key(K_SPIN)
                self._start_spin()
            elif action == "mode":
                self.awaiting_ack = False
                self._redraw_static()
                self._update_prompts()
                self._update_leds_idle()
                self._flash_key(K_MODE)
            return

        if self.spinning and action not in ("mode", "adv"):
            return

        if action == "left":
            self.sides = max(MIN_SIDES, self.sides - 1)
            self._update_prompts(); self._flash_key(k)
        elif action == "right":
            self.sides = min(MAX_SIDES, self.sides + 1)
            self._update_prompts(); self._flash_key(k)
        elif action == "up":
            self._quick_next(); self._update_prompts(); self._flash_key(k)
        elif action == "down":
            self._quick_prev(); self._update_prompts(); self._flash_key(k)
        elif action == "mode":
            self.theme_idx = (self.theme_idx + 1) % len(THEMES)
            self._redraw_static(); self._update_prompts(); self._update_leds_idle(); self._flash_key(k)
        elif action == "adv":
            self.roll_mode = (self.roll_mode + 1) % 3
            self._update_prompts(); self._flash_key(k)
        elif action == "spin":
            if not self.spinning:
                self._flash_key(k); self._start_spin()

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        dt = now - self._t_last
        if dt < 0: dt = 0
        self._t_last = now

        # ----- Non-blocking crit pulse -----
        if self._crit_t0 is not None and hasattr(self.macropad, "pixels"):
            t = now - self._crit_t0
            if t < self._crit_duration:
                phase = (t / self._crit_duration) * self._crit_cycles
                phase -= int(phase)
                y = 1.0 - 0.5 * (1.0 + math.cos(math.pi * phase))  # 0→1→0
                b = self._led_floor + (1.0 - self._led_floor) * y
                col = _scale_color(self._crit_color, b)
                self._write_pixels([col]*12)
                return
            else:
                self._crit_t0 = None
                if self.last_roll is not None:
                    self._update_leds_result(self.last_roll)

        # ----- Spinning: demoscene wireframe + cosine LED chase -----
        if self.spinning:
            dur = self.spin_t1 - self.spin_t0
            u = (now - self.spin_t0) / dur if dur > 0 else 1.0
            if u < 0.0: u = 0.0
            if u > 1.0: u = 1.0
            e = self._ease_out_cubic(u)

            ang = self._ang0 + (self._ang1 - self._ang0) * e

            if self._cube_prev_edges:
                draw_cube_edges(self.bmp, self._cube_prev_edges, 0, CUBE_CLIP)
            edges = compute_cube_edges_demoscene(ang)
            draw_cube_edges(self.bmp, edges, 1, CUBE_CLIP)
            self._cube_prev_edges = edges

            if hasattr(self.macropad, "pixels"):
                base, accent, highlight = self._theme_triplet()
                head_color = accent
                omega = 6.0 * (1.0 - 0.5 * e)   # LEDs/sec; eases down
                self._led_phase = (self._led_phase + omega * dt) % 12.0

                cols = [0]*12
                for i in range(12):
                    d = (i - self._led_phase)
                    while d > 6.0:  d -= 12.0
                    while d < -6.0: d += 12.0
                    x = abs(d) / max(1e-6, self._led_width)
                    if x > 1.0:
                        w = 0.0
                    else:
                        w = 0.5 * (1.0 + math.cos(math.pi * x))
                    b = self._led_floor + (1.0 - self._led_floor) * w
                    cols[i] = _scale_color(head_color, b)
                self._write_pixels(cols)

            if now >= self.spin_t1:
                self._finish_spin()
            return

        # ----- Awaiting acknowledgement: freeze LEDs/scene -----
        if self.awaiting_ack:
            return

        # ----- Idle LED management / key flashes -----
        tnow = time.monotonic()
        if getattr(self, "_result_until", 0) and tnow > self._result_until:
            self._result_until = 0
            self._update_leds_idle()

        if getattr(self, "_key_flash_until", None):
            if self._key_flash_until:
                self._apply_key_flash_frame()

    # Internals
    def _clear_cube_area(self, pad=2):
        x, y, w, h = CUBE_CLIP
        x -= pad; y -= pad; w += pad * 2; h += pad * 2
        if x < 0: w += x; x = 0
        if y < 0: h += y; y = 0
        if x + w > SCREEN_W: w = SCREEN_W - x
        if y + h > SCREEN_H: h = SCREEN_H - y
        if w > 0 and h > 0:
            _safe_fill_region(self.bmp, x, y, w, h, 0)

    def _start_spin(self):
        self.spinning = True
        dur = _rand_uniform(SPIN_TIME_MIN, SPIN_TIME_MAX)
        self.spin_t0 = time.monotonic()
        self.spin_t1 = self.spin_t0 + dur

        # Start exactly at idle (45°) and end exactly at idle (45° + N full turns)
        self._ang0 = IDLE_ANGLE
        turns = _randint_inclusive(4, 7)      # whole turns for a clean landing
        self._ang1 = IDLE_ANGLE + turns * TAU

        # Redraw static frame WITHOUT an idle cube, then clear cube area with margin.
        self._redraw_static()
        self._clear_cube_area(pad=2)
        self._cube_prev_edges = []  # nothing to erase on first animated frame

        # LED wave: start aligned with K9-ish visually
        self._led_phase = float(K_SPIN % 12)

        self._update_prompts(spinning=True)

    def _finish_spin(self):
        self.spinning = False

        # Erase last cube if any
        if self._cube_prev_edges:
            draw_cube_edges(self.bmp, self._cube_prev_edges, 0, CUBE_CLIP)
            self._cube_prev_edges = []

        # --- Roll logic with Adv/Dis ---
        a = _randint_inclusive(1, self.sides)
        if self.roll_mode == RM_NORMAL:
            chosen, b = a, None
        else:
            b = _randint_inclusive(1, self.sides)
            chosen = max(a, b) if self.roll_mode == RM_ADV else min(a, b)

        self.last_roll = chosen
        self.last_detail = (a, b, chosen) if b is not None else None

        # Start non-blocking crit pulse if d20 nat 20 / nat 1
        if self.sides == 20 and (chosen == 20 or chosen == 1) and hasattr(self.macropad, "pixels"):
            self._crit_color = 0x00FF00 if chosen == 20 else 0xFF0000
            self._crit_t0 = time.monotonic()
        else:
            self._update_leds_result(chosen)

        # Result screen: keep frame, hide cube, draw number (only update cube area)
        self._clear_cube_area()
        self._draw_big_number(chosen)
        if self.roll_mode != RM_NORMAL and self.last_detail:
            a, b, chosen = self.last_detail
            self._draw_adv_dis_markers(a, b, chosen, self.roll_mode)

        self._update_prompts(result=chosen)
        self.awaiting_ack = True

    # ----- LED composition + fading -----
    def _read_pixels(self):
        """Try to read current hardware LEDs; fallback to cached buffer."""
        if not hasattr(self.macropad, "pixels"):
            return self._led_buf[:]
        try:
            out = []
            for i in range(12):
                v = self.macropad.pixels[i]
                if isinstance(v, tuple) and len(v) == 3:
                    r, g, b = v
                    out.append((int(r) << 16) | (int(g) << 8) | int(b))
                else:
                    out.append(int(v) & 0xFFFFFF)
            return out
        except Exception:
            return self._led_buf[:]

    def _write_pixels(self, colors):
        """Write list[int RGB] to hardware and cache."""
        if hasattr(self.macropad, "pixels"):
            for i, col in enumerate(colors[:12]):
                self.macropad.pixels[i] = col & 0xFFFFFF
            self.macropad.pixels.show()
        self._led_buf = colors[:12] + [0]*(12 - len(colors[:12]))

    def _compose_leds_idle(self):
        cols = [0x000000]*12
        used = (K_UP, K_LEFT, K_RIGHT, K_DOWN, K_SPIN, K_MODE, K_ADV)
        for k in used:
            if 0 <= k < 12:
                cols[k] = self._btn_color_idle(k)
        return cols

    def _compose_leds_result(self, chosen):
        theme_colors = THEMES[self.theme_idx][1]
        _, _, highlight = self._theme_triplet()
        cols = [0x000000]*12
        cols[chosen % 12] = led_wheel(chosen, theme_colors)
        if 0 <= K_SPIN < 12:
            cols[K_SPIN] = highlight
        if 0 <= K_MODE < 12:
            cols[K_MODE] = highlight
        return cols

    def _fade_to_colors(self, target_colors, duration=0.18, steps=16):
        """
        Smooth crossfade from current -> target (no fade-to-black).
        Cosine ease-in-out for a gentle feel.
        """
        if not hasattr(self.macropad, "pixels"):
            self._write_pixels(target_colors)
            return
        # Don't fight with spinner or crit pulse
        if self.spinning or self._crit_t0 is not None:
            self._write_pixels(target_colors)
            return

        current = self._read_pixels()
        tgt = (target_colors[:12] + [0x000000] * 12)[:12]
        cur = (current[:12] + [0x000000] * 12)[:12]

        # Time per step
        dt = 0.0
        if steps > 0 and duration > 0:
            dt = duration / float(steps)

        for s in range(0, steps + 1):
            # Cosine ease-in-out: 0→1 smoothly
            t = s / float(steps) if steps else 1.0
            t_eased = 0.5 - 0.5 * math.cos(math.pi * t)

            frame = [_mix_color(cur[i], tgt[i], t_eased) for i in range(12)]
            self._write_pixels(frame)
            if dt > 0:
                time.sleep(dt)

    def _update_leds_idle(self):
        self._fade_to_colors(self._compose_leds_idle())

    def _update_leds_result(self, chosen):
        self._fade_to_colors(self._compose_leds_result(chosen))

    # ----- Drawing digits & UI text -----
    def _draw_big_number(self, n):
        self._draw_vector_digits(str(n))

    def _draw_vector_digits(self, s):
        CXC, CYC = _clip_center()
        W_PER = 16
        total_w = len(s) * W_PER - 2
        x0 = CXC - total_w // 2
        glyph_h = 20
        y0 = CYC - glyph_h // 2 + 3
        for idx, ch in enumerate(s):
            self._draw_digit(ch, x0 + idx * W_PER, y0)

    def _ease_out_cubic(self, u):
        if u <= 0: return 0.0
        if u >= 1: return 1.0
        t = 1.0 - u
        return 1.0 - (t * t * t)

    def _draw_digit(self, ch, x, y):
        if ch == '-':
            _hline(self.bmp, x + 1, x + 10, y + 9, 1)
            _hline(self.bmp, x + 1, x + 10, y + 10, 1)
            return
        try:
            d = int(ch)
        except Exception:
            return

        W, H = 12, 20
        T, M = 2, 1
        mid = y + (H // 2 - T // 2)
        xL  = x
        xR  = x + W - T
        yT  = y
        yB  = y + H - T
        yU0 = y + M;   yU1 = mid - 1
        yL0 = mid + 1; yL1 = y + H - M - 1

        def hbar(yy):
            _safe_fill_region(self.bmp, x + M, yy, W - 2 * M, T, 1)
        def vbar(xx, y0, y1):
            if y1 >= y0:
                _safe_fill_region(self.bmp, xx, y0, T, y1 - y0 + 1, 1)

        segs = {
            0: ('A','B','C','D','E','F'),
            1: ('B','C'),
            2: ('A','B','G','E','D'),
            3: ('A','B','G','C','D'),
            4: ('F','G','B','C'),
            5: ('A','F','G','C','D'),
            6: ('A','F','G','E','C','D'),
            7: ('A','B','C'),
            8: ('A','B','C','D','E','F','G'),
            9: ('A','B','C','D','F','G'),
        }

        s = segs.get(d, ())
        if 'A' in s: hbar(yT)
        if 'G' in s: hbar(mid)
        if 'D' in s: hbar(yB)
        if 'F' in s: vbar(xL, yU0, yU1)
        if 'B' in s: vbar(xR, yU0, yU1)
        if 'E' in s: vbar(xL, yL0, yL1)
        if 'C' in s: vbar(xR, yL0, yL1)

    # Tiny digits used elsewhere (e.g., legacy helpers)
    def _draw_tiny_digit(self, ch, x, y):
        try:
            d = int(ch)
        except:
            # Was: _hline(self.bmp, x, x + 4, y + 3, 1)
            return  # don't draw anything for non-digits

        if d == 0:
            rect(self.bmp, x, y, 5, 6, 1)
        elif d == 1:
            _vline(self.bmp, x + 2, y, y + 5, 1)
        elif d == 2:
            _hline(self.bmp, x, x + 4, y, 1); line(self.bmp, x + 4, y, x, y + 5, 1); _hline(self.bmp, x, x + 4, y + 5, 1)
        elif d == 3:
            _hline(self.bmp, x, x + 4, y, 1); _vline(self.bmp, x + 4, y, y + 5, 1)
            _hline(self.bmp, x, x + 3, y + 2, 1); _hline(self.bmp, x, x + 4, y + 5, 1)
        elif d == 4:
            _vline(self.bmp, x, y, y + 3, 1); _hline(self.bmp, x, x + 4, y + 3, 1); _vline(self.bmp, x + 4, y, y + 5, 1)
        elif d == 5:
            _hline(self.bmp, x, x + 4, y, 1); _vline(self.bmp, x, y, y + 2, 1)
            _hline(self.bmp, x, x + 4, y + 2, 1); _vline(self.bmp, x + 4, y + 2, y + 5, 1); _hline(self.bmp, x, x + 4, y + 5, 1)
        elif d == 6:
            rect(self.bmp, x, y, 5, 6, 1); _vline(self.bmp, x + 4, y, y + 5, 0)
        elif d == 7:
            _hline(self.bmp, x, x + 4, y, 1); line(self.bmp, x + 4, y, x, y + 5, 1)
        elif d == 8:
            rect(self.bmp, x, y, 5, 3, 1); rect(self.bmp, x, y + 3, 5, 3, 1)
        elif d == 9:
            rect(self.bmp, x, y, 5, 6, 1); _vline(self.bmp, x, y + 3, y + 6, 0)
        # <-- remove the old trailing else entirely

    # Small 7-seg digits for Adv/Dis boxes (robust)
    def _draw_seg_digit_small(self, ch, x, y, W=5, H=8, T=1, M=0):
        try:
            d = int(ch)
        except Exception:
            return
        mid = y + (H // 2 - T // 2)
        xL  = x
        xR  = x + W - T
        yT  = y
        yB  = y + H - T
        yU0 = y + M;   yU1 = mid - 1
        yL0 = mid + 1; yL1 = y + H - M - 1
        def hbar(yy): _safe_fill_region(self.bmp, x + M, yy, W - 2*M, T, 1)
        def vbar(xx, y0, y1):
            if y1 >= y0:
                _safe_fill_region(self.bmp, xx, y0, T, y1 - y0 + 1, 1)
        segs = {
            0: ('A','B','C','D','E','F'),
            1: ('B','C'),
            2: ('A','B','G','E','D'),
            3: ('A','B','G','C','D'),
            4: ('F','G','B','C'),
            5: ('A','F','G','C','D'),
            6: ('A','F','G','E','C','D'),
            7: ('A','B','C'),
            8: ('A','B','C','D','E','F','G'),
            9: ('A','B','C','D','F','G'),
        }
        s = segs.get(d, ())
        if 'A' in s: hbar(yT)
        if 'G' in s: hbar(mid)
        if 'D' in s: hbar(yB)
        if 'F' in s: vbar(xL, yU0, yU1)
        if 'B' in s: vbar(xR, yU0, yU1)
        if 'E' in s: vbar(xL, yL0, yL1)
        if 'C' in s: vbar(xR, yL0, yL1)

    def _draw_seg_str_small(self, s, x, y, W=5, H=8, T=1, M=0, spacing=1):
        for i, ch in enumerate(s):
            self._draw_seg_digit_small(ch, x + i*(W+spacing), y, W=W, H=H, T=T, M=M)

    def _draw_adv_dis_markers(self, a, b, chosen, mode):
        """
        Two framed boxes (left=a, right=b), small 7-seg digits centered,
        'A'/'D' above, and an arrow IN THE GAP pointing toward the chosen box.
        Everything clamped to CUBE_CLIP.
        """
        # Content band bounds and center
        clip_x, clip_y, clip_w, clip_h = CUBE_CLIP
        CXC, CYC = _clip_center()
        clip_left   = clip_x + 1
        clip_right  = clip_x + clip_w - 2
        clip_top    = clip_y + 1
        clip_bottom = clip_y + clip_h - 2

        # Box geometry
        w, h = 24, 10
        gap = 8

        # Target y a bit above the big number; clamp inside band
        y = CYC - 20
        if y < clip_top: y = clip_top
        if y + h > clip_bottom: y = max(clip_top, clip_bottom - h)

        # Center boxes around band center (then clamp as a pair)
        left_x  = CXC - (w + gap//2) - (gap//2)
        right_x = CXC + (gap//2)

        if left_x < clip_left:
            dx = clip_left - left_x
            left_x  += dx
            right_x += dx
        if right_x + w - 1 > clip_right:
            dx = (right_x + w - 1) - clip_right
            left_x  -= dx
            right_x -= dx

        # Frames
        rect(self.bmp, left_x,  y, w, h, 1)
        rect(self.bmp, right_x, y, w, h, 1)

        # Small 7-seg digits centered inside each box
        inner_mx, inner_my = 2, 1
        inner_w = w - 2*inner_mx
        inner_h = h - 2*inner_my

        DW, DH, DT, DM, SP = 5, 8, 1, 0, 1  # digit metrics

        def center_str_in_box(val_str, bx):
            total_w = len(val_str)*DW + (len(val_str)-1)*SP
            tx = bx + inner_mx + max(0, (inner_w - total_w)//2)
            ty = y + inner_my + max(0, (inner_h - DH)//2)
            return tx, ty

        a_str = str(a); b_str = str(b)
        a_tx, a_ty = center_str_in_box(a_str, left_x)
        b_tx, b_ty = center_str_in_box(b_str, right_x)
        self._draw_seg_str_small(a_str, a_tx, a_ty, W=DW, H=DH, T=DT, M=DM, spacing=SP)
        self._draw_seg_str_small(b_str, b_tx, b_ty, W=DW, H=DH, T=DT, M=DM, spacing=SP)

        # Mode letter ("A" or "D") centered above
        mode_y = max(clip_top, y - 8)
        self._draw_tiny_str("A" if mode == RM_ADV else "D", CXC - 3, mode_y)

        # ---- Arrow in the gap between boxes ----
        gap_left  = left_x + w
        gap_right = right_x
        cx = (gap_left + gap_right) // 2         # horizontal center of the gap
        cy = y + h // 2                          # vertical midline of boxes
        max_len = max(5, min(7, gap - 1))        # arrow total length to fit the gap
        head    = 3 if max_len >= 6 else 2       # arrow head length

        if chosen == a:
            # ← arrow: tip near left side of the gap
            x_tip  = cx - max_len // 2
            x_tail = x_tip + max_len
            _hline(self.bmp, x_tip + head, x_tail, cy, 1)
            line(self.bmp, x_tip + head, cy - (head // 2 + 1), x_tip, cy, 1)
            line(self.bmp, x_tip + head, cy + (head // 2 + 1), x_tip, cy, 1)
        else:
            # → arrow: tip near right side of the gap
            x_tip  = cx + max_len // 2
            x_tail = x_tip - max_len
            _hline(self.bmp, x_tail, x_tip - head, cy, 1)
            line(self.bmp, x_tip - head, cy - (head // 2 + 1), x_tip, cy, 1)
            line(self.bmp, x_tip - head, cy + (head // 2 + 1), x_tip, cy, 1)

    def _draw_tiny_str(self, s, x, y):
        for i, ch in enumerate(s):
            self._draw_tiny_digit(ch, x + i * 6, y)

    def _redraw_static(self):
        clear(self.bmp)
        # Only draw the idle cube when not spinning and not showing a result.
        if (not self.spinning) and (not self.awaiting_ack):
            edges = compute_cube_edges_demoscene(IDLE_ANGLE)
            draw_cube_edges(self.bmp, edges, 1, CUBE_CLIP)

    def _update_prompts(self, spinning=False, result=None):
        theme_name = THEMES[self.theme_idx][0]
        mode_name  = ROLLMODE_NAMES[self.roll_mode]

        if self.awaiting_ack:
            r = result if result is not None else self.last_roll
            btm = f"Result: {r}  SPIN=OK"
        elif spinning:
            btm = "Rolling..."
        else:
            btm = f"D{self.sides}  {theme_name} {mode_name}"

        if self.lbl_btm:
            self.lbl_btm.text = btm[:24]

    def _quick_next(self):
        if self.sides in COMMON_DICE:
            i = COMMON_DICE.index(self.sides)
            self.sides = COMMON_DICE[(i + 1) % len(COMMON_DICE)]
        else:
            larger = [d for d in COMMON_DICE if d >= self.sides]
            self.sides = larger[0] if larger else COMMON_DICE[-1]

    def _quick_prev(self):
        if self.sides in COMMON_DICE:
            i = COMMON_DICE.index(self.sides)
            self.sides = COMMON_DICE[(i - 1) % len(COMMON_DICE)]
        else:
            smaller = [d for d in COMMON_DICE if d <= self.sides]
            self.sides = smaller[-1] if smaller else COMMON_DICE[0]

    def _load_settings(self):
        try:
            with open(SETTINGS_PATH, "r") as f:
                data = json.load(f)
            self.sides = int(data.get("sides", self.sides))
            self.theme_idx = int(data.get("theme", self.theme_idx)) % len(THEMES)
            self.roll_mode = int(data.get("roll_mode", self.roll_mode)) % 3
        except Exception:
            pass
        self.sides = max(MIN_SIDES, min(MAX_SIDES, self.sides))

    def _save_settings(self):
        try:
            with open(SETTINGS_PATH, "w") as f:
                json.dump({"sides": self.sides, "theme": self.theme_idx, "roll_mode": self.roll_mode}, f)
        except Exception:
            pass

    # ----- LED UI helpers -----
    def _theme_triplet(self):
        t = THEMES[self.theme_idx][1]
        if len(t) >= 3: return t[0], t[1], t[2]
        if len(t) == 2: return t[0], t[1], t[1]
        return t[0], t[0], t[0]

    def _btn_color_idle(self, k):
        base, accent, highlight = self._theme_triplet()
        dim = ((base >> 2) & 0x3F3F3F)
        if k in (K_UP, K_LEFT, K_RIGHT, K_DOWN):
            return dim
        if k == K_SPIN: return accent
        if k == K_MODE: return highlight
        if k == K_ADV:  return highlight
        
        return 0x000000

    def _btn_color_flash(self, k):
        base, accent, highlight = self._theme_triplet()
        if k in (K_UP, K_LEFT, K_RIGHT, K_DOWN): return base
        if k == K_SPIN: return accent
        if k == K_MODE: return highlight
        if k == K_ADV: return (base + 0x202020) & 0xFFFFFF
        return 0xFFFFFF

    def _apply_key_flash_frame(self):
        if not hasattr(self.macropad, "pixels"): return
        # Show idle frame (no fade to keep flash snappy), then overlay flash
        self._write_pixels(self._compose_leds_idle())
        t = time.monotonic(); active = False
        for k, until in list(getattr(self, "_key_flash_until", {}).items()):
            if t <= until and 0 <= k < 12:
                buf = self._led_buf[:]
                buf[k] = self._btn_color_flash(k)
                self._write_pixels(buf); active = True
            else:
                del self._key_flash_until[k]
        if active and hasattr(self.macropad, "pixels"):
            self.macropad.pixels.show()

    def _flash_key(self, key_index, dur=0.15):
        t = time.monotonic()
        if not hasattr(self, "_key_flash_until"): self._key_flash_until = {}
        self._key_flash_until[key_index] = t + dur
        if not self.spinning and not getattr(self, "_result_until", 0) and not self.awaiting_ack:
            self._apply_key_flash_frame()