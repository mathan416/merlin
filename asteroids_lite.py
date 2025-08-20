# asteroids_lite.py — Asteroids-lite (Swap 2P, Wave Inherit + Creative LEDs + Sounds)
# For Merlin MacroPad Launcher (CircuitPython 9.x)
#
# Exposes: .group, .new_game(), .tick(), .button(key), .button_up(key), .cleanup()
# Constructor accepts (macropad, tones, **kwargs) but also works with (macropad) or ().
#
# Notes:
# - Uses MerlinChrome.bmp like your launcher on the menu screen (hidden during gameplay).
# - Cosine-smoothing ONLY for keypad LEDs (no screen flashing).
# - Defensive bitmaptools: _hline, _vline, _rect_fill clamp and guard fill_region.

import math, random, time, json
import displayio, bitmaptools, terminalio
from micropython import const
try:
    from adafruit_display_text import label
    HAVE_LABEL = True
except Exception:
    HAVE_LABEL = False

HAS_BLIT = hasattr(bitmaptools, "blit")
EDGE_PAD = 6  # when any object is within this many pixels of an edge, do a full clear

# ---------- Display & physics tunables ----------
SCREEN_W, SCREEN_H = const(128), const(64)
BG, FG = const(0), const(1)

THRUST = 52.0
TURN_SPEED = math.radians(180)
DRAG = 0.92
MAX_SPEED = 75.0
BULLET_SPEED = 120.0
BULLET_LIFE = 0.66
BULLET_COOLDOWN = 0.22
SHIP_RADIUS = 5.0
SPAWN_SAFE_RADIUS = 28.0

# Fewer rocks on a small screen; we’ll spawn just 1 per wave
AST_MIN, AST_MAX = 1, 1
AST_SLOW, AST_FAST = 12.0, 22.0
AST_CAP = 1  # absolute cap on screen (keep it tiny for 128x64)

# ---------- Controls ----------
KEYS = {
    "up": 1, "left": 3, "right": 5,
    "fire_list": (6, 7, 8),      # K6–K8 all FIRE
    "toggle": 9,                 # K9 toggles 1P/2P on menu
    "start": 11,                 # K11 starts game
    "menu_back": 9               # K9 also returns to in-game menu
}

# ---------- Options ----------
INHERIT_WAVE_ON_SWAP = True
SETTINGS_PATH = "/asteroids_settings.json"

# ---------- LED theme & easing ----------
LED_BREATH_PERIOD = 1.6
LED_MENU_SWEEP_PERIOD = 1.2
LED_BRIGHT_MIN = 6
LED_BRIGHT_MAX = 28
LED_DT_SMOOTH = 0.25  # seconds to ~63% toward target (exp smoothing)

# colors (r,g,b) 0..255
COL_SILVER = (32, 32, 32)
COL_AMBER  = (64, 24, 0)
COL_ORANGE = (80, 28, 0)
COL_WHITE  = (80, 80, 80)
COL_P1     = (0, 32, 64)
COL_P2     = (48, 0, 48)
COL_FIRE   = (80, 0, 0)
COL_START  = (0, 48, 0)

# ---------- Fast trig (sin/cos LUT) ----------
LUT_N = 64  # power of two keeps modulo cheap
_LUT = [ (math.cos(2*math.pi*i/LUT_N), math.sin(2*math.pi*i/LUT_N)) for i in range(LUT_N) ]

def _lut_cs(angle):
    """Return (cos, sin) from a 64-entry LUT for speed."""
    a = angle % (2*math.pi)
    idx = int(a * (LUT_N / (2*math.pi))) & (LUT_N-1)
    return _LUT[idx]

def rot_pts_lut(pts, angle):
    """Rotate points using fast LUT cos/sin."""
    ca, sa = _lut_cs(angle)
    return [(x*ca - y*sa, x*sa + y*ca) for (x, y) in pts]

# ---------- Defensive bitmap helpers ----------
def _clamp_int(v, lo, hi):
    if v < lo: return lo
    if v > hi: return hi
    return v

def _clampi(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

def _hline(bmp, x0, x1, y, c=FG):
    if y < 0 or y >= SCREEN_H: return
    if x0 > x1: x0, x1 = x1, x0
    x0 = _clamp_int(x0, 0, SCREEN_W - 1)
    x1 = _clamp_int(x1, 0, SCREEN_W - 1)
    try:
        bitmaptools.draw_line(bmp, x0, y, x1, y, c)
    except Exception:
        pass

def _vline(bmp, x, y0, y1, c=FG):
    if x < 0 or x >= SCREEN_W: return
    if y0 > y1: y0, y1 = y1, y0
    y0 = _clamp_int(y0, 0, SCREEN_H - 1)
    y1 = _clamp_int(y1, 0, SCREEN_H - 1)
    try:
        bitmaptools.draw_line(bmp, x, y0, x, y1, c)
    except Exception:
        pass

def _rect_fill(bmp, x, y, w, h, c=BG):
    if w <= 0 or h <= 0: return
    x = _clamp_int(x, 0, SCREEN_W - 1)
    y = _clamp_int(y, 0, SCREEN_H - 1)
    x2 = _clamp_int(x + w, 0, SCREEN_W)
    y2 = _clamp_int(y + h, 0, SCREEN_H)
    if x2 <= x or y2 <= y: return
    try:
        bitmaptools.fill_region(bmp, x, y, x2 - x, y2 - y, c)
    except Exception:
        for yy in range(y, y2):
            _hline(bmp, x, x2 - 1, yy, c)

# ---------- Math helpers ----------
def wrapf(x, w):
    while x < 0: x += w
    while x >= w: x -= w
    return x

def d2(ax, ay, bx, by):
    dx, dy = ax-bx, ay-by
    return dx*dx + dy*dy

def draw_poly_lines(bmp, pts):
    """Line outline with wrap clones based on coarse bounds (kept for asteroids)."""
    n = len(pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    near_x = (min(xs) < 1) or (max(xs) > SCREEN_W - 2)
    near_y = (min(ys) < 1) or (max(ys) > SCREEN_H - 2)

    def _dl(x0, y0, x1, y1):
        try:
            bitmaptools.draw_line(bmp, int(x0), int(y0), int(x1), int(y1), FG)
        except Exception:
            pass

    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        _dl(x0, y0, x1, y1)
        if near_x:
            _dl(x0 - SCREEN_W, y0, x1 - SCREEN_W, y1)
            _dl(x0 + SCREEN_W, y0, x1 + SCREEN_W, y1)
        if near_y:
            _dl(x0, y0 - SCREEN_H, x1, y1 - SCREEN_H)
            _dl(x0, y0 + SCREEN_H, x1, y1 + SCREEN_H)
        if near_x and near_y:
            _dl(x0 - SCREEN_W, y0 - SCREEN_H, x1 - SCREEN_W, y1 - SCREEN_H)
            _dl(x0 + SCREEN_W, y0 - SCREEN_H, x1 + SCREEN_W, y1 - SCREEN_H)
            _dl(x0 - SCREEN_W, y0 + SCREEN_H, x1 - SCREEN_W, y1 + SCREEN_H)
            _dl(x0 + SCREEN_W, y0 + SCREEN_H, x1 + SCREEN_W, y1 + SCREEN_H)

# ---------- Shapes ----------
SHIP_POINTS = [(8.0, 0.0), (-6.5, 4.0), (-4.0, 0.0), (-6.5, -4.0)]

def make_asteroid_shape(seed, size):
    verts = 7 + random.randint(0, 3)
    r0 = 4 + size * 4
    pts = []
    for i in range(verts):
        ang = (i / verts) * 2 * math.pi
        rad = r0 * (0.82 + 0.36 * random.random())
        pts.append((math.cos(ang)*rad, math.sin(ang)*rad))
    return pts, r0

# ---------- Game Class ----------
class asteroids_lite:
    def __init__(self, macropad=None, tones=None, **kwargs):
        self.macropad = macropad
        self.tones = tones
        self._dirty_prev = []
        self._dirty_acc = []
        
        self._led_last_show = 0.0
        self._led_min_interval = 1.0 / 30.0  # cap NeoPixel pushes to ~30 Hz
        self._led_prev_out = [(0,0,0)] * 12  # for change detection
        self._hud_cache = ("", "", "", 0, 0, 0)  # (mode, state, prompt1, p1, p2, lives)
        self._last_firepulse_t = -999.0

        # Display group
        self.group = displayio.Group()

        # Merlin logo (menu only)
        self.logo_tile = None
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            self.logo_tile = displayio.TileGrid(
                bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            self.group.append(self.logo_tile)  # background layer
        except Exception:
            self.logo_tile = None

        # Framebuffer
        self.bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
        self.pal = displayio.Palette(2); self.pal[0] = 0x000000; self.pal[1] = 0xFFFFFF
        self.tg = displayio.TileGrid(self.bmp, pixel_shader=self.pal)
        self.group.append(self.tg)

        # Title + HUD
        self.title_lbl = None
        self.prompt1 = None
        self.prompt2 = None
        if HAVE_LABEL:
            self.title_lbl = label.Label(terminalio.FONT, text="ASTEROIDS-LITE", color=0xFFFFFF, x=4, y=10)
            self.prompt1 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=21)
            self.prompt2 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=35)
            self.group.append(self.title_lbl); self.group.append(self.prompt1); self.group.append(self.prompt2)

        # Build ship sprite sheet (blitted instead of line-drawing)
        self._make_ship_atlas()

        # Mode/state
        self.swap_mode = False
        self._state = "menu"   # "menu" | "play" | "round_over"
        self._prev = time.monotonic()

        # Per-run state
        self._ship = None
        self._bullets = []
        self._rocks = []
        self._cooldown = 0.0
        self._lives = 3

        # Wave progression
        self._asteroid_base = 1
        self._asteroid_target = self._asteroid_base
        self._round_timer = 0.0

        # Swap bookkeeping
        self.active_player = 0          # 0=Player1, 1=Player2
        self.score = [0, 0]
        self._p2_started = False

        # Sounds (non-blocking)
        self._snd_q = []
        self._snd_playing_until = 0.0

        # LEDs
        self._led_cols_current = [(0,0,0)] * 12
        self._led_events = []

        # Settings
        self._load_settings()
        self._update_prompts()
        self._led_menu()
        self._clear()
        self._show_logo(True)

    # ---------- Sprites: ship atlas ----------
    def _make_ship_atlas(self):
        """Build a 1-bit sprite sheet of the ship for 32 angles and cache rects."""
        self._ship_frames = 32
        F = self._ship_frames

        # --- auto-size the sprite from geometry + margin ---
        xabs = max(abs(p[0]) for p in SHIP_POINTS)
        yabs = max(abs(p[1]) for p in SHIP_POINTS)
        margin = 3  # pad to avoid clipping/rounding issues
        self._ship_w = int(math.ceil(xabs * 2 + margin * 2))
        self._ship_h = int(math.ceil(yabs * 2 + margin * 2))
        W, H = self._ship_w, self._ship_h
        cx, cy = W // 2, H // 2

        # atlas bitmap (1-bit indices: 0/1)
        self._ship_atlas = displayio.Bitmap(W * F, H, 2)

        # clear the whole atlas correctly (no screen-size clamp)
        try:
            bitmaptools.fill_region(self._ship_atlas, 0, 0, W * F, H, 0)
        except Exception:
            # very unlikely fallback
            for yy in range(H):
                for xx in range(W * F):
                    self._ship_atlas[xx, yy] = 0

        # draw each rotated outline into its frame
        for i in range(F):
            ang = (i / F) * 2 * math.pi
            pts = rot_pts_lut(SHIP_POINTS, ang)
            pts = [(cx + x, cy + y) for (x, y) in pts]
            xoff = i * W
            n = len(pts)
            for j in range(n):
                x0, y0 = pts[j]
                x1, y1 = pts[(j + 1) % n]
                try:
                    bitmaptools.draw_line(
                        self._ship_atlas,
                        int(xoff + x0), int(y0),
                        int(xoff + x1), int(y1),
                        1  # draw index 1 pixels
                    )
                except Exception:
                    pass

        # source rects (exclusive x2/y2 as expected by blit)
        self._ship_src_rects = []
        for i in range(F):
            self._ship_src_rects.append((i * W, 0, i * W + W, H))

    def _ship_frame_index(self, angle):
        a = angle % (2*math.pi)
        return int(a * (self._ship_frames / (2*math.pi))) % self._ship_frames


    def _blit_ship(self, x, y, angle):
        # Always try to blit; fall back to outline on any failure
        fi = self._ship_frame_index(angle)
        W, H = self._ship_w, self._ship_h
        tlx = int(x) - W // 2
        tly = int(y) - H // 2

        # compute source rect
        try:
            x1, y1, x2, y2 = self._ship_src_rects[fi]
        except Exception:
            # atlas not ready? draw outline instead
            self._draw_ship_outline(x, y, angle)
            self._dirty_acc.append((int(x - W//2) - 2, int(y - H//2) - 2, W + 4, H + 4))
            return

        # list of offsets for wrap clones
        offsets = [(0, 0)]
        if tlx < 0:                 offsets.append((SCREEN_W, 0))
        if tlx + W > SCREEN_W:      offsets.append((-SCREEN_W, 0))
        if tly < 0:                 offsets.append((0, SCREEN_H))
        if tly + H > SCREEN_H:      offsets.append((0, -SCREEN_H))
        if tlx < 0 and tly < 0:                     offsets.append((SCREEN_W, SCREEN_H))
        if tlx < 0 and tly + H > SCREEN_H:          offsets.append((SCREEN_W, -SCREEN_H))
        if tlx + W > SCREEN_W and tly < 0:          offsets.append((-SCREEN_W, SCREEN_H))
        if tlx + W > SCREEN_W and tly + H > SCREEN_H:offsets.append((-SCREEN_W, -SCREEN_H))

        pad = 2
        blit_ok = True
        for dx, dy in offsets:
            try:
                bitmaptools.blit(
                    self.bmp, self._ship_atlas,
                    x=tlx + dx, y=tly + dy,
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    skip_index=0
                )
            except Exception:
                blit_ok = False
                break

        if not blit_ok:
            # fallback: simple vector ship
            self._draw_ship_outline(x, y, angle)
            offsets = [(0, 0)]  # outline already wraps internally via draw_poly_lines

        # record dirty rects (so we can erase next frame)
        for dx, dy in offsets:
            self._dirty_acc.append((tlx + dx - pad, tly + dy - pad, W + 2*pad, H + 2*pad))

    # ---------- Launcher API ----------
    def new_game(self):
        self._state = "menu"
        try:
            if self.macropad:
                self.macropad.display.auto_refresh = False
        except Exception:
            pass
        self.active_player = 0
        self.score = [0, 0]
        self._p2_started = False
        self._reset_run_vars(reset_wave=True)
        self._update_prompts()
        self._led_menu()
        self._clear()
        self._snd_stop()
        self._show_logo(True)

    def tick(self):
        now = time.monotonic()
        dt = now - self._prev
        self._prev = now
        if dt <= 0:
            dt = 1 / 60.0

        # Service subsystems first (sound queue + LED animations)
        self._snd_service(now)
        self._led_service(now, dt)

        if self._state == "menu":
            self._draw_menu(now)
            try:
                if self.macropad:
                    self.macropad.display.refresh(minimum_frames_per_second=0)
            except Exception:
                pass
            return

        # ---- Gameplay ----
        self._cooldown = max(0.0, self._cooldown - dt)
        self._step_ship(dt)
        self._step_bullets(dt)
        self._step_rocks(dt)
        self._collide()

        # Wave clear → next wave (exactly one asteroid)
        if len(self._rocks) == 0:
            self._asteroid_target = 1
            self._spawn_wave()
            self._snd_wave()
            self._led_event("wave", dur=0.40)

        # Death/round handling
        if (not self._ship or not self._ship["alive"]) and self._lives <= 0 and self._state != "round_over":
            self._state = "round_over"
            self._round_timer = 1.0

        if self._state == "round_over":
            self._round_timer -= dt
            if self._round_timer <= 0:
                if self.swap_mode and self.active_player == 0:
                    self.active_player = 1
                    self._p2_started = True
                    self._reset_run_vars(reset_wave=not INHERIT_WAVE_ON_SWAP)
                    self._start_run()
                    self._state = "play"
                    self._snd_swap()
                    self._led_event("swap", dur=0.60, theme=(COL_P2))
                else:
                    self._state = "menu"
                    self._update_prompts()
                    self._led_menu()
                    self._show_logo(True)

        self._render(now)

        try:
            if self.macropad:
                self.macropad.display.refresh(minimum_frames_per_second=0)
        except Exception:
            pass

    def button(self, key):
        if self._state == "menu":
            if key == KEYS["toggle"]:
                self.swap_mode = not self.swap_mode
                self._update_prompts()
                self._led_menu()
            elif (key == KEYS["start"]) or (key in KEYS["fire_list"]):
                self._start_session()
            return

        # Gameplay — K9 returns to in-game menu
        if key == KEYS["menu_back"]:
            self._state = "menu"
            self._update_prompts()
            self._led_menu()
            self._show_logo(True)
            self._snd_stop()
            return

        if not self._ship: return
        if key == KEYS["left"]:   self._ship["left"] = True
        if key == KEYS["right"]:  self._ship["right"] = True
        if key == KEYS["up"]:     self._ship["thrust"] = True
        if key in KEYS["fire_list"]:
            self._fire()
        self._led_play()

    def button_up(self, key):
        if not self._ship: return
        if key == KEYS["left"]:   self._ship["left"] = False
        if key == KEYS["right"]:  self._ship["right"] = False
        if key == KEYS["up"]:     self._ship["thrust"] = False
        self._led_play()

    def cleanup(self):
        self._snd_stop()
        try:
            self._led_events[:] = []
            self._led_cols_current = [(0, 0, 0)] * 12
            if self.macropad:
                self.macropad.pixels.fill((0, 0, 0))
                self.macropad.pixels.show()
        except Exception:
            pass
        try:
            if self.macropad:
                self.macropad.display.auto_refresh = True
        except Exception:
            pass

    # ---------- Settings ----------
    def _load_settings(self):
        try:
            with open(SETTINGS_PATH, "r") as f:
                data = json.load(f)
            if "swap_mode" in data:
                self.swap_mode = bool(data["swap_mode"])
            if "asteroids" in data:
                self._asteroid_base = int(data["asteroids"]) or 1
                self._asteroid_target = self._asteroid_base
        except Exception:
            pass

    # ---------- Menu / HUD ----------
    def _show_logo(self, show):
        if self.logo_tile is not None:
            try:
                self.logo_tile.hidden = (not show)
            except Exception:
                pass

    def _update_prompts(self):
        if not HAVE_LABEL: return
        mode = "2P SWAP" if self.swap_mode else "1P"
        state = self._state

        ap = self.active_player
        other = 1 - ap
        p1 = self.score[0]
        p2 = self.score[1]
        lives = max(0, self._lives)

        if state == "menu":
            prompt1 = f"[{mode}]"
            prompt2 = ""
        else:
            prompt1 = f"P{ap+1}:{p1:04d} L{lives}"
            prompt2 = f"P{other+1}:{p2:04d}" if self.swap_mode else ""

        key = (mode, state, prompt1, p1, p2, lives)
        if key == self._hud_cache:
            return  # nothing to change

        self._hud_cache = key
        self.title_lbl.text = "ASTEROIDS-LITE"
        self.prompt1.text = prompt1
        self.prompt2.text = prompt2

    def _draw_ship_outline(self, x, y, angle):
        pts = rot_pts_lut(SHIP_POINTS, angle)
        pts = [(x + px, y + py) for (px, py) in pts]
        draw_poly_lines(self.bmp, pts)
        
    def _draw_menu(self, now):
        # full wipe is cheap at 128×64 and guarantees no trails
        self._clear(full=True)
        self._show_logo(True)

        cx, cy = SCREEN_W // 2, SCREEN_H // 2 + 8
        ang = (now * 0.9) % (2 * math.pi)

        self._dirty_acc = []
        self._blit_ship(cx, cy, ang)

        # still record a rect list (not strictly needed with full clear, but harmless)
        self._dirty_prev = self._clamp_rects(self._dirty_acc)

    # ---------- Session / Run control ----------
    def _start_session(self):
        self.active_player = 0
        self._p2_started = False
        self.score = [0, 0]
        self._reset_run_vars(reset_wave=True)
        self._start_run()
        self._state = "play"
        self._led_play()
        self._snd_wave()
        self._led_event("wave", dur=0.40)
        self._show_logo(False)

    def _reset_run_vars(self, reset_wave=False):
        self._ship = None
        self._bullets = []
        self._rocks = []
        self._cooldown = 0.0
        self._lives = 3
        if reset_wave:
            self._asteroid_target = 1

    def _start_run(self):
        self._ship = self._make_ship(SCREEN_W*0.50, SCREEN_H*0.50, 0.0)
        self._bullets.clear()
        self._rocks.clear()
        self._spawn_wave()
        self._state = "play"
        self._update_prompts()

    # ---------- Entities / Sim ----------
    def _make_ship(self, x, y, ang):
        return {"x":x, "y":y, "vx":0.0, "vy":0.0, "ang":ang,
                "left":False, "right":False, "thrust":False,
                "alive":True, "inv":0.8}

    def _spawn_wave(self):
        # enforce exactly one asteroid on screen
        remaining = max(0, min(self._asteroid_target, AST_CAP) - len(self._rocks))
        if remaining <= 0:
            return
        for _ in range(remaining):
            # spawn from edges
            edge = random.randint(0, 3)
            if edge == 0:
                x, y = 0, random.uniform(0, SCREEN_H)
            elif edge == 1:
                x, y = SCREEN_W-1, random.uniform(0, SCREEN_H)
            elif edge == 2:
                x, y = random.uniform(0, SCREEN_W), 0
            else:
                x, y = random.uniform(0, SCREEN_W), SCREEN_H-1

            # safe radius from ship
            tries = 0
            while self._ship and ((x - self._ship["x"])**2 + (y - self._ship["y"])**2) ** 0.5 < SPAWN_SAFE_RADIUS and tries < 20:
                tries += 1
                x = random.uniform(0, SCREEN_W)
                y = random.uniform(0, SCREEN_H)

            size = 2  # start largish; children will be smaller
            ang = random.uniform(0, 2*math.pi)
            spd = random.uniform(AST_SLOW, AST_FAST)
            vx, vy = math.cos(ang)*spd, math.sin(ang)*spd
            shape, r = make_asteroid_shape(random.randint(0, 999_999), size)
            self._rocks.append({"x":x,"y":y,"vx":vx,"vy":vy,"ang":random.random()*2*math.pi,
                                "spin":random.uniform(-0.7,0.7),"size":size,"shape":shape,"r":r})

    def _step_ship(self, dt):
        s = self._ship
        if not s or not s["alive"]: return
        if s["left"]:  s["ang"] -= TURN_SPEED * dt
        if s["right"]: s["ang"] += TURN_SPEED * dt
        if s["thrust"]:
            s["vx"] += math.cos(s["ang"]) * THRUST * dt
            s["vy"] += math.sin(s["ang"]) * THRUST * dt
        drag = DRAG**dt
        s["vx"] *= drag; s["vy"] *= drag
        sp = (s["vx"] * s["vx"] + s["vy"] * s["vy"]) ** 0.5
        if sp > MAX_SPEED:
            k = MAX_SPEED/sp; s["vx"]*=k; s["vy"]*=k
        s["x"] = wrapf(s["x"] + s["vx"]*dt, SCREEN_W)
        s["y"] = wrapf(s["y"] + s["vy"]*dt, SCREEN_H)
        if s["inv"] > 0: s["inv"] = max(0.0, s["inv"] - dt)

    def _step_bullets(self, dt):
        keep = []
        for b in self._bullets:
            b["t"] -= dt
            if b["t"] <= 0: continue
            b["x"] = wrapf(b["x"] + b["vx"]*dt, SCREEN_W)
            b["y"] = wrapf(b["y"] + b["vy"]*dt, SCREEN_H)
            keep.append(b)
        self._bullets = keep

    def _step_rocks(self, dt):
        for a in self._rocks:
            a["ang"] += a["spin"] * dt
            a["x"] = wrapf(a["x"] + a["vx"]*dt, SCREEN_W)
            a["y"] = wrapf(a["y"] + a["vy"]*dt, SCREEN_H)

    def _collide(self):
        # bullets vs rocks
        i = 0
        while i < len(self._bullets):
            b = self._bullets[i]
            hit = -1
            for j, a in enumerate(self._rocks):
                if d2(b["x"], b["y"], a["x"], a["y"]) <= (a["r"]*a["r"]):
                    hit = j; break
            if hit >= 0:
                a = self._rocks.pop(hit)
                self.score[self.active_player] += 10 + 10*a["size"]
                if a["size"] > 0:
                    # only ONE child to keep density low
                    size = a["size"] - 1
                    shape, r = make_asteroid_shape(random.randint(0,999_999), size)
                    ang = random.uniform(0, 2*math.pi)
                    spd = random.uniform(AST_SLOW, AST_FAST)
                    vx, vy = math.cos(ang)*spd, math.sin(ang)*spd
                    self._rocks.append({"x":a["x"],"y":a["y"],"vx":vx,"vy":vy,"ang":random.random()*2*math.pi,
                                        "spin":random.uniform(-0.9,0.9),"size":size,"shape":shape,"r":r})
                self._snd_hit()
                self._led_event("firepulse", dur=0.18)
                self._bullets[i] = self._bullets[-1]; self._bullets.pop(); continue
            i += 1

        # rocks vs ship
        s = self._ship
        if not s or not s["alive"] or s["inv"] > 0: return
        for a in self._rocks:
            if d2(s["x"], s["y"], a["x"], a["y"]) <= (a["r"]+SHIP_RADIUS)*(a["r"]+SHIP_RADIUS):
                s["alive"] = False
                self._lives -= 1
                self._snd_ship_down()
                if self._lives > 0:
                    self._ship = self._make_ship(SCREEN_W*0.50, SCREEN_H*0.50, 0.0)
                self._update_prompts()
                break

    def _fire(self):
        if self._cooldown > 0: return
        s = self._ship
        if not s or not s["alive"]: return
        nx = s["x"] + math.cos(s["ang"])*8.0
        ny = s["y"] + math.sin(s["ang"])*8.0
        bvx = s["vx"] + math.cos(s["ang"])*BULLET_SPEED
        bvy = s["vy"] + math.sin(s["ang"])*BULLET_SPEED
        self._bullets.append({"x":nx,"y":ny,"vx":bvx,"vy":bvy,"t":BULLET_LIFE})
        self._cooldown = BULLET_COOLDOWN
        self._snd_fire()
        now = time.monotonic()
        if now - self._last_firepulse_t >= 0.10:  # at most 10 Hz
            self._led_event("firepulse", dur=0.18)
            self._last_firepulse_t = now

    # ---------- Rendering ----------
    def _render(self, now):
        # edge-proximity ⇒ full clear (wrap clones will be drawn)
        needs_full = False
        s = self._ship
        if s and s.get("alive"):
            if (s["x"] < EDGE_PAD or s["x"] > SCREEN_W - EDGE_PAD or
                s["y"] < EDGE_PAD or s["y"] > SCREEN_H - EDGE_PAD):
                needs_full = True

        for a in self._rocks:
            if (a["x"] - a["r"] < EDGE_PAD or a["x"] + a["r"] > SCREEN_W - EDGE_PAD or
                a["y"] - a["r"] < EDGE_PAD or a["y"] + a["r"] > SCREEN_H - EDGE_PAD):
                needs_full = True
                break

        if not needs_full:
            for b in self._bullets:
                if (b["x"] < EDGE_PAD or b["x"] > SCREEN_W - EDGE_PAD or
                    b["y"] < EDGE_PAD or b["y"] > SCREEN_H - EDGE_PAD):
                    needs_full = True
                    break

        # Erase previous frame
        self._clear(full=needs_full)
        self._show_logo(False)

        # new dirty accumulator
        self._dirty_acc = []
        pad = 2

        # ---- Ship (blit) ----
        if s and s["alive"]:
            self._blit_ship(s["x"], s["y"], s["ang"])

        # ---- Asteroids (outline, but using LUT for rotation) ----
        for a in self._rocks:
            verts = [(a["x"] + vx, a["y"] + vy) for (vx, vy) in rot_pts_lut(a["shape"], a["ang"])]
            draw_poly_lines(self.bmp, verts)
            self._dirty_acc.append((
                int(a["x"] - (a["r"] + pad)),
                int(a["y"] - (a["r"] + pad)),
                int(2*(a["r"] + pad)),
                int(2*(a["r"] + pad)),
            ))

        # ---- Bullets ----
        for b in self._bullets:
            x, y = int(b["x"]), int(b["y"])
            if 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
                try:
                    self.bmp[x, y] = FG
                except Exception:
                    pass
            bx = _clamp_int(x - 1, 0, SCREEN_W)
            by = _clamp_int(y - 1, 0, SCREEN_H)
            bw = 2; bh = 2
            if bx + bw > SCREEN_W: bw = SCREEN_W - bx
            if by + bh > SCREEN_H: bh = SCREEN_H - by
            if bw > 0 and bh > 0:
                self._dirty_acc.append((bx, by, bw, bh))

        # ---- HUD ----
        self._update_prompts()

        if not needs_full:
            self._dirty_prev = self._clamp_rects(self._dirty_acc)

    def _clamp_rects(self, rects):
        out = []
        for (x, y, w, h) in rects:
            x2, y2 = x + w, y + h
            x = _clamp_int(x, 0, SCREEN_W)
            y = _clamp_int(y, 0, SCREEN_H)
            x2 = _clamp_int(x2, 0, SCREEN_W)
            y2 = _clamp_int(y2, 0, SCREEN_H)
            w = x2 - x
            h = y2 - y
            if w > 0 and h > 0:
                out.append((x, y, w, h))
        return out

    def _clear(self, full=False):
        """Erase last frame. If full=True, clear entire screen."""
        if full:
            _rect_fill(self.bmp, 0, 0, SCREEN_W, SCREEN_H, BG)
            self._dirty_prev = [(0, 0, SCREEN_W, SCREEN_H)]
            return
        prev = getattr(self, "_dirty_prev", [])
        for (x, y, w, h) in prev:
            _rect_fill(self.bmp, x, y, w, h, BG)
        self._dirty_prev = []

    # ---------- LEDs ----------
    def _led_menu(self):
        try:
            if not self.macropad: return
            self.macropad.pixels.auto_write = False  # was True
            base = [(0,0,0)] * 12
            base[KEYS["toggle"]] = COL_AMBER
            base[KEYS["start"]]  = COL_START
            for k in (KEYS["up"], KEYS["left"], KEYS["right"]):
                if 0 <= k < 12: base[k] = COL_SILVER
            for k in KEYS["fire_list"]:
                if 0 <= k < 12: base[k] = (int(COL_FIRE[0]*0.4), int(COL_FIRE[1]*0.4), int(COL_FIRE[2]*0.4))
            self._led_cols_current = base[:]
            for i, c in enumerate(base):
                self.macropad.pixels[i] = c
            self.macropad.pixels.show()
        except Exception:
            pass

    def _led_play(self):
        try:
            if not self.macropad: return
            theme = COL_P1 if self.active_player == 0 else COL_P2
            base = [(0,0,0)] * 12
            self.macropad.pixels.auto_write = False 
            for k in (KEYS["up"], KEYS["left"], KEYS["right"]):
                if 0 <= k < 12: base[k] = theme
            for k in KEYS["fire_list"]:
                if 0 <= k < 12: base[k] = COL_FIRE
            base[KEYS["menu_back"]] = COL_AMBER
            self._led_cols_current = base[:]
            for i, c in enumerate(base):
                self.macropad.pixels[i] = c
            self.macropad.pixels.show()
        except Exception:
            pass

    def _led_event(self, name, dur=0.35, **extra):
        self._led_events.append({"name": name, "t0": time.monotonic(), "dur": dur, "extra": extra})

    def _led_service(self, now, dt):
        """Animate keypad LEDs with smoothing, but only push to hardware
        when colors changed AND at most ~30 Hz to save CPU."""
        if not self.macropad:
            return
        try:
            cols = [(0, 0, 0)] * 12

            if self._state == "menu":
                # start from menu base colors chosen in _led_menu()
                cols = self._led_cols_current[:]  # use current as base palette
                phase = (now % LED_MENU_SWEEP_PERIOD) / LED_MENU_SWEEP_PERIOD
                for i in range(12):
                    p = (phase + i / 12.0) % 1.0
                    t = 0.5 * (1.0 - math.cos(2 * math.pi * p))  # 0..1
                    amp = (LED_BRIGHT_MIN / 32.0) + ((LED_BRIGHT_MAX - LED_BRIGHT_MIN) / 32.0) * t
                    r, g, b = cols[i]
                    cols[i] = (int(r * amp), int(g * amp), int(b * amp))
                for k in (KEYS["toggle"], KEYS["start"]):
                    r, g, b = cols[k]
                    cols[k] = (int(r * 1.25), int(g * 1.25), int(b * 1.25))

            elif self._state == "play":
                theme = COL_P1 if self.active_player == 0 else COL_P2
                # base controls
                for k in (KEYS["up"], KEYS["left"], KEYS["right"]):
                    if 0 <= k < 12:
                        cols[k] = theme
                for k in KEYS["fire_list"]:
                    if 0 <= k < 12:
                        cols[k] = COL_FIRE
                cols[KEYS["menu_back"]] = COL_AMBER

                # thrust flare
                if self._ship and self._ship.get("thrust"):
                    k = KEYS["up"]
                    if 0 <= k < 12:
                        cols[k] = _lerp(cols[k], COL_ORANGE, 0.65)

                # gentle breath on left/right
                phase = (now % LED_BREATH_PERIOD) / LED_BREATH_PERIOD
                tL = 0.5 * (1.0 - math.cos(2 * math.pi * ((phase + 0.15) % 1.0)))
                tR = 0.5 * (1.0 - math.cos(2 * math.pi * ((phase + 0.65) % 1.0)))
                kL, kR = KEYS["left"], KEYS["right"]
                if 0 <= kL < 12:
                    cols[kL] = _scale(_lerp(cols[kL], COL_WHITE, 0.25), 0.6 + 0.4 * tL)
                if 0 <= kR < 12:
                    cols[kR] = _scale(_lerp(cols[kR], COL_WHITE, 0.25), 0.6 + 0.4 * tR)

                # fire cooldown pulse
                if self._cooldown > 0 and BULLET_COOLDOWN > 0:
                    cool_t = _clampi(1.0 - (self._cooldown / BULLET_COOLDOWN), 0.0, 1.0)
                    pulse = 0.5 * (1.0 - math.cos(2 * math.pi * cool_t))
                    for k in KEYS["fire_list"]:
                        if 0 <= k < 12:
                            cols[k] = _lerp(cols[k], COL_WHITE, 0.55 * pulse)

                # menu/back heartbeat
                tB = 0.5 * (1.0 - math.cos(2 * math.pi * ((now % 1.8) / 1.8)))
                cols[KEYS["menu_back"]] = _scale(cols[KEYS["menu_back"]], 0.7 + 0.6 * tB)

                # low-lives amber wash
                if self._lives <= 1:
                    slow = 0.5 * (1.0 - math.cos(2 * math.pi * ((now % 2.4) / 2.4))) * 0.35
                    overlay = _scale(COL_AMBER, slow)
                    for i in range(12):
                        cols[i] = _add_sat(cols[i], overlay)

                # transient LED events (wave/swap/firepulse)
                if self._led_events:
                    keep = []
                    for ev in self._led_events:
                        tnorm = (now - ev["t0"]) / ev["dur"]
                        if tnorm < 0:
                            keep.append(ev)
                            continue
                        if tnorm <= 1.0:
                            e = 0.5 * (1.0 - math.cos(2 * math.pi * tnorm))
                            if ev["name"] == "wave":
                                for i in range(12):
                                    cols[i] = _lerp(cols[i], COL_WHITE, 0.35 * e)
                            elif ev["name"] == "swap":
                                new_theme = ev.get("theme", theme)
                                for k in (KEYS["up"], KEYS["left"], KEYS["right"]):
                                    if 0 <= k < 12:
                                        cols[k] = _lerp(cols[k], new_theme, 0.6 * e)
                            elif ev["name"] == "firepulse":
                                for k in KEYS["fire_list"]:
                                    if 0 <= k < 12:
                                        cols[k] = _lerp(cols[k], COL_WHITE, 0.7 * e)
                            keep.append(ev)
                    self._led_events = keep

            # --- exponential smoothing toward target palette ---
            alpha = 1.0 - math.exp(-dt / LED_DT_SMOOTH) if LED_DT_SMOOTH > 1e-6 else 1.0
            cur = self._led_cols_current
            out = [_lerp(cur[i], cols[i], alpha) for i in range(12)]
            self._led_cols_current = out  # store smoothed state for next tick

            # --- push to hardware only if changed AND not more than ~30 Hz ---
            changed = any(out[i] != self._led_prev_out[i] for i in range(12))
            if changed and (now - self._led_last_show) >= self._led_min_interval:
                for i, c in enumerate(out):
                    self.macropad.pixels[i] = c
                self.macropad.pixels.show()
                self._led_prev_out = out[:]      # remember last pushed frame
                self._led_last_show = now

        except Exception:
            pass

    # ---------- Sounds (non-blocking) ----------
    def _snd_play(self, freq, ms, now=None):
        if not self.macropad or freq <= 0 or ms <= 0: return
        if now is None: now = time.monotonic()
        if now < self._snd_playing_until:
            return  # already playing; skip new tones to keep CPU free
        try:
            self.macropad.play_tone(freq)
            self._snd_playing_until = now + (ms / 1000.0)
        except Exception:
            self._snd_playing_until = 0.0

    def _snd_service(self, now):
        if now >= self._snd_playing_until and self._snd_playing_until != 0.0:
            self._snd_stop()
        if (self._snd_playing_until == 0.0) and self._snd_q:
            freq, ms = self._snd_q.pop(0)
            try:
                self.macropad.play_tone(freq)
                self._snd_playing_until = now + (ms / 1000.0)
            except Exception:
                self._snd_playing_until = 0.0
                self._snd_q[:] = []

    def _snd_stop(self):
        if not self.macropad: return
        try:
            self.macropad.stop_tone()
        except Exception:
            pass
        self._snd_playing_until = 0.0

    # one-shots
    def _snd_fire(self):
        self._snd_play(880, 30)  # was 45

    def _snd_hit(self):
        self._snd_play(330, 70)
        self._snd_play(220, 90)

    def _snd_ship_down(self):
        self._snd_play(140, 160)

    def _snd_wave(self):
        self._snd_play(494, 90)
        self._snd_play(659, 120)

    def _snd_swap(self):
        self._snd_play(587, 100)
        self._snd_play(784, 120)