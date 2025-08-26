# adventure.py — Merlin Adventure
# Merlin Launcher Compatible, Low-Memory Roguelike with Scrolling Camera
# CircuitPython 9.x / Adafruit MacroPad RP2040 (128×64 mono OLED)
# Written by Iain Bennett — 2025
#
#
# Controls:
#   MENU:
#     ◀/▶ (K3/K5): Toggle Solo / Swap-2P
#     K11: Start
#     K9 : Back to Launcher Menu
#   PLAY:
#     K1/K3/K5/K7: Move (↑←→↓)
#     K8: Guard / Wait (chance to heal)
#     K11: Pause
#     K9 : Pause & return to Menu
#   PAUSE:
#     K11: Resume
#     K9 : Back to Menu
#   GAME OVER:
#     K11 or K9: Return to Menu
#
# Notes:
# - Player max HP: 9
# - Level generation: drunkard-walk backbone with random rooms/treasure/hearts/enemies
# - Enemies pursue nearest player (Manhattan distance), fallback to wandering
# - HUD shows scores, HP, level, and current turn (in 2P mode)
# - LEDs highlight active keys (directions, start/menu) with context-sensitive colors
#

import math, random, time
import displayio, terminalio
import bitmaptools
from micropython import const

try:
    from adafruit_display_text import label
    HAVE_LABEL = True
except Exception:
    HAVE_LABEL = False

# ---------- Screen / Tiles ----------
SCREEN_W, SCREEN_H = const(128), const(64)
BG, FG = const(0), const(1)
TS = const(4)  # 32x16 tiles visible

VIEW_W, VIEW_H = SCREEN_W // TS, SCREEN_H // TS  # 32 x 16

# World size (keep generous but smaller than earlier if still tight):
MAP_W, MAP_H = const(80), const(56)  # tuneable; 80*56=4480 tiles (fits well)

# Keys (launcher 0..11)
K_UP, K_LEFT, K_RIGHT, K_DOWN = 1, 3, 5, 7
K_FIRE, K_MENU, K_START       = 8, 9, 11

# LEDs
LED_PERIOD_S = 3.0
LED_DIM = 16
LED_BRIGHT = 64

# Gameplay
PLAYER_MAX_HP = 9

# Slightly trimmed counts for RAM + perf
MAX_ENEMIES = 22
MAX_TREASURE = 64
MAX_HEARTS = 16
ENEMY_BASE_HP = 2
ENEMY_HP_PER_LEVEL = 0   # or 1 every N levels
PLAY_Y0 = const(13)  # top pixel row where the map begins

# Tiles (byte values 0..5)
T_FLOOR, T_WALL, T_TREASURE, T_HEART, T_STAIRS = 0, 1, 2, 3, 4

# ---------- Defensive drawing ----------
def _clamp(v, lo, hi):
    if v < lo: return lo
    if v > hi: return hi
    return v

def _rect_fill(bmp, x, y, w, h, c=1):
    bw, bh = bmp.width, bmp.height
    if w <= 0 or h <= 0: return
    x0 = _clamp(x, 0, bw)
    y0 = _clamp(y, 0, bh)
    x1 = _clamp(x + w, 0, bw)
    y1 = _clamp(y + h, 0, bh)
    w2 = x1 - x0
    h2 = y1 - y0
    if w2 <= 0 or h2 <= 0: return
    try:
        bitmaptools.fill_region(bmp, x0, y0, w2, h2, c)
    except Exception:
        for yy in range(y0, y0 + h2):
            try:
                for xx in range(x0, x0 + w2):
                    bmp[xx, yy] = c
            except Exception:
                break

# ---------- Small helpers ----------
def _shuffle(seq):
    # In-place Fisher–Yates shuffle
    n = len(seq)
    for i in range(n - 1, 0, -1):
        j = random.randint(0, i)
        seq[i], seq[j] = seq[j], seq[i]
    return seq

def _hline(bmp, x0, x1, y, c=1):
    bw, bh = bmp.width, bmp.height
    if y < 0 or y >= bh: return
    if x0 > x1: x0, x1 = x1, x0
    x0 = _clamp(x0, 0, bw - 1)
    x1 = _clamp(x1, 0, bw - 1)
    _rect_fill(bmp, x0, y, (x1 - x0 + 1), 1, c)

def _vline(bmp, x, y0, y1, c=1):
    bw, bh = bmp.width, bmp.height
    if x < 0 or x >= bw: return
    if y0 > y1: y0, y1 = y1, y0
    y0 = _clamp(y0, 0, bh - 1)
    y1 = _clamp(y1, 0, bh - 1)
    _rect_fill(bmp, x, y0, 1, (y1 - y0 + 1), c)

# ---------- Utils ----------
def _cos01(t):  # cosine mapped to [0..1]
    return 0.5 + 0.5 * math.cos(t)

def _safe_tone(macropad, freq, dur):
    try:
        if macropad and hasattr(macropad, "play_tone"):
            macropad.play_tone(freq, dur)
    except Exception:
        pass

# ---------- Grid helpers (bytearray) ----------
def _idx(x, y): return y * MAP_W + x

# ---------- Main Class ----------
class adventure:
    def __init__(self, macropad=None, tones=None, **kwargs):
        self.macropad = macropad
        self.group = displayio.Group()

        self.palette = displayio.Palette(2)
        self.palette[0] = 0x000000
        self.palette[1] = 0xFFFFFF

        self.surface = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
        self.screen = displayio.TileGrid(self.surface, pixel_shader=self.palette)
        self.group.append(self.screen)

        # --- Merlin chrome background (OnDiskBitmap) ---
        self._chrome_bg = None      # displayio.TileGrid or None
        self._chrome_bmp = None     # displayio.OnDiskBitmap or None
        
        # Labels
        self._lbl1 = None
        self._lbl2 = None
        self._hud = None

        # Game state
        self.state = "menu"     # menu, play, paused, over
        self.two_player = False
        self.cur_player = 0
        self.level = 1
        self.led_t = 0.0
        self._dirty = True

        # Internal dt
        self._last_t = time.monotonic()

        # Camera (pixels)
        self.cam_px_x = 0.0
        self.cam_px_y = 0.0
        self.cam_target_x = 0.0
        self.cam_target_y = 0.0
        self.cam_speed = 220.0  # px/s

        # World
        self.grid = bytearray(MAP_W * MAP_H)  # all zeros initially (floors/walls set later)
        self.enemies = []  # list of [x, y]
        self.players = [
            {"x": 1, "y": 1, "hp": PLAYER_MAX_HP, "score": 0, "alive": True},
            {"x": 1, "y": 1, "hp": PLAYER_MAX_HP, "score": 0, "alive": True},
        ]

        self._draw_menu()
        self._update_leds()

    # ---------- Merlin chrome helpers ----------
    def _ensure_chrome_bg(self):
        if self._chrome_bg is not None:
            return
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile = displayio.TileGrid(
                bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            # Insert as the very back layer
            self.group.insert(0, tile)
            self._chrome_bmp = bmp
            self._chrome_bg = tile
        except Exception:
            # If anything fails, leave _chrome_bg as None
            self._chrome_bg = None
            self._chrome_bmp = None

    def _show_chrome(self, show=True):
        # Toggle the game surface visibility so chrome isn't occluded
        try:
            if hasattr(self, "screen") and self.screen is not None:
                self.screen.hidden = bool(show)   # hide game bitmap while chrome shows
        except Exception:
            pass

        if show:
            if self._chrome_bg is None:
                self._ensure_chrome_bg()
            else:
                # Re-add at back if it was removed
                try:
                    if self._chrome_bg not in self.group:
                        self.group.insert(0, self._chrome_bg)
                except Exception:
                    pass
        else:
            # Remove chrome (keep objects alive for quick return)
            try:
                if self._chrome_bg is not None and self._chrome_bg in self.group:
                    self.group.remove(self._chrome_bg)
            except Exception:
                pass
    # ---------- Public API ----------
    def _begin_play(self):
        self.state = "play"
        self.level = 1
        self.cur_player = 0
        for i in (0, 1):
            self.players[i]["hp"] = PLAYER_MAX_HP
            self.players[i]["score"] = 0
            self.players[i]["alive"] = True

        self._gen_level()
        self._center_camera_on_current()
        self._show_chrome(False)      # hide chrome during gameplay
        self._dirty = True

        # Start jingle
        _safe_tone(self.macropad, 880, 0.05)
        _safe_tone(self.macropad, 1175, 0.06)
        _safe_tone(self.macropad, 1567, 0.07)
    
    def new_game(self):
        random.seed(int(time.monotonic() * 1000) & 0xFFFFFFFF)
        self.state = "menu"
        self.level = 1
        self.cur_player = 0
        for i in (0, 1):
            self.players[i]["hp"] = PLAYER_MAX_HP
            self.players[i]["score"] = 0
            self.players[i]["alive"] = True

        # Make sure the chrome/logo is visible on the menu
        self._show_chrome(True)

        # Draw the menu screen
        self._dirty = True
        # (Optional) soft “ready” chirp
        _safe_tone(self.macropad, 660, 0.03)

    def tick(self):
        now = time.monotonic()
        dt = now - self._last_t
        if dt < 0 or dt > 0.5:
            dt = 1/30
        self._last_t = now

        self.led_t += dt
        self._update_camera(dt)

        if self._dirty:
            if self.state == "menu":
                self._draw_menu()
            elif self.state == "play":
                self._draw_play()
            elif self.state == "paused":
                self._draw_pause()
            elif self.state == "over":
                self._draw_game_over()
            self._dirty = False

        self._update_leds()

    def button(self, key, pressed=True):
        if not pressed:
            return

        # -------- MENU --------
        if self.state == "menu":
            if key in (K_LEFT, K_RIGHT):
                self.two_player = not self.two_player
                self._dirty = True
            elif key == K_START:
                # Start game: gameplay hides chrome
                self._begin_play()              # new_game() calls _show_chrome(False)
            return

        # -------- PLAY --------
        if self.state == "play":
            if key in (K_UP, K_DOWN, K_LEFT, K_RIGHT):
                self._attempt_move(key)      # handles camera target + end-turn
            elif key == K_FIRE:
                # Guard/Wait (small heal chance) then end turn
                p = self.players[self.cur_player]
                if (p["hp"] < PLAYER_MAX_HP) and (random.random() < 0.05):
                    p["hp"] += 1
                    _safe_tone(self.macropad, 660, 0.04)
                    self._dirty = True
                self._end_turn()
            elif key in (K_START, K_MENU):
                # Enter paused menu; show Merlin chrome
                self.state = "paused"
                self._show_chrome(True)
                self._dirty = True
            return

        # -------- PAUSED --------
        if self.state == "paused":
            if key == K_START:
                # Resume gameplay; hide chrome
                self.state = "play"
                self._show_chrome(False)
                self._dirty = True
            elif key == K_MENU:
                # Back to main menu; keep chrome visible
                self.state = "menu"
                self._show_chrome(True)
                self._dirty = True
            return

        # -------- GAME OVER --------
        if self.state == "over":
            if key in (K_START, K_MENU):
                # Return to menu; keep chrome visible
                self.state = "menu"
                self._show_chrome(True)
                self._dirty = True
            return

    def button_up(self, key):
        pass

    def cleanup(self):
        try:
            if self.macropad and hasattr(self.macropad, "pixels"):
                for i in range(12):
                    self.macropad.pixels[i] = (0, 0, 0)
        except Exception:
            pass
        try:
            _rect_fill(self.surface, 0, 0, SCREEN_W, SCREEN_H, BG)
        except Exception:
            pass

    # ---------- Camera ----------
    def _center_camera_on_current(self):
        p = self.players[self.cur_player]
        tx = p["x"] * TS + TS//2 - SCREEN_W//2
        ty = p["y"] * TS + TS//2 - SCREEN_H//2
        self.cam_px_x = self.cam_target_x = self._clamp_cam_x(tx)
        self.cam_px_y = self.cam_target_y = self._clamp_cam_y(ty)

    def _set_camera_target_to_player(self):
        p = self.players[self.cur_player]
        tx = p["x"] * TS + TS//2 - SCREEN_W//2
        ty = p["y"] * TS + TS//2 - SCREEN_H//2
        self.cam_target_x = self._clamp_cam_x(tx)
        self.cam_target_y = self._clamp_cam_y(ty)

    def _clamp_cam_x(self, cx):
        max_px_x = MAP_W * TS - SCREEN_W
        return _clamp(cx, 0, max(0, max_px_x))

    def _clamp_cam_y(self, cy):
        max_px_y = MAP_H * TS - SCREEN_H
        return _clamp(cy, 0, max(0, max_px_y))

    def _update_camera(self, dt):
        dx = self.cam_target_x - self.cam_px_x
        dy = self.cam_target_y - self.cam_px_y
        dist = (dx*dx + dy*dy) ** 0.5
        if dist > 0.5:
            step = self.cam_speed * dt
            if step >= dist:
                self.cam_px_x = self.cam_target_x
                self.cam_px_y = self.cam_target_y
            else:
                self.cam_px_x += dx * (step / dist)
                self.cam_px_y += dy * (step / dist)

    # ---------- Level Generation (low alloc) ----------
    def _set(self, x, y, t): self.grid[_idx(x,y)] = t
    def _get(self, x, y):     return self.grid[_idx(x,y)]

    def _gen_level(self):
        # Fill with walls
        self.grid[:] = bytes([T_WALL]) * (MAP_W * MAP_H)
        self.enemies = []

        # Drunkard-walk backbone
        cx, cy = MAP_W // 2, MAP_H // 2
        x, y = cx, cy
        self._set(x, y, T_FLOOR)
        steps = MAP_W * MAP_H * 2  # modest; more rooms carve further
        for _ in range(steps):
            if random.random() < 0.5: x += random.choice((-1, 1))
            else:                      y += random.choice((-1, 1))
            x = _clamp(x, 1, MAP_W-2)
            y = _clamp(y, 1, MAP_H-2)
            self._set(x, y, T_FLOOR)

        # Rooms (no temp arrays)
        for _ in range(18):
            rw = random.randint(5, 11)
            rh = random.randint(4, 7)
            rx = random.randint(1, MAP_W - rw - 2)
            ry = random.randint(1, MAP_H - rh - 2)
            for yy in range(ry, ry + rh):
                base = yy * MAP_W + rx
                # slice write (fast) to floors
                self.grid[base:base+rw] = bytes([T_FLOOR]) * rw

        # Place players near center
        self.players[0]["x"], self.players[0]["y"] = self._find_floor_near(cx, cy)
        if self.two_player:
            self.players[1]["x"], self.players[1]["y"] = self._find_floor_near(cx+6, cy+4)
        else:
            self.players[1]["x"], self.players[1]["y"] = self.players[0]["x"], self.players[0]["y"]

        # Streaming placement without building "empties":
        # helper that tries N random floor cells not under players nor over specials
        def place_many(tile, count, max_tries_per_item=200):
            placed = 0
            tries = 0
            p0 = (self.players[0]["x"], self.players[0]["y"])
            p1 = (self.players[1]["x"], self.players[1]["y"])
            while placed < count and tries < count * max_tries_per_item:
                tries += 1
                rx = random.randint(1, MAP_W-2)
                ry = random.randint(1, MAP_H-2)
                if (rx, ry) == p0 or (rx, ry) == p1:
                    continue
                t = self._get(rx, ry)
                if t != T_FLOOR:
                    continue
                self._set(rx, ry, tile)
                placed += 1

        place_many(T_TREASURE, MAX_TREASURE)
        place_many(T_HEART,    MAX_HEARTS)

        # Enemies: also streaming; store as tiny [x,y]
        def place_enemies(count):
            placed = 0
            tries = 0
            p0 = (self.players[0]["x"], self.players[0]["y"])
            p1 = (self.players[1]["x"], self.players[1]["y"])
            while placed < count and tries < count * 200:
                tries += 1
                rx = random.randint(1, MAP_W-2)
                ry = random.randint(1, MAP_H-2)
                if (rx, ry) == p0 or (rx, ry) == p1:
                    continue
                if self._get(rx, ry) != T_FLOOR:
                    continue
                hp = ENEMY_BASE_HP + (self.level - 1) * ENEMY_HP_PER_LEVEL
                self.enemies.append([rx, ry, hp])
                placed += 1
        place_enemies(MAX_ENEMIES)

        # Stairs: try a few random floors
        for _ in range(400):
            rx = random.randint(1, MAP_W-2)
            ry = random.randint(1, MAP_H-2)
            if self._get(rx, ry) == T_FLOOR:
                self._set(rx, ry, T_STAIRS)
                break

        self._set_camera_target_to_player()

    def _find_floor_near(self, x, y):
        best = (x, y)
        bestd = 1_000_000
        # scan with stride to save time, then refine small window
        for yy in range(1, MAP_H-1, 1):
            base = yy * MAP_W
            for xx in range(1, MAP_W-1, 1):
                if self.grid[base + xx] == T_FLOOR:
                    d = (xx-x)*(xx-x) + (yy-y)*(yy-y)
                    if d < bestd:
                        bestd, best = d, (xx, yy)
        return best

    # ---------- Gameplay ----------
    def _attempt_move(self, key):
        p = self.players[self.cur_player]
        dx, dy = 0, 0
        if key == K_UP: dy = -1
        elif key == K_DOWN: dy = 1
        elif key == K_LEFT: dx = -1
        elif key == K_RIGHT: dx = 1
        nx, ny = p["x"] + dx, p["y"] + dy
        if nx < 0 or ny < 0 or nx >= MAP_W or ny >= MAP_H:
            return

        tile = self._get(nx, ny)
        if tile == T_WALL:
            _safe_tone(self.macropad, 220, 0.04)
            return

        # Enemy there?
        eidx = self._enemy_at(nx, ny)
        if eidx is not None:
            e = self.enemies[eidx]
            # Option A: deterministic damage each hit
            e[2] -= 1
            if e[2] <= 0:
                self.enemies.pop(eidx)
                p["score"] += 5
                _safe_tone(self.macropad, 880, 0.05)
            else:
                # hurt tone on nonlethal hit
                _safe_tone(self.macropad, 520, 0.05)
            self._dirty = True
            self._end_turn()
            return

        # Step
        p["x"], p["y"] = nx, ny
        _safe_tone(self.macropad, 660, 0.02)

        if tile == T_TREASURE:
            p["score"] += 10
            self._set(nx, ny, T_FLOOR)
            _safe_tone(self.macropad, 1200, 0.07)
        elif tile == T_HEART:
            if p["hp"] < PLAYER_MAX_HP:
                p["hp"] += 1
            self._set(nx, ny, T_FLOOR)
            _safe_tone(self.macropad, 990, 0.05)
        elif tile == T_STAIRS:
            self.level += 1
            p["hp"] = min(PLAYER_MAX_HP, p["hp"] + 1)
            self._gen_level()
            _safe_tone(self.macropad, 1567, 0.06)

        self._set_camera_target_to_player()
        self._dirty = True
        self._end_turn()

    def _end_turn(self):
        if self.two_player and self.players[1]["alive"]:
            self.cur_player ^= 1
        # Enemies act once after the player’s turn
        if self.state == "play":
            self._enemies_step()
            self._dirty = True
        self._set_camera_target_to_player()

    def _enemy_at(self, x, y):
        for i, e in enumerate(self.enemies):
            if e[0] == x and e[1] == y:
                return i
        return None

    def _enemies_step(self):
        living = [i for i in (0,1) if self.players[i]["alive"]]
        if not living:
            return
        for e in self.enemies:
            # Chase nearest living player (Manhattan)
            nearest = None; nd = 1_000_000
            for i in living:
                p = self.players[i]
                d = abs(p["x"] - e[0]) + abs(p["y"] - e[1])
                if d < nd:
                    nd, nearest = d, i
            px, py = self.players[nearest]["x"], self.players[nearest]["y"]
            choices = []
            if e[0] < px: choices.append((1,0))
            if e[0] > px: choices.append((-1,0))
            if e[1] < py: choices.append((0,1))
            if e[1] > py: choices.append((0,-1))
            _shuffle(choices)
            moved = False
            for dx, dy in choices or [(0,0)]:
                nx, ny = e[0] + dx, e[1] + dy
                if 0 <= nx < MAP_W and 0 <= ny < MAP_H and self._get(nx, ny) != T_WALL:
                    # If stepping INTO player: deal damage, but DON'T move into the player's tile
                    hit_player = False
                    for i in living:
                        p = self.players[i]
                        if p["alive"] and p["x"] == nx and p["y"] == ny:
                            p["hp"] -= 1
                            _safe_tone(self.macropad, 180, 0.06)
                            if p["hp"] <= 0:
                                p["alive"] = False
                                _safe_tone(self.macropad, 120, 0.25)
                                self._check_game_over()
                            hit_player = True
                            break

                    if not hit_player:
                        # normal move
                        e[0], e[1] = nx, ny

                    moved = True
                    break
            if not moved:
                # Random wander fallback (don't enter player's tile)
                for _ in range(2):
                    dx, dy = random.choice(((1,0),(-1,0),(0,1),(0,-1)))
                    nx, ny = e[0] + dx, e[1] + dy
                    if 0 <= nx < MAP_W and 0 <= ny < MAP_H and self._get(nx, ny) != T_WALL:
                        hit_player = False
                        for i in living:
                            p = self.players[i]
                            if p["alive"] and p["x"] == nx and p["y"] == ny:
                                p["hp"] -= 1
                                _safe_tone(self.macropad, 180, 0.06)
                                if p["hp"] <= 0:
                                    p["alive"] = False
                                    _safe_tone(self.macropad, 120, 0.25)
                                    self._check_game_over()
                                hit_player = True
                                break
                        if not hit_player:
                            e[0], e[1] = nx, ny
                        break
                    
    def _check_game_over(self):
        if not self.two_player:
            if not self.players[0]["alive"]:
                self.state = "over"; self._dirty = True
        else:
            if not self.players[0]["alive"] and not self.players[1]["alive"]:
                self.state = "over"; self._dirty = True

    def _draw_play(self):
        self._show_chrome(False)
        _rect_fill(self.surface, 0, 0, SCREEN_W, SCREEN_H, BG)

        camx = int(self.cam_px_x)
        camy = int(self.cam_px_y)

        first_tx = camx // TS
        first_ty = camy // TS
        off_x = -(camx % TS)
        off_y = -(camy % TS)

        tiles_x = VIEW_W + 1
        tiles_y = VIEW_H + 1

        # Tiles
        for ty in range(tiles_y):
            my = first_ty + ty
            if my < 0 or my >= MAP_H:
                continue
            sy = PLAY_Y0 + off_y + ty * TS
            row_base = my * MAP_W
            for tx in range(tiles_x):
                mx = first_tx + tx
                if mx < 0 or mx >= MAP_W:
                    continue
                sx = off_x + tx * TS
                t = self.grid[row_base + mx]
                if t == T_WALL:
                    _rect_fill(self.surface, sx, sy, TS, TS, FG)
                elif t == T_TREASURE:
                    _rect_fill(self.surface, sx+1, sy+1, TS-2, TS-2, FG)
                    _rect_fill(self.surface, sx+2, sy+2, TS-4, TS-4, BG)
                elif t == T_HEART:
                    if 0 <= sx+1 < SCREEN_W and 0 <= sy+1 < SCREEN_H: self.surface[sx+1, sy+1] = FG
                    if 0 <= sx+2 < SCREEN_W and 0 <= sy+1 < SCREEN_H: self.surface[sx+2, sy+1] = FG
                    if 0 <= sx+1 < SCREEN_W and 0 <= sy+2 < SCREEN_H: self.surface[sx+1, sy+2] = FG
                    if 0 <= sx+2 < SCREEN_W and 0 <= sy+2 < SCREEN_H: self.surface[sx+2, sy+2] = FG
                elif t == T_STAIRS:
                    _hline(self.surface, sx+1, sx+TS-2, sy+1, FG)
                    _hline(self.surface, sx+1, sx+TS-2, sy+TS-2, FG)
                    _vline(self.surface, sx+2, sy+1, sy+TS-2, FG)
                    _vline(self.surface, sx+TS-3, sy+1, sy+TS-2, FG)

        # Enemies
        for e in self.enemies:
            sx = e[0] * TS - camx
            sy = e[1] * TS - camy + PLAY_Y0
            if -TS <= sx < SCREEN_W and -TS <= sy < SCREEN_H:
                _rect_fill(self.surface, sx+1, sy+1, TS-2, TS-2, FG)

        # Players
        for i in (0, 1):
            p = self.players[i]
            if not p["alive"]:
                continue
            sx = p["x"] * TS - camx
            sy = p["y"] * TS - camy + PLAY_Y0
            if -TS <= sx < SCREEN_W and -TS <= sy < SCREEN_H:
                if i == 0:
                    _rect_fill(self.surface, sx, sy, TS, TS, FG)
                    _rect_fill(self.surface, sx+1, sy+1, TS-2, TS-2, BG)
                    _hline(self.surface, sx+1, sx+TS-2, sy+1, FG)
                else:
                    _rect_fill(self.surface, sx, sy, TS, TS, FG)

        # Text HUD at the very top (y ~ 1), then the separator line at y = 8
        if HAVE_LABEL:
            self._ensure_labels()
            if self.two_player:
                p1 = self.players[0]
                p2 = self.players[1]
                turn = 1 if self.cur_player == 0 else 2
                self._set_label(
                    self._hud,
                    "L{}  P1 S:{} HP:{}/{}  P2 S:{} HP:{}/{}  [{}]".format(
                        self.level,
                        p1["score"], p1["hp"], PLAYER_MAX_HP,
                        p2["score"], p2["hp"], PLAYER_MAX_HP,
                        turn
                    ),
                    64, 0, scale=1, anchor=(0.5, 0)
                )
            else:
                p0 = self.players[0]
                self._set_label(
                    self._hud,
                    "L{}  S:{} HP:{}/{}".format(
                        self.level, p0["score"], p0["hp"], PLAYER_MAX_HP
                    ),
                    64, 0, scale=1, anchor=(0.5, 0)
                )
            # Clear lower prompts during play
            self._set_label(self._lbl1, "", 64, 39, scale=1, anchor=(0.5, 0))
            self._set_label(self._lbl2, "", 64, 53, scale=1, anchor=(0.5, 0))

        # Separator line
        _hline(self.surface, 0, SCREEN_W - 1, PLAY_Y0-2, FG)
        
    def _draw_menu(self):
        # Clear screen under overlays; chrome sits behind as bg
        _rect_fill(self.surface, 0, 0, SCREEN_W, SCREEN_H, BG)
        self._show_chrome(True)

        if HAVE_LABEL:
            self._ensure_labels()
            # Keep prompts below logo: Y=21 and Y=35
            self._set_label(self._hud,  " ", 64, 8,  scale=2, anchor=(0.5,0.5))  # no text; chrome shows logo
            self._set_label(self._lbl1, "Merlin Adventure", 64, 38, scale=1, anchor=(0.5,0))
            mode_txt = "Solo" if not self.two_player else "Swap"
            self._set_label(self._lbl2, mode_txt + "   Start", 64, 53, scale=1, anchor=(0.5,0))
        else:
            # Fallback: minimal separators if labels are unavailable
            _hline(self.surface, 0, SCREEN_W-1, 21, FG)
            _hline(self.surface, 0, SCREEN_W-1, 35, FG)

    def _draw_pause(self):
        self._show_chrome(True)
        _rect_fill(self.surface, 0, 0, SCREEN_W, SCREEN_H, BG)
        if HAVE_LABEL:
            self._ensure_labels()
            self._set_label(self._hud,  " ", 64, 8,  scale=2, anchor=(0.5,0.5))
            self._set_label(self._lbl1, "Paused", 64, 31, scale=1, anchor=(0.5,0))
            self._set_label(self._lbl2, "Menu   Resume", 64, 45, scale=1, anchor=(0.5,0))
        else:
            _hline(self.surface, 0, SCREEN_W-1, 21, FG)
            _hline(self.surface, 0, SCREEN_W-1, 35, FG)

    def _draw_game_over(self):
        self._show_chrome(True)
        _rect_fill(self.surface, 0, 0, SCREEN_W, SCREEN_H, BG)
        if HAVE_LABEL:
            self._ensure_labels()
            self._set_label(self._hud,  " ", 64, 8,  scale=2, anchor=(0.5,0.5))
            if not self.two_player:
                p = self.players[0]
                self._set_label(self._lbl1, f"Score: {p['score']}   L{self.level}", 64, 31, scale=1, anchor=(0.5,0))
            else:
                p1, p2 = self.players[0], self.players[1]
                self._set_label(self._lbl1, f"P1:{p1['score']}  P2:{p2['score']}  L{self.level}", 64, 31, scale=1, anchor=(0.5,0))
            self._set_label(self._lbl2, "Death by Monster", 64, 45, scale=1, anchor=(0.5,0))
        else:
            _hline(self.surface, 0, SCREEN_W-1, 31, FG)
            _hline(self.surface, 0, SCREEN_W-1, 45, FG)

    # ---------- Labels ----------
    def _ensure_labels(self):
        if self._lbl1 is None and HAVE_LABEL:
            self._lbl1 = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
            self.group.append(self._lbl1)
        if self._lbl2 is None and HAVE_LABEL:
            self._lbl2 = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
            self.group.append(self._lbl2)
        if self._hud is None and HAVE_LABEL:
            self._hud = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
            self.group.append(self._hud)

    def _set_label(self, lbl, txt, x, y, scale=1, anchor=(0.5,0)):
        if not HAVE_LABEL or lbl is None: return
        lbl.text = txt
        lbl.scale = scale
        lbl.anchor_point = anchor
        lbl.anchored_position = (x, y)

    # ---------- LEDs ----------
    def _update_leds(self):
        mp = self.macropad
        if not mp or not hasattr(mp, "pixels"):
            return
        t = self.led_t / LED_PERIOD_S * 2.0 * math.pi
        try:
            for i in range(12):
                base = LED_DIM
                # keep the same breathing brightness animation on the “important” keys
                if i in (K_UP, K_DOWN, K_LEFT, K_RIGHT, K_START, K_MENU, K_FIRE):
                    phase = (i * 0.7) % (2*math.pi)
                    b = base + int(LED_BRIGHT * _cos01(t + phase))
                else:
                    b = base
                if b < 0: b = 0
                if b > 255: b = 255

                # Default colors
                if i in (K_UP, K_DOWN, K_LEFT, K_RIGHT):
                    # Light cyan for the directional keys (animated by b)
                    color = (0, b, b)
                else:
                    # White fade for everything else, unless state overrides below
                    color = (b, b, b)

                # --- State-specific overrides ---
                if self.state == "menu":
                    # Start button highlighted (light green)
                    if i == K_START:
                        color = (0, b, 0)
                        
                elif self.state == "play":
                    # K9 and K11 = light green
                    if i in (K_MENU, K_START):
                        color = (0, b, 0)

                elif self.state == "paused":
                    # K9 = light red; K11 = light green
                    if i == K_MENU:
                        color = (b, 0, 0)
                    if i == K_START:
                        color = (0, b, 0)

                elif self.state == "over":
                    # K9 and K11 = light green
                    if i in (K_MENU, K_START):
                        color = (0, b, 0)

                mp.pixels[i] = color
        except Exception:
            pass