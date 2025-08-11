# hot_potato.py — Master Merlin "Hot Potato" for Adafruit MacroPad
# CircuitPython 8.x / 9.x compatible, non-blocking animations
# Written by Iain Bennett — 2025
# Inspired by Keith Tanner's Merlin for the Macropad
#
# hot_potato.py — Master Merlin "Hot Potato" for Adafruit MacroPad
# CircuitPython 8.x / 9.x compatible, non-blocking animations
# Written by Iain Bennett — 2025
# Inspired by Keith Tanner's Merlin for the Macropad
#
# Hot Potato is a party guessing game: there’s a secret number (0–99). Players
# take turns guessing; Merlin shows HI or LO after each guess. Whoever guesses
# the hot number “gets burned” (explosion!) and everyone else wins.
#
# This implementation keeps the simple one/two-digit entry + ENTER (K11)
# from Hi/Lo, but also shows the *allowed tens* as guidance: after a guess,
# keys whose digits (0..9) match possible tens for the next guess will glow.
#
# Controls:
#   • K0..K8  – digits 1 to 9
#   • K10     – digit 0
#   • K11     – Enter: submit the guess
#   • K9      – New game (allowed during play or after a win)
#
# Features:
#   • Startup explosion preview
#   • HI/LO arrow flash after each valid guess
#   • Allowed-range guidance: tens keys pulse to hint valid tens (e.g., 3..9)
#   • Invalid/repeat guess: red “X” flash and error tone; turn does not advance
#   • Tracks player_count and per-player turn counts (default 2 players)
#   • Non-blocking explosion effect on win
#
# Design Notes / Key Features
#  • Non‑blocking effects:  All animations (guidance pulse, arrows, explosion)
#    are time‑based using time.monotonic(); the main loop stays responsive.
#  • Simple numeric entry:  Players press digit keys (K0–K8 for 1‑9, K10 for 0)
#    up to two digits, then confirm with Enter (K11).  Excess digits shift.
#  • Allowed‑tens guidance:  When no digits are typed, keys whose digit matches
#    a valid tens value in the current [low_bound…high_bound] flash brighter.
#  • Range enforcement and duplicate checking:  Guesses outside the current
#    bounds or repeats prompt a red “X” flash and an error tone; turn is lost.
#  • HI/LO feedback:  A correct guess triggers a non‑blocking explosion.
#    Higher guesses flash a red “up” arrow; lower guesses flash a red “down”.
#  • Multi‑player support:  Tracks `player_count` (minimum 2) and per‑player
#    turn counts; automatically advances the turn index after each valid guess.
#  • UI caching:  Uses a “dirty” flag (`_ui_dirty`) to avoid repainting static
#    keypad state on every tick, improving performance.  Dynamic effects
#    (e.g., pulsing Enter key) are updated each frame.
#  • Cleanup:  `cleanup()` restores pixels and auto_write state when exiting.
#


import time, math, random
import displayio, terminalio
from adafruit_display_text import label

class hot_potato:
    def __init__(self, macropad, tones):
        self.mac = macropad
        self.tones = tones

        # Colors
        self.BRIGHT          = 0.30
        self.C_BG            = 0x000000
        self.C_NUM_IDLE      = 0x102040  # dim steel-blue for number keys (idle)
        self.C_NUM_ACTIVE    = 0x3060A0  # brighter hint for allowed tens
        self.C_ENTER         = 0x00AA00  # green for K11
        self.C_NEW           = 0x202020  # dim white for K9
        self.C_HINT          = 0xFF0000  # red arrows (HI/LO)
        self.C_ERR           = 0xFF0000  # red 'X' for invalid

        # Buttons
        self.K_NEW   = 9
        self.K_ZERO  = 10
        self.K_ENTER = 11
        self.NUM_KEYS = tuple(range(0, 9)) + (self.K_ZERO,)  # K0..K8, K10

        # Arrow shapes (as key indexes)
        self.ARROW_UP    = {1, 3, 4, 5, 7, 10}
        self.ARROW_DOWN  = {1, 4, 6, 7, 8, 10}

        # Game state
        self.mode = "entry"              # "entry" | "hint" | "won" | "preview"
        self.entry_digits = []           # up to 2 digits
        self.target = 0
        self.low_bound = 0               # inclusive
        self.high_bound = 99             # inclusive
        self.used = set()
        self.player_count = 2
        self.turn_index = 0              # 0..player_count-1
        self.turns_per_player = [0] * self.player_count
        self.hint_until = 0.0
        
        # --- UI cache / dirtiness ---
        self._ui_dirty = True                  # when True, repaint the static entry UI

        # LED driver
        try:
            self.mac.pixels.auto_write = False
        except AttributeError:
            pass
        self.mac.pixels.brightness = self.BRIGHT

        # Explosion state
        self._init_explosion_state()

        # Display
        self._build_display()

    # ---------- Public ----------
    def new_game(self):
        # Startup explosion preview
        self._lights_off()
        self._set_title("Hot Potato")
        self._set_status("Get ready…")
        self._show()
        self.start_explosion()
        self.mode = "preview"

        # Initialize a new round
        self.target = random.randint(0, 99)
        self.low_bound = 0
        self.high_bound = 99
        self.used.clear()
        self.entry_digits = []
        self.turn_index = 0
        self.player_count = max(2, self.player_count)
        self.turns_per_player = [0] * self.player_count

    def button(self, key):
        now = time.monotonic()

        # Allow New anytime
        if key == self.K_NEW:
            self._click(key)
            self.new_game()
            return

        # Ignore input while explosion or hint is active
        if self.expl_active:
            return
        if self.mode == "hint" and now < self.hint_until:
            return
        if self.mode == "won":
            return

        # Entry mode
        if self.mode == "entry":
            if key == self.K_ENTER:
                self._click(key)
                self._commit_guess()
                return

            d = self._digit_for_key(key)
            if d is not None:
                self._click(key)
                self._press_digit_feedback(key)

                # Maintain a 1–2 digit buffer
                if len(self.entry_digits) >= 2:
                    self.entry_digits = [self.entry_digits[-1], d]
                else:
                    self.entry_digits.append(d)

                # Update text; defer LED repaint to tick()
                self._update_status_for_entry()
                self._mark_entry_dirty()
                return

    def tick(self):
        now = time.monotonic()

        # Explosion animation owns LEDs while active
        if self.expl_active:
            self._explosion_frame()
            # When preview explosion finishes, transition to entry UI on next frame
            if (not self.expl_active) and self.mode == "preview":
                self.mode = "entry"
                self._update_status_for_entry()
                self._mark_entry_dirty()   # defer repaint to the next tick
                self._show()
            return

        # After hint flash, return to entry UI and defer repaint
        if self.mode == "hint" and now >= self.hint_until:
            self.mode = "entry"
            self._update_status_for_entry()
            self._mark_entry_dirty()
            return

        # After win: freeze LEDs (K9 shown by _paint_won_ui); wait for New
        if self.mode == "won":
            return

        # Entry mode: repaint static UI only when dirty; always pulse Enter
        if self.mode == "entry":
            if self._ui_dirty:
                self._paint_entry_static()  # heavy work only when needed

            # Cheap per-frame pulse for K11
            pulse = 0.35 + 0.65 * (0.5 + 0.5 * math.cos(now * 2 * math.pi * 0.9))
            self._paint_entry_dynamic(pulse)
            return

    def cleanup(self):
        # Stop any transient effect
        self.expl_active = False

        # Give pixels back in a clean, predictable state
        try:
            self.mac.pixels.auto_write = True
        except AttributeError:
            pass
        self.mac.pixels.brightness = self.BRIGHT
        for i in range(12):
            self.mac.pixels[i] = 0x000000
        try:
            self.mac.pixels.show()
        except AttributeError:
            pass

        # Reset transient UI flags so a future resume/new_game repaints correctly
        self._ui_dirty = True

    # ---------- Internals ----------
    def _digit_for_key(self, k):
        if 0 <= k <= 8:  # 1..9
            return k + 1
        if k == self.K_ZERO:
            return 0
        return None

    def _commit_guess(self):
        # No digits typed?
        if not self.entry_digits:
            self._set_status(self._turn_prefix() + "Enter a number")
            return

        # Parse 1–2 digit number, clamp 0..99
        guess = self.entry_digits[0] if len(self.entry_digits) == 1 else (self.entry_digits[0]*10 + self.entry_digits[1])
        guess = max(0, min(99, guess))

        # Validate: within current bounds and unused
        if (guess < self.low_bound) or (guess > self.high_bound) or (guess in self.used):
            self._sound_error()
            self._flash_invalid_x()          # does its own brief paint/show
            self._update_status_for_entry()
            self._mark_entry_dirty()         # ensure entry UI refreshes after the X
            return

        # Valid turn
        self.used.add(guess)
        self.turns_per_player[self.turn_index] += 1

        if guess < self.target:
            # Higher: tighten lower bound, show HI arrow, next player
            self.low_bound = max(self.low_bound, guess + 1)
            self._flash_arrow(self.ARROW_UP, self.C_HINT, 0.9)
            self._advance_turn()
            self._mark_entry_dirty()         # allowed tens changed

        elif guess > self.target:
            # Lower: tighten upper bound, show LO arrow, next player
            self.high_bound = min(self.high_bound, guess - 1)
            self._flash_arrow(self.ARROW_DOWN, self.C_HINT, 0.9)
            self._advance_turn()
            self._mark_entry_dirty()         # allowed tens changed

        else:
            # Boom! Guesser is burned; everyone else wins.
            self.mode = "won"  # set first so post-explosion paint shows K9
            self._set_status(f"Player {self.turn_index+1} burned!")
            self.start_explosion()           # explosion temporarily owns LEDs

        # Reset entry buffer for next input/turn
        self.entry_digits = []

    def _advance_turn(self):
        self.turn_index = (self.turn_index + 1) % self.player_count
        self._update_status_for_entry()

    # ---------- UI paint ----------
    def _allowed_tens(self):
        """Return a set of allowed tens (0..9) given [low_bound..high_bound]."""
        lo_t, hi_t = self.low_bound // 10, self.high_bound // 10
        return set(range(lo_t, hi_t + 1))

    def _key_for_digit(self, d):
        """Map digit 0..9 to key index used by this layout."""
        if d == 0: return self.K_ZERO
        if 1 <= d <= 9: return d - 1  # digit 1..9 -> K0..K8
        return None

    def _press_digit_feedback(self, key):
        # brief bright flash on the pressed number key
        old = self.mac.pixels[key]
        self.mac.pixels[key] = self.C_NUM_ACTIVE
        try: self.mac.pixels.show()
        except AttributeError: pass
        time.sleep(0.05)
        self.mac.pixels[key] = old
        try: self.mac.pixels.show()
        except AttributeError: pass

    def _flash_arrow(self, keys_set, color, dur):
        # Clear, draw only the arrow, hold for dur
        for i in range(12):
            self.mac.pixels[i] = 0x000000
        for k in keys_set:
            self.mac.pixels[k] = color
        try: self.mac.pixels.show()
        except AttributeError: pass
        self.mode = "hint"
        self.hint_until = time.monotonic() + dur

    def _flash_invalid_x(self):
        lit = {0, 2, 4, 6, 8}
        for i in range(12):
            self.mac.pixels[i] = 0x000000
        for i in lit:
            self.mac.pixels[i] = self.C_ERR
        try: self.mac.pixels.show()
        except AttributeError: pass
        time.sleep(0.35)
        self._mark_entry_dirty()  # <- let tick repaint
        
    # ---------- Display ----------
    def _build_display(self):
        W, H = self.mac.display.width, self.mac.display.height
        g = displayio.Group()

        # Background
        bg = displayio.Bitmap(W, H, 1)
        pal = displayio.Palette(1); pal[0] = self.C_BG
        g.append(displayio.TileGrid(bg, pixel_shader=pal))

        # Logo (optional)
        y0 = 0
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            x = max(0, (W - bmp.width)//2)
            g.append(displayio.TileGrid(
                bmp,
                pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter()),
                x=x, y=0
            ))
            y0 = bmp.height + 2
        except Exception:
            y0 = 0

        self.title = label.Label(
            terminalio.FONT, text="Hot Potato",
            color=0xFFFFFF, anchor_point=(0.5, 0.0),
            anchored_position=(W//2, y0)
        )
        g.append(self.title)

        self.status = label.Label(
            terminalio.FONT, text="",
            color=0xA0A0A0, anchor_point=(0.5, 0.0),
            anchored_position=(W//2, y0 + 14)
        )
        g.append(self.status)

        self.group = g

    def _show(self):
        try:
            self.mac.display.show(self.group)      # CP 8.x
        except AttributeError:
            self.mac.display.root_group = self.group  # CP 9.x

    def _set_title(self, s):
        if hasattr(self, "title") and self.title:
            self.title.text = s

    def _set_status(self, s):
        if hasattr(self, "status") and self.status:
            self.status.text = s

    def _turn_prefix(self):
        return f"P{self.turn_index+1}: "

    def _update_status_for_entry(self):
        # Example: "P1: 0–99" or "P2: 36–99" etc.
        if not self.entry_digits:
            self._set_status(self._turn_prefix() + f"{self.low_bound} to {self.high_bound}")
        elif len(self.entry_digits) == 1:
            self._set_status(self._turn_prefix() + f"Guess: {self.entry_digits[0]}")
        else:
            val = self.entry_digits[0]*10 + self.entry_digits[1]
            self._set_status(self._turn_prefix() + f"Guess: {val}")

    # ---------- Explosion (non-blocking) ----------
    def _init_explosion_state(self):
        self.expl_active = False
        self.expl_t0 = 0.0
        self.expl_ring_speed = 3.2     # LEDs per second (wavefront speed)
        self.expl_hot_time   = 0.38    # per-key hot window
        self.expl_total_time = 1.1     # overall effect duration
        self.expl_ignite_at = [-1.0] * 12
        self._grid_r = [((i%3 - 1)**2 + (i//3 - 1)**2) ** 0.5 for i in range(9)]
        self._spark_keys = []

    def start_explosion(self):
        self.expl_active = True
        self.expl_t0 = time.monotonic()
        self.expl_ignite_at = [-1.0] * 12
        try:
            for f, d in ((660, 0.04), (880, 0.04), (220, 0.10)):
                self.mac.play_tone(f, d)
        except Exception:
            pass

        pool = [9, 10, 11]
        try:
            self._spark_keys = self._rand_sample2(pool)
        except Exception:
            self._spark_keys = pool[:2]

    def _explosion_frame(self):
        now = time.monotonic()
        t = now - self.expl_t0

        if t >= self.expl_total_time:
            self.expl_active = False
            if self.mode == "won":
                self._paint_won_ui()
            else:
                self._lights_off()
                try: self.mac.pixels.show()
                except AttributeError: pass
            return

        R = t * self.expl_ring_speed

        px = self.mac.pixels       # local for speed
        ignite = self.expl_ignite_at
        hot_time = self.expl_hot_time
        inv_hot = 1.0 / hot_time
        grid_r = self._grid_r

        # clear all
        for i in range(12):
            px[i] = 0x000000

        # animate K0..K8
        for i in range(9):
            r = grid_r[i]

            if ignite[i] < 0 and R >= (r - 0.05):
                ignite[i] = now

            t0 = ignite[i]
            if t0 >= 0:
                age = now - t0
                u = age * inv_hot
                if u <= 0.0:
                    continue
                if u >= 1.0:
                    u = 1.0

                heat = 1.0 - self._ease_cos(u)

                # color ramp
                if u < 0.15:
                    col = self._blend(0xFFFFFF, 0xFFD040, u / 0.15)
                else:
                    v = (u - 0.15) * (1.0 / 0.85)
                    if v > 1.0: v = 1.0
                    hue = 0.13 * (1.0 - v)
                    if hue < 0.0: hue = 0.0
                    col = self._hsv_to_rgb(hue, 1.0, 1.0)

                px[i] = self._scale(col, 0.25 + 0.75 * heat)

        # center pop
        c = 4
        tc = ignite[c]
        if tc >= 0:
            if (now - tc) < (hot_time * 0.7):
                px[c] = self._blend(px[c], 0xFFFFFF, 0.5)

        # quick sparks on K9..K11
        if t < 0.45:
            for k in self._spark_keys:
                if random.random() < 0.35:
                    px[k] = 0xFFFFFF

        try:
            px.show()
        except AttributeError:
            pass

    # ---------- tiny helpers ----------
    def _lights_off(self):
        for i in range(12):
            self.mac.pixels[i] = 0x000000
            
    def _rand_sample2(self, seq):
        n = len(seq)
        if n == 0:
            return []
        if n == 1:
            return [seq[0]]
        i = random.randrange(n)
        j = random.randrange(n - 1)
        if j >= i:
            j += 1
        return [seq[i], seq[j]] 

    def _scale(self, color, s):
        # Accept either 24-bit int or (r,g,b) tuple
        if isinstance(color, tuple):
            r, g, b = color
        else:
            r = (color >> 16) & 0xFF
            g = (color >> 8)  & 0xFF
            b = color & 0xFF
        r = int(r * s); g = int(g * s); b = int(b * s)
        return (r << 16) | (g << 8) | b

    def _hsv_to_rgb(self, h, s, v):
        i = int(h * 6.0) % 6
        f = (h * 6.0) - i
        p = int(255 * v * (1 - s))
        q = int(255 * v * (1 - f * s))
        t = int(255 * v * (1 - (1 - f) * s))
        vv = int(255 * v)
        if i == 0: r, g, b = vv, t, p
        elif i == 1: r, g, b = q, vv, p
        elif i == 2: r, g, b = p, vv, t
        elif i == 3: r, g, b = p, q, vv
        elif i == 4: r, g, b = t, p, vv
        else:        r, g, b = vv, p, q
        return (r << 16) | (g << 8) | b

    def _ease_cos(self, u):
        if u <= 0: return 0.0
        if u >= 1: return 1.0
        return 0.5 - 0.5 * math.cos(math.pi * u)

    def _blend(self, c1, c2, t):
        # Accept either 24-bit int or (r,g,b) tuple for c1/c2
        if isinstance(c1, tuple):
            r1, g1, b1 = c1
        else:
            r1, g1, b1 = (c1 >> 16) & 255, (c1 >> 8) & 255, c1 & 255

        if isinstance(c2, tuple):
            r2, g2, b2 = c2
        else:
            r2, g2, b2 = (c2 >> 16) & 255, (c2 >> 8) & 255, c2 & 255

        # clamp t just in case
        if t <= 0: return (r1 << 16) | (g1 << 8) | b1
        if t >= 1: return (r2 << 16) | (g2 << 8) | b2

        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return (r << 16) | (g << 8) | b

    # ---------- sounds ----------
    def _play(self, freq, dur):
        try:
            self.mac.play_tone(freq, dur)
        except Exception:
            pass

    def _click(self, key=None):
        f = 523  # default C5
        if key == self.K_NEW:
            f = 440
        elif key == self.K_ENTER:
            f = 659
        elif key is not None:
            try:
                if isinstance(self.tones, (list, tuple)) and len(self.tones) > 0:
                    f = self.tones[key % len(self.tones)]
            except Exception:
                pass
        self._play(f, 0.03)

    def _sound_error(self):
        self._play(220, 0.05)
        
    def _paint_won_ui(self):
        # turn everything off first
        for i in range(12):
            self.mac.pixels[i] = 0x000000
        # show K9 (New) as a dim white hint
        self.mac.pixels[self.K_NEW] = 0x202020
        try: self.mac.pixels.show()
        except AttributeError: pass
    
    def _mark_entry_dirty(self):
        self._ui_dirty = True

    def _paint_entry_static(self):
        """Heavywork: draw keypad + allowed tens only when something changed."""
        # Base all-off
        for i in range(12):
            self.mac.pixels[i] = 0x000000

        # Number keys idle
        for k in self.NUM_KEYS:
            self.mac.pixels[k] = self.C_NUM_IDLE

        # Guidance: allowed tens when no digits typed
        if not self.entry_digits:
            allowed = self._allowed_tens()
            for td in allowed:
                key = self._key_for_digit(td)
                if key is not None:
                    self.mac.pixels[key] = self.C_NUM_ACTIVE

        # Controls (K9 dim; K11 dynamic in tick)
        self.mac.pixels[self.K_NEW] = self.C_NEW

        try: self.mac.pixels.show()
        except AttributeError: pass

        # cache what we drew
        self._ui_dirty = False

    def _paint_entry_dynamic(self, pulse):
        """Cheap per-frame update for K11 pulse only."""
        self.mac.pixels[self.K_ENTER] = self._scale(self.C_ENTER, pulse)
        try: self.mac.pixels.show()
        except AttributeError: pass