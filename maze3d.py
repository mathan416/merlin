# maze3d.py — Macro Maze (launcher-compatible)
# Works with Merlin Launcher (CircuitPython 9.x)
# Exposes class `maze3d` with .group, .new_game(), .tick(), .button(), .cleanup()
# Encoder: single press exits (handled by launcher)

import math, random, time, json
import displayio, bitmaptools, terminalio
from micropython import const
try:
    from adafruit_display_text import label
    HAVE_LABEL = True
except Exception:
    HAVE_LABEL = False

# ---------- Tunables ----------
SCREEN_W, SCREEN_H = const(128), const(64)
RAYS = const(64)                              # 2 px columns across 128 px
FOV = math.radians(60)
MOVE_SPEED = 0.12
TURN_SPEED = math.radians(10)
WALL_COLOR = const(1)
BG_COLOR = const(0)
SETTINGS_PATH = "/maze3d_settings.json"

# Key mapping (launcher forwards 0..11)
K_UP, K_LEFT, K_RIGHT, K_DOWN = 1, 3, 5, 7
K_SETTINGS, K_START = 10, 11
K_MINIMAP = 9
FAST_MULT = 0.25   # move ~2x faster when all four D-pad keys are held

# ---------- Tiny 5x5 block font (only letters we need) ----------
_FONT5 = {
    "A":["01110","10001","11111","10001","10001"],
    "C":["01110","10000","10000","10000","01110"],
    "D":["11110","10001","10001","10001","11110"],
    "E":["11111","10000","11110","10000","11111"],
    "H":["10001","10001","11111","10001","10001"],
    "M":["10001","11011","10101","10001","10001"],
    "O":["01110","10001","10001","10001","01110"],
    "R":["11110","10001","11110","10100","10010"],
    "S":["01111","10000","01110","00001","11110"],
    "Y":["10001","01010","00100","00100","00100"],
    "Z":["11111","00010","00100","01000","11111"],
    " ":[ "00000","00000","00000","00000","00000" ],
}

def _mk_framebuffer():
    bitmap = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
    palette = displayio.Palette(2)
    palette[0] = 0x000000
    palette[1] = 0xFFFFFF
    tg = displayio.TileGrid(bitmap, pixel_shader=palette)
    grp = displayio.Group()
    grp.append(tg)
    return bitmap, palette, tg, grp

def _clear(bitmap):
    _safe_fill(bitmap, 0, 0, SCREEN_W, SCREEN_H, BG_COLOR)

    
def _draw_vert_slice(bitmap, x, h):
    h = 1 if h < 1 else (SCREEN_H if h > SCREEN_H else h)
    top = (SCREEN_H - h) // 2
    _safe_fill(bitmap, x, top, 2, h, WALL_COLOR)

def _safe_load_json(path, default):
    try:
        with open(path, "r") as f: return json.load(f)
    except Exception:
        return default

def _safe_save_json(path, data):
    try:
        with open(path, "w") as f: json.dump(data, f)
    except Exception:
        pass
    
def _safe_fill(bitmap, x, y, w, h, color):
    # Accept x,y,width,height — convert to x2,y2 (exclusive) + clip
    x = int(x); y = int(y); w = int(w); h = int(h)
    if w <= 0 or h <= 0:
        return
    x2 = x + w
    y2 = y + h
    # Clip to bitmap bounds
    if x < 0: x = 0
    if y < 0: y = 0
    if x2 > SCREEN_W: x2 = SCREEN_W
    if y2 > SCREEN_H: y2 = SCREEN_H
    # Still valid?
    if x >= x2 or y >= y2:
        return
    # IMPORTANT: this CP build expects (x1, y1, x2, y2, value)
    bitmaptools.fill_region(bitmap, x, y, x2, y2, color)
    
        
# ---------- Maze generation ----------
def _gen_maze(cells):
    w = h = cells  # odd sizes: 9,13,17...
    grid = [[1]*w for _ in range(h)]
    def nbrs(cx, cy):
        for dx, dy in ((2,0),(-2,0),(0,2),(0,-2)):
            nx, ny = cx+dx, cy+dy
            if 1 <= nx < w-1 and 1 <= ny < h-1 and grid[ny][nx] == 1:
                yield nx, ny, (dx//2, dy//2)
    stack = [(1,1)]
    grid[1][1] = 0
    while stack:
        x, y = stack[-1]
        opts = list(nbrs(x,y))
        if not opts:
            stack.pop(); continue
        nx, ny, mid = random.choice(opts)
        grid[y+mid[1]][x+mid[0]] = 0
        grid[ny][nx] = 0
        stack.append((nx, ny))
    grid[1][0] = 0               # entrance
    grid[h-2][w-1] = 0           # exit
    return grid, (1.5, 1.5), (w-1.5, h-2.5)

# ---------- Raycaster ----------
class _Raycaster:
    def __init__(self, bitmap, maze, fov=FOV, rays=RAYS):
        self.bitmap = bitmap
        self.set_maze(maze)
        self.rays = rays
        self.fov = fov
        self.offs = [((i + 0.5)/rays - 0.5) * fov for i in range(rays)]

    def set_maze(self, maze):
        self.maze = maze
        self.h = len(maze)
        self.w = len(maze[0])

    def draw(self, px, py, ang):
        _clear(self.bitmap)
        for i, aoff in enumerate(self.offs):
            ra = ang + aoff
            rx, ry = math.cos(ra), math.sin(ra)
            mapX, mapY = int(px), int(py)
            dX = 1e9 if rx == 0 else abs(1.0 / rx)
            dY = 1e9 if ry == 0 else abs(1.0 / ry)
            if rx < 0: stepX = -1; sideX = (px - mapX) * dX
            else:      stepX =  1; sideX = (mapX + 1.0 - px) * dX
            if ry < 0: stepY = -1; sideY = (py - mapY) * dY
            else:      stepY =  1; sideY = (mapY + 1.0 - py) * dY
            hit, side = False, 0
            for _ in range(128):
                if sideX < sideY:
                    sideX += dX; mapX += stepX; side = 0
                else:
                    sideY += dY; mapY += stepY; side = 1
                if mapX < 0 or mapX >= self.w or mapY < 0 or mapY >= self.h: hit=True; break
                if self.maze[mapY][mapX] == 1: hit=True; break
            if not hit:
                dist = 999.0
            else:
                if side == 0:
                    dist = (mapX - px + (1 - stepX)*0.5) / (rx if rx else 1e-6)
                else:
                    dist = (mapY - py + (1 - stepY)*0.5) / (ry if ry else 1e-6)
                if dist == 0: dist = 1e-3
                dist = abs(dist)
            slice_h = int(SCREEN_H / dist)
            _draw_vert_slice(self.bitmap, i*2, slice_h)

# ---------- Core (event-driven, no blocking loop) ----------
class _MacroMazeCore:
    DIFFS = [("EASY", 9), ("MED", 13), ("HARD", 17)]
    COLORS = [
        (0x20,0x20,0xFF), (0x00,0xFF,0x40), (0xFF,0x90,0x10),
        (0xFF,0x10,0x10), (0xE0,0xE0,0xE0), (0x90,0x30,0xE0),
    ]

    def __init__(self, macropad):
        self.macropad = macropad
        
        self._orig_auto_refresh = getattr(self.macropad.display, "auto_refresh", True)
        self.macropad.display.auto_refresh = False

        self.bitmap, self.palette, self._tg, self.group = _mk_framebuffer()
        self.pressed = set()
        

        self.title = None
        if HAVE_LABEL:
            self.title = label.Label(terminalio.FONT, text="", color=0xFFFFFF,
                                     scale=1, anchored_position=(1,1), anchor_point=(0,0))
            self.group.append(self.title)

        self.macropad.display.root_group = self.group
        self.macropad.display.auto_refresh = False

        # Persisted settings
        s = _safe_load_json(SETTINGS_PATH, {"sfx": True, "dir_color_idx": 0, "diff_idx": 0})
        self.sfx = bool(s.get("sfx", True))
        self.dir_color_idx = int(s.get("dir_color_idx", 0)) % len(self.COLORS)
        self.diff_idx = int(s.get("diff_idx", 0)) % len(self.DIFFS)

        self.dir_color = self.COLORS[self.dir_color_idx]
        self._light_dpad()
        
        # Map Settings
        self.show_minimap = False
        self._visited = set()

        # Game state
        self._set_mode("MENU")               # MENU | SETTINGS | GAME
        self.maze = [[1,1],[1,1]]
        self.cam_x = 1.5; self.cam_y = 1.5; self.cam_a = 0.0
        self.exit_pos = (1.5, 1.5)
        self.ray = _Raycaster(self.bitmap, self.maze)
        self.last_pose = None
        self.needs_redraw = True
        self.did_splash = False

    def cleanup(self):
        """Release resources cleanly when unloading the game."""
        # 1) Persist settings
        try:
            self._save_settings()
        except Exception:
            pass

        # 2) Stop any held motion
        try:
            self.pressed.clear()
        except Exception:
            pass

        # 3) Restore display state and detach our group
        try:
            if getattr(self.macropad, "display", None):
                # Detach our group (even if not currently set, just be safe)
                try:
                    if self.macropad.display.root_group is self.group:
                        self.macropad.display.root_group = None
                except Exception:
                    # Fallback: just clear it
                    self.macropad.display.root_group = None
                # Restore auto_refresh to what code.py expects
                try:
                    self.macropad.display.auto_refresh = getattr(self, "_orig_auto_refresh", True)
                except Exception:
                    pass
                # One manual refresh to push the detach if still in manual mode
                try:
                    self.macropad.display.refresh()
                except Exception:
                    pass
        except Exception:
            pass

        # 4) Turn off LEDs
        try:
            self.macropad.pixels.fill((0, 0, 0))
            self.macropad.pixels.show()
        except Exception:
            pass

        # 5) Drop big references so GC can reclaim memory
        self.title = None
        self.group = None
        self.bitmap = None
        self.palette = None
        self._tg = None
        self.ray = None
        self.maze = None
        try:
            if self._visited is not None:
                self._visited.clear()
        except Exception:
            pass
        self._visited = None

        # 6) GC sweep
        try:
            import gc
            gc.collect()
        except Exception:
            pass

    # ---------- tiny beeper ----------
    def _tone(self, f=660, d=0.04):
        if not self.sfx: return
        try: self.macropad.play_tone(f, d)
        except Exception: pass

    # ---------- LEDs ----------
    def _light_dpad(self):
        p = self.macropad.pixels
        c = self.dir_color
        for i in range(12): p[i]=(0,0,0)
        for k in (K_UP, K_LEFT, K_RIGHT, K_DOWN): p[k]=c
        try: p.show()
        except Exception: pass

    def _led_theme_start(self):
        p = self.macropad.pixels
        base = self.dir_color
        rings = [[4,5,6,7], [1,3,8,10], [0,2,9,11]]
        for step in range(3):
            for i in range(12): p[i]=(0,0,0)
            for idx in rings[step]: p[idx]=base
            try: p.show()
            except Exception: pass
            self._tone(520+step*140, 0.05)
            time.sleep(0.08)
        self._light_dpad()

    # ---------- Splash ----------
    def _draw_minimap(self):
        # Top-left HUD ~30x30 px. Scales to fit any odd maze up to 17x17.
        mw, mh = len(self.maze[0]), len(self.maze)
        pad = 1
        max_size = 30
        sx = max(1, (max_size - 2*pad) // mw)
        sy = max(1, (max_size - 2*pad) // mh)
        s = sx if sx < sy else sy  # cell pixel size
        w = mw * s
        h = mh * s
        x0 = pad
        y0 = pad

        # Clear window + draw a simple 1px frame (all safely clipped)
        _safe_fill(self.bitmap, x0-1, y0-1, w+2, h+2, BG_COLOR)
        _safe_fill(self.bitmap, x0-1, y0-1, w+2, 1, WALL_COLOR)         # top
        _safe_fill(self.bitmap, x0-1, y0+h, w+2, 1, WALL_COLOR)          # bottom
        _safe_fill(self.bitmap, x0-1, y0-1, 1, h+2, WALL_COLOR)          # left
        _safe_fill(self.bitmap, x0+w, y0-1, 1, h+2, WALL_COLOR)          # right

        # Breadcrumbs (visited cells)
        for (ix, iy) in self._visited:
            _safe_fill(self.bitmap, x0 + ix*s, y0 + iy*s, 1, 1, WALL_COLOR)

        # Exit marker (slightly larger)
        ex, ey = int(self.exit_pos[0]), int(self.exit_pos[1])
        _safe_fill(self.bitmap, x0 + ex*s, y0 + ey*s, max(1, s//2 + 1), max(1, s//2 + 1), WALL_COLOR)

        # Player marker (2×2 if room)
        px, py = int(self.cam_x), int(self.cam_y)
        ps = 2 if s >= 2 else 1
        _safe_fill(self.bitmap, x0 + px*s, y0 + py*s, ps, ps, WALL_COLOR)
    
    def _draw_text5(self, x, y, text, color=WALL_COLOR, block=2, gap=1):
        # 5x5 bitmap glyphs, scalable via block; uses _safe_fill (no edges crash)
        gw = 5*block + 4*gap   # width of one glyph block
        for i, ch in enumerate(text.upper()):
            pat = _FONT5.get(ch, _FONT5[" "])
            gx = x + i * (gw + gap)
            gy = y
            yy = gy
            for r in range(5):
                row = pat[r]
                xx = gx
                for c in range(5):
                    if row[c] == "1":
                        _safe_fill(self.bitmap, xx, yy, block, block, color)
                    xx += block + gap
                yy += block + gap
               
    def _draw_block_centered(self, lines):
        block = 3; gap = 1
        gw = 5*block + 4*gap
        gh = 5*block + 4*gap

        # Compute total sizes
        text_w = 0
        for ln in lines:
            # width of N glyphs = N*gw + (N-1)*gap   (NOT +block)
            w = len(ln)*gw + (len(ln)-1)*gap
            if w > text_w: text_w = w
        total_h = len(lines)*gh + (len(lines)-1)*gap

        x0 = max(4, (SCREEN_W - text_w)//2) 
        y0 = max(0, (SCREEN_H - total_h)//2)

        for r, ln in enumerate(lines):
            y = y0 + r*(gh + gap)
            x = x0
            for ch in ln:
                pat = _FONT5.get(ch, _FONT5[" "])
                yy = y
                for rr in range(5):
                    row = pat[rr]; xx = x
                    for cc in range(5):
                        if row[cc] == "1":
                            # Clip each tiny block to the screen to avoid x2/y2 errors
                            if 0 <= xx < SCREEN_W and 0 <= yy < SCREEN_H:
                                w = min(block, SCREEN_W - xx)
                                h = min(block, SCREEN_H - yy)
                                if w > 0 and h > 0:
                                    _safe_fill(self.bitmap, xx, yy, w, h, WALL_COLOR)
                        xx += block + gap
                    yy += block + gap
                x += gw + gap   # <-- advance by gw + gap (was gw + block)

    def _splash(self):
        _clear(self.bitmap)
        self._draw_block_centered(["MACRO","MAZE"])
        if HAVE_LABEL: self._set_title("")
        self.macropad.display.refresh()
        self._tone(880, 0.08)
        time.sleep(0.8)
        self._set_stage_leds("menu")
        _clear(self.bitmap); self.macropad.display.refresh()

    def _set_mode(self, new_mode):
        # If we're leaving GAME, drop any held keys so motion doesn't "stick"
        if getattr(self, "mode", None) == "GAME" and new_mode != "GAME":
            if hasattr(self, "pressed") and self.pressed:
                self.pressed.clear()
        self.mode = new_mode
    # ---------- UI ----------
    def enter_menu(self, first=False):
        # Do the splash exactly once per process
        if not self.did_splash:
            self._splash()
            self.did_splash = True
        self._set_mode("MENU")
        self.needs_redraw = True
        self._draw_menu(True)
        
    def _set_title(self, t):
        if self.title and self.title.text != t:
            self.title.text = t

    def _draw_menu(self, force=False):
        if not force and not self.needs_redraw:
            return

        _clear(self.bitmap)

        if HAVE_LABEL:
            self._set_title("")

        y0 = 12
        row_h = 14

        # Row chrome (highlight for selected row, thin divider for others)
        for i, (name, _) in enumerate(self.DIFFS):
            y = y0 + i * row_h
            if i == self.diff_idx:
                _safe_fill(self.bitmap, 4,  y - 1,        SCREEN_W - 8,  12, WALL_COLOR)  # white bar
                _safe_fill(self.bitmap, 8,  y + 2,        SCREEN_W - 16,  6, BG_COLOR)    # inner black stripe
            else:
                _safe_fill(self.bitmap, 6,  y,            SCREEN_W - 12,  1, WALL_COLOR)  # thin line

        # Center the labels
        block, gap = 2, 1
        glyph_w = 5*block + 4*gap
        def text_px_w(s): return len(s) * (glyph_w + gap) - gap
        max_w = 0
        for name, _ in self.DIFFS:
            w = text_px_w(name)
            if w > max_w:
                max_w = w
        x_text = (SCREEN_W - max_w) // 2

        # Draw labels (invert color for selected row)
        for i, (name, _) in enumerate(self.DIFFS):
            y = y0 + i * row_h + 2
            color = BG_COLOR if i == self.diff_idx else WALL_COLOR
            self._draw_text5(x_text, y, name, color=color, block=block, gap=gap)

        self._set_stage_leds("menu")
        self.macropad.display.refresh()
        self.needs_redraw = False

    def _draw_settings(self, force=False):
        if not force and not self.needs_redraw: return
        _clear(self.bitmap)
        if HAVE_LABEL:
            self._set_title("SETTINGS  K7:Back  K1:SFX  K3/K5:Color")
        y1 = 18
        _safe_fill(self.bitmap, 12, y1, 40, 10, WALL_COLOR if not self.sfx else BG_COLOR)
        _safe_fill(self.bitmap, 76, y1, 40, 10, WALL_COLOR if self.sfx else BG_COLOR)
        y2 = 40
        for i in range(len(self.COLORS)):
            x = 12 + i*18
            _safe_fill(self.bitmap, x,     y2, 12,  8, WALL_COLOR if i==self.dir_color_idx else BG_COLOR)
            _safe_fill(self.bitmap, x,     y2, 12,  1, WALL_COLOR)
            _safe_fill(self.bitmap, x,   y2+7, 12,  1, WALL_COLOR)
            _safe_fill(self.bitmap, x,     y2,  1,  8, WALL_COLOR)
            _safe_fill(self.bitmap, x+11,  y2,  1,  8, WALL_COLOR)
        self._set_stage_leds("settings")
        self.macropad.display.refresh()
        self.needs_redraw = False

    def _set_stage_leds(self, stage):
        p = self.macropad.pixels
        if stage == "splash":
            p.fill((0,0,0)); 
            for k in (0,2,9,11): p[k] = (0,40,60)
        elif stage == "menu":
            p.fill((8,8,12))
            for k in (K_UP, K_LEFT, K_RIGHT, K_DOWN): p[k] = self.dir_color
            p[K_SETTINGS] = (255,180,30)
            p[K_START]    = (40,200,60)
        elif stage == "settings":
            p.fill((0,0,0))
            for k in (K_UP, K_LEFT, K_RIGHT, K_DOWN): p[k] = self.dir_color
            p[K_DOWN] = (200,60,60)   # back
            p[K_UP]   = (80,160,255)  # SFX
            p[K_LEFT] = (180,100,255) # color prev
            p[K_RIGHT]= (180,100,255) # color next
            p[K_MINIMAP] = (120,200,200)
        elif stage == "game":
            p.fill((0,0,0))
            for k in (K_UP, K_LEFT, K_RIGHT, K_DOWN): p[k] = self.dir_color
            p[K_SETTINGS] = (255,140,0)
            p[K_MINIMAP]  = (0,200,200)
        try: p.show()
        except Exception: pass
        
    # ---------- Game lifecycle ----------
    def _start(self):
        name, cells = self.DIFFS[self.diff_idx]
        self._led_theme_start()
        self.maze, (self.cam_x, self.cam_y), self.exit_pos = _gen_maze(cells)
        self.cam_a = 0.0
        self.ray.set_maze(self.maze)
        self._set_mode("GAME")
        self.last_pose = None
        self.needs_redraw = True
        self._visited = {(int(self.cam_x), int(self.cam_y))}
        self._tone(880, 0.05)
        self._set_stage_leds("game")
        self.pressed.clear()
        self._last_t = time.monotonic()

    def _save_settings(self):
        _safe_save_json(SETTINGS_PATH, {
            "sfx": self.sfx,
            "dir_color_idx": self.dir_color_idx,
            "diff_idx": self.diff_idx,
        })

    # ---------- Movement ----------
    def _try_move(self, dx, dy):
        nx = self.cam_x + dx; ny = self.cam_y + dy
        if 0 <= int(nx) < len(self.maze[0]) and 0 <= int(ny) < len(self.maze):
            if self.maze[int(ny)][int(nx)] == 0:
                self.cam_x, self.cam_y = nx, ny; self._tone(600, 0.02)
                # record breadcrumb on entering a new cell
                self._visited.add((int(self.cam_x), int(self.cam_y)))
            else:
                self._tone(220, 0.02)
        
    # ---------- Tick (called by launcher loop) ----------
    def tick(self):
        if self.mode != "GAME":
            return

        # --- global speed scale ---
        now = time.monotonic()
        last = getattr(self, "_last_t", now)
        dt = now - last if now > last else 0.0
        self._last_t = now

        # Apply FAST_MULT globally (FAST_MULT < 1 slows, > 1 speeds)
        lin = MOVE_SPEED * dt * 60.0 * FAST_MULT
        rot = TURN_SPEED * dt * 60.0 * FAST_MULT

        moved = False
        prs = getattr(self, "pressed", set())

        if K_UP in prs:
            self._try_move(math.cos(self.cam_a) * lin, math.sin(self.cam_a) * lin); moved = True
        if K_DOWN in prs:
            self._try_move(-math.cos(self.cam_a) * lin, -math.sin(self.cam_a) * lin); moved = True
        if K_LEFT in prs:
            self.cam_a -= rot; moved = True
        if K_RIGHT in prs:
            self.cam_a += rot; moved = True

        if moved:
            self.last_pose = None

        pose = (round(self.cam_x, 3), round(self.cam_y, 3), round(self.cam_a, 3))
        if pose != self.last_pose:
            self.ray.draw(self.cam_x, self.cam_y, self.cam_a)
            if HAVE_LABEL: self._set_title("")
            if self.show_minimap: self._draw_minimap()
            self.macropad.display.refresh()
            self.last_pose = pose

        # Win condition
        ex, ey = self.exit_pos
        if (self.cam_x - ex) ** 2 + (self.cam_y - ey) ** 2 < 0.16:
            for _ in range(2):
                _clear(self.bitmap); self.macropad.display.refresh(); self._tone(1200, 0.05); time.sleep(0.07)
                _safe_fill(self.bitmap, 0, 0, SCREEN_W, SCREEN_H, WALL_COLOR); self.macropad.display.refresh(); time.sleep(0.07)
            self._set_mode("MENU"); self.needs_redraw = True; self._draw_menu(True); self._set_stage_leds("menu")
    # ---------- Button handlers (launcher forwards key events) ----------
    def button(self, key):
        if self.mode == "MENU":
            if key == K_SETTINGS:
                self._set_mode("SETTINGS"); self.needs_redraw = True; self._draw_settings(True); self._tone(500, 0.02)
            elif key == K_START:
                self._start()
            elif key == K_UP:
                self.diff_idx = (self.diff_idx - 1) % len(self.DIFFS); self.needs_redraw = True; self._draw_menu(); self._tone(700, 0.02); self._save_settings()
            elif key == K_DOWN:
                self.diff_idx = (self.diff_idx + 1) % len(self.DIFFS); self.needs_redraw = True; self._draw_menu(); self._tone(700, 0.02); self._save_settings()

        elif self.mode == "SETTINGS":
            if key == K_DOWN:   # back
                self._set_mode("MENU"); self.needs_redraw = True; self._draw_menu(True); self._tone(500, 0.02); self._save_settings()
            elif key == K_UP:   # toggle SFX
                self.sfx = not self.sfx; self.needs_redraw = True; self._draw_settings(); self._tone(500, 0.02); self._save_settings()
            elif key == K_LEFT: # prev color
                self.dir_color_idx = (self.dir_color_idx - 1) % len(self.COLORS); self.dir_color = self.COLORS[self.dir_color_idx]; self._light_dpad(); self.needs_redraw = True; self._draw_settings(); self._tone(650, 0.02); self._save_settings()
            elif key == K_RIGHT:# next color
                self.dir_color_idx = (self.dir_color_idx + 1) % len(self.COLORS); self.dir_color = self.COLORS[self.dir_color_idx]; self._light_dpad(); self.needs_redraw = True; self._draw_settings(); self._tone(650, 0.02); self._save_settings()

        elif self.mode == "GAME":
            mult = FAST_MULT
            tap_lin = MOVE_SPEED * mult
            tap_rot = TURN_SPEED * mult
            # record that a movement key is being held
            if key in (K_UP, K_DOWN, K_LEFT, K_RIGHT):
                self.pressed.add(key)

            if key == K_SETTINGS:
                self._set_mode("SETTINGS"); self.needs_redraw = True
                self._draw_settings(True); self._tone(500, 0.02)
                # (optional) stop continuous motion when leaving game
                self.pressed.clear()
                return

            # one-shot tap behavior stays the same
            if key == K_UP:
                self._try_move(math.cos(self.cam_a)*tap_lin, math.sin(self.cam_a)*tap_lin); self.last_pose=None
            elif key == K_DOWN:
                self._try_move(-math.cos(self.cam_a)*tap_lin, -math.sin(self.cam_a)*tap_lin); self.last_pose=None
            elif key == K_LEFT:
                self.cam_a -= tap_rot; self.last_pose=None; self._tone(520, 0.015)
            elif key == K_RIGHT:
                self.cam_a += tap_rot; self.last_pose=None; self._tone(520, 0.015)
            elif key == K_MINIMAP:
                self.show_minimap = not self.show_minimap
                self.last_pose = None
                self._tone(740 if self.show_minimap else 540, 0.03)

    # Optional (not required)
    def button_up(self, key):
        if key in self.pressed:
            self.pressed.discard(key)

    # Launcher will call this with encoder state; we don’t need it
    def encoderChange(self, pos, last_pos):
        pass

    # Launcher forwards encoder button; we don’t intercept (single press exits)
    def encoder_button(self, pressed):
        # If you ever want in-game handling, you could add hints here.
        # Leaving empty so launcher’s single-press exit is used.
        return

# ---------- Public game wrapper (meets launcher API) ----------
class maze3d:
    # If set True, launcher expects double-press to exit; we want default single press.
    supports_double_encoder_exit = False    
    def __init__(self, macropad, *args, **kwargs):
        self.macropad = macropad
        self.core = _MacroMazeCore(macropad)
        # Expose group for the launcher to set as root_group
        self.group = self.core.group

    def cleanup(self):
        # Prefer the core's thorough cleanup (saves settings, detaches group, clears LEDs, GC)
        try:
            if getattr(self, "core", None):
                self.core.cleanup() 
                return
        except Exception:
            pass

        # Fallback if core is missing or failed
        try:
            self.macropad.display.root_group = None
        except Exception:
            pass
        try:
            self.macropad.pixels.fill((0, 0, 0))
            self.macropad.pixels.show()
        except Exception:
            pass
            
    def new_game(self):
        # Reset to menu view (fresh splash not needed on re-entry)
        self.core.enter_menu(first=True)

    def tick(self):
        self.core.tick()

    def button(self, key):
        self.core.button(key)

    def button_up(self, key):
        if hasattr(self.core, "button_up"):
            self.core.button_up(key)

    def encoderChange(self, pos, last_pos):
        if hasattr(self.core, "encoderChange"):
            self.core.encoderChange(pos, last_pos)

    def encoder_button(self, pressed):
        # Let the launcher handle exit; we could show an exit hint if desired.
        self.core.encoder_button(pressed)