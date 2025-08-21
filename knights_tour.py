# knights_tour.py — Knight’s Tour (MacroPad Launcher-compatible)
# CircuitPython 9.x / Adafruit MacroPad (128×64 mono OLED)
# Written by Iain Bennett — 2025
#
# Game:
#   Move a chess knight so that every square of the 8×8 board is visited once.
#   Single-player: complete a full tour (64 moves). Undo when needed.
#
# Controls:
#   K3 (←) / K5 (→)  : Cycle through legal moves (clockwise ordering)
#   K7 (↓)           : Undo last move
#   K9               : Restart (same single-player mode)
#   K10              : Toggle Hint (UI only; order remains clockwise)
#   K11              : Commit / Fire — confirm selected move
#
# Hint mode:
#   • OFF  — legal moves are listed in a fixed, clockwise spatial order (K3/K5 walk that ring).
#   • ON   — legal moves are ordered by Warnsdorff’s heuristic (fewest onward moves first),
#            i.e., best → worst. K3/K5 still cycle through that ordered list.
#
# Display:
#   • 8×8 chessboard drawn in center of 128×64 screen
#   • Visited squares filled, path drawn, knight ring shown
#   • Legal moves shown as box outlines; selected move shown filled with a tiny 2×2 hole
#   • HUD shows hint mode, steps and number of legal moves
#
# LEDs (cosine-fade, no flashing):
#   • First N LEDs lit = number of legal moves; selected one pulses in blue
#   • Accent LEDs: K9 amber (Restart), K10 cyan/slate (Hint ON/OFF),
#                  K11 green (Commit), K7 violet (Undo)
#
# Sounds (via macropad.play_tone):
#   • Move = short high beep; Undo = lower beep; Stuck = deep buzz; Win = bright tone
#
# Exposes class `knights_tour` with:
#   .group (display group), .new_game(), .tick(), .button(), .cleanup()
#
# Constructor accepts (macropad, tones, **kwargs) — works with the launcher.

import math, random
import displayio, bitmaptools
from micropython import const

# ---------- Screen ----------
SCREEN_W, SCREEN_H = const(128), const(64)
C_BG, C_FG = const(0), const(1)

# ---------- Keys ----------
K_LEFT, K_RIGHT, K_DOWN = const(3), const(5), const(7)

# ---------- LED colors ----------
P1_COLOR = (0, 0, 120)  # blue for legal-move LEDs
UI_AMBER      = (255,120,0)   # K9 (Restart)
UI_CYAN       = (0,120,255)   # K10 when Hint ON
UI_SLATE      = (40,40,60)    # K10 when Hint OFF
UI_GREEN      = (0,180,0)     # K11 (Commit)
UI_VIOLET     = (160,0,200)   # K7 (Undo)

def clamp(v,a,b): return a if v < a else (b if v > b else v)

# Knight deltas, clockwise starting at (x+1,y-2)
MOVES = (
    (+1, -2), (+2, -1), (+2, +1), (+1, +2),
    (-1, +2), (-2, +1), (-2, -1), (-1, -2),
)

# ---------- Defensive draw helpers ----------
_HAS_FILL_REGION = hasattr(bitmaptools, "fill_region")

def _rect_fill(bmp, x, y, w, h, color):
    if w <= 0 or h <= 0: return
    x0 = clamp(x, 0, bmp.width - 1)
    y0 = clamp(y, 0, bmp.height - 1)
    x1 = clamp(x + w - 1, 0, bmp.width - 1)
    y1 = clamp(y + h - 1, 0, bmp.height - 1)
    if x1 < x0 or y1 < y0: return
    try:
        if _HAS_FILL_REGION:
            bitmaptools.fill_region(bmp, x0, y0, (x1-x0+1), (y1-y0+1), color)
            return
    except Exception:
        pass
    for yy in range(y0, y1+1):
        for xx in range(x0, x1+1):
            bmp[xx, yy] = color

def _hline(bmp, x0, x1, y, color=C_FG):
    if y < 0 or y >= bmp.height: return
    if x0 > x1: x0, x1 = x1, x0
    x0 = clamp(x0, 0, bmp.width-1)
    x1 = clamp(x1, 0, bmp.width-1)
    if x1 < x0: return
    for x in range(x0, x1+1):
        bmp[x, y] = color

def _vline(bmp, x, y0, y1, color=C_FG):
    if x < 0 or x >= bmp.width: return
    if y0 > y1: y0, y1 = y1, y0
    y0 = clamp(y0, 0, bmp.height-1)
    y1 = clamp(y1, 0, bmp.height-1)
    if y1 < y0: return
    for y in range(y0, y1+1):
        bmp[x, y] = color

def _line(bmp, x0, y0, x1, y1, color=C_FG):
    dx = abs(x1-x0); sx = 1 if x0<x1 else -1
    dy = -abs(y1-y0); sy = 1 if y0<y1 else -1
    err = dx + dy
    while True:
        if 0 <= x0 < bmp.width and 0 <= y0 < bmp.height:
            bmp[x0,y0] = color
        if x0 == x1 and y0 == y1: break
        e2 = 2*err
        if e2 >= dy: err += dy; x0 += sx
        if e2 <= dx: err += dx; y0 += sy

# ---- Tiny 4x6 font + HUD ----
_FONT = {}
for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 :/-":
    _FONT[ord(ch)] = [0,0,0,0,0,0]
for k,v in {
 '0':[0b1110,0b1001,0b1001,0b1001,0b1001,0b1110],
 '1':[0b0100,0b1100,0b0100,0b0100,0b0100,0b1110],
 '2':[0b1110,0b0001,0b0010,0b0100,0b1000,0b1111],
 '3':[0b1110,0b0001,0b0110,0b0001,0b0001,0b1110],
 '4':[0b0010,0b0110,0b1010,0b1111,0b0010,0b0010],
 '5':[0b1111,0b1000,0b1110,0b0001,0b0001,0b1110],
 '6':[0b0110,0b1000,0b1110,0b1001,0b1001,0b0110],
 '7':[0b1111,0b0001,0b0010,0b0100,0b0100,0b0100],
 '8':[0b0110,0b1001,0b0110,0b1001,0b1001,0b0110],
 '9':[0b0110,0b1001,0b1001,0b0111,0b0001,0b0110],
 'S':[0b0111,0b1000,0b1110,0b0001,0b0001,0b1110],
 'T':[0b1111,0b0100,0b0100,0b0100,0b0100,0b0100],
 'E':[0b1111,0b1000,0b1110,0b1000,0b1000,0b1111],
 'P':[0b1110,0b1001,0b1110,0b1000,0b1000,0b1000],
 'L':[0b1000,0b1000,0b1000,0b1000,0b1000,0b1111],
 'G':[0b0111,0b1000,0b1000,0b1011,0b1001,0b0111],
 'A':[0b0110,0b1001,0b1001,0b1111,0b1001,0b1001],
 'H':[0b1001,0b1001,0b1111,0b1001,0b1001,0b1001],
 'N':[0b1001,0b1101,0b1101,0b1011,0b1011,0b1001],
 'O':[0b0110,0b1001,0b1001,0b1001,0b1001,0b0110],
 'F':[0b1111,0b1000,0b1110,0b1000,0b1000,0b1000],
 ':':[0b0000,0b0110,0b0110,0b0000,0b0110,0b0110],
}.items(): _FONT[ord(k)]=v

def _draw_text(bmp, x, y, text, color=C_FG):
    cx = x
    for ch in text.upper():
        g = _FONT.get(ord(ch))
        if not g:
            cx += 5; continue
        for row in range(6):
            bits = g[row]; py = y + row - 5
            if py < 0 or py >= bmp.height: continue
            for col in range(4):
                if (bits >> (3-col)) & 1:
                    px = cx + col
                    if 0 <= px < bmp.width:
                        bmp[px, py] = color
        cx += 5

def _draw_hud(bmp, steps, legal, hint_on):
    _draw_text(bmp, 2, 43, "H:{}".format("ON" if hint_on else "OFF"))
    _draw_text(bmp, 2, 50, "S:{}/64".format(steps))
    _draw_text(bmp, 2, 57, "L:{}".format(legal))

# ---------- LED animator ----------
class _LEDAnimator:
    def __init__(self, macropad=None):
        self.macropad = macropad
        self.t = 0.0
        self.legal_count = 0
        self.sel_idx = -1
        self.player_color = (80,80,80)
        self._prev = [(0,0,0)] * 12
        self._overlay = [(0,0,0)] * 12

    def set_overlay(self, overlay_colors):
        if overlay_colors and len(overlay_colors) == 12:
            self._overlay = list(overlay_colors)

    def set(self, count, sel, player_color):
        self.legal_count = max(0, min(12, count))
        self.sel_idx = sel
        self.player_color = player_color

    def off(self):
        try:
            if self.macropad and hasattr(self.macropad, "pixels"):
                old_auto = getattr(self.macropad.pixels, "auto_write", True)
                try: self.macropad.pixels.auto_write = False
                except Exception: pass
                for i in range(12):
                    if self._prev[i] != (0,0,0):
                        self.macropad.pixels[i] = (0,0,0)
                        self._prev[i] = (0,0,0)
                try: self.macropad.pixels.show()
                except Exception: pass
                try: self.macropad.pixels.auto_write = old_auto
                except Exception: pass
        except Exception:
            pass

    def _scale(self, rgb, s):
        return (clamp(int(rgb[0]*s),0,255),
                clamp(int(rgb[1]*s),0,255),
                clamp(int(rgb[2]*s),0,255))

    def _blend_max(self, a, b):
        return (max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2]))

    def update(self, dt):
        if not (self.macropad and hasattr(self.macropad, "pixels")):
            return
        self.t += dt
        sel_s  = 0.675 + 0.325 * (0.5 - 0.5 * math.cos(2.0*math.pi*(self.t*0.6)))
        base_s = 0.25

        desired = [(0,0,0)] * 12
        for i in range(self.legal_count):
            s = sel_s if i == self.sel_idx else base_s
            desired[i] = self._scale(self.player_color, s)

        for i in range(12):
            if self._overlay[i] != (0,0,0):
                desired[i] = self._blend_max(desired[i], self._overlay[i])

        if desired == self._prev:
            return

        old_auto = getattr(self.macropad.pixels, "auto_write", True)
        try: self.macropad.pixels.auto_write = False
        except Exception: pass
        try:
            for i in range(12):
                if desired[i] != self._prev[i]:
                    self.macropad.pixels[i] = desired[i]
                    self._prev[i] = desired[i]
            try: self.macropad.pixels.show()
            except Exception: pass
        finally:
            try: self.macropad.pixels.auto_write = old_auto
            except Exception: pass

# ---------- Sounds ----------
class _SFX:
    def __init__(self, macropad=None): self.mp=macropad
    def tone(self,freq,dur):
        try:
            if self.mp and hasattr(self.mp,"play_tone"): self.mp.play_tone(freq,dur)
        except: pass
    def move(self): self.tone(660,0.04)
    def undo(self): self.tone(360,0.05)
    def stuck(self): self.tone(220,0.12)
    def win(self): self.tone(880,0.18)

# ---------- Utils ----------
def in_bounds(x,y): return 0<=x<8 and 0<=y<8

# ---------- Game ----------
class knights_tour:
    def __init__(self, macropad=None, tones=None, **kwargs):
        self.group = displayio.Group()
        self.bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
        self.pal = displayio.Palette(2); self.pal[0]=0x000000; self.pal[1]=0xFFFFFF
        self.tg = displayio.TileGrid(self.bmp, pixel_shader=self.pal)
        self.group.append(self.tg)

        self.macropad = macropad
        self.leds = _LEDAnimator(macropad)
        self.sfx  = _SFX(macropad)

        self.CELL,self.GRID=6,1
        self.BOARD_W=8*self.CELL+9*self.GRID
        self.BOARD_H=self.BOARD_W
        self.BX=(SCREEN_W-self.BOARD_W)//2
        self.BY=(SCREEN_H-self.BOARD_H)//2

        self.hint_on=True
        self.visited=[[False]*8 for _ in range(8)]
        self.path=[]; self.legal=[]; self.sel_idx=0

        self._apply_ui_overlay()
        self.new_game()

    def _cell_rect(self,ix,iy):
        x=self.BX+self.GRID+ix*(self.CELL+self.GRID)
        y=self.BY+self.GRID+iy*(self.CELL+self.GRID)
        return x,y,self.CELL,self.CELL
    def _cell_center(self,ix,iy):
        rx,ry,rw,rh=self._cell_rect(ix,iy)
        return rx+rw//2, ry+rh//2

    def _apply_ui_overlay(self):
        ov = [(0,0,0)] * 12
        ov[7]  = UI_VIOLET       # Undo
        ov[9]  = UI_AMBER        # Restart
        ov[10] = (UI_CYAN if self.hint_on else UI_SLATE)  # Hint toggle
        ov[11] = UI_GREEN        # Commit
        self.leds.set_overlay(ov)

    def new_game(self, opts=None):
        self.hint_on = True
        for y in range(8):
            for x in range(8):
                self.visited[y][x] = False
        self.path = []
        self.legal = []
        self.sel_idx = 0

        # Start square (center-ish)
        self._push_move((4,3))
        # Or random:
        # self._push_move((random.randrange(8), random.randrange(8)))

        self._recompute_legal()
        self._update_leds()
        self._apply_ui_overlay()
        self._redraw()

    def cleanup(self): self.leds.off()

    def _push_move(self,pos):
        x,y=pos; self.visited[y][x]=True; self.path.append(pos)
        self.sfx.move()

    def _pop_move(self):
        if len(self.path)<=1: return
        x,y=self.path.pop(); self.visited[y][x]=False
        self.sfx.undo()

    def _current(self): return self.path[-1]

    def _recompute_legal(self):
        cx,cy=self._current(); leg=[]
        for dx,dy in MOVES:
            nx,ny=cx+dx,cy+dy
            if in_bounds(nx,ny) and not self.visited[ny][nx]:
                leg.append((nx,ny))
        # Ordering is always clockwise per MOVES (even if hint_on is True)
        self.legal=leg; self.sel_idx=0 if leg else -1

    def _clear(self): _rect_fill(self.bmp,0,0,SCREEN_W,SCREEN_H,C_BG)

    def _draw_grid(self):
        _hline(self.bmp,self.BX,self.BX+self.BOARD_W-1,self.BY)
        _hline(self.bmp,self.BX,self.BX+self.BOARD_W-1,self.BY+self.BOARD_H-1)
        _vline(self.bmp,self.BX,self.BY,self.BY+self.BOARD_H-1)
        _vline(self.bmp,self.BX+self.BOARD_W-1,self.BY,self.BY+self.BOARD_H-1)
        for i in range(1,9):
            _vline(self.bmp,self.BX+i*(self.CELL+self.GRID),self.BY,self.BY+self.BOARD_H-1)
            _hline(self.bmp,self.BX,self.BX+self.BOARD_W-1,self.BY+i*(self.CELL+self.GRID))

    def _draw_visited(self):
        for y in range(8):
            for x in range(8):
                if self.visited[y][x]:
                    rx,ry,rw,rh=self._cell_rect(x,y)
                    _rect_fill(self.bmp,rx+1,ry+1,rw-2,rh-2,C_FG)

    def _draw_path(self):
        if len(self.path)<2: return
        x0,y0=self._cell_center(*self.path[0])
        for i in range(1,len(self.path)):
            x1,y1=self._cell_center(*self.path[i])
            _line(self.bmp,x0,y0,x1,y1,C_FG); x0,y0=x1,y1

    def _draw_current_and_legal(self):
        # Current "ring"
        cx,cy = self._current()
        rx,ry,rw,rh = self._cell_rect(cx,cy)
        ox,oy = rx+rw//2, ry+rh//2
        for dx in (-2,-1,0,1,2):
            if 0<=ox+dx<SCREEN_W and 0<=oy-2<SCREEN_H: self.bmp[ox+dx, oy-2] = C_FG
            if 0<=ox+dx<SCREEN_W and 0<=oy+ 2<SCREEN_H: self.bmp[ox+dx, oy+2] = C_FG
        for dy in (-1,0,1):
            if 0<=ox-2<SCREEN_W and 0<=oy+dy<SCREEN_H: self.bmp[ox-2, oy+dy] = C_FG
            if 0<=ox+2<SCREEN_W and 0<=oy+dy<SCREEN_H: self.bmp[ox+2, oy+dy] = C_FG

        # Legal moves: outline all; fill selected with tiny 2×2 hole
        for i, (mx, my) in enumerate(self.legal):
            rx, ry, rw, rh = self._cell_rect(mx, my)
            if i == self.sel_idx:
                _rect_fill(self.bmp, rx+1, ry+1, rw-2, rh-2, C_FG)
                cx2 = rx + rw//2; cy2 = ry + rh//2
                for yy in (cy2, cy2-1):
                    for xx in (cx2, cx2-1):
                        if 0 <= xx < SCREEN_W and 0 <= yy < SCREEN_H:
                            self.bmp[xx, yy] = C_BG
            _hline(self.bmp, rx, rx+rw-1, ry)
            _hline(self.bmp, rx, rx+rw-1, ry+rh-1)
            _vline(self.bmp, rx, ry, ry+rh-1)
            _vline(self.bmp, rx+rw-1, ry, ry+rh-1)

    def _redraw(self):
        self._clear(); self._draw_grid(); self._draw_path(); self._draw_visited(); self._draw_current_and_legal()
        _draw_hud(self.bmp, len(self.path), len(self.legal), self.hint_on)

    def _update_leds(self):
        sel = self.sel_idx if self.legal else 0
        self.leds.set(len(self.legal), clamp(sel,0,11), P1_COLOR)

    def _commit_selection(self):
        if not self.legal: self.sfx.stuck(); return
        nx,ny=self.legal[self.sel_idx]; self._push_move((nx,ny))
        if len(self.path)==64: self._update_leds(); self._redraw(); self.sfx.win(); return
        self._recompute_legal()
        if not self.legal: self.sfx.stuck()
        self._update_leds(); self._redraw()

    def _undo(self):
        if len(self.path)<=1: return
        self._pop_move(); self._recompute_legal(); self._update_leds(); self._redraw()

    def tick(self,dt=0.016): self.leds.update(dt)

    def button(self, k):
        # Restart (K9)
        if k == 9:
            self.new_game()
            return

        # Hint toggle (K10) — UI only; order remains clockwise
        if k == 10:
            self.hint_on = not self.hint_on
            self._apply_ui_overlay()
            self._redraw()
            return

        # Navigation
        if k == 3 and self.legal:  # Left
            self.sel_idx = (self.sel_idx - 1) % len(self.legal)
            self._update_leds(); self._redraw(); return
        if k == 5 and self.legal:  # Right
            self.sel_idx = (self.sel_idx + 1) % len(self.legal)
            self._update_leds(); self._redraw(); return
        if k == 7:  # Undo
            self._undo(); return

        # Commit (K11)
        if k == 11:
            self._commit_selection(); return

    def button_up(self, k): return

def create(*args,**kwargs): return knights_tour(*args,**kwargs)