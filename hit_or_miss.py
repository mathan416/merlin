# hit_or_miss.py — Master Merlin "Hit or Miss" for Adafruit MacroPad
# CircuitPython 8.x / 9.x compatible, non-blocking fades and animations
# Written by Iain Bennett — 2025
# Inspired by Keith Tanner's Merlin for the Macropad
#
# Hit or Miss is a Master Merlin-style memory and deduction game where the
# player tries to find hidden shapes on a 3×3 grid. Two levels are available:
#
# Level 1:
#   • One hidden shape (T, V, or I) in a random orientation
#   • K11 (Reveal) shows an abstract version of the shape only while held
#
# Level 2:
#   • Three hidden shapes of random types
#   • Shapes may overlap only at the center cell (K4)
#   • No reveal option on K11
#
# Gameplay:
#   • Press keys K0..K8 to guess cells
#   • Hits turn red and stay lit
#   • Misses briefly light blue, then fade out
#   • Win when all target cells are found
#
# Controls:
#   • K0..K8 — Select grid cells
#   • K11    — Reveal shape (Level 1 only)
#   • K9     — New game / return to level select
#   • K3     — Start Level 1
#   • K5     — Start Level 2
#
# Features:
#   • Non-blocking LED fades for misses
#   • Persistent hit indicators
#   • Level selection with pulsing indicators
#   • Distinct sounds for hits, misses, errors, and wins

import time
import math
import random
import displayio
import terminalio
from adafruit_display_text import label

class hit_or_miss:
    SHAPES = {
        "V": [{0,4,2}, {6,4,8}, {0,4,6}, {2,4,8}],
        "T": [{0,1,2,4}, {6,7,8,4}, {0,3,6,4}, {2,5,8,4}],
        "I": [{0,1}, {1,2}, {3,4}, {4,5}, {6,7}, {7,8},
              {0,3}, {3,6}, {1,4}, {4,7}, {2,5}, {5,8}],
    }
    SHAPE_TYPES = ("T", "I", "V")
    

    def __init__(self, macropad, tones):
        self.mac = macropad
        self.tones = tones

        # Setup the shapes
        self.CANDIDATES = [(s, frozenset(c)) for s in self.SHAPE_TYPES for c in self.SHAPES[s]]

        # LED / colors
        self.BRIGHT = 0.30
        self.COLOR_BG   = 0x000000
        self.COLOR_HIT  = 0xFF0000  # red
        self.COLOR_MISS = 0x0000FF  # blue

        # Buttons
        self.CELLS = tuple(range(9))  # 0..8
        self.K_NEW = 9
        self.K_REVEAL = 11
        self.revealing = False

        # Pulsing
        self.SLOW_PULSE_HZ = 0.8

        # Miss fade store: key -> (start_time, duration)
        self.miss_fades = {}   # non-blocking fade out for misses
        self.MISS_FADE_DUR = 0.6

        # --- LED driver (anti-flicker) ---
        self._led = [0] * 12          # cached colors
        self._led_dirty = False
        self._last_led_show = 0.0
        self.LED_FRAME_DT = 1.0 / 30.0   # cap ~30 FPS
        try:
            self.mac.pixels.auto_write = False
        except AttributeError:
            pass
        self.mac.pixels.brightness = self.BRIGHT

        # Display
        self._build_display()

        # Game state
        self._to_level_select()

    # ------ Cleanup ------
    def cleanup(self):
        # Reset transient state so nothing lingers after exit
        self.miss_fades.clear()
        self.revealing = False
        try:
            self.mac.pixels.auto_write = True
        except AttributeError:
            pass
        for i in range(12):
            self.mac.pixels[i] = 0x000000
        try:
            self.mac.pixels.show()
        except AttributeError:
            pass
        # Let code.py reclaim the display; no root_group change needed here.

    # ---------------- Display ----------------
    def _build_display(self):
        W, H = self.mac.display.width, self.mac.display.height
        self.group = displayio.Group()

        # Background
        bg_bitmap = displayio.Bitmap(W, H, 1)
        pal = displayio.Palette(1)
        pal[0] = self.COLOR_BG
        self.group.append(displayio.TileGrid(bg_bitmap, pixel_shader=pal))

        # Status lines
        self.title = label.Label(
            terminalio.FONT, text="Hit or Miss",
            color=0xFFFFFF, anchor_point=(0.5, 0.0), anchored_position=(W//2, 0)
        )
        self.line1 = label.Label(
            terminalio.FONT, text="",
            color=0xFFFFFF, anchor_point=(0.5, 0.0), anchored_position=(W//2, 12)
        )
        self.line2 = label.Label(
            terminalio.FONT, text="",
            color=0xAAAAAA, anchor_point=(0.5, 0.0), anchored_position=(W//2, 22)
        )
        self.group.append(self.title)
        self.group.append(self.line1)
        self.group.append(self.line2)

    def _show(self):
        try:
            self.mac.display.root_group = self.group
        except AttributeError:
            self.mac.display.show(self.group)

    # ---------------- Public API ----------------
    def new_game(self):
        self._to_level_select()
        self._show()

    def button(self, key):
        now = time.monotonic()

        if self.mode == "level_select":
            if key == 3:     # K3 -> Level 1
                self.level = 1
                self._start_round()
            elif key == 5:   # K5 -> Level 2
                self.level = 2
                self._start_round()
            elif key == self.K_NEW:
                self._to_level_select()  # reflash LEDs
            return

        # From here: mode == "play" or "won"
        if key == self.K_NEW:
            self._to_level_select()
            return

        if self.mode != "play":
            return

        # Reveal (Level 1 only) handled on press (start) and release in button_up()
        if key == self.K_REVEAL and self.level == 1:
            self.revealing = True
            return

        # Board presses
        if key in self.CELLS:
            if key in self.guessed:
                self._sound_error()
                return
            self.guessed.add(key)

            self.shots += 1
            target_cells = self.solution_cells if self.level == 1 else self.union_cells

            if key in target_cells:
                # HIT
                self.hits.add(key)
                self._led_set(key, self.COLOR_HIT)  # immediate visual
                self._led_show()
                self._sound_hit()
            else:
                # MISS — start fade (blue -> black), non-blocking
                self.miss_fades[key] = (now, self.MISS_FADE_DUR)
                self._led_set(key, self.COLOR_MISS)  # immediate blue, fade next frames
                self._led_show()
                self._sound_miss()

            self._update_stats()

            # Win check (works for both levels)
            if target_cells.issubset(self.hits):
                self._on_win()

    def button_up(self, key):
        # Stop reveal on release (Level 1 only)
        if key == self.K_REVEAL and self.level == 1 and self.mode == "play":
            self.revealing = False

    def encoderChange(self, new, old):
        return

    def tick(self):
        now = time.monotonic()

        if self.mode == "level_select":
            self._render_level_select(now)
            return

        # While revealing (Level 1 only), draw ONLY the overlay each loop.
        if self.mode == "play" and self.level == 1 and self.revealing:
            self._render_reveal_overlay()
            return

        # Normal gameplay/won frame
        self._render_game_leds(now)

    # ---------------- Internals ----------------
    def _start_round(self):
        self.mode = "play"
        self.shots = 0
        self.hits = set()
        self.guessed = set()
        self.revealing = False
        self.miss_fades.clear()
        self._lights_clear()

        if self.level == 1:
            # One random shape, random placement set
            shape = random.choice(("T", "I", "V"))
            cells = self._place_ship_any(shape, occupied=set(), max_attempts=200)
            if cells is None:
                # Fallback if something odd happens
                shape, cells = self._random_shape_L1()

            self.shape_type = shape          # "T","V","I" (for the reveal overlay)
            self.solution_cells = set(cells)
            self.line1.text = "Level 1"
            self._update_stats()

        else:
            # Level 2: three ships, no overlap except center (4) allowed
            occupied = set()
            ships = []
            tries = 0
            while len(ships) < 3 and tries < 800:
                tries += 1
                shape = random.choice(("T", "I", "V"))
                cells = self._place_ship_any(shape, occupied=occupied, max_attempts=200)
                if cells is None:
                    continue
                ships.append((shape, set(cells)))
                for c in cells:
                    if c != 4:
                        occupied.add(c)

            # If randomness didn’t find three, fall back to exact backtracking
            if len(ships) < 3:
                exact = self._place_three_ships_exact()
                if exact:
                    ships = exact
                else:
                    # ultra-safe fallback so the round is always playable
                    ships = [("V", {0,4,2}), ("V", {6,4,8}), ("V", {0,4,6})]

            # Attributes expected elsewhere
            self.shape_sets = [cells for _, cells in ships]
            u = set()
            for s in self.shape_sets:
                u |= s
            self.union_cells = u
            self.line1.text = "Level 2"
            self._update_stats()

        # Draw LED state immediately
        self._render_game_leds(time.monotonic())

    def _to_level_select(self):
        # enter level-select mode
        self.mode = "level_select"
        self.level = None
        self.shots = 0
        self.hits = set()
        self.guessed = set()
        self.revealing = False
        self.miss_fades.clear()

        self.solution_cells = set()
        self.union_cells = set()
        self.shape_type = None

        self.line1.text = "\nSelect Level:"
        self.line2.text = "\nL1    L2"

        self._lights_clear()
        self._show()

    def _update_stats(self):
        # Update display with shots and (optionally) hits
        if self.mode == "play":
            self.line2.text = "Shots: {}".format(self.shots)
        elif self.mode == "won":
            # Split over two lines
            self.line1.text = "You Won in"
            self.line2.text = "{} shots!".format(self.shots)

    # ----- Shapes -----
    def _random_shape_L1(self):
        shape = random.choice(self.SHAPE_TYPES)
        return shape, set(random.choice(self.SHAPES[shape]))

    # Random valid placement for a given shape (list of cell indices)
    def _random_positions_for_shape(self, shape):
        # Return a list (not set) to keep call sites unchanged
        #return list(random.choice(self.SHAPES[shape]))
        return random.choice(self.SHAPES[shape]) 

    def _place_ship_any(self, shape, occupied=None, max_attempts=60):
        if occupied is None:
            occupied = set()

        for _ in range(max_attempts):
            cells = self._random_positions_for_shape(shape)
            if self._overlap_ok(cells, occupied):
                return cells
        return None

    def _overlap_ok(self, cells, occupied):
        # Overlap is allowed ONLY at center cell 4
        for c in cells:
            if c in occupied and c != 4:
                return False
        return True

    # ----- Rendering -----
    def _render_level_select(self, now):
        # Base: everything off (diffed)
        self._led_fill(0x000000)

        # Pulse K3 and K5 only
        pulse = self._pulse(now)
        green_dim = self._scale(0x00FF00, 0.20 + 0.60 * pulse)
        self._led_set(3, green_dim)
        self._led_set(5, green_dim)

        # K11 OFF during level select
        self._led_set(self.K_REVEAL, 0x000000)

        self._led_show()

    def _render_game_leds(self, now):
        # Start from 'off' (diffed)
        self._led_fill(0x000000)

        # hits stay red
        for k in self.hits:
            self._led_set(k, self.COLOR_HIT)

        # misses fade out (blue -> black)
        self._update_miss_fades(now)

        # K11: dim blue ONLY while actively playing Level 1
        if self.mode == "play" and self.level == 1:
            self._led_set(self.K_REVEAL, self._scale(self.COLOR_MISS, 0.12))
        else:
            self._led_set(self.K_REVEAL, 0x000000)

        # New button: pulse when won, dim otherwise
        if self.mode == "won":
            self._led_set(self.K_NEW, self._scale(0xFFFFFF, 0.65 + 0.35 * self._pulse(now)))
        else:
            self._led_set(self.K_NEW, self._scale(0xFFFFFF, 0.10))

        self._led_show()

    def _render_reveal_overlay(self):
        # Level 1 only: show abstract shape while K11 held
        # T -> {0,1,2,4}; V -> {0,4,2}; I -> {1,4}
        overlay = set()
        if self.shape_type == "T":
            overlay = {0,1,2,4}
        elif self.shape_type == "V":
            overlay = {0,4,2}
        else:  # "I"
            overlay = {1,4}

        self._led_fill(0x000000)
        for i in overlay:
            self._led_set(i, 0xFFFFFF)

        # Keep K11 dim blue during reveal to signal "hold"
        self._led_set(self.K_REVEAL, self._scale(self.COLOR_MISS, 0.12))
        self._led_show()

    def _update_miss_fades(self, now):
        # For each fading miss, compute progress and set scaled blue
        to_delete = []
        for k, (t0, dur) in self.miss_fades.items():
            t = (now - t0) / dur
            if t >= 1.0:
                to_delete.append(k)
                continue
            # cosine ease-out from 1 -> 0
            s = 0.5 * (1 + math.cos(t * math.pi))  # 1..0
            self._led_set(k, self._scale(self.COLOR_MISS, 0.15 + 0.35 * s))
        for k in to_delete:
            # ensure fully off at end
            self._led_set(k, 0x000000)
            del self.miss_fades[k]

    # ----- Win / lose -----
    def _on_win(self):
        self.mode = "won"
        self._update_stats()
        self._sound_win()

    # ----- Helpers -----
    def _lights_clear(self):
        self._led_fill(0x000000)
        self._led_show()

    # ---------- LED helpers (diff + rate-limit) ----------
    def _led_set(self, idx, color):
        if 0 <= idx < 12 and self._led[idx] != color:
            self._led[idx] = color
            self._led_dirty = True

    def _led_fill(self, color):
        changed = False
        for i in range(12):
            if self._led[i] != color:
                self._led[i] = color
                changed = True
        if changed:
            self._led_dirty = True

    def _led_show(self):
        now = time.monotonic()
        if not self._led_dirty or (now - self._last_led_show) < self.LED_FRAME_DT:
            return
        for i, c in enumerate(self._led):
            self.mac.pixels[i] = c
        self._last_led_show = now
        self._led_dirty = False
        try:
            self.mac.pixels.show()
        except AttributeError:
            pass

    def _pulse(self, now):
        return 0.5 + 0.5 * math.cos(now * 2 * math.pi * self.SLOW_PULSE_HZ)

    def _scale(self, color, s):
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        r = int(r * s); g = int(g * s); b = int(b * s)
        return (r << 16) | (g << 8) | b

    def _place_three_ships_exact(self):
        # Uses class-level CANDIDATES: [(shape, frozenset(cells)), ...]
        candidates = list(self.CANDIDATES)  # copy so we can shuffle without mutating the class constant
        random.shuffle(candidates)

        result = []

        def ok_overlap(cells, occupied):
            # Overlap allowed only at center (4)
            return all((c == 4 or c not in occupied) for c in cells)

        def backtrack(start, occupied):
            if len(result) == 3:
                return True
            for i in range(start, len(candidates)):
                shape, cells = candidates[i]
                if ok_overlap(cells, occupied):
                    result.append((shape, set(cells)))          # return mutable sets like your callers expect
                    new_occupied = occupied | (cells - {4})     # track all non-center cells as taken
                    if backtrack(i + 1, new_occupied):
                        return True
                    result.pop()
            return False

        if backtrack(0, set()):
            return result    # [(shape, set_of_cells), x3]
        return None

    # ----- Sounds -----
    def _play(self, f, d):
        try:
            self.mac.play_tone(f, d)
        except Exception:
            pass

    def _sound_hit(self):
        self._play(659, 0.04)

    def _sound_miss(self):
        self._play(330, 0.05)

    def _sound_error(self):
        self._play(150, 0.07)

    def _sound_win(self):
        for f in (660, 880, 990):
            self._play(f, 0.05)