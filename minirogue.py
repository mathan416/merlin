# ---------------------------------------------------------------------------
# minirogue.py — Merlin Rogue
# ---------------------------------------------------------------------------
# A compact roguelike adventure designed for the Merlin Launcher environment
# on the Adafruit MacroPad (CircuitPython 9.x, 128×64 monochrome OLED).
# Written by Iain Bennett — 2025
#
# Core Features:
#   • Randomly generated dungeon rooms with doors, walls, gold, monsters, and
#     the legendary Amulet (appears on depth 12).
#   • Player stats: HP (max 6), gold (score), and dungeon depth tracking.
#   • Turn-based combat:
#       - Player and monster attack chances, criticals, knockback, and damage.
#       - Gold pickup with chance to heal.
#       - Monster HP scales gently with depth.
#   • Victory achieved by collecting the Amulet; defeat occurs on HP = 0.
#   • Adaptive monster cadence (faster with depth, slower when player is low HP).
#
# Display & Input:
#   • Top 40px grid area with custom 5×5 ASCII-style glyphs (drawn into bitmap).
#   • Bottom HUD with centered text prompts (HP, gold, depth, messages).
#   • Title screen, in-game HUD, death screen, and victory screen with logo.
#   • Input cluster (keys K1/K3/K5/K7) moves the player in four directions.
#   • K9 acts as an “escape/restart” button to return to the title.
#
# LED Feedback:
#   • D-Pad LEDs show current HP with breathing effect when low.
#   • Gold count shown as up to 4 lit LEDs.
#   • Key 9 LED indicates active play (solid blue) or restart prompts (blinking).
#
# Implementation Notes:
#   • Uses defensive drawing (bitmaptools optional).
#   • Grid auto-sizes to fit 128×64 OLED with SCALE=1 (6×5 cell grid).
#   • Efficient incremental drawing: only touched cells are redrawn each turn.
#   • LED helper (_LedSmooth) prevents flicker by batching pixel updates.
#   • Self-contained: no external assets required except optional MerlinChrome.bmp.
#
# ---------------------------------------------------------------------------
# Controls (MacroPad key mapping):
#
#   ┌───────────────┐
#   │   K1          │   Move Up
#   │K3     K5      │   Move Left / Right
#   │   K7          │   Move Down
#   └───────────────┘
#
#   K9   → Escape / Restart (return to title)
#   Other keys unused in this game.
# ---------------------------------------------------------------------------

import time, math, random
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

# ---------- Screen & grid ----------
SCREEN_W, SCREEN_H = const(128), const(64)
PROMPT_Y1, PROMPT_Y2 = const(38), const(52)

# Tile IDs
T_EMPTY, T_WALL, T_DOOR, T_GOLD, T_AMULET = 0,1,2,3,4

# States
STATE_ENTRY, STATE_PLAY, STATE_DEAD, STATE_WIN = 0,1,2,3

# ---------- Balance tunables ----------
PLAYER_HIT = 0.85
PLAYER_CRIT = 0.10
PLAYER_DMG_MIN, PLAYER_DMG_MAX = 1, 2   # crit adds +1

MONSTER_HIT = 0.50
MONSTER_DMG_SCALE_DEPTH = 8             # at depth >= 8, monster can roll 1–2
GOLD_HEAL_CHANCE = 0.33                 # +1 HP (cap 6)
MON_HP_MAX = 4                          # monster HP clamp 2..4
VICTORY_DEPTH = 12                      # Amulet spawns on entering depth 12

def _cos01(t): return 0.5 - 0.5*math.cos(t)
def _scale_color(rgb, k):
    r=(rgb>>16)&0xFF; g=(rgb>>8)&0xFF; b=rgb&0xFF
    return (int(r*k)<<16)|(int(g*k)<<8)|int(b*k)

def _make_surface():
    bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
    pal = displayio.Palette(2); pal[0]=0x000000; pal[1]=0xFFFFFF
    g = displayio.Group()
    g.append(displayio.TileGrid(bmp, pixel_shader=pal))
    return g, bmp

# ---------- LED anti-flicker helper ----------
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
                self.px.brightness = 0.35
                for i in range(12): self.px[i] = 0x000000
                try: self.px.show()
                except Exception: pass
            except Exception:
                self.ok = False
    def set(self, i, color):
        if self.ok and 0 <= i < 12:
            self.buf[i] = int(color) & 0xFFFFFF
    def fill(self, color):
        if self.ok:
            c = int(color) & 0xFFFFFF
            for i in range(12): self.buf[i] = c
    def show(self, now=None):
        if not self.ok: return
        import time as _t
        t = now if (now is not None) else _t.monotonic()
        if (t - self._last_show) < self._min_dt:
            return
        changed = False
        for i, c in enumerate(self.buf):
            if c != self._last[i]:
                self.px[i] = c
                self._last[i] = c
                changed = True
        if changed:
            try: self.px.show()
            except Exception: pass
        self._last_show = t
    def off(self):
        if not self.ok: return
        for i in range(12):
            self.buf[i] = 0x000000
            self._last[i] = 0x111111
        self.show()
    def restore(self):
        if self.ok and hasattr(self.px, "auto_write"):
            try: self.px.auto_write = getattr(self, "_saved_auto", True)
            except Exception: pass

# ---------- Tiny ASCII glyphs (5x5), cell = 6x5, fits in 8 rows × 5px = 40px ----------
_GLYPHS = {
    " ": ("00000","00000","00000","00000","00000"),
    "#": ("11111","10001","11111","10001","11111"),
    "+": ("00100","00100","11111","00100","00100"),
    "$": ("01110","10100","01110","00101","11110"),
    "M": ("10001","11011","10101","10001","10001"),
    "@": ("01110","10001","10111","10101","01110"),
    "A": ("01110","10001","11111","10101","10101"),
}

_CELL_W, _CELL_H = const(6), const(5)
_GRID_X0, _GRID_Y0 = const(4), const(2)  # top-left of grid in pixels (within 0..39)

# Dynamically size the grid to fill the width (and fit in 40px tall area)
GRID_W = (SCREEN_W - 2*_GRID_X0) // _CELL_W          # as wide as the screen allows
GRID_H = (40 - _GRID_Y0) // _CELL_H                   # as tall as the top area allows

def _plot5x5(bmp, x, y, ch):
    pat = _GLYPHS.get(ch, _GLYPHS[" "])
    # Clear the 6x5 cell
    if _HAS_BT:
        try:
            bitmaptools.fill_region(bmp, x, y, _CELL_W, _CELL_H, 0)
        except Exception:
            for yy in range(_CELL_H):
                for xx in range(_CELL_W): bmp[x+xx, y+yy] = 0
    # Draw 5x5 pattern centered in 6x5 cell (1px left pad)
    for yy, row in enumerate(pat):
        for xx, bit in enumerate(row):
            if bit == "1":
                bmp[x+1+xx, y+yy] = 1

class minirogue:
    def __init__(self, macropad=None, *_tones, **_kwargs):
        self.macropad = macropad
        self.group, self.bmp = _make_surface()

        # ---- Logo (title screen) ----
        self._logo_tile = None
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile = displayio.TileGrid(
                bmp,
                pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            tile.hidden = True  # start hidden; show in STATE_ENTRY
            # Append behind labels so prompts stay readable.
            self.group.append(tile)
            self._logo_tile = tile
        except Exception:
            self._logo_tile = None

        # ---- Prompt labels only (grid is drawn into bitmap now) ----
        self.lbl1=self.lbl2=None
        if _HAVE_LABEL:
            self.lbl1 = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
            self.lbl2 = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
            # Center both labels
            self.lbl1.anchor_point = (0.5, 0.0)
            self.lbl2.anchor_point = (0.5, 0.0)
            self.lbl1.anchored_position = (SCREEN_W//2, PROMPT_Y1)
            self.lbl2.anchored_position = (SCREEN_W//2, PROMPT_Y2)
            self.group.append(self.lbl1)
            self.group.append(self.lbl2)

        self.led = _LedSmooth(self.macropad, limit_hz=30)
        self.new_game()

    # ---------- Audio / UI helpers ----------
    def _set_logo_visible(self, show: bool):
        if self._logo_tile is not None:
            try: self._logo_tile.hidden = not bool(show)
            except Exception: pass

    def _blip(self,f):
        if self.macropad and hasattr(self.macropad,"play_tone"):
            try: self.macropad.play_tone(int(f))
            except Exception: pass

    # ---------- Game lifecycle ----------
    def new_game(self):
        self.state=STATE_ENTRY
        self.hp=6
        self.gold=0
        self.depth=0                      # rooms cleared so far
        self._new_room()
        self.t0=time.monotonic()
        self._set_logo_visible(True)      # show logo on title
        self._draw()

    # ---------- Room generation ----------
    def _new_room(self):
        # build empty room
        g=[[T_EMPTY for _ in range(GRID_W)] for __ in range(GRID_H)]
        # borders
        for x in range(GRID_W): g[0][x]=g[GRID_H-1][x]=T_WALL
        for y in range(GRID_H): g[y][0]=g[y][GRID_W-1]=T_WALL

        reserved = set()  # tiles we must not overwrite

        if self.depth + 1 == VICTORY_DEPTH:
            # Final level: place Amulet in center
            ay, ax = GRID_H//2, GRID_W//2
            g[ay][ax] = T_AMULET
            reserved.add((ay, ax))
        else:
            # place a single door on a random side first (so walls can't overwrite it)
            midx, midy = GRID_W//2, GRID_H//2
            side = random.choice(("TOP","BOT","LFT","RGT"))
            if side=="TOP":
                dy,dx = 0, midx; in_y,in_x = 1, midx
            elif side=="BOT":
                dy,dx = GRID_H-1, midx; in_y,in_x = GRID_H-2, midx
            elif side=="LFT":
                dy,dx = midy, 0; in_y,in_x = midy, 1
            else: # "RGT"
                dy,dx = midy, GRID_W-1; in_y,in_x = midy, GRID_W-2
            g[dy][dx]=T_DOOR
            g[in_y][in_x]=T_EMPTY  # ensure just inside the door isn't blocked
            reserved.add((dy,dx)); reserved.add((in_y,in_x))

        # sprinkle internal walls (skip reserved tiles)
        for _ in range(random.randint(3,6)):
            y=random.randrange(1,GRID_H-1); x=random.randrange(1,GRID_W-1)
            if (y,x) not in reserved and g[y][x]==T_EMPTY:
                g[y][x]=T_WALL

        # sprinkle treasure (skip reserved tiles)
        for _ in range(random.randint(2,4)):
            y=random.randrange(1,GRID_H-1); x=random.randrange(1,GRID_W-1)
            if (y,x) not in reserved and g[y][x]==T_EMPTY:
                g[y][x]=T_GOLD

        self.grid=g

        # player & monster
        self.py,self.px=GRID_H//2,GRID_W//2
        # find a spawn that isn't reserved
        while True:
            my,mx=random.randrange(1,GRID_H-1),random.randrange(1,GRID_W-1)
            if self.grid[my][mx]==T_EMPTY and (my,mx) not in reserved and not (my==self.py and mx==self.px):
                self.mon=[my,mx]; break

        # monster HP scales gently with depth (clamped 2..4)
        base = 2 + self.depth // 4
        self.mon_hp = max(2, min(MON_HP_MAX, base))

        # Draw the whole room once (then incremental updates only)
        self._redraw_room_full()

    # ---------- Drawing helpers (incremental) ----------
    def _cell_char(self, gy, gx):
        if [gy,gx]==self.mon and self.mon_hp>0:
            return "M"
        if gy==self.py and gx==self.px:
            return "@"
        t = self.grid[gy][gx]
        if t==T_EMPTY:  return " "
        if t==T_WALL:   return "#"
        if t==T_DOOR:   return "+"
        if t==T_GOLD:   return "$"
        if t==T_AMULET: return "A"
        return " "

    def _plot_cell(self, gy, gx):
        if not (0 <= gy < GRID_H and 0 <= gx < GRID_W): return
        _plot5x5(
            self.bmp,
            _GRID_X0 + gx*_CELL_W,
            _GRID_Y0 + gy*_CELL_H,
            self._cell_char(gy, gx)
        )

    def _clear_grid_area(self):
        # Clear the grid area (top 40 px)
        if _HAS_BT:
            try:
                bitmaptools.fill_region(self.bmp, 0, 0, SCREEN_W, 40, 0)
                return
            except Exception:
                pass
        for yy in range(40):
            for xx in range(SCREEN_W): self.bmp[xx, yy] = 0

    def _redraw_room_full(self):
        # Clear then draw all cells (on room entry / restart only)
        self._clear_grid_area()
        for gy in range(GRID_H):
            for gx in range(GRID_W):
                self._plot_cell(gy, gx)

    # ---------- HUD / LEDs ----------
    def _refresh_hud(self):
        if not _HAVE_LABEL: return
        if self.state==STATE_ENTRY:
            self.lbl1.text="Merlin Rogue"
            self.lbl2.text="Press to begin"
        elif self.state==STATE_PLAY:
            self.lbl1.text=""  # keep top prompt empty during play
            self.lbl2.text="HP:{}  G:{}  D:{}/{}".format(self.hp,self.gold,self.depth,VICTORY_DEPTH)
        elif self.state==STATE_WIN:
            self.lbl1.text="You got the Amulet!"
            self.lbl2.text="Press to restart"
        else:  # STATE_DEAD
            self.lbl1.text="You fell in battle"
            self.lbl2.text="Press to restart"

    def _draw_leds(self):
        # clear all first
        self.led.fill(0x000000)

        # --- HP color for the D-Pad (K1 up, K7 down, K3 left, K5 right) ---
        hp=max(0,min(6,self.hp))
        # breathing when low HP
        t=(time.monotonic()-self.t0)%1.2
        k=0.4+0.6*_cos01(t/1.2) if hp<=2 else 1.0
        col = 0x00FF40 if hp>=5 else (0xFFA000 if hp>=3 else 0xFF4020)
        col=_scale_color(col,k)
        for i in (1,7,3,5):
            self.led.set(i, col)

        # --- Gold pips on K0, K2, K6, K8 ---
        pips = min(4, self.gold)
        gold_slots = (0,2,6,8)
        for idx, key in enumerate(gold_slots):
            self.led.set(key, 0xFFFFFF if idx < pips else 0x000000)

        # --- Escape / Restart key (K9) ---
        if self.state == STATE_PLAY:
            # solid blue while playing
            self.led.set(9, 0x2020FF)
        elif self.state in (STATE_DEAD, STATE_WIN):
            # blink blue every ~0.5s
            blink = int(time.monotonic() * 2) & 1
            if blink:
                self.led.set(9, 0x2020FF)

        self.led.show()

    def _draw(self):
        # In PLAY, we don't touch the grid (incremental updates handle it)
        # In other states, clear grid area so no room shows under prompts
        if self.state != STATE_PLAY:
            self._clear_grid_area()
        self._refresh_hud()
        self._draw_leds()

    # ---------- Combat helpers ----------
    def _rand(self, a, b):
        return int(a + random.random() * (b - a + 1))

    def _try_knockback(self, from_y, from_x, to_y, to_x):
        dy = to_y - from_y; dx = to_x - from_x
        sy = 1 if dy>0 else (-1 if dy<0 else 0)
        sx = 1 if dx>0 else (-1 if dx<0 else 0)
        ky, kx = to_y + sy, to_x + sx
        if 0 < ky < GRID_H-1 and 0 < kx < GRID_W-1 and self.grid[ky][kx] != T_WALL:
            self.mon = [ky, kx]
            # repaint old and new monster cells
            self._plot_cell(to_y, to_x)
            self._plot_cell(ky, kx)

    def _player_attack(self):
        if self.mon_hp <= 0: return False
        if random.random() <= PLAYER_HIT:
            dmg = self._rand(PLAYER_DMG_MIN, PLAYER_DMG_MAX)
            crit = (random.random() <= PLAYER_CRIT)
            if crit: dmg += 1
            self.mon_hp -= dmg
            self._blip(660 if not crit else 784)
            if crit:
                self._try_knockback(self.py, self.px, self.mon[0], self.mon[1])
            if self.mon_hp <= 0:
                # reward on kill
                self.gold += 1
                self._blip(880)
                # erase monster cell now that it's gone
                omy, omx = self.mon
                self.mon = [-1, -1]
                self._plot_cell(omy, omx)
                return True
        else:
            self._blip(180)  # miss thunk
        return False

    def _monster_attack(self):
        if self.state != STATE_PLAY or self.hp <= 0: return
        if random.random() <= MONSTER_HIT:
            hi = 1 if (self.depth < MONSTER_DMG_SCALE_DEPTH) else 2
            dmg = self._rand(1, hi)
            self.hp -= dmg
            self._blip(220)
            if self.hp <= 0:
                self.state = STATE_DEAD
        # HUD/LEDs can change after damage
        self._refresh_hud()
        self._draw_leds()

    # ----- Mechanics -----
    def _move_player(self, dx, dy):
        if self.state!=STATE_PLAY: return
        nx,ny=self.px+dx,self.py+dy
        if not (0<=nx<GRID_W and 0<=ny<GRID_H): return
        t=self.grid[ny][nx]
        if t==T_WALL: return

        opx,opy = self.px,self.py  # remember old player cell

        if t==T_GOLD:
            self.gold+=1; self.grid[ny][nx]=T_EMPTY
            if random.random() < GOLD_HEAL_CHANCE and self.hp < 6:
                self.hp += 1
                self._blip(988)
            else:
                self._blip(523)
        elif t==T_DOOR:
            self.depth += 1
            self._blip(392)
            # Enter next room; if it's the final room, it will contain the Amulet
            self._new_room()
            self.state=STATE_PLAY
            self._refresh_hud()
            self._draw_leds()
            return
        elif t==T_AMULET:
            # Win on pickup
            self._blip(1047)  # celebratory tone
            self.state = STATE_WIN
            self._set_logo_visible(False)
            self._refresh_hud()
            self._draw_leds()
            return

        # commit move
        self.px,self.py=nx,ny
        # repaint only the two player-related cells
        self._plot_cell(opy, opx)    # old cell now shows what's underneath
        self._plot_cell(ny, nx)      # new cell shows '@' (or 'M' if overlapped)

        # bump into monster => attack; surviving monster may counterattack
        if [self.py,self.px]==self.mon and self.mon_hp>0:
            killed = self._player_attack()
            if not killed and self.mon_hp>0:
                self._monster_attack()
        else:
            # if not engaging, monster gets a chase step after our move
            self._move_monster()

        self._refresh_hud()
        self._draw_leds()

    def _move_monster(self):
        if self.state!=STATE_PLAY or self.mon_hp<=0: return
        if self.mon[0] < 0: return  # removed
        omy, omx = self.mon[0], self.mon[1]

        dy = 1 if self.py>self.mon[0] else (-1 if self.py<self.mon[0] else 0)
        dx = 1 if self.px>self.mon[1] else (-1 if self.px<self.mon[1] else 0)
        if random.random()<0.5: dx,dy=dy,dx
        ny=max(1,min(GRID_H-2,self.mon[0]+dy))
        nx=max(1,min(GRID_W-2,self.mon[1]+dx))
        if self.grid[ny][nx]!=T_WALL:
            self.mon=[ny,nx]
            # repaint only old and new monster cells
            self._plot_cell(omy, omx)
            self._plot_cell(ny, nx)

        if [self.py,self.px]==self.mon:
            self._monster_attack()

    # ---------- Adaptive monster cadence ----------
    def _monster_period(self):
        # Base cadence
        base = 0.90
        # Deeper = faster (cap total -0.45s)
        base -= min(0.45, self.depth * 0.05)
        # Low HP relief: slow monsters when you're hurting
        if self.hp <= 2:
            base += 0.60
        elif self.hp <= 3:
            base += 0.30
        # Safety clamp
        return max(0.25, base)

    def tick(self, dt=0.016):
        if self.state==STATE_PLAY:
            now=time.monotonic()
            period = self._monster_period()
            if now - getattr(self,"_tmon",0.0) > period:
                self._tmon=now; self._move_monster()
        else:
            self._draw_leds()

    def button(self, key, pressed=True):
        if not pressed:
            return

        # K9: jump back to title screen immediately (from any non-title state)
        if key == 9 and self.state != STATE_ENTRY:
            self.state = STATE_ENTRY
            self._set_logo_visible(True)
            self._draw()            # clears grid area, updates HUD/LEDs
            return

        # --- State-specific input handling ---
        if self.state == STATE_ENTRY:
            # START RUN: do NOT call new_game() here.
            # Room already exists in memory; just switch to play and paint it once.
            self.state = STATE_PLAY
            self._set_logo_visible(False)
            self._redraw_room_full()        # draw the room now that title is gone
            self._blip(330 if self.hp > 0 else 294)
            self._draw()                    # HUD/LEDs only; grid already painted
            return

        if self.state in (STATE_DEAD, STATE_WIN):
            # After an ended run, first press should reset to TITLE (not auto-start).
            self.new_game()                 # resets to STATE_ENTRY and draws title
            return

        # STATE_PLAY: movement cluster
        if key == 1:      self._move_player(0, -1)   # up
        elif key == 7:    self._move_player(0,  1)   # down
        elif key == 3:    self._move_player(-1, 0)   # left
        elif key == 5:    self._move_player(1,  0)   # right

    def cleanup(self):
        try:
            self._set_logo_visible(False)
        except Exception:
            pass
        try:
            self.led.off()
            self.led.restore()
        except Exception:
            pass