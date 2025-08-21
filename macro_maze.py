# maze3d.py — Macro Maze (3D Raycast Maze for Adafruit MacroPad)
# Target: CircuitPython 9.x — fully Merlin Launcher compatible
# Written by Iain Bennett — 2025
#
# Overview:
#   Classic 3D maze crawler using a lightweight raycaster on the 128×64 OLED.
#   Procedurally generates solvable mazes (odd sizes: 9×9, 13×13, 17×17).
#   Features minimap, difficulty selection, and persistent settings.
#
# Exposes:
#   • class maze3d(macropad)
#       .group         — display group (set as root_group by launcher)
#       .new_game()    — reset to menu
#       .tick()        — update loop (called by launcher)
#       .button(k)     — handle key press
#       .button_up(k)  — handle key release
#       .encoderChange — (unused, passthrough)
#       .encoder_button — (unused, launcher handles exit)
#       .cleanup()     — teardown and restore launcher state
#
# Controls:
#   • MENU: 
#       – K1 ↑ / K7 ↓ → change difficulty (EASY, MED, HARD)
#       – K9 → enter SETTINGS
#       – K11 → START game
#   • SETTINGS:
#       – K1 ↑ → toggle SFX
#       – K3 ← / K5 → → change D-pad LED colour
#       – K9 → back to MENU
#   • GAME:
#       – K1 ↑ / K7 ↓ → move forward/back
#       – K3 ← / K5 → → turn left/right
#       – K9 → return to MENU
#       – K11 → toggle minimap
#   • Encoder:
#       – Single press → exit to launcher (default Merlin behaviour)
#
# Display:
#   • MENU: centered difficulty labels, selected row highlighted
#   • SETTINGS: “SFX” (ON/OFF), “COLOUR” with single-letter colour code
#   • GAME: live raycast view; optional minimap overlay
#   • WIN: “YOU GOT OUT” splash before returning to menu
#
# LEDs:
#   • MENU: dim grey background, D-pad in theme colour, K9 amber (Settings), K11 green (Start)
#   • SETTINGS: only arrows lit (← / → in theme colour, ↑ for SFX), K9 amber (Back)
#   • GAME: D-pad in theme colour, K9 amber (Menu), K11 cyan (Minimap)
#   • Startup: themed LED “ring” animation
#
# Sound:
#   • Uses macropad.play_tone() exclusively (movement ticks, bumps, win beeps)
#   • Toggleable in SETTINGS
#
# Persistence:
#   • Settings saved to /macro_maze_settings.json
#   • SFX enabled/disabled, D-pad LED colour, last difficulty

import math, random, time, json
import displayio, bitmaptools, terminalio
import os
from micropython import const
try:
    from adafruit_display_text import label
    HAVE_LABEL = False
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
SETTINGS_PATH = "/macro_maze_settings.json"

# Shading mode for side==1 walls
# 0 = stripe (fast, vertical resolution friendly)
# 1 = checker (true checkerboard, darker look)
SHADE_MODE = 1

# Key mapping (launcher forwards 0..11)
K_UP, K_LEFT, K_RIGHT, K_DOWN = 1, 3, 5, 7
K_SETTINGS, K_START = 9, 11     # <- Settings now on K9
K_MINIMAP = 11                  # <- moved from 9 to 11
FAST_MULT = 0.25                # move faster or slower when all four D-pad keys are held

# ---------- Tiny 5x5 block font (only letters we need) ----------
_FONT5 = {
    " ": ["00000","00000","00000","00000","00000"],
    "-": ["00000","00000","11111","00000","00000"],
    "A": ["01110","10001","11111","10001","10001"],
    "B": ["11110","10001","11110","10001","11110"],
    "C": ["01110","10000","10000","10000","01110"],
    "D": ["11110","10001","10001","10001","11110"],
    "E": ["11111","10000","11110","10000","11111"],
    "F": ["11111","10000","11110","10000","10000"],
    "G": ["01110","10000","10111","10001","01110"],
    "H": ["10001","10001","11111","10001","10001"],
    "I": ["01110","00100","00100","00100","01110"],
    "J": ["00111","00010","00010","10010","01100"],
    "K": ["10001","10010","11100","10010","10001"],
    "L": ["10000","10000","10000","10000","11111"],
    "M": ["10001","11011","10101","10001","10001"],
    "N": ["10001","11001","10101","10011","10001"],
    "O": ["01110","10001","10001","10001","01110"],
    "P": ["11110","10001","11110","10000","10000"],
    "Q": ["01110","10001","10001","10011","01111"],
    "R": ["11110","10001","11110","10100","10010"],
    "S": ["01111","10000","01110","00001","11110"],
    "T": ["11111","00100","00100","00100","00100"],
    "U": ["10001","10001","10001","10001","01110"],
    "V": ["10001","10001","10001","01010","00100"],
    "W": ["10001","10001","10101","11011","10001"],
    "X": ["10001","01010","00100","01010","10001"],
    "Y": ["10001","01010","00100","00100","00100"],
    "Z": ["11111","00010","00100","01000","11111"],
}

def _mk_framebuffer():
    bitmap = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
    palette = displayio.Palette(2)
    palette[0] = 0x000000
    palette[1] = 0xFFFFFF
    tg = displayio.TileGrid(bitmap, pixel_shader=palette)
    grp = displayio.Group()
    grp.append(tg)
    return bitmap, palette, grp

def _clear(bitmap):
    _safe_fill(bitmap, 0, 0, SCREEN_W, SCREEN_H, BG_COLOR)

    
def _draw_vert_slice(bitmap, x, h, shaded=False):
    h = 1 if h < 1 else (SCREEN_H if h > SCREEN_H else h)
    top = (SCREEN_H - h) // 2

    if not shaded:
        _safe_fill(bitmap, x, top, 2, h, WALL_COLOR)
        return

    if SHADE_MODE == 0:
        # --- STRIPE MODE ---
        start = ((x >> 1) & 1)  # stagger by column
        y = top + start
        y_end = top + h
        while y < y_end:
            _safe_fill(bitmap, x, y, 2, 1, WALL_COLOR)
            y += 2
    else:
        # --- CHECKER MODE ---
        #y_end = top + h
        #for y in range(top, y_end):
        #    if ((x >> 1) + y) & 1:
        #        _safe_fill(bitmap, x, y, 2, 1, WALL_COLOR)
                
        y = top + (((x >> 1) + top) & 1)  # pick the first row that should be "on"
        y_end = top + h
        while y < y_end:
            _safe_fill(bitmap, x, y, 2, 1, WALL_COLOR)
            y += 2

def _norm_angle(a):
    while a <= -math.pi: a += 2*math.pi
    while a >   math.pi: a -= 2*math.pi
    return a

def _safe_load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        # If the file is corrupt or missing, return default
        try:
            print("Settings load failed:", repr(e))
        except Exception:
            pass
        return default

def _remount_temporarily_rw():
    # Remounts the root filesystem RW if it's currently RO.
    # Returns (did_change, ok) where:
    #  - did_change: True if we flipped RO->RW and should flip back later
    #  - ok:        True if the FS is RW after this call, False if not
    try:
        import storage
        m = storage.getmount("/")
        was_ro = getattr(m, "readonly", True)
        if was_ro:
            try:
                # Make RW
                storage.remount("/", False)
            except Exception:
                # Some builds need a second attempt or differ based on USB
                try:
                    storage.remount("/", readonly=False)
                except Exception:
                    return (False, False)
            return (True, True)
        else:
            return (False, True)
    except Exception:
        # If storage isn't available, assume we can write (older builds)
        return (False, True)

def _restore_ro_if_needed(did_change):
    try:
        if not did_change:
            return
        import storage
        try:
            storage.remount("/", True)
        except Exception:
            try:
                storage.remount("/", readonly=True)
            except Exception:
                pass
    except Exception:
        pass

def _safe_save_json(path, data):
    # Safely save JSON even when CIRCUITPY is normally RO while USB is connected.
    # Temporarily flips to RW, writes, flushes, then flips back.
    did_flip, ok = _remount_temporarily_rw()
    if not ok:
        try: print("Settings save skipped: filesystem is read-only")
        except Exception: pass
        return

    err = None
    try:
        with open(path, "w") as f:
            json.dump(data, f)
            try:
                f.flush()
                os.sync()  # ok if this fails; best effort
            except Exception:
                pass
    except Exception as e:
        err = e

    _restore_ro_if_needed(did_flip)

    if err:
        try: print("Settings save failed:", repr(err))
        except Exception: pass

def _ensure_settings_file_exists(current):
    try:
        open(SETTINGS_PATH, "r").close()
    except Exception:
        _safe_save_json(SETTINGS_PATH, current)
        
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
    w = h = cells
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
        opts = list(nbrs(x, y))
        if not opts:
            stack.pop(); continue
        nx, ny, mid = random.choice(opts)
        grid[y+mid[1]][x+mid[0]] = 0
        grid[ny][nx] = 0
        stack.append((nx, ny))

    # Entrance: left border adjacent to start (always connected)
    grid[1][0] = 0

    # Exit: open the RIGHT border at a row that already has a corridor at w-2.
    # This guarantees connectivity.
    candidates = [y for y in range(1, h-1) if grid[y][w-2] == 0]
    if candidates:
        ey = random.choice(candidates)
    else:
        # Extremely defensive: if somehow no candidates, force one near the bottom.
        ey = h-2
        grid[ey][w-2] = 0
    grid[ey][w-1] = 0
    exit_pos = (w-1.5, ey + 0.5)

    return grid, (1.5, 1.5), exit_pos

# ---------- Raycaster ----------
class _Raycaster:
    def __init__(self, bitmap, maze, fov=FOV, rays=RAYS):
        self.bitmap = bitmap
        self.set_maze(maze)
        self.rays = rays
        self.fov = fov
        self.offs = [((i + 0.5)/rays - 0.5) * fov for i in range(rays)]
        self._off_cos = [math.cos(a) for a in self.offs]
        self._off_sin = [math.sin(a) for a in self.offs]
        self._last_top = [0] * rays
        self._last_h = [0] * rays
        self._last_shaded = [2] * rays  # 2 = unknown, forces first-frame draw

    def set_maze(self, maze):
        self.maze = maze
        self.h = len(maze)
        self.w = len(maze[0])

    def draw(self, px, py, ang):
        # Incremental update: no full-screen clear—only touch changed columns

        cosA = math.cos(ang)
        sinA = math.sin(ang)

        offc = self._off_cos   # cos(offset)
        offs = self._off_sin   # sin(offset)
        maze = self.maze
        w = self.w
        h = self.h
        bm = self.bitmap
        rays = self.rays

        inv_eps = 1e-6
        max_steps = (w + h) * 2  # cap DDA steps by maze size

        last_top = self._last_top
        last_h   = self._last_h
        last_sh  = self._last_shaded

        for i in range(rays):
            # Rotate precomputed offset by camera angle
            rx = cosA * offc[i] - sinA * offs[i]
            ry = sinA * offc[i] + cosA * offs[i]

            mapX = int(px); mapY = int(py)
            dX = abs(1.0 / (rx if abs(rx) > inv_eps else inv_eps))
            dY = abs(1.0 / (ry if abs(ry) > inv_eps else inv_eps))

            if rx < 0:
                stepX = -1; sideX = (px - mapX) * dX
            else:
                stepX =  1; sideX = (mapX + 1.0 - px) * dX
            if ry < 0:
                stepY = -1; sideY = (py - mapY) * dY
            else:
                stepY =  1; sideY = (mapY + 1.0 - py) * dY

            hit = False; side = 0
            for _ in range(max_steps):
                if sideX < sideY:
                    sideX += dX; mapX += stepX; side = 0
                else:
                    sideY += dY; mapY += stepY; side = 1
                if mapX < 0 or mapX >= w or mapY < 0 or mapY >= h:
                    hit = True; break
                if maze[mapY][mapX] == 1:
                    hit = True; break

            if not hit:
                perp = 999.0
            else:
                if side == 0:
                    dist = (mapX - px + (1 - stepX)*0.5) / (rx if abs(rx) > inv_eps else inv_eps)
                else:
                    dist = (mapY - py + (1 - stepY)*0.5) / (ry if abs(ry) > inv_eps else inv_eps)
                if dist == 0:
                    dist = inv_eps
                perp = abs(dist) * offc[i]  # perpendicular correction via cos(offset)

            if perp < 1e-3:
                perp = 1e-3

            new_h = int(SCREEN_H / perp)
            if new_h < 1: new_h = 1
            if new_h > SCREEN_H: new_h = SCREEN_H
            new_top = (SCREEN_H - new_h) // 2
            shaded = 1 if (hit and side == 1) else 0

            # Skip if this column is identical to the last frame
            if new_top == last_top[i] and new_h == last_h[i] and shaded == last_sh[i]:
                continue

            # Erase previous slice for this column (if any)
            prev_h = last_h[i]
            if prev_h > 0:
                prev_top = last_top[i]
                _safe_fill(bm, i*2, prev_top, 2, prev_h, BG_COLOR)

            # Draw the new slice
            _draw_vert_slice(bm, i*2, new_h, shaded=bool(shaded))

            # Save state for next frame
            last_h[i]   = new_h
            last_top[i] = new_top
            last_sh[i]  = shaded

# ---------- Core (event-driven, no blocking loop) ----------
class _MacroMazeCore:
    DIFFS = [("EASY", 9), ("MED", 13), ("HARD", 17)]
    COLORS = [
        (0x70,0x20,0xB0),  # Purple (deeper violet)
        (0x10,0x10,0xC0),  # Blue (navy-like)
        (0x00,0xB0,0x30),  # Green (forest-ish)
        (0xD0,0xD0,0x00),  # Yellow (golden, less neon)
        (0xC0,0x60,0x00),  # Orange (amber)
        (0xC0,0x00,0x00),  # Red (deep crimson)
        (0xE0,0xE0,0xE0),  # White (unchanged)
    ]
    COLOR_LABELS = ["P","B","G","Y","O","R","W"]

    def _load_settings(self):
        s = _safe_load_json(SETTINGS_PATH, {
            "sfx": True,
            "dir_color_idx": 0,
            "diff_idx": 0,
        })
        self.sfx = bool(s.get("sfx", True))
        self.diff_idx = int(s.get("diff_idx", 0)) % len(self.DIFFS)
        self.dir_color_idx = int(s.get("dir_color_idx", 0)) % len(self.COLORS)
        self.dir_color = self.COLORS[self.dir_color_idx]

        # NEW: ensure a file is created immediately (with whatever we just loaded)
        _ensure_settings_file_exists({
            "sfx": self.sfx,
            "dir_color_idx": self.dir_color_idx,
            "diff_idx": self.diff_idx,
        })
        
    def __init__(self, macropad):
        self.macropad = macropad
        self._settings_dirty = False
        
        self._orig_auto_refresh = getattr(self.macropad.display, "auto_refresh", True)
        self.macropad.display.auto_refresh = False

        self.bitmap, self.palette, self.group = _mk_framebuffer()
        self.pressed = set()
        

        self.title = None
        if HAVE_LABEL:
            self.title = label.Label(terminalio.FONT, text="", color=0xFFFFFF,
                                     scale=1, anchored_position=(1,1), anchor_point=(0,0))
            self.group.append(self.title)

        self.macropad.display.root_group = self.group

        # Persisted settings
        self._load_settings()
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
        # 0) Persist settings if needed (best-effort)
        try:
            if getattr(self, "_settings_dirty", False):
                self._save_settings()
                self._settings_dirty = False
        except Exception:
            pass

        # 1) Stop any held inputs and any tone
        try:
            if hasattr(self, "pressed") and self.pressed:
                self.pressed.clear()
        except Exception:
            pass
        try:
            if hasattr(self.macropad, "stop_tone"):
                self.macropad.stop_tone()
        except Exception:
            pass

        # 2) Display: freeze, blank our framebuffer once, detach our group,
        #    and restore the original auto_refresh state
        try:
            disp = getattr(self.macropad, "display", None)
            if disp:
                # Freeze redraws while we change things
                try: disp.auto_refresh = False
                except Exception: pass

                # Push a clean frame using our own bitmap (no new allocations)
                try:
                    if getattr(self, "bitmap", None) is not None:
                        _clear(self.bitmap)
                    disp.refresh(minimum_frames_per_second=0)
                except Exception:
                    # Some builds only accept refresh() without args
                    try: disp.refresh()
                    except Exception: pass

                # Detach ONLY if our group is the current root_group
                try:
                    if getattr(disp, "root_group", None) is self.group:
                        disp.root_group = None
                except Exception:
                    # Last-ditch: force None anyway
                    try: disp.root_group = None
                    except Exception: pass

                # Restore whatever the display’s auto_refresh was when we started
                try:
                    disp.auto_refresh = getattr(self, "_orig_auto_refresh", True)
                except Exception:
                    pass
        except Exception:
            pass

        # 3) LEDs off (return control to launcher visuals)
        try:
            if hasattr(self.macropad, "pixels"):
                self.macropad.pixels.fill((0, 0, 0))
                self.macropad.pixels.show()
        except Exception:
            pass

        # 4) Drop references so GC can reclaim RAM
        try:
            if hasattr(self, "_visited") and self._visited is not None:
                self._visited.clear()
        except Exception:
            pass

        self.title   = None
        self.group   = None
        self.bitmap  = None
        self.palette = None
        self.ray     = None
        self.maze    = None

        # 5) GC sweep
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
            yy = y
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
        prev = getattr(self, "mode", None)

        # If we're leaving GAME, drop any held keys so motion doesn't "stick"
        if prev == "GAME" and new_mode != "GAME":
            if hasattr(self, "pressed") and self.pressed:
                self.pressed.clear()

        # Only save when leaving SETTINGS, and only if something changed
        if prev == "SETTINGS" and new_mode != "SETTINGS":
            if getattr(self, "_settings_dirty", False):
                try:
                    self._save_settings()
                except Exception:
                    pass
                self._settings_dirty = False

        self.mode = new_mode
        
    # ---------- UI ----------
    def enter_menu(self):
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

        # Text metrics (must match _draw_text5 settings)
        block, gap = 2, 1
        glyph_w = 5*block + 4*gap         # 14 px per glyph width unit (incl gaps within glyph)
        glyph_h = 5*block + 4*gap         # 14 px tall
        row_h   = glyph_h                  # row height exactly equals glyph height
        y0      = 12                       # top of first row

        # Compute centered x for the widest label so all rows are aligned
        def text_px_w(s): return len(s) * (glyph_w + gap) - gap
        max_w = max(text_px_w(name) for name, _ in self.DIFFS)
        x_text = (SCREEN_W - max_w) // 2

        # Draw only the selected bar (no horizontal dividers)
        sel_y_top = y0 + self.diff_idx * row_h
        _safe_fill(self.bitmap, 4, sel_y_top, SCREEN_W - 8, glyph_h, WALL_COLOR)  # solid white bar

        # Draw labels: black on the selected white bar, white elsewhere
        for i, (name, _) in enumerate(self.DIFFS):
            y = y0 + i * row_h
            color = BG_COLOR if i == self.diff_idx else WALL_COLOR
            self._draw_text5(x_text, y, name, color=color, block=block, gap=gap)

        self._set_stage_leds("menu")
        self.macropad.display.refresh()
        self.needs_redraw = False

    def _draw_settings(self, force=False):
        if not force and not self.needs_redraw:
            return

        _clear(self.bitmap)
        # no tiny label, we’ve removed _set_title calls

        # --- metrics (match _draw_text5) ---
        block, gap = 2, 1
        glyph_w = 5*block + 4*gap      # 14
        glyph_h = 5*block + 4*gap      # 14
        def text_px_w(s): return len(s) * (glyph_w + gap) - gap

        # ---------- Title ----------
        title = "SETTINGS"
        x_title = (SCREEN_W - text_px_w(title)) // 2
        self._draw_text5(x_title, 2, title, color=WALL_COLOR, block=block, gap=gap)

        # ---------- SFX row ----------
        y_sfx = 20
        self._draw_text5(8, y_sfx, "SFX", color=WALL_COLOR, block=block, gap=gap)

        # Make the block width = width of "OFF" (fixed), height = glyph height
        sfx_block_h = glyph_h
        sfx_block_w = text_px_w("OFF")
        sfx_block_right = SCREEN_W - 8   # right margin align
        sfx_block_x = sfx_block_right - sfx_block_w
        sfx_block_y = y_sfx

        if self.sfx:
            # ON: solid white rectangle with black text
            _safe_fill(self.bitmap, sfx_block_x, sfx_block_y, sfx_block_w, sfx_block_h, WALL_COLOR)
            on_x = sfx_block_x + (sfx_block_w - text_px_w("ON")) // 2
            self._draw_text5(on_x, sfx_block_y, "ON", color=BG_COLOR, block=block, gap=gap)
        else:
            # OFF: just white text on black (no rect at all)
            off_x = sfx_block_x + (sfx_block_w - text_px_w("OFF")) // 2
            self._draw_text5(off_x, sfx_block_y, "OFF", color=WALL_COLOR, block=block, gap=gap)

        # ---------- COLOUR row ----------
        y_color = 40
        self._draw_text5(8, y_color, "COLOUR", color=WALL_COLOR, block=block, gap=gap)

        slot_x = 8 + text_px_w("COLOUR") + 12
        cur_lbl = self.COLOR_LABELS[self.dir_color_idx]

        # Highlight only the currently selected colour
        if True:  # always draw current selection highlighted
            self._draw_text5(slot_x, y_color, cur_lbl, color=WALL_COLOR, block=block, gap=gap)
        # If you later want to show all colours, you’d draw them unhighlighted instead

        self._set_stage_leds("settings")
        self.macropad.display.refresh()
        self.needs_redraw = False

    def _set_stage_leds(self, stage):
        p = self.macropad.pixels
        if stage == "menu":
            p.fill((8,8,12))
            for k in (K_UP, K_LEFT, K_RIGHT, K_DOWN): p[k] = self.dir_color
            p[K_SETTINGS] = (255,180,30)
            p[K_START]    = (40,200,60)
        elif stage == "settings":
            p.fill((0,0,0))
            # K3/K5 show the current theme colour
            p[K_LEFT]  = self.dir_color
            p[K_RIGHT] = self.dir_color
            # Keep the rest as hints
            p[K_UP]       = (80,160,255)   # SFX toggle hint
            p[K_DOWN]     = (0,0,0)        # unlit / back not used here
            p[K_SETTINGS] = (255,180,30)   # K9 = back to MENU
            try: p.show()
            except Exception: pass
            return
        elif stage == "game":
            p.fill((0,0,0))
            for k in (K_UP, K_LEFT, K_RIGHT, K_DOWN): p[k] = self.dir_color
            p[K_SETTINGS] = (255,140,0)
            p[K_MINIMAP]  = (0,200,200)
        try: p.show()
        except Exception: pass
        
    # ---------- Game lifecycle ----------
    def _start(self):
        _, cells = self.DIFFS[self.diff_idx]
        self._led_theme_start()
        
        # --- clear screen before entering GAME ---
        # Ensure any MENU graphics are gone immediately, even before first tick.
        try:
            _clear(self.bitmap)
            self.macropad.display.refresh(minimum_frames_per_second=0)
        except Exception:
            try: self.macropad.display.refresh()
            except Exception: pass
        
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
            
        self.cam_a = _norm_angle(self.cam_a)

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
            # quick double-beep (same feel as before, but no flash)
            for _ in range(2):
                self._tone(1200, 0.05)
                time.sleep(0.06)

            # Clear, show centered message, pause
            _clear(self.bitmap)
            self._draw_block_centered(["YOU", "GOT", "OUT"])
            self.macropad.display.refresh()
            time.sleep(2.0)

            # Back to menu
            self._set_mode("MENU")
            self.needs_redraw = True
            self._draw_menu(True)
            self._set_stage_leds("menu")
    # ---------- Button handlers (launcher forwards key events) ----------
    def button(self, key):
        if self.mode == "MENU":          
            if key == K_SETTINGS:  # K9 now
                self._set_mode("SETTINGS"); self.needs_redraw = True; self._draw_settings(True); self._tone(500, 0.02)
            elif key == K_START:
                self._start()
            elif key == K_UP:
                self.diff_idx = (self.diff_idx - 1) % len(self.DIFFS); self.needs_redraw = True; self._draw_menu(); self._tone(700, 0.02); self._save_settings()
            elif key == K_DOWN:
                self.diff_idx = (self.diff_idx + 1) % len(self.DIFFS); self.needs_redraw = True; self._draw_menu(); self._tone(700, 0.02); self._save_settings()

        elif self.mode == "SETTINGS":
            if key == K_SETTINGS:   # back to MENU
                self._set_mode("MENU")
                self.needs_redraw = True
                self._draw_menu(True)
                self._tone(500, 0.02)
                # no direct save here; _set_mode handles it if dirty

            elif key == K_UP:       # toggle SFX
                self.sfx = not self.sfx
                self._settings_dirty = True
                self.needs_redraw = True
                self._draw_settings()
                self._tone(500, 0.02)

            elif key == K_LEFT:     # prev colour
                self.dir_color_idx = (self.dir_color_idx - 1) % len(self.COLORS)
                self.dir_color = self.COLORS[self.dir_color_idx]
                self._settings_dirty = True
                self._set_stage_leds("settings")
                self.needs_redraw = True
                self._draw_settings()
                self._tone(650, 0.02)

            elif key == K_RIGHT:    # next colour
                self.dir_color_idx = (self.dir_color_idx + 1) % len(self.COLORS)
                self.dir_color = self.COLORS[self.dir_color_idx]
                self._settings_dirty = True
                self._set_stage_leds("settings")
                self.needs_redraw = True
                self._draw_settings()
                self._tone(650, 0.02)
                
        elif self.mode == "GAME":
            mult = FAST_MULT
            tap_lin = MOVE_SPEED * mult
            tap_rot = TURN_SPEED * mult
            # record that a movement key is being held
            if key in (K_UP, K_DOWN, K_LEFT, K_RIGHT):
                self.pressed.add(key)

            if key == K_SETTINGS:
                self._set_mode("MENU"); self.needs_redraw = True
                self._draw_menu(True); self._tone(500, 0.02)
                # (optional) stop continuous motion when leaving game
                self.pressed.clear()
                return

            # one-shot tap behavior stays the same
            if key == K_UP:
                self._try_move(math.cos(self.cam_a)*tap_lin, math.sin(self.cam_a)*tap_lin); self.last_pose=None
            elif key == K_DOWN:
                self._try_move(-math.cos(self.cam_a)*tap_lin, -math.sin(self.cam_a)*tap_lin); self.last_pose=None
            elif key == K_LEFT:
                self.cam_a -= tap_rot; 
                self.cam_a = _norm_angle(self.cam_a)
                self.last_pose=None; self._tone(520, 0.015)
            elif key == K_RIGHT:
                self.cam_a += tap_rot; 
                self.cam_a = _norm_angle(self.cam_a)
                self.last_pose=None; self._tone(520, 0.015)
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
        """Prefer the core’s teardown; otherwise fall back to a minimal reset."""
        try:
            if getattr(self, "core", None):
                self.core.cleanup()
                return
        except Exception:
            pass

        # Fallback if core missing/failed
        try:
            disp = getattr(self.macropad, "display", None)
            if disp:
                try: disp.auto_refresh = False
                except Exception: pass
                try: disp.root_group = None
                except Exception: pass
                try: disp.refresh(minimum_frames_per_second=0)
                except Exception: pass
                try: disp.auto_refresh = True
                except Exception: pass
        except Exception:
            pass
        try:
            if hasattr(self.macropad, "pixels"):
                self.macropad.pixels.fill((0, 0, 0))
                self.macropad.pixels.show()
        except Exception:
            pass
            
    def new_game(self):
        # Reset to menu view (fresh splash not needed on re-entry)
        self.core.enter_menu()

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