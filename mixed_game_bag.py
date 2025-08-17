# mix_bag.py — Mix Game Bag (Breakout + Invaders) for Merlin Launcher
# CircuitPython 9.x / Adafruit MacroPad
#
# Inspired by the Timex Sinclair 1000 / Sinclair ZX81 — my very first computer.
# Back then, we coded our own starfields, mazes, and even crude games on tiny
# monochrome displays: green screen, amber screen, or just stark black-and-white.
# The MacroPad’s sharp 128×64 OLED may be far beyond that, but the spirit here
# is the same — minimalist graphics, punchy motion, and imagination filling in
# the rest.
#
# The name “Mixed Game Bag” is also a nod to three cassette game packs sold for the
# Sinclair: *Mixed Game Bag 1, 2 and 3*. They were collections of
# simple titles — a bingo number generator, Robot Wars, Bowling, and others —
# that loaded painfully slowly from tape. Anyone who lived through it remembers
# the notorious 16K RAM Pack wobble that could crash everything, or the 10-minute
# load of Frogger that might abort if someone bumped the machine!
#
# # In a perfect homage to those days, this game uses 15,872 bytes of memory out of 
# 16,384 leaving 512 bytes free.  That's cutting it close!
#
# Controls
#   Menu:    Rotate encoder to select; single press starts after a short window
#            (double-press within the window is reserved for the launcher).
#   In Game: Single press returns to the menu.
#   Breakout: K3/K5 move, K7 launch (and restart when ended)
#   Invaders: K3/K5 move, K7 fire (and restart when ended)
#
# LEDs
#   In games: K3/K5 green (move), K7 red (fire/launch). Off in menu.
#
# Date: 2025-08-15
# Author: Iain Bennett (adapted for MacroPad Battleship)

import time, math, random
import displayio, terminalio
from adafruit_display_text import label

# ---------- Display ----------
SCREEN_W, SCREEN_H = 128, 64

# ---------- Keys (0..11) ----------
K_LEFT  = 3
K_RIGHT = 5
K_FIRE  = 7

# ---------- Tunables ----------
# Global
WAVES_TO_WIN    = 3      # waves to clear to "win" a session
DOUBLE_PRESS_WINDOW = 0.35  # seconds to wait for a potential double-press in menu
# Breakout
BALL_SPEED_INIT = 0.80   # initial ball speed magnitude
BALL_SPEED_INC  = 0.20   # per-wave increment
BALL_SPEED_MAX  = 2.20   # cap
PADDLE_SPEED    = 3      # px/tick
# Invaders
INV_PADDLE_SPEED = 2     # px/tick
SHOT_W, SHOT_H   = 2, 4  # bullet footprint for XOR draw


# ---------- Helpers ----------
def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)

def make_surface():
    bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
    pal = displayio.Palette(2)
    pal[0] = 0x000000
    pal[1] = 0xFFFFFF
    return bmp, pal

def clear(bmp):
    try: bmp.fill(0)
    except AttributeError:
        for y in range(SCREEN_H):
            for x in range(SCREEN_W):
                bmp[x, y] = 0

def hline(bmp, x0, x1, y, c=1):
    if y < 0 or y >= SCREEN_H: return
    if x0 > x1: x0, x1 = x1, x0
    x0 = max(0, min(SCREEN_W-1, x0))
    x1 = max(0, min(SCREEN_W-1, x1))
    for x in range(x0, x1+1):
        bmp[x, y] = c

def rect(bmp, x, y, w, h, c=1):
    x2, y2 = x + w, y + h
    for yy in range(y, y2):
        if 0 <= yy < SCREEN_H:
            for xx in range(x, x2):
                if 0 <= xx < SCREEN_W:
                    bmp[xx, yy] = c

def xor_rect(bmp, x, y, w, h):
    x2, y2 = x + w, y + h
    for yy in range(y, y2):
        if 0 <= yy < SCREEN_H:
            for xx in range(x, x2):
                if 0 <= xx < SCREEN_W:
                    bmp[xx, yy] ^= 1  # flip 0<->1

def text_label(txt, y, anchor_x=0.5):
    return label.Label(
        terminalio.FONT, text=txt, color=0xFFFFFF,
        anchor_point=(anchor_x, 0.0),
        anchored_position=(int(SCREEN_W*anchor_x), y)
    )

# =========================================================
# Breakout (dirty-rect)
# =========================================================
class BreakoutGame:
    def __init__(self):
        self.w, self.h = SCREEN_W, SCREEN_H
        self.pw, self.ph = 20, 3
        self.px, self.py = (self.w - self.pw)//2, self.h - 8

        self.bx, self.by = self.w//2, self.py - 4
        self.bvx, self.bvy = 0.0, 0.0
        self.ball_speed = BALL_SPEED_INIT  # constantized

        self.brick_w, self.brick_h = 12, 5
        self.cols, self.rows = self.w // (self.brick_w + 1), 4
        self.bricks = set()

        self.wave = 1
        self.lives, self.score = 3, 0
        self.game_over = False
        self.win = False

        # dirty-rect bookkeeping
        self.last_removed = None
        self._prev_ball = None
        self._prev_paddle = None

        self.bg_dirty = False 
        self.reset_bricks()

    def reset_bricks(self):
        self.bricks.clear()
        margin_x = (self.w - self.cols*(self.brick_w+1)+1)//2
        for r in range(self.rows):
            for c in range(self.cols):
                x = margin_x + c*(self.brick_w+1)
                y = 10 + r*(self.brick_h+2)
                self.bricks.add((x, y))
        self.bg_dirty = True

    def draw_static_bg(self, bmp):
        for (x, y) in self.bricks:
            rect(bmp, x, y, self.brick_w, self.brick_h, 1)

    def _paddle_rect(self, px=None):
        if px is None: px = self.px
        return (int(px), self.py, self.pw, self.ph)

    def _ball_rect(self, bx=None, by=None):
        if bx is None: bx = self.bx
        if by is None: by = self.by
        return (int(bx)-1, int(by)-1, 3, 3)

    def launch(self):
        if self.bvy == 0 and self.lives > 0 and not (self.game_over or self.win):
            ang = math.radians(random.choice([60, 70, 110, 120]))
            self.bvx = self.ball_speed * math.cos(ang)
            self.bvy = -abs(self.ball_speed * math.sin(ang))

    def _stick_ball_to_paddle(self):
        self.bvx = 0.0
        self.bvy = 0.0
        self.bx = self.px + self.pw//2
        self.by = self.py - 4

    def step(self, left, right):
        if self.game_over or self.win:
            return

        if left:  self.px -= PADDLE_SPEED
        if right: self.px += PADDLE_SPEED
        self.px = clamp(self.px, 0, self.w - self.pw)

        self.last_removed = None

        if self.lives <= 0:
            self.game_over = True
            self._stick_ball_to_paddle()
            return

        if self.bvy == 0:
            self._stick_ball_to_paddle()
            return

        self.bx += self.bvx
        self.by += self.bvy

        # walls
        if self.bx <= 1 or self.bx >= self.w-2:
            self.bvx = -self.bvx
            self.bx = clamp(self.bx, 1, self.w-2)
        if self.by <= 10:
            self.bvy = -self.bvy
            self.by = 10
        if self.by > self.h:
            self.lives -= 1
            self._stick_ball_to_paddle()
            return

        # paddle
        if (self.py-3 <= self.by <= self.py) and (self.px-2 <= self.bx <= self.px+self.pw+2) and self.bvy > 0:
            self.bvy = -abs(self.bvy)
            hit = (self.bx - (self.px + self.pw/2)) / (self.pw/2)
            self.bvx = clamp(self.bvx + 0.4*hit, -1.8, 1.8)
            if self.bvy < 0:
                self.by = min(self.by, self.py - 3)
            self.bx = clamp(self.bx, self.px - 1, self.px + self.pw + 1)

        # bricks
        hit = None
        for (x, y) in self.bricks:
            if (x-1 <= self.bx <= x+self.brick_w+1) and (y-1 <= self.by <= y+self.brick_h+1):
                hit = (x, y); break
        if hit:
            self.bricks.remove(hit)
            self.score += 10
            self.bvy = -self.bvy
            self.last_removed = hit

        # wave / win
        if not self.bricks:
            if self.wave >= WAVES_TO_WIN:
                self.win = True
                self._stick_ball_to_paddle()
            else:
                self.wave += 1
                self.ball_speed = min(self.ball_speed + BALL_SPEED_INC, BALL_SPEED_MAX)
                self.reset_bricks()
                self._stick_ball_to_paddle()

# =========================================================
# Invaders (dirty-rects for paddle/aliens; XOR bullets)
# =========================================================
class InvadersGame:
    def __init__(self):
        self.w, self.h = SCREEN_W, SCREEN_H
        self.pw, self.ph = 10, 3
        self.px, self.py = (self.w - self.pw)//2, self.h - 9
        self.cols, self.rows = 5, 2        # two rows
        self.iv_w, self.iv_h = 8, 5
        self.iv_dx, self.iv_dt = 1, 0.17
        self._last_step = time.monotonic()
        self.iv_set = set()
        self.shots, self.enemy_shots = [], []
        self.cooldown, self.score = 0.0, 0
        self.lives = 3
        self.game_over = False
        self.win = False
        self.wave = 1

        self._spawn_invaders()

    def _spawn_invaders(self):
        self.iv_set.clear()
        margin_x, margin_y, gap_x, gap_y = 8, 14, 7, 4
        for r in range(self.rows):
            for c in range(self.cols):
                x = margin_x + c*(self.iv_w+gap_x)
                y = margin_y + r*(self.iv_h+gap_y)
                self.iv_set.add((x, y))
        self.iv_dx = 1
        self._last_step = time.monotonic()

    def _paddle_rect(self, px=None):
        if px is None: px = self.px
        return (int(px), self.py, self.pw, self.ph)

    def _invader_rects(self):
        w, h = self.iv_w, self.iv_h
        return [(x, y, w, h) for (x, y) in self.iv_set]

    def fire(self):
        if self.game_over or self.win:
            return
        now = time.monotonic()
        if now >= self.cooldown:
            self.cooldown = now + 0.18
            self.shots.append((int(self.px + self.pw//2), self.py-2))

    def _lose_life(self):
        self.lives -= 1
        if self.lives <= 0:
            self.game_over = True
        # center paddle and clear shots for clarity
        self.px = (self.w - self.pw)//2
        self.shots.clear()
        self.enemy_shots.clear()

    def step(self, left, right):
        if self.game_over or self.win:
            return

        if left:  self.px -= INV_PADDLE_SPEED
        if right: self.px += INV_PADDLE_SPEED
        self.px = clamp(self.px, 0, self.w - self.pw)

        now = time.monotonic()
        if now - self._last_step >= self.iv_dt:
            self._last_step = now
            if self.iv_set:
                minx = min(x for (x, _) in self.iv_set)
                maxx = max(x+self.iv_w for (x, _) in self.iv_set)
                if minx <= 1 and self.iv_dx < 0:
                    self.iv_dx = 1; self.iv_set = {(x, y+4) for (x, y) in self.iv_set}
                elif maxx >= self.w-1 and self.iv_dx > 0:
                    self.iv_dx = -1; self.iv_set = {(x, y+4) for (x, y) in self.iv_set}
                else:
                    self.iv_set = {(x+self.iv_dx, y) for (x, y) in self.iv_set}

                # random enemy fire
                if random.random() < 0.35:
                    idx = random.randrange(len(self.iv_set))
                    for i, (ex, ey) in enumerate(self.iv_set):
                        if i == idx:
                            self.enemy_shots.append((ex + self.iv_w//2, ey + self.iv_h + 1))
                            break

                # speedup as they thin out
                count = len(self.iv_set)
                self.iv_dt = max(0.07, 0.17 - (0.17-0.09)*(1 - count/max(1, self.cols*self.rows)))

        # move shots (positions only)
        self.shots       = [(x, y-3) for (x, y) in self.shots if y > -4]
        self.enemy_shots = [(x, y+2) for (x, y) in self.enemy_shots if y < self.h+4]

        # player hit?
        for (x, y) in list(self.enemy_shots):
            if (self.py-2 <= y <= self.py+self.ph) and (self.px-1 <= x <= self.px+self.pw+1):
                self._lose_life()
                break

        # invaders hit
        new_inv, new_shots = set(self.iv_set), []
        for (sx, sy) in self.shots:
            hit = None
            for (ix, iy) in new_inv:
                if (ix-1 <= sx <= ix+self.iv_w+1) and (iy-1 <= sy <= iy+self.iv_h+1):
                    hit = (ix, iy); break
            if hit:
                new_inv.remove(hit); self.score += 5
            else:
                new_shots.append((sx, sy))
        self.iv_set  = new_inv
        self.shots   = new_shots

        # ground reached? (instant game over)
        if any(iy + self.iv_h >= self.py for (_, iy) in self.iv_set):
            self.game_over = True

        # wave / win
        if not self.iv_set and not self.game_over:
            if self.wave >= WAVES_TO_WIN:
                self.win = True
                self.shots.clear()
                self.enemy_shots.clear()
            else:
                self.wave += 1
                self.iv_dt = max(0.06, self.iv_dt * 0.92)
                self._spawn_invaders()

# =========================================================
# Wrapper with encoder-driven mini menu
# =========================================================
class mix_bag:
    def __init__(self, macropad, *_, **__):
        self.supports_double_encoder_exit = True
        self.macropad = macropad
        self.group = displayio.Group()
        self.bmp, self.pal = make_surface()
        self.tile = displayio.TileGrid(self.bmp, pixel_shader=self.pal)
        self.group.append(self.tile)

        # Menu screen starts blank; divider is drawn in new_game()
        clear(self.bmp)

        # Title label
        self.title = text_label("Mix Game Bag", 1)
        self.group.append(self.title)

        # Menu labels
        self.menu_lbl   = text_label("Select:", 18, anchor_x=0.0)
        self.choice_lbl = text_label("Breakout", 30)
        self.hint_lbl   = text_label("", 46)
        self.group.append(self.menu_lbl)
        self.group.append(self.choice_lbl)
        self.group.append(self.hint_lbl)

        # HUD created, added on enter
        self.hud = text_label("", 1)
        self._hud_last = None

        self._menu_items = ("Breakout", "Invaders")
        self._menu_index = 0
        self.state = "menu"
        self.game = None
        self._left = self._right = False
        self._fire_pending = False
        self._last_frame = 0.0

        # Breakout caches
        self._bo_prev_ball = None
        self._bo_prev_pad  = None

        # Invaders caches (paddle/aliens only; bullets use XOR)
        self._inv_prev_pad = None
        self._inv_prev_inv = []

        # LED colors
        self.COL_OFF  = (0, 0, 0)
        self.COL_MOVE = (0, 25, 0)   # K3/K5 movement = green
        self.COL_FIRE = (40, 0, 0)   # K7 fire = red
        self._enc_pending_at = 0.0
        self._menu_press_t = None
        self._led_all_off()

    # ---------- LED helpers ----------
    def _led_set(self, idx, col):
        try:
            self.macropad.pixels[idx] = col
            self.macropad.pixels.show()
        except Exception:
            pass

    def _led_all_off(self):
        try:
            for i in range(len(self.macropad.pixels)):
                self.macropad.pixels[i] = self.COL_OFF
            self.macropad.pixels.show()
        except Exception:
            pass

    def _set_menu_lights(self):
        self._led_all_off()

    def _set_breakout_lights(self):
        self._led_all_off()
        self._led_set(K_LEFT,  self.COL_MOVE)
        self._led_set(K_RIGHT, self.COL_MOVE)
        self._led_set(K_FIRE,  self.COL_FIRE)

    def _set_invaders_lights(self):
        self._led_all_off()
        self._led_set(K_LEFT,  self.COL_MOVE)
        self._led_set(K_RIGHT, self.COL_MOVE)
        self._led_set(K_FIRE,  self.COL_FIRE)

    # ---------- HUD ----------
    def _set_hud(self, s: str):
        if s != self._hud_last:
            self.hud.text = s
            self._hud_last = s

    def new_game(self):
        clear(self.bmp)
        hline(self.bmp, 0, SCREEN_W-1, 12, 1)
        self.choice_lbl.text = self._menu_items[self._menu_index]
        self._set_menu_lights()
        self._menu_press_t = None   # ← add this line
        try: self.macropad.display.auto_refresh = True
        except Exception: pass

    def encoderChange(self, pos, last_pos):
        if self.state != "menu" or pos == last_pos: return
        self._menu_index = pos % len(self._menu_items)
        self.choice_lbl.text = self._menu_items[self._menu_index]

    def encoder_button(self, pressed):
        # In menu: single press (after window) starts game; double-press goes to launcher (handled by launcher)
        # In game: single press returns to menu
        if not pressed:
            return

        now = time.monotonic()
        if self.state == "menu":
            if self._menu_press_t is None:
                # first press: arm and wait to see if it's a double
                self._menu_press_t = now
                return
            # second press within window -> treat as double (do NOT start a game)
            if (now - self._menu_press_t) <= DOUBLE_PRESS_WINDOW:
                self._menu_press_t = None  # clear; launcher will handle exiting
                return
            # if it’s outside the window, treat this as a new first press
            self._menu_press_t = now
            return
        else:
            # in a game: single press returns to menu immediately
            self._to_menu()

    def _to_menu(self):
        try: self.macropad.display.auto_refresh = False
        except Exception: pass

        clear(self.bmp)
        for w in (self.title, self.menu_lbl, self.choice_lbl, self.hint_lbl):
            if w not in self.group:
                self.group.append(w)
        # hide HUD in menu
        try:
            if self.hud in self.group:
                self.group.remove(self.hud)
        except Exception:
            pass

        hline(self.bmp, 0, SCREEN_W - 1, 12, 1)
        self.choice_lbl.text = self._menu_items[self._menu_index]

        # --- add these resets ---
        self.state = "menu"
        self.game = None
        self._left = False
        self._right = False
        self._fire_pending = False
        self._bo_prev_ball = None
        self._bo_prev_pad = None
        self._inv_prev_pad = None
        self._inv_prev_inv = []
        self._menu_press_t = None
        # ------------------------

        self._set_menu_lights()

        try:
            self.macropad.display.refresh(minimum_frames_per_second=0)
            self.macropad.display.auto_refresh = True
        except Exception:
            pass

    def _enter(self, which_name):
        # remove menu labels
        for w in (self.menu_lbl, self.choice_lbl, self.hint_lbl, self.title):
            try: self.group.remove(w)
            except Exception: pass

        if self.hud not in self.group: self.group.append(self.hud)

        try: self.macropad.display.auto_refresh = False
        except Exception: pass

        # Ensure the menu divider is gone when gameplay begins
        clear(self.bmp)

        self.state = "breakout" if which_name == "Breakout" else "invaders"

        if self.state == "breakout":
            self.game = BreakoutGame()
            self.game.draw_static_bg(self.bmp)
            px, py, pw, ph = self.game._paddle_rect()
            rect(self.bmp, px, py, pw, ph, 1)
            bx, by, bw, bh = self.game._ball_rect()
            rect(self.bmp, bx, by, bw, bh, 1)
            self._bo_prev_pad  = (px, py, pw, ph)
            self._bo_prev_ball = (bx, by, bw, bh)
            self._set_hud("Score 0   Lives 3")
            self._set_breakout_lights()
        else:
            self.game = InvadersGame()
            hline(self.bmp, 0, SCREEN_W-1, 12, 1)  # ground line for Invaders
            pad = self.game._paddle_rect()
            rect(self.bmp, *pad, 1)
            inv = self.game._invader_rects()
            for r in inv: rect(self.bmp, *r, 1)
            self._inv_prev_pad = pad
            self._inv_prev_inv = inv
            self._set_hud("Score:0   Lives:3")
            self._set_invaders_lights()

        try: self.macropad.display.refresh(minimum_frames_per_second=0)
        except Exception: pass

    def _draw_hud(self):
        if isinstance(self.game, BreakoutGame):
            if self.game.win or self.game.game_over:
                tag = "  You Win!" if self.game.win else "You Lose!"
                self._set_hud(f"Score:{self.game.score}   {tag}")
            else:
                self._set_hud(f"Score:{self.game.score}   Lives:{self.game.lives}")
        elif isinstance(self.game, InvadersGame):
            if self.game.win or self.game.game_over:
                tag = "  You Win!" if self.game.win else "You Lose!"
                self._set_hud(f"Score:{self.game.score}   {tag}")
            else:
                self._set_hud(f"Score:{self.game.score}   Lives:{self.game.lives}")

    # ---------- Breakout delta draw ----------
    def _breakout_draw_delta(self):
        g = self.game

        # NEW: full background redraw when a new wave starts (or bricks were rebuilt)
        if getattr(g, "bg_dirty", False):
            clear(self.bmp)
            g.draw_static_bg(self.bmp)
            g.bg_dirty = False
            self._bo_prev_pad  = None
            self._bo_prev_ball = None

        # existing partial erases
        if self._bo_prev_pad:  rect(self.bmp, *self._bo_prev_pad, 0)
        if self._bo_prev_ball: rect(self.bmp, *self._bo_prev_ball, 0)

        if g.last_removed:
            bx, by = g.last_removed
            rect(self.bmp, bx, by, g.brick_w, g.brick_h, 0)

        p = g._paddle_rect(); rect(self.bmp, *p, 1)
        b = g._ball_rect();   rect(self.bmp, *b, 1)
        self._bo_prev_pad  = p
        self._bo_prev_ball = b

    # ---------- Invaders delta draw (XOR bullets) ----------
    def _invaders_draw_delta(self, prev_ps, prev_es):
        g = self.game

        # erase previous paddle & invaders (solid erase)
        if self._inv_prev_pad: rect(self.bmp, *self._inv_prev_pad, 0)
        for r in self._inv_prev_inv: rect(self.bmp, *r, 0)

        # erase previous bullets by XORing their old footprints
        for (x, y) in prev_ps: xor_rect(self.bmp, x-1, y-2, SHOT_W, SHOT_H)
        for (x, y) in prev_es: xor_rect(self.bmp, x-1, y-2, SHOT_W, SHOT_H)

        # draw new paddle & invaders
        pad = g._paddle_rect()
        rect(self.bmp, *pad, 1)
        inv = g._invader_rects()
        for r in inv: rect(self.bmp, *r, 1)

        # draw horizon BEFORE bullets so bullets appear "on top"
        hline(self.bmp, 0, SCREEN_W-1, 12, 1)

        # draw new bullets by XOR (so they erase themselves next frame)
        if not (g.game_over or g.win):
            for (x, y) in g.shots:       xor_rect(self.bmp, x-1, y-2, SHOT_W, SHOT_H)
            for (x, y) in g.enemy_shots: xor_rect(self.bmp, x-1, y-2, SHOT_W, SHOT_H)
        else:
            g.shots.clear(); g.enemy_shots.clear()

        # cache for next frame
        self._inv_prev_pad = pad
        self._inv_prev_inv = inv

    def _restart_current(self):
        which = "Breakout" if self.state == "breakout" else "Invaders"
        self._enter(which)

    def tick(self):
        now = time.monotonic()
        if now - self._last_frame < 0.016:
            return
        self._last_frame = now

        # Handle "single press in menu" after waiting for double-press window
        if self.state == "menu" and self._menu_press_t is not None:
            if (now - self._menu_press_t) > DOUBLE_PRESS_WINDOW:
                self._menu_press_t = None
                self._enter(self._menu_items[self._menu_index])
                return  # we've just transitioned into a game

        if self.state == "menu" or self.game is None:
            return

        # ---------- Breakout ----------
        if isinstance(self.game, BreakoutGame):
            self.game.step(self._left, self._right)
            if self._fire_pending:
                self.game.launch()
            self._fire_pending = False

            self._breakout_draw_delta()
            self._draw_hud()
            try:
                self.macropad.display.refresh(minimum_frames_per_second=0)
            except Exception:
                pass

        # ---------- Invaders ----------
        else:
            prev_ps = list(self.game.shots)
            prev_es = list(self.game.enemy_shots)

            self.game.step(self._left, self._right)
            if self._fire_pending:
                self.game.fire()
            self._fire_pending = False

            self._invaders_draw_delta(prev_ps, prev_es)
            self._draw_hud()
            try:
                self.macropad.display.refresh(minimum_frames_per_second=0)
            except Exception:
                pass

    def button(self, key):
        if self.state == "menu": return
        # restart on Fire if ended
        if key == K_FIRE and self.game and (getattr(self.game, "game_over", False) or getattr(self.game, "win", False)):
            self._restart_current()
            return
        if key == K_LEFT:   self._left = True
        elif key == K_RIGHT:self._right = True
        elif key == K_FIRE: self._fire_pending = True

    def button_up(self, key):
        if key == K_LEFT:   self._left = False
        elif key == K_RIGHT:self._right = False

    # ---- double-press exit hints (launcher calls these) ----
    def on_exit_hint(self):
        self._enc_pending_at = 0.0
        if self.state != "menu":
            s = self._hud_last or self.hud.text or ""
            if "Press again to exit" not in s:
                #self._set_hud((s + "  (Press again to exit)").strip())
                try: self.macropad.display.refresh(minimum_frames_per_second=0)
                except Exception: pass

    def on_exit_hint_clear(self):
        self._enc_pending_at = 0.0
        if self.state != "menu":
            s = self._hud_last or self.hud.text or ""
            #self._set_hud(s.replace("  (Press again to exit)", ""))
            try: self.macropad.display.refresh(minimum_frames_per_second=0)
            except Exception: pass

    def cleanup(self):
        # turn LEDs off and restore display refresh so the launcher regains control cleanly
        self._enc_pending_at = 0.0
        self._led_all_off()
        try: self.macropad.display.auto_refresh = True
        except Exception: pass
        try:
            if self.tile and self.group:
                self.group.remove(self.tile)
        except Exception: pass
        self.group = None; self.bmp = None; self.pal = None; self.tile = None
        self.title = None; self.menu_lbl = None; self.choice_lbl = None
        self.hint_lbl = None; self.hud = None; self.game = None
        self._bo_prev_ball = None; self._bo_prev_pad = None
        self._inv_prev_pad = None; self._inv_prev_inv = []