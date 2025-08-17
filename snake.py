# snake.py — Nokia-style Snake / Snake II for Adafruit MacroPad
# CircuitPython 8.x / 9.x compatible, non-blocking tick-based movement
# Written by Iain Bennett — 2025
# Inspired by Keith Tanner's Merlin for the Macropad
#
# License:
#   Released under the CC0 1.0 Universal (Public Domain Dedication).
#   You can copy, modify, distribute, and perform the work, even for commercial purposes,
#   all without asking permission. Attribution is appreciated but not required.
#
# "Snake" and "Snake II" are classic arcade-style games where you guide a growing
# snake around the keypad, eating food and avoiding collisions with walls or yourself.
# This implementation supports both Snake I (basic) and Snake II (with wrap-around
# playfield and potential obstacles, if enabled).
#
# Gameplay:
#   • The snake starts at a set length and moves automatically each tick.
#   • Eating food causes the snake to grow and score points.
#   • The game ends if the snake runs into itself or the edges of the playfield
#     (Snake I) — or into itself only, if wrap-around is enabled (Snake II).
#
# Controls:
#   • Arrow keys mapped to MacroPad buttons for up/down/left/right movement
#   • K9     = New Game
#   • K11    = Pause / Resume (if implemented)
#
# Features:
#   • Works for both Snake I and Snake II variants
#   • Adjustable movement speed via tick rate
#   • Non-blocking game loop for responsive input
#   • LED-based grid display for snake body, head, and food
#   • On-screen title and score tracking
#   • Distinct tones for eating, losing, and starting

import time
import math
import random
import displayio
import terminalio
from adafruit_display_text import label
from adafruit_display_shapes.rect import Rect  # border frame

class snake:
    def __init__(self, macropad, tones, wraparound=False):
        self.mac = macropad
        self.tones = tones
        self.wraparound = wraparound

        # Make LED animations smooth by batching updates
        self.BRIGHT = 0.30

        # LED backbuffer + smooth updates
        try:
            self.mac.pixels.auto_write = False
        except AttributeError:
            pass
        self.mac.pixels.brightness = self.BRIGHT
        self._led = [0] * 12          # backbuffer
        self._led_dirty = False
        self._led_fps = 30            # cap refresh rate
        self._led_min_dt = 1.0 / self._led_fps
        self._last_led_push = time.monotonic()

        # ---- LED / color config ----
        self.COLOR_SNAKE = 0x00FF00  # Green (direction LEDs)
        self.COLOR_PAUSE = 0xFFFF00  # Yellow (pause)
        self.COLOR_BG    = 0x000000

        # Buttons
        self.K_NEW   = 0   # K0  : New (only at game over)
        self.K_PAUSE = 2   # K2  : Pause/Resume
        self.K_UP    = 4   # K4  : Up
        self.K_LEFT  = 6   # K6  : Left
        self.K_RIGHT = 8   # K8  : Right
        self.K_DOWN  = 10  # K10 : Down
        self.DIR_KEYS = (self.K_UP, self.K_LEFT, self.K_RIGHT, self.K_DOWN)

        # Board geometry (fits 128x64 OLED nicely)
        self.BOARD_W = 16
        self.BOARD_H = 8
        self.CELL    = 6  # pixels per cell
        self.OFF_X   = (128 - self.BOARD_W * self.CELL) // 2  # center
        self.OFF_Y   = 12

        # Timing
        self.BASE_INTERVAL = 0.25  # seconds per step at start
        self.MIN_INTERVAL  = 0.08
        self.SPEED_FACTOR  = 0.97  # multiply interval each fruit eaten
        self._last_led_refresh = time.monotonic()

        # Pulse behavior (cosine-based, smooth)
        self.SLOW_PULSE_HZ = 0.6  # gentle "breathe" rate

        # Key flash overlay (accepted / illegal inputs)
        self.flash = {}  # key_index -> (until_time, color)

        # Per-mode high score file + value
        self._hs_path = "/snake_highscore_wrap.txt" if self.wraparound else "/snake_highscore_classic.txt"
        self.high_score = self._load_high_score()

        # Build OLED + initial state
        self._build_display()
        self._reset_state()

    # ------ Cleanup ------
    def cleanup(self):
        # Make the game inert so tick() does nothing
        self._inactive = True

        # Best-effort: stop any tone
        try:
            if hasattr(self.mac, "stop_tone"):
                self.mac.stop_tone()
        except Exception:
            pass

        # LEDs: hard clear and hand control back to the launcher
        try:
            self._led = [0]*12
            self._led_dirty = False
            self.mac.pixels.fill(0x000000)
            self.mac.pixels.show()
            self.mac.pixels.auto_write = True
        except Exception:
            pass

        # Display: detach our group so the launcher can draw immediately
        try:
            blank = displayio.Group()
            try:
                self.mac.display.root_group = blank   # CP 9.x
            except AttributeError:
                self.mac.display.show(blank)          # CP 8.x
        except Exception:
            pass
        
    # ---------- Display ----------
    def _build_display(self):
        W, H = self.mac.display.width, self.mac.display.height
        self.group = displayio.Group()

        # Background
        bg_bitmap = displayio.Bitmap(W, H, 1)
        pal = displayio.Palette(1)
        pal[0] = self.COLOR_BG
        self.group.append(displayio.TileGrid(bg_bitmap, pixel_shader=pal))

        # Title / status
        self.status = label.Label(
            terminalio.FONT, text="Snake",
            color=0xFFFFFF, anchor_point=(0.5, 0.0), anchored_position=(W//2, 0)
        )
        self.group.append(self.status)

        # Board bitmap (monochrome palette)
        bw_px = self.BOARD_W * self.CELL
        bh_px = self.BOARD_H * self.CELL
        self.board_bitmap = displayio.Bitmap(bw_px, bh_px, 4)
        self.board_pal = displayio.Palette(4)
        self.board_pal[0] = self.COLOR_BG   # empty = black
        self.board_pal[1] = 0xFFFFFF        # snake body = white
        self.board_pal[2] = 0xFFFFFF        # snake head  = white
        self.board_pal[3] = 0xFFFFFF        # food        = white
        self.board_tile = displayio.TileGrid(
            self.board_bitmap, pixel_shader=self.board_pal, x=self.OFF_X, y=self.OFF_Y
        )
        self.group.append(self.board_tile)

        # Border frame (thin white outline around the playfield)
        self.border = Rect(
            self.OFF_X - 1, self.OFF_Y - 1,
            bw_px + 2, bh_px + 2,
            outline=0xFFFFFF, stroke=1
        )
        self.group.append(self.border)

        # End-of-game score lines (hidden during play) — SAME SIZE (scale=1)
        self.end_score = label.Label(
            terminalio.FONT, text="", color=0xFFFFFF,
            scale=1,
            anchor_point=(0.5, 0.0), anchored_position=(W//2, 12)
        )
        self.end_best  = label.Label(
            terminalio.FONT, text="", color=0xAAAAAA,
            scale=1,
            anchor_point=(0.5, 0.0), anchored_position=(W//2, 26)
        )
        self.end_score.hidden = True
        self.end_best.hidden = True
        self.group.append(self.end_score)
        self.group.append(self.end_best)

    def _show_group(self):
        try:
            self.mac.display.root_group = self.group  # CP 9.x
        except AttributeError:
            self.mac.display.show(self.group)         # CP 8.x

    # ---------- Public API ----------
    def new_game(self):
        print("new Snake" + (" II" if self.wraparound else ""))
        self._lights_clear()
        self._reset_state()
        self._show_group()

    def button(self, key):
        now = time.monotonic()

        # End-of-game: only K0 (New) works
        if self.game_over:
            if key == self.K_NEW:
                self.new_game()
            return

        # Pause toggle
        if key == self.K_PAUSE:
            self.paused = not self.paused
            self.status.text = ("Snake II" if self.wraparound else "Snake") + (" — Paused" if self.paused else "")
            self.end_score.hidden = True
            self.end_best.hidden = True
            self._flash_key(self.K_PAUSE, self.COLOR_PAUSE, 0.15)
            return

        # Ignore movement while paused
        if self.paused:
            return

        # Movement keys
        if key in self.DIR_KEYS:
            dx, dy = self._dir_for_key(key)
            # prevent 180° reversal when length>1
            if len(self.snake) > 1 and (dx, dy) == (-self.dir[0], -self.dir[1]):
                self._flash_key(key, 0xFF0000, 0.12)  # red flash for illegal
                return
            # accept turn
            self.dir = (dx, dy)
            self._flash_key(key, 0xFFFFFF, 0.07)  # white flash

    def encoderChange(self, position, last_position):
        return

    def tick(self):
        if getattr(self, "_inactive", False):
            return
        now = time.monotonic()

        if self.game_over:
            self._render_controls(now)
            return

        if self.paused:
            self._render_controls(now)
            return

        if now >= self.next_step:
            self._step()
            self.next_step = now + self.step_interval

        if now - self._last_led_refresh >= 0.03:
            self._last_led_refresh = now
            self._render_controls(now)

    # ---------- Internals ----------
    def _reset_state(self):
        # Nokia-style start: single block (just the head)
        cx, cy = self.BOARD_W // 2, self.BOARD_H // 2
        self.snake = [(cx, cy)]     # length = 1
        self.dir = (1, 0)
        self.spawn_food()
        self.game_over = False
        self.paused = False

        # Score/overlay
        self.score = 0
        self.grow_pending = 0      # queued growth segments to add
        self.end_score.hidden = True
        self.end_best.hidden = True

        # Timing
        self.step_interval = self.BASE_INTERVAL
        self.next_step = time.monotonic() + self.step_interval

        # Clear flashes
        self.flash.clear()

        # Initial draw: fruit once, snake once (no full-board redraws afterward)
        self._clear_board_bitmap()
        self._draw_food()
        self._draw_snake_initial()

        self.status.text = "Snake II" if self.wraparound else "Snake"

    def _dir_for_key(self, key):
        if key == self.K_UP:    return (0, -1)
        if key == self.K_DOWN:  return (0, 1)
        if key == self.K_LEFT:  return (-1, 0)
        if key == self.K_RIGHT: return (1, 0)
        return self.dir

    def spawn_food(self):
        # Prefer inner cells (avoid the border ring) so fruit isn't on the wall
        inner = {(x, y)
                 for x in range(1, self.BOARD_W - 1)
                 for y in range(1, self.BOARD_H - 1)}
        snake_cells = set(self.snake)

        inner_empty = list(inner - snake_cells)
        if inner_empty:
            self.food = random.choice(inner_empty)
            return

        # Fallback: if inner is full, allow anywhere empty
        all_empty = {(x, y) for x in range(self.BOARD_W) for y in range(self.BOARD_H)} - snake_cells
        if not all_empty:
            # Board completely full — big win!
            self._on_game_over()
            return
        self.food = random.choice(tuple(all_empty))

    def _step(self):
        if self.game_over or self.paused:
            return

        hx, hy = self.snake[0]
        dx, dy = self.dir

        if self.wraparound:
            nx = (hx + dx) % self.BOARD_W
            ny = (hy + dy) % self.BOARD_H
            hit_wall = False
        else:
            nx = hx + dx
            ny = hy + dy
            hit_wall = (nx < 0 or nx >= self.BOARD_W or ny < 0 or ny >= self.BOARD_H)

        if hit_wall or (nx, ny) in self.snake:
            self._on_game_over()
            return

        # Move: insert new head
        self.snake.insert(0, (nx, ny))
        ate = (nx, ny) == self.food

        # --- Incremental bitmap updates (no full redraw) ---
        # old head becomes body (if previous length > 0)
        self._set_cell_index(hx, hy, 1)
        # new head cell
        self._set_cell_index(nx, ny, 2)

        if ate:
            self._sound_eat()
            self.score += 1
            self.grow_pending += 1                      # +1 segments per fruit
            self.step_interval = max(self.MIN_INTERVAL, self.step_interval * self.SPEED_FACTOR)
            self.spawn_food()
            self._draw_food()                           # draw new fruit only now
        else:
            if self.grow_pending > 0:
                self.grow_pending -= 1                  # consume one unit of growth
            else:
                # no growth: remove tail
                tx, ty = self.snake.pop()
                self._set_cell_index(tx, ty, 0)

    # ---------- Board rendering (helpers) ----------
    def _clear_board_bitmap(self):
        bw, bh = self.board_bitmap.width, self.board_bitmap.height
        for y in range(bh):
            for x in range(bw):
                self.board_bitmap[x, y] = 0  # background

    # Write by palette index directly (fast small edits)
    def _set_cell_index(self, cx, cy, idx):
        ox = cx * self.CELL
        oy = cy * self.CELL
        for y in range(oy, oy + self.CELL):
            for x in range(ox, ox + self.CELL):
                self.board_bitmap[x, y] = idx

    def _draw_food(self):
        fx, fy = self.food
        self._set_cell_index(fx, fy, 3)  # palette index 3 = food (white)

    def _draw_snake_initial(self):
        for i, (sx, sy) in enumerate(self.snake):
            self._set_cell_index(sx, sy, 2 if i == 0 else 1)

    # ---------- Key LEDs ----------
    # _render_controls(now): replace all direct writes with _led_set/_led_fill and finish with _led_show()
    def _render_controls(self, now):
        
        # Start with everything off
        self._led_fill(0x000000)

        if self.game_over:
            pulse = self._pulse(now)
            self._led_set(self.K_NEW, self._scale(0xFFFFFF, pulse))
            return self._led_show()

        # Movement keys: static dim green
        dim_g = self._scale(self.COLOR_SNAKE, 0.18)
        for k in self.DIR_KEYS:
            self._led_set(k, dim_g)

        # Current direction: bright green
        dir_key = self._key_for_dir(self.dir)
        if dir_key is not None:
            self._led_set(dir_key, self._scale(self.COLOR_SNAKE, 0.9))

        # Pause indicator
        if self.paused:
            pulse = self._pulse(now)
            self._led_set(self.K_PAUSE, self._scale(self.COLOR_PAUSE, pulse))
        else:
            self._led_set(self.K_PAUSE, self._scale(0xFFFFFF, 0.12))

        # Flash overlays
        to_del = []
        for k, (until, col) in self.flash.items():
            if now <= until:
                self._led_set(k, col)
            else:
                to_del.append(k)
        for k in to_del:
            del self.flash[k]

        self._led_show()

    def _key_for_dir(self, d):
        if d == (0, -1): return self.K_UP
        if d == (0, 1):  return self.K_DOWN
        if d == (-1, 0): return self.K_LEFT
        if d == (1, 0):  return self.K_RIGHT
        return None

    def _flash_key(self, key, color, dur):
        self.flash[key] = (time.monotonic() + dur, color)

    # ---------- Game over ----------
    def _on_game_over(self):
        self.game_over = True
        self._just_finished = True 
        title = "Snake II" if self.wraparound else "Snake"
        self.status.text = title + " Game Over"
        self._sound_crash()

        # Clear snake + fruit from the screen before showing scores
        self._clear_board_bitmap()

        if self.score > self.high_score:
            self.high_score = self.score
            self._save_high_score(self.high_score)

        self.end_score.text = "Score: {}".format(self.score)
        self.end_best.text  = "Best:  {}".format(self.high_score)
        self.end_score.hidden = False
        self.end_best.hidden  = False

    # ---------- Sounds ----------
    def _play(self, freq, dur):
        try:
            self.mac.play_tone(freq, dur)
        except Exception:
            pass

    def _sound_eat(self):
        for f in (523, 659):
            self._play(f, 0.03)

    def _sound_crash(self):
        for f in (196, 130):
            self._play(f, 0.25)

    # ---------- High score helpers ----------
    def _load_high_score(self):
        try:
            with open(self._hs_path, "r") as f:
                return int(f.read().strip() or "0")
        except Exception:
            return 0

    def _save_high_score(self, value):
        try:
            with open(self._hs_path, "w") as f:
                f.write(str(int(value)))
        except Exception:
            pass

    # ---------- Misc helpers ----------
    def _pulse(self, now):
        # Cosine-based smooth pulse between ~35% and 100%
        return 0.35 + 0.65 * (0.5 + 0.5 * math.cos(now * 2 * math.pi * self.SLOW_PULSE_HZ))

    def _scale(self, color, s):
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        r = int(r * s); g = int(g * s); b = int(b * s)
        return (r << 16) | (g << 8) | b
               
    def _lights_clear(self):
        self._led_fill(0x000000)
        self._led_show(force=True)
            
    # --- add these helper methods somewhere in the class (e.g., near other helpers) ---
    def _led_set(self, i, color):
        if 0 <= i < 12:
            if self._led[i] != color:
                self._led[i] = color
                self._led_dirty = True

    def _led_fill(self, color):
        changed = False
        for i in range(12):
            if self._led[i] != color:
                self._led[i] = color
                changed = True
        if changed:
            self._led_dirty = True

    def _led_show(self, force=False):
        now = time.monotonic()
        if not force and (now - self._last_led_push) < self._led_min_dt:
            return
        if not self._led_dirty:
            return
        # push backbuffer to actual pixels in one go
        for i in range(12):
            self.mac.pixels[i] = self._led[i]
        try:
            self.mac.pixels.show()
        except AttributeError:
            pass
        self._led_dirty = False
        self._last_led_push = now