# ---------------------------------------------------------------------------
# pacman.py — Pac Man
# ---------------------------------------------------------------------------
# A Merlin Launcher–compatible clone of Pac-Man for the Adafruit MacroPad
# (CircuitPython 9.x / 128×64 1-bit OLED). Single-player, zoom+scroll engine.
# Written by Iain Bennett — 2025
#
# Features:
#   • Auto-scrolling, zoomed-in maze view (2× software scale).
#   • Title, pause, between-level, and game-over states with centered HUD.
#   • Score and lives indicator (centered at top bar).
#   • Pellet and power-pellet collection with score/bonus system.
#   • Ghost AI with chase + wander modes; frightened mode on power pellet.
#   • Warp tunnel across the maze’s mid-row.
#   • LED “cosine fade” accent colors (no flashing).
#   • Defensive drawing wrappers so bitmaptools is optional.
#   • Debug logging throttled with DEBUG_MIN_INTERVAL.
#
# Controls (MacroPad keys):
#   • K1/K3/K5/K7 → UP/LEFT/RIGHT/DOWN
#   • K11 → START / Pause toggle
#   • K9  → MENU (return to launcher)
#
# Gameplay tuning (constants):
#   • Player speed, ghost speed, frightened ghost speed.
#   • Power pellet duration (`FRIGHT_TIME`).
#   • Scoring: pellet, power, ghost, etc.
#   • Starting lives (`START_LIVES`).
#
# Implementation notes:
#   • Maze is tile-based (TILE=4 px logic, rendered as 8×8 OLED cells at SCALE=2).
#   • `_build_map()` carves simple lanes, ghost pen, warp corridor, and pellets.
#   • Movement is pixel-based with gentle lane-centering and queued turns.
#   • Ghosts choose directions at tile centers via Manhattan distance or random.
#   • Drawing is dirty-rect based: only changed tiles/actors are redrawn.
#   • Optional MerlinChrome.bmp logo shown in title/between/gameover states.
#
# ---------------------------------------------------------------------------

import math, random, time
import displayio, terminalio
from micropython import const

# ---- Optional deps ----
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

# ---- Display / layout (use const ONLY for literals) ----
SCREEN_W = const(128)
SCREEN_H = const(64)
SCALE = const(2)                 # software 2× zoom
SCORE_BAR_H = const(10)          # reserved strip at top for score
HUD_Y1 = const(40)               # keep prompts below Merlin logo
HUD_Y2 = const(53)

# Derived values (NO const() on expressions)
VIEW_W_LOG = SCREEN_W // SCALE
VIEW_H_LOG = (SCREEN_H - SCORE_BAR_H) // SCALE

# ---- Key mapping (prompts never show numbers) ----
K_UP, K_LEFT, K_RIGHT, K_DOWN = 1, 3, 5, 7
K_MENU  = 9
K_START = 11

# ---- Colors (1-bit) ----
BG = const(0)
FG = const(1)

# ---- Tiles & maze ----
TILE = const(4)  # 4×4 logical pixels (renders as 8×8 on OLED with SCALE=2)
WALL = const(1)
FLOOR = const(0)
PELLET = const(2)
POWER = const(3)

# ---- Gameplay tuning ----
PLAYER_SPEED = 26.0
GHOST_SPEED  = 22.0
FRIGHT_SPEED = 16.0
FRIGHT_TIME  = 10.0
PELLET_SCORE = 10
POWER_SCORE  = 50
GHOST_SCORE  = 200
START_LIVES  = 3

# ---- LEDs: cosine fade (no flashing) ----
LED_PERIOD = 3.2
LED_RGB    = (255, 160, 40)
LED_DIM, LED_MAX = 0.12, 0.65

# ---- Debugging ----
DEBUG = True
DEBUG_MIN_INTERVAL = 0.06  # throttle prints a bit tighter

# ---- Defensive bitmaptools helpers ----
def _clamp(v, lo, hi):
    if v < lo: return lo
    if v > hi: return hi
    return v

def _rect_fill(bmp, x, y, w, h, c=1):
    if w <= 0 or h <= 0: return
    x0 = _clamp(x, 0, bmp.width)
    y0 = _clamp(y, 0, bmp.height)
    x1 = _clamp(x + w, 0, bmp.width)
    y1 = _clamp(y + h, 0, bmp.height)
    if x1 <= x0 or y1 <= y0: return
    W, H = x1 - x0, y1 - y0
    if _HAS_BT:
        try:
            bitmaptools.fill_region(bmp, x0, y0, W, H, c)
            return
        except Exception:
            pass
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            bmp[xx, yy] = c

# ---- Main class ----
class pacman:
    # ---------- Debug helpers ----------
    def _dbg(self, *args):
        if not DEBUG: return
        t = time.monotonic()
        if not hasattr(self, "_dbg_last"): self._dbg_last = 0.0
        if (t - self._dbg_last) >= DEBUG_MIN_INTERVAL:
            try: print(*args)
            except Exception: pass
            self._dbg_last = t

    def _key_name(self, key):
        if key == K_UP: return "UP"
        if key == K_DOWN: return "DOWN"
        if key == K_LEFT: return "LEFT"
        if key == K_RIGHT: return "RIGHT"
        if key == K_START: return "START"
        if key == K_MENU: return "MENU"
        return str(key)

    def __init__(self, macropad=None, tones=None, **kwargs):
        self.macropad = macropad
        self.group = displayio.Group()

        # Framebuffer (1-bit)
        self._bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
        self._pal = displayio.Palette(2); self._pal[BG]=0x000000; self._pal[FG]=0xFFFFFF
        self._tg  = displayio.TileGrid(self._bmp, pixel_shader=self._pal, x=0, y=0)
        self.group.append(self._tg)

        # Optional Merlin logo
        self._logo_tg = None

        # HUD labels
        self._lbl1 = None; self._lbl2 = None
        if _HAVE_LABEL:
            self._lbl1 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=HUD_Y1)
            self._lbl2 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=HUD_Y2)
            self.group.append(self._lbl1); self.group.append(self._lbl2)

        # Score label
        self._score_lbl = None
        if _HAVE_LABEL:
            self._score_lbl = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=8)
            self.group.append(self._score_lbl)

        # RNG
        try: random.seed(0xE1EC)
        except Exception: pass

        # World / camera
        self._build_map(16, 16)
        self.cam_x, self.cam_y = 0, 0
        self.prev_cam_x, self.prev_cam_y = -9999, -9999

        # State
        self._state  = "title"
        self._score  = 0
        self._lives  = START_LIVES
        self._level  = 1
        self._fright_t = 0.0
        self._want_dir = (0, 0)
        self._last_t = time.monotonic()
        self._led_phase = 0.0

        # Spawns & actors
        self._create_spawns()
        self._reset_positions(clear_want=True)

        # dirty-draw caches
        self._prev_player_xy = None
        self._prev_ghost_xy = [None]*2

        # Title UI
        self._show_logo(True)
        self._set_prompts("Pac Man", "D-Pad to Start")
        self._update_camera()
        self._draw_frame(force_full=True)
        self._update_score_label()  # clear initially
        
        # LED throttling
        self._led_phase = 0.0
        self._led_last_t = 0.0
        self._led_cache = [(-1, -1, -1)] * 12
        try:
            if self.macropad:
                self.macropad.pixels.auto_write = False
        except Exception:
            pass

        # one-shot full redraw flag (prevents double draw on state transition)
        self._force_full_redraw = False

        self._dbg_last = 0.0
        self._dbg("PAC DEBUG: map=%dx%d tile=%d view=%dx%d" %
                  (self.MW, self.MH, TILE, VIEW_W_LOG, VIEW_H_LOG))
        tx, ty = self._tile_xy(self.px0, self.py0)
        self._dbg("PAC DEBUG: spawn tile=(%d,%d) px=(%.1f,%.1f)" % (tx, ty, self.px0, self.py0))

    # ---------- Map & spawns ----------
    def _build_map(self, W, H):
        self.MW, self.MH = W, H

        # Start with solid walls
        self.map = [[WALL for _ in range(W)] for _ in range(H)]

        # Carve lanes: odd rows open horizontally; every 4th column opens vertically
        for y in range(1, H - 1):
            for x in range(1, W - 1):
                if (y % 2 == 1) or (x % 4 == 1):
                    self.map[y][x] = FLOOR

        # Simple "ghost pen" near center (open interior, top wall except a doorway)
        gy, gx = H // 2 - 1, W // 2 - 3
        for yy in range(gy, gy + 3):
            for xx in range(gx, gx + 6):
                if 0 <= yy < H and 0 <= xx < W:
                    self.map[yy][xx] = FLOOR
        for xx in range(gx, gx + 6):
            if 0 <= gy - 1 < H and 0 <= xx < W:
                if xx not in (gx + 2, gx + 3):
                    self.map[gy - 1][xx] = WALL

        # Side warp corridor row (the row used by _apply_warp); open 3 tiles at each edge
        wr = H // 2 + 2
        if 0 <= wr < H:
            for k in range(0, 3):
                if 0 <= k < W: self.map[wr][k] = FLOOR
                if 0 <= (W - 1 - k) < W: self.map[wr][W - 1 - k] = FLOOR

        # Power pellets: store coordinates so _refill_pellets() can restore them every level
        self._power_tiles = [(1, 1), (W - 2, 1), (1, H - 2), (W - 2, H - 2)]
        for (cx, cy) in self._power_tiles:
            if 0 <= cx < W and 0 <= cy < H and self.map[cy][cx] != WALL:
                self.map[cy][cx] = POWER

        # Fill all remaining floors with pellets and count them
        self._refill_pellets()

    def _refill_pellets(self):
        # Convert any FLOOR back to PELLET (do not touch WALL)
        for y in range(self.MH):
            for x in range(self.MW):
                if self.map[y][x] == FLOOR:
                    self.map[y][x] = PELLET

        # Re-place power pellets every level
        # (Defensive: if _power_tiles wasn't set for some reason, compute corners)
        if not hasattr(self, "_power_tiles") or not self._power_tiles:
            self._power_tiles = [(1, 1), (self.MW-2, 1), (1, self.MH-2), (self.MW-2, self.MH-2)]
        for (cx, cy) in self._power_tiles:
            if 0 <= cx < self.MW and 0 <= cy < self.MH and self.map[cy][cx] != WALL:
                self.map[cy][cx] = POWER

        # Recount pellets (normal + power)
        self._pellets = 0
        for y in range(self.MH):
            for x in range(self.MW):
                if self.map[y][x] in (PELLET, POWER):
                    self._pellets += 1

    def _create_spawns(self):
        cx, cy = self.MW // 2, self.MH - 3

        def is_open(tx, ty):
            return (0 <= tx < self.MW) and (0 <= ty < self.MH) and self.map[ty][tx] != WALL

        best = None
        best_d = 1e9

        # Prefer true 4-way intersections
        for ty in range(1, self.MH - 1):
            for tx in range(1, self.MW - 1):
                if self.map[ty][tx] == WALL:
                    continue
                horiz = is_open(tx - 1, ty) and is_open(tx + 1, ty)
                vert  = is_open(tx, ty - 1) and is_open(tx, ty + 1)
                if horiz and vert:
                    d = abs(tx - cx) + abs(ty - cy)
                    if d < best_d:
                        best_d = d
                        best = (tx, ty)

        # Fallback: any tile that has at least one horizontal AND one vertical option (T-junction)
        if best is None:
            for ty in range(1, self.MH - 1):
                for tx in range(1, self.MW - 1):
                    if self.map[ty][tx] == WALL:
                        continue
                    horiz = is_open(tx - 1, ty) or is_open(tx + 1, ty)
                    vert  = is_open(tx, ty - 1) or is_open(tx, ty + 1)
                    if horiz and vert:
                        d = abs(tx - cx) + abs(ty - cy)
                        if d < best_d:
                            best_d = d
                            best = (tx, ty)

        # Final fallback: mid column, near bottom, but still center within tile
        if best is None:
            best = (self.MW // 2, self.MH - 3)

        spx_t, spy_t = best
        # IMPORTANT: place at tile CENTER (+2) so we are "centered" for the first turn
        self.px0 = spx_t * TILE + 2.0
        self.py0 = spy_t * TILE + 2.0

        # Ghosts near center, on tile centers too
        gc_y = self.MH // 2
        self.ghost_spawns = [
            ((self.MW // 2 - 1) * TILE + 2.0, gc_y * TILE + 2.0),
            ((self.MW // 2 + 1) * TILE + 2.0, gc_y * TILE + 2.0),
        ]

    def _clear_playfield(self):
        _rect_fill(self._bmp, 0, SCORE_BAR_H, SCREEN_W, SCREEN_H - SCORE_BAR_H, BG)

    # ---------- Logo & HUD ----------
    def _show_logo(self, show):
        try:
            if self._tg:
                self._tg.hidden = bool(show)
        except Exception:
            pass
        if show and self._logo_tg is None:
            try:
                bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
                self._logo_tg = displayio.TileGrid(
                    bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
                )
                self.group.insert(1, self._logo_tg)
            except Exception:
                self._logo_tg = None
        elif (not show) and self._logo_tg is not None:
            try:
                self.group.remove(self._logo_tg)
            except Exception:
                pass
            self._logo_tg = None

    def _set_prompts(self, line1, line2):
        if not _HAVE_LABEL:
            return

        def _center(lbl, text, y):
            if not lbl:
                return
            lbl.text = text or ""
            if lbl.text == "":
                lbl.x = 0
                lbl.hidden = True
                return
            lbl.hidden = False
            # width in pixels = (character count) * (font width)
            font_w, font_h = terminalio.FONT.get_bounding_box()
            txt_w = len(lbl.text) * font_w
            lbl.x = max(0, (SCREEN_W - txt_w) // 2)
            lbl.y = y

        _center(self._lbl1, line1, HUD_Y1)
        _center(self._lbl2, line2, HUD_Y2)

    def _update_score_label(self):
        if not _HAVE_LABEL or not self._score_lbl:
            return

        if self._state == "play":
            self._score_lbl.text = "S: %d   L: %d" % (self._score, self._lives)
        elif self._state == "pause":
            self._score_lbl.text = "Paused"
        elif self._state == "gameover":
            # in gameover we already show score in prompt lines → hide top label
            self._score_lbl.text = ""
        else:
            self._score_lbl.text = ""

        # --- center it horizontally ---
        font_w, font_h = terminalio.FONT.get_bounding_box()
        txt_w = len(self._score_lbl.text) * font_w
        self._score_lbl.x = max(0, (SCREEN_W - txt_w) // 2)
        # keep it near the top bar
        self._score_lbl.y = 8

    # ---------- Beeps & LEDs ----------
    def _beep(self, f, ms):
        if not self.macropad: return
        try:
            self.macropad.play_tone(f, ms / 1000.0)
        except Exception:
            pass

    def _leds_cosine(self, dt):
        if not self.macropad:
            return
        now = time.monotonic()
        if (now - self._led_last_t) < 0.033:
            return
        self._led_last_t = now

        self._led_phase += (dt / LED_PERIOD) * (2.0 * math.pi)
        while self._led_phase > 2.0 * math.pi:
            self._led_phase -= 2.0 * math.pi
        c = 0.5 + 0.5 * math.cos(self._led_phase)
        scale = LED_DIM + (LED_MAX - LED_DIM) * c
        base = (int(LED_RGB[0] * scale), int(LED_RGB[1] * scale), int(LED_RGB[2] * scale))

        RED  = (90, 0, 0)
        BLUE = (0, 0, 120)

        frame = [base] * 12
        for k in (1, 3, 5, 7):
            frame[k] = RED
        frame[4] = BLUE

        dirty = False
        try:
            for i in range(12):
                if frame[i] != self._led_cache[i]:
                    self.macropad.pixels[i] = frame[i]
                    self._led_cache[i] = frame[i]
                    dirty = True
            if dirty:
                self.macropad.pixels.show()
        except Exception:
            pass

    # ---------- Tile helpers ----------
    def _tile_xy(self, px, py):
        return int(px // TILE), int(py // TILE)

    def _is_wall(self, tx, ty):
        if tx < 0 or ty < 0 or tx >= self.MW or ty >= self.MH: return True
        return self.map[ty][tx] == WALL

    def _is_open(self, tx, ty):
        if tx < 0 or ty < 0 or tx >= self.MW or ty >= self.MH: return False
        return self.map[ty][tx] != WALL

    def _center_in_tile(self, p):
        fx = (p["x"] % TILE); fy = (p["y"] % TILE)
        EPS = 0.35
        return ((1.0 - EPS) <= fx <= (TILE - 1.0 + EPS)) and ((1.0 - EPS) <= fy <= (TILE - 1.0 + EPS))

    def _apply_warp(self, p):
        ty = int(p["y"] // TILE)
        wr = self.MH // 2 + 2
        if ty == wr:
            if p["x"] < TILE:
                p["x"] = float((self.MW - 2) * TILE - 1)
            elif p["x"] >= (self.MW - 1) * TILE:
                p["x"] = float(1 * TILE)

    # ---------- Movement / turning ----------
    def _attempt_turn(self, p, want, *, force=False):
        if want == (0, 0):
            return False

        tx, ty = self._tile_xy(p["x"], p["y"])
        nx, ny = tx + want[0], ty + want[1]
        moving = (abs(p["dx"]) + abs(p["dy"])) > 0.0
        centered = self._center_in_tile(p)
        open_ok = self._is_open(nx, ny)

        self._dbg("TURN? pos=(%.2f,%.2f) tile=(%d,%d) want=%s moving=%s centered=%s open=%s force=%s" %
                  (p["x"], p["y"], tx, ty, str(want), str(moving), str(centered), str(open_ok), str(force)))

        if not open_ok:
            return False

        # stopped -> always ok; moving -> ok if centered or forced
        if (not moving) or centered or force:
            if want[0] != 0:
                p["y"] = ty * TILE + 2.0
            else:
                p["x"] = tx * TILE + 2.0
            p["dx"], p["dy"] = float(want[0]), float(want[1])
            # nudge out of the exact tile center
            NUDGE = 0.08
            p["x"] += p["dx"] * NUDGE
            p["y"] += p["dy"] * NUDGE
            self._dbg("TURN APPLY -> dir=(%.0f,%.0f) pos=(%.2f,%.2f) [nudged]" %
                      (p["dx"], p["dy"], p["x"], p["y"]))
            return True

        return False

    def _apply_queued_now_if_possible(self, a):
        if a is not self.player: return False
        want = self._want_dir
        if want == (0, 0): return False
        tx, ty = self._tile_xy(a["x"], a["y"])
        nx, ny = tx + want[0], ty + want[1]
        if self._is_open(nx, ny):
            if self._attempt_turn(a, want, force=True):
                self._dbg("APPLY QUEUED -> clear want")
                self._want_dir = (0, 0)
                return True
        return False

    def _move_actor(self, a, speed, dt):
        # If the player is stopped, try to start moving immediately with any queued dir.
        if a is self.player and (abs(a["dx"]) + abs(a["dy"])) == 0.0:
            self._apply_queued_now_if_possible(a)

        nx = a["x"] + a["dx"] * speed * dt
        ny = a["y"] + a["dy"] * speed * dt
        self._dbg("MOVE in pos=(%.2f,%.2f) dir=(%.0f,%.0f) nx,ny=(%.2f,%.2f)" %
                (a["x"], a["y"], a["dx"], a["dy"], nx, ny))

        # ---- X axis first ----
        xdir = 1 if a["dx"] > 0 else (-1 if a["dx"] < 0 else 0)
        x_clamped = False
        if xdir != 0:
            ty  = int(a["y"] // TILE)
            tx0 = int(a["x"] // TILE)
            txn = int(nx // TILE)
            if txn != tx0:
                ahead = tx0 + xdir
                blocked = self._is_wall(ahead, ty)
                self._dbg("X step: ty=%d tx0->txn: %d->%d ahead=(%d,%d) blocked=%s" %
                        (ty, tx0, txn, ahead, ty, str(blocked)))
                if blocked:
                    # Clamp and stop X, then immediately try queued turn if any.
                    if xdir > 0:
                        a["x"] = (tx0 + 1) * TILE - 1
                    else:
                        a["x"] = tx0 * TILE
                    a["dx"] = 0.0
                    x_clamped = True
                    self._dbg("X CLAMP stop at x=%.1f" % a["x"])
                    if a is self.player:
                        self._apply_queued_now_if_possible(a)
                else:
                    a["x"] = nx
            else:
                a["x"] = nx
        else:
            a["x"] = nx

        # ---- Y axis second ----
        ydir = 1 if a["dy"] > 0 else (-1 if a["dy"] < 0 else 0)
        y_clamped = False
        if ydir != 0:
            tx  = int(a["x"] // TILE)
            ty0 = int(a["y"] // TILE)
            tyn = int(ny // TILE)
            if tyn != ty0:
                ahead = ty0 + ydir
                blocked = self._is_wall(tx, ahead)
                self._dbg("Y step: tx=%d ty0->tyn: %d->%d ahead=(%d,%d) blocked=%s" %
                        (tx, ty0, tyn, tx, ahead, str(blocked)))
                if blocked:
                    # Clamp and stop Y, then immediately try queued turn if any.
                    if ydir > 0:
                        a["y"] = (ty0 + 1) * TILE - 1
                    else:
                        a["y"] = ty0 * TILE
                    a["dy"] = 0.0
                    y_clamped = True
                    self._dbg("Y CLAMP stop at y=%.1f" % a["y"])
                    if a is self.player:
                        self._apply_queued_now_if_possible(a)
                else:
                    a["y"] = ny
            else:
                a["y"] = ny
        else:
            a["y"] = ny

        # ---- Gentle lane-centering on the orthogonal axis only ----
        moving_x = (a["dx"] != 0.0)
        moving_y = (a["dy"] != 0.0)
        if moving_x and not moving_y:
            # Moving horizontally -> only center Y
            ty = int(a["y"] // TILE)
            a["y"] = ty * TILE + 2.0
        elif moving_y and not moving_x:
            # Moving vertically -> only center X
            tx = int(a["x"] // TILE)
            a["x"] = tx * TILE + 2.0
        elif (not moving_x) and (not moving_y):
            # Fully stopped -> center both
            tx = int(a["x"] // TILE)
            ty = int(a["y"] // TILE)
            a["x"] = tx * TILE + 2.0
            a["y"] = ty * TILE + 2.0

        # If we ended fully stopped (e.g., clamped into a corner), try queued turn once more.
        if a is self.player and a["dx"] == 0.0 and a["dy"] == 0.0 and (x_clamped or y_clamped):
            self._apply_queued_now_if_possible(a)

        self._apply_warp(a)
        self._dbg("MOVE out pos=(%.2f,%.2f) dir=(%.0f,%.0f)" % (a["x"], a["y"], a["dx"], a["dy"]))
        
    # ---------- Ghost AI ----------
    def _ghost_options(self, g):
        tx, ty = self._tile_xy(g["x"], g["y"])
        opts, dirs = [], [(1,0),(-1,0),(0,1),(0,-1)]
        bx, by = int(-g["dx"]), int(-g["dy"])
        for (dx,dy) in dirs:
            if dx == bx and dy == by: continue
            if self._is_open(tx + dx, ty + dy):
                opts.append((dx,dy))
        if not opts and self._is_open(tx + bx, ty + by):
            opts = [(bx,by)]
        return opts

    def _manhattan_after(self, g, dx, dy, flee=False):
        gx = g["x"] + dx * TILE
        gy = g["y"] + dy * TILE
        d = abs(gx - self.player["x"]) + abs(gy - self.player["y"])
        return -d if flee else d

    def _ghost_choose(self, g, frightened):
        if not self._center_in_tile(g): return
        opts = self._ghost_options(g)
        if not opts: return
        if frightened:
            best, bd = opts[0], -1
            for (dx,dy) in opts:
                d = self._manhattan_after(g, dx, dy, flee=True)
                if d > bd: bd, best = d, (dx,dy)
            g["dx"], g["dy"] = float(best[0]), float(best[1])
        else:
            if g["kind"] == "chase":
                best, bd = opts[0], 1e9
                for (dx,dy) in opts:
                    d = self._manhattan_after(g, dx, dy, flee=False)
                    if d < bd: bd, best = d, (dx,dy)
                g["dx"], g["dy"] = float(best[0]), float(best[1])
            else:
                idx = random.randint(0, len(opts)-1)
                g["dx"], g["dy"] = opts[idx]

    # ---------- Eating & collisions ----------
    def _eat_at_player(self):
        tx, ty = self._tile_xy(self.player["x"], self.player["y"])
        if tx < 0 or ty < 0 or tx >= self.MW or ty >= self.MH: return
        v = self.map[ty][tx]
        if v == PELLET:
            self.map[ty][tx] = FLOOR
            self._pellets -= 1
            self._score += PELLET_SCORE
            self._beep(880, 25)
            self._draw_tile(tx, ty)
            self._update_score_label()
        elif v == POWER:
            self.map[ty][tx] = FLOOR
            self._pellets -= 1
            self._score += POWER_SCORE
            self._fright_t = FRIGHT_TIME
            self._beep(523, 90)
            self._draw_tile(tx, ty)
            self._update_score_label()

    def _collide_ghosts(self):
        px, py = self.player["x"], self.player["y"]
        for g in self.ghosts:
            if abs(px - g["x"]) <= 2 and abs(py - g["y"]) <= 2:
                if self._fright_t > 0:
                    self._score += GHOST_SCORE
                    self._beep(1200, 110)
                    spx, spy = self.ghost_spawns[0 if g["kind"] == "chase" else 1]
                    g["x"], g["y"] = float(spx), float(spy)
                    g["dx"], g["dy"] = 1.0, 0.0
                    self._update_score_label()
                else:
                    self._lives -= 1
                    self._beep(220, 200)
                    self._reset_positions(clear_want=True)
                    self._update_camera()
                    # Do NOT draw here; let the next tick perform the full redraw
                    self._force_full_redraw = True
                    self._update_score_label()
                    self._dbg("DEATH: positions reset (want cleared)")
                    break

    def _reset_positions(self, clear_want=True):
        self.player = {"x": float(self.px0), "y": float(self.py0), "dx": 0.0, "dy": 0.0}
        self.ghosts = []
        for i, (gx, gy) in enumerate(self.ghost_spawns):
            self.ghosts.append({
                "x": float(gx), "y": float(gy),
                "dx": (1.0 if i == 0 else -1.0), "dy": 0.0,
                "kind": "chase" if i == 0 else "wander",
            })
        if clear_want:
            self._want_dir = (0, 0)
        self._prev_player_xy = None
        self._prev_ghost_xy = [None]*len(self.ghosts)
        self._started = False
        self._play_t0 = time.monotonic()
        self._dbg("RESET: clear_want=%s want=%s" % (str(clear_want), str(self._want_dir)))

    # ---------- Dirty drawing helpers ----------
    def _draw_tile(self, tx, ty):
        if tx < 0 or ty < 0 or tx >= self.MW or ty >= self.MH:
            return
        px_log = tx * TILE - self.cam_x
        py_log = ty * TILE - self.cam_y
        if px_log >= VIEW_W_LOG or py_log >= VIEW_H_LOG or (px_log + TILE) <= 0 or (py_log + TILE) <= 0:
            return
        px = px_log * SCALE
        py = py_log * SCALE + SCORE_BAR_H
        tw = TILE * SCALE
        th = TILE * SCALE

        cell = self.map[ty][tx]
        _rect_fill(self._bmp, px, py, tw, th, BG)
        if cell == WALL:
            _rect_fill(self._bmp, px, py, tw, th, FG)
        elif cell == PELLET:
            cx = _clamp(px + tw // 2, 0, self._bmp.width - 1)
            cy = _clamp(py + th // 2, 0, self._bmp.height - 1)
            self._bmp[cx, cy] = FG
        elif cell == POWER:
            s = 2 * SCALE
            _rect_fill(self._bmp, px + tw // 2 - s // 2, py + th // 2 - s // 2, s, s, FG)

    def _draw_actor(self, x, y, size=3, ghost=False):
        # Convert world → screen pixels
        px = int((x - self.cam_x) * SCALE) - (size * SCALE) // 2
        py = int((y - self.cam_y) * SCALE) - (size * SCALE) // 2 + SCORE_BAR_H

        w = max(1, size * SCALE)
        h = max(1, size * SCALE)

        # Clip to framebuffer and to the playfield (y >= SCORE_BAR_H)
        x0 = _clamp(px, 0, self._bmp.width)
        y0 = _clamp(py, SCORE_BAR_H, self._bmp.height)
        x1 = _clamp(px + w, 0, self._bmp.width)
        y1 = _clamp(py + h, SCORE_BAR_H, self._bmp.height)
        if x1 <= x0 or y1 <= y0:
            return

        # Body
        _rect_fill(self._bmp, x0, y0, x1 - x0, y1 - y0, FG)

        # Ghost “eye”: a black dot in the center (scaled for visibility)
        # Flash the dot while frightened (power pellet active): dot toggles on/off.
        if ghost:
            # Blink ~6 times per second while frightened
            frightened = (self._fright_t > 0.0)
            blink_on = (int(time.monotonic() * 6) & 1) == 0  # toggles 0/1

            # Draw the dot if not frightened OR (frightened and blink_on)
            if (not frightened) or blink_on:
                cx = (x0 + x1) // 2
                cy = (y0 + y1) // 2
                dot = max(1, SCALE // 1)   # usually 2×2 with SCALE=2
                _rect_fill(
                    self._bmp,
                    _clamp(cx - dot // 2, 0, self._bmp.width),
                    _clamp(cy - dot // 2, SCORE_BAR_H, self._bmp.height),
                    min(dot, self._bmp.width - cx + dot // 2),
                    min(dot, self._bmp.height - cy + dot // 2),
                    BG
                )
              
    def _erase_actor_footprint(self, wx, wy, size=3):
        half = (size * 0.5)
        x0 = int((wx - half) // TILE)
        y0 = int((wy - half) // TILE)
        x1 = int((wx + half) // TILE)
        y1 = int((wy + half) // TILE)
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                self._draw_tile(tx, ty)

    # ---------- Camera & drawing ----------
    def _update_camera(self):
        ptx, pty = self._tile_xy(self.player["x"], self.player["y"])
        cx = ptx * TILE - VIEW_W_LOG // 2
        cy = pty * TILE - VIEW_H_LOG // 2
        max_x = self.MW * TILE - VIEW_W_LOG
        max_y = self.MH * TILE - VIEW_H_LOG
        if cx < 0: cx = 0
        if cy < 0: cy = 0
        if cx > max_x: cx = max_x
        if cy > max_y: cy = max_y
        cx = (cx // TILE) * TILE
        cy = (cy // TILE) * TILE
        self.prev_cam_x, self.prev_cam_y = self.cam_x, self.cam_y
        self.cam_x, self.cam_y = int(cx), int(cy)

    def _draw_frame(self, force_full=False):
        cam_moved = force_full or (self.prev_cam_x != self.cam_x) or (self.prev_cam_y != self.cam_y)

        if cam_moved:
            # Always clean the score bar so no stray pixels linger behind labels
            _rect_fill(self._bmp, 0, 0, SCREEN_W, SCORE_BAR_H, BG)

            self._clear_playfield()
            tx0 = self.cam_x // TILE
            ty0 = self.cam_y // TILE
            tiles_w = VIEW_W_LOG // TILE + 2
            tiles_h = VIEW_H_LOG // TILE + 2
            for ty in range(ty0, ty0 + tiles_h):
                if ty < 0 or ty >= self.MH: continue
                for tx in range(tx0, tx0 + tiles_w):
                    if tx < 0 or tx >= self.MW: continue
                    self._draw_tile(tx, ty)
        else:
            if self._prev_player_xy is not None:
                ox, oy = self._prev_player_xy
                self._erase_actor_footprint(ox, oy, 3)

            if len(self._prev_ghost_xy) != len(self.ghosts):
                self._prev_ghost_xy = [None] * len(self.ghosts)
            for i, prev in enumerate(self._prev_ghost_xy):
                if prev is not None:
                    self._erase_actor_footprint(prev[0], prev[1], 3)

        # Player
        self._draw_actor(self.player["x"], self.player["y"], 3)
        self._prev_player_xy = (self.player["x"], self.player["y"])

        if len(self._prev_ghost_xy) != len(self.ghosts):
            self._prev_ghost_xy = [None] * len(self.ghosts)
        for i, g in enumerate(self.ghosts):
            self._draw_actor(g["x"], g["y"], 3, ghost=True)
            self._prev_ghost_xy[i] = (g["x"], g["y"])

    # ---------- Frame batching ----------
    def _begin_draw(self):
        if not self.macropad: return
        try:
            self._saved_autorefresh = getattr(self.macropad.display, "auto_refresh", True)
            self.macropad.display.auto_refresh = False
        except Exception:
            self._saved_autorefresh = None

    def _end_draw(self):
        if not self.macropad: return
        try:
            self.macropad.display.refresh(minimum_frames_per_second=0)
        except Exception:
            try:
                self.macropad.display.refresh()
            except Exception:
                pass
        try:
            if self._saved_autorefresh is not None:
                self.macropad.display.auto_refresh = self._saved_autorefresh
        except Exception:
            pass

    # ---------- Start helpers ----------
    def _start_play(self):
        self._state = "play"
        self._show_logo(False)
        self._set_prompts(" ", "")
        self._beep(784, 120)
        self._update_camera()
        # Defer the first full draw to next tick to avoid double-render flash
        self._force_full_redraw = True
        self._update_score_label()
        self._started = False
        self._play_t0 = time.monotonic()
        self._dbg("STATE -> play (setup complete, want=%s)" % (str(self._want_dir),))

    # ---------- State update ----------
    def _tick_play(self, dt):
        self._leds_cosine(dt)

        # Try queued turn once per tick (only if queued)
        if self._want_dir != (0, 0):
            if self._attempt_turn(self.player, self._want_dir):
                self._dbg("TICK APPLY OK -> clear want")
                self._want_dir = (0, 0)

        frightened = (self._fright_t > 0.0)
        ps = PLAYER_SPEED
        gs = FRIGHT_SPEED if frightened else GHOST_SPEED

        self._move_actor(self.player, ps, dt)

        allow_ghosts = self._started or ((time.monotonic() - self._play_t0) > 1.25)
        if allow_ghosts:
            for g in self.ghosts:
                self._ghost_choose(g, frightened=frightened)
                self._move_actor(g, gs, dt)

        self._eat_at_player()
        self._collide_ghosts()
        if self._fright_t > 0.0:
            self._fright_t -= dt
            if self._fright_t < 0.0: self._fright_t = 0.0

        if self._pellets <= 0:
            self._level += 1
            self._show_logo(True)
            self._state = "between"
            self._set_prompts("S", "Next Level")
            self._beep(660, 160)

        if self._state == "play" and self._lives <= 0:
            self._state = "gameover"
            self._show_logo(True)
            # Show the final score above the "Game Over" line
            self._set_prompts(f"Score: {self._score}", "Game Over")
            # Hide the top score/lives indicator
            self._update_score_label()

        self._update_camera()
        if self._state == "play":
            self._update_hud_play()

        # One-shot forced full redraw after starting or death reset
        self._draw_frame(force_full=self._force_full_redraw)
        self._force_full_redraw = False

    def _update_hud_play(self):
        self._set_prompts(" ", "")
        self._update_score_label()

    # ---------- Public API ----------
    def new_game(self):
        self._score = 0
        self._lives = START_LIVES
        self._level = 1
        self._fright_t = 0.0
        self._refill_pellets()
        self._create_spawns()  # ensure spawns consistent with current map
        self._reset_positions(clear_want=True)
        self._show_logo(True)
        self._state = "title"
        self._set_prompts("Press Start", "…or use an arrow")
        self._update_camera()
        self._draw_frame(force_full=True)
        self._update_score_label()
        self._dbg("STATE -> title (new_game)")

    def tick(self, dt=None):
        now = time.monotonic()
        if dt is None:
            dt = now - self._last_t
        self._last_t = now
        if dt < 0: dt = 0.0
        if dt > 0.08: dt = 0.08

        self._begin_draw()

        if self._state == "title":
            self._leds_cosine(dt)
            self._end_draw()
            return

        if self._state == "play":
            self._tick_play(dt)
            self._end_draw()
            return

        if self._state == "pause":
            self._leds_cosine(dt)
            self._end_draw()
            return

        if self._state in ("between","gameover"):
            self._leds_cosine(dt)
            self._end_draw()
            return

    def button(self, key, pressed=True):
        # Back to menu
        if pressed and key == K_MENU:
            self._beep(440, 60)
            self._state = "title"
            self._show_logo(True)
            self._set_prompts("Press Start", "…or use an arrow")
            self._update_camera()
            self._draw_frame(force_full=True)
            self._update_score_label()
            self._dbg("STATE -> title (menu)")
            return

        # Auto-start on arrow from title/between/gameover
        if self._state in ("title", "between", "gameover"):
            if pressed and key in (K_LEFT, K_RIGHT, K_UP, K_DOWN):
                if key == K_LEFT:  self._want_dir = (-1, 0)
                if key == K_RIGHT: self._want_dir = ( 1, 0)
                if key == K_UP:    self._want_dir = ( 0,-1)
                if key == K_DOWN:  self._want_dir = ( 0, 1)
                self._dbg("BTN %s -> queue %s (auto-start)" % (self._key_name(key), str(self._want_dir)))
                if self._state == "between":
                    self._refill_pellets()
                    self._reset_positions(clear_want=False)
                else:
                    self._score = 0
                    self._lives = START_LIVES
                    self._level = 1
                    self._fright_t = 0.0
                    self._refill_pellets()
                    self._reset_positions(clear_want=False)
                self._started = True
                self._start_play()
                # Try to apply at spawn immediately
                self._apply_queued_now_if_possible(self.player)
                return

            if pressed and key == K_START:
                if self._state == "between":
                    self._refill_pellets()
                    self._reset_positions(clear_want=True)
                else:
                    self._score = 0
                    self._lives = START_LIVES
                    self._level = 1
                    self._fright_t = 0.0
                    self._refill_pellets()
                    self._reset_positions(clear_want=True)
                self._started = False
                self._dbg("START -> play")
                self._start_play()
            return

        # Pause toggle
        if pressed and key == K_START:
            if self._state == "play":
                self._state = "pause"
                self._set_prompts("", "")
                self._update_score_label()
                self._beep(392, 60)
                self._dbg("STATE -> pause")
            elif self._state == "pause":
                self._state = "play"
                self._set_prompts("", "")
                self._update_score_label()
                self._beep(784, 60)
                self._dbg("STATE -> play")
            return
        
        # Direction queue (play/pause)
        if pressed and key in (K_LEFT, K_RIGHT, K_UP, K_DOWN):
            if key == K_LEFT:  want = (-1, 0)
            if key == K_RIGHT: want = ( 1, 0)
            if key == K_UP:    want = ( 0,-1)
            if key == K_DOWN:  want = ( 0, 1)
            self._want_dir = want
            self._started = True
            self._dbg("BTN %s -> queue %s (state=%s)" % (self._key_name(key), str(self._want_dir), self._state))
            if self._state == "play":
                # Apply right now if possible; else it will apply on next clamp/stop/tick
                self._apply_queued_now_if_possible(self.player)

    def cleanup(self):
        # --- LEDs off (and restore auto_write) ---
        try:
            if self.macropad:
                try:
                    for i in range(12):
                        self.macropad.pixels[i] = (0, 0, 0)
                    self.macropad.pixels.show()
                except Exception:
                    pass
                try:
                    # Put pixels back to default behavior
                    self.macropad.pixels.auto_write = True
                except Exception:
                    pass
        except Exception:
            pass

        # --- Stop any tone ---
        try:
            if self.macropad and hasattr(self.macropad, "stop_tone"):
                self.macropad.stop_tone()
        except Exception:
            pass

        # --- Clear HUD labels / score label ---
        if _HAVE_LABEL:
            try:
                if self._lbl1: self._lbl1.text = ""
                if self._lbl2: self._lbl2.text = ""
                if self._score_lbl: self._score_lbl.text = ""
            except Exception:
                pass

        # --- Hide/remove optional logo tilegrid ---
        try:
            # This will also drop the logo TileGrid from the display group if present
            self._show_logo(False)
        except Exception:
            pass

        # --- Blank the framebuffer and refresh once ---
        try:
            # Clear full screen (score bar + playfield)
            _rect_fill(self._bmp, 0, 0, SCREEN_W, SCREEN_H, BG)
        except Exception:
            pass

        # --- Ensure display gets one clean refresh; also restore auto_refresh if we changed it ---
        try:
            if self.macropad:
                try:
                    # Force a refresh regardless of FPS throttling
                    self.macropad.display.refresh(minimum_frames_per_second=0)
                except Exception:
                    try:
                        self.macropad.display.refresh()
                    except Exception:
                        pass
                # If we had disabled auto_refresh in _begin_draw, turn it back on
                try:
                    if hasattr(self, "_saved_autorefresh") and (self._saved_autorefresh is not None):
                        self.macropad.display.auto_refresh = self._saved_autorefresh
                except Exception:
                    pass
        except Exception:
            pass