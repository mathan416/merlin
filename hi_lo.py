# hi_lo.py — Master Merlin "Hi/Lo" for Adafruit MacroPad
# CircuitPython 8.x / 9.x compatible, non-blocking animations
# Written by Iain Bennett — 2025
# Inspired by Keith Tanner's Merlin for the Macropad
#
# License:
#   Released under the CC0 1.0 Universal (Public Domain Dedication).
#   You can copy, modify, distribute, and perform the work, even for commercial purposes,
#   all without asking permission. Attribution is appreciated but not required.
#
# Hi/Lo is a Master Merlin-style number guessing game where the player tries
# to guess a secret number between 0 and 99. After each guess, the MacroPad
# displays an arrow indicating whether the secret number is higher or lower.
# A green double arrow appears when the player wins.
#
# Controls:
#   • K0..K8 — Digits 1–9
#   • K10    — Digit 0
#   • K11    — Enter guess
#   • K9     — New game
#
# Features:
#   • On-screen status text showing guesses and hints
#   • LED arrow indicators for higher/lower hints
#   • Green win animation with double arrow
#   • Click sounds for key presses and distinct tones for win/hint/error

import time, math, random
import displayio, terminalio
from adafruit_display_text import label

class hi_lo:
    def __init__(self, macropad, tones):
        self.mac = macropad
        self.tones = tones

        # Colors
        self.BRIGHT          = 0.30
        self.C_BG            = 0x000000
        self.C_NUM_IDLE      = 0x102040  # dim steel-blue for number keys (idle)
        self.C_NUM_ACTIVE    = 0x3060A0  # brighter on press
        self.C_ENTER         = 0x00AA00  # green for K11
        self.C_NEW           = 0x202020  # dim white for K9
        self.C_HINT          = 0xFF0000  # red arrows
        self.C_WIN           = 0x00FF00  # green for win double arrow

        # Buttons
        self.K_NEW   = 9
        self.K_ENTER = 11
        self.K_ZERO  = 10
        self.NUM_KEYS = tuple(range(0, 9)) + (self.K_ZERO,)

        # Arrow shapes (as key indexes)
        self.ARROW_UP    = {1, 3, 4, 5, 7, 10}
        self.ARROW_DOWN  = {1, 4, 6, 7, 8, 10}
        self.ARROW_WIN   = {1, 3, 4, 5, 6, 7, 8, 10}

        # State
        self.mode = "entry"         # "entry" | "hint" | "won"
        self.entry_digits = []      # up to 2 digits
        self.target = 0
        self.tries = 0
        self.hint_until = 0.0

        # LED updates (simple batching)
        try:
            self.mac.pixels.auto_write = False
        except AttributeError:
            pass
        self.mac.pixels.brightness = self.BRIGHT
        self._win_cleared = False

        # Display
        self._build_display()

    # ---------- Public ----------
    def new_game(self):
        print("new Hi/Lo game")
        self.target = random.randint(0, 99)
        self.tries = 0
        self.entry_digits = []
        self.mode = "entry"
        self._update_status_for_entry()
        self._paint_entry_ui()
        self._show()
        self._win_cleared = False
        # print("DEBUG target:", self.target)

    def button(self, key):
        now = time.monotonic()

        # New game anytime
        if key == self.K_NEW:
            self._click(key)
            self.new_game()
            return

        # Ignore inputs during hint flash (very short)
        if self.mode == "hint" and now < self.hint_until:
            return

        # Enter
        if key == self.K_ENTER:
            if self.mode == "entry":
                self._click(key)
                self._commit_guess()
            return

        # Number keys while entering
        if self.mode == "entry":
            d = self._digit_for_key(key)
            if d is not None:
                self._click(key)
                self._press_digit_feedback(key)
                if len(self.entry_digits) >= 2:
                    # Keep last two digits (feel like a real 2-digit entry)
                    self.entry_digits = [self.entry_digits[-1], d]
                else:
                    self.entry_digits.append(d)
                self._update_status_for_entry()
                self._paint_entry_ui()
            return

    def tick(self):
        now = time.monotonic()

        # After hint flash, return to entry UI
        if self.mode == "hint" and now >= self.hint_until:
            self.mode = "entry"
            self._paint_entry_ui()
            self._update_status_for_entry()
            return

        # After a win, keep the double arrow up until hint_until,
        # then restore neutral LEDs (once), leaving Enter dark.
        if self.mode == "won":
            if not self._win_cleared and now >= self.hint_until:
                self._paint_entry_ui()                 # neutral keypad
                self.mac.pixels[self.K_ENTER] = 0x000000  # Enter off in won state
                try: self.mac.pixels.show()
                except AttributeError: pass
                self._win_cleared = True
            return

        # Normal entry-mode pulse
        if self.mode == "entry":
            pulse = 0.35 + 0.65 * (0.5 + 0.5 * math.cos(now * 2 * math.pi * 0.9))
            self.mac.pixels[self.K_ENTER] = self._scale(self.C_ENTER, pulse)
            self.mac.pixels[self.K_NEW] = self.C_NEW
            try: self.mac.pixels.show()
            except AttributeError: pass

    def cleanup(self):
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True

        # 1) Stop any sound
        try:
            if hasattr(self.mac, "stop_tone"):
                self.mac.stop_tone()
        except Exception:
            pass
        try:
            spk = getattr(self.mac, "speaker", None)
            if spk is not None:
                spk.enable = False
        except Exception:
            pass

        # 2) LEDs off (and restore auto_write so the launcher sees changes immediately)
        try:
            if hasattr(self.mac, "pixels"):
                try:
                    self.mac.pixels.auto_write = True
                except Exception:
                    pass
                self.mac.pixels.fill(0x000000)
                try: self.mac.pixels.show()
                except Exception: pass
        except Exception:
            pass

        # 3) Detach our display group and leave the screen in a neutral state
        try:
            disp = getattr(self, "mac", None)
            disp = getattr(disp, "display", None)
            if disp:
                # Avoid mid-frame flicker
                try: disp.auto_refresh = False
                except Exception: pass

                # Best-effort blank (no new allocations if possible)
                try:
                    # If we own the root, clear it
                    if getattr(disp, "root_group", None) is getattr(self, "group", None):
                        try:
                            disp.root_group = None     # CP 9.x
                        except Exception:
                            try: disp.show(None)       # CP 8.x
                            except Exception: pass
                    # Push a refresh so the launcher gets a clean canvas
                    try: disp.refresh(minimum_frames_per_second=0)
                    except TypeError:
                        disp.refresh()
                except Exception:
                    pass

                # Restore auto_refresh to default-on
                try: disp.auto_refresh = True
                except Exception: pass
        except Exception:
            pass

        # 4) Drop big references; let GC reclaim memory
        try:
            self.group = None
            # Optional: drop label refs if you like
            # self.title = None
            # self.status = None
        except Exception:
            pass

        # 5) GC sweep
        try:
            import gc
            gc.collect()
        except Exception:
            pass

    # ---------- Internals ----------
    def _digit_for_key(self, k):
        if 0 <= k <= 8:  # 1..9
            return k + 1
        if k == self.K_ZERO:
            return 0
        return None

    def _press_digit_feedback(self, key):
        # brief bright flash on the pressed number key
        self.mac.pixels[key] = self.C_NUM_ACTIVE
        try: self.mac.pixels.show()
        except AttributeError: pass
        time.sleep(0.05)
        self.mac.pixels[key] = self.C_NUM_IDLE
        try: self.mac.pixels.show()
        except AttributeError: pass

    def _commit_guess(self):
        if not self.entry_digits:
            self._set_status("Enter a number")
            return  # nothing entered
        # Parse 1–2 digits (single-digit allowed)
        if len(self.entry_digits) == 1:
            guess = self.entry_digits[0]
        else:
            guess = self.entry_digits[0] * 10 + self.entry_digits[1]

        # Clamp to 0..99 (paranoia)
        guess = max(0, min(99, guess))

        self.tries += 1
        if guess < self.target:
            self._flash_arrow(self.ARROW_UP, self.C_HINT, 1)
            self._set_status(f"{guess} — Higher")
            self._sound_tie()
        elif guess > self.target:
            self._flash_arrow(self.ARROW_DOWN, self.C_HINT, 1)
            self._set_status(f"{guess} — Lower")
            self._sound_tie()
        else:
            # Win!
            self._win_cleared = False
            self._flash_arrow(self.ARROW_WIN, self.C_WIN, 3)
            self._set_status(f"Correct! Tries: {self.tries}")
            self.mode = "won"
            self._sound_win()
            
            try:
                self.mac.pixels.show()
            except AttributeError:
                pass
  
            return

        # Back to entry for next try
        self.entry_digits = []

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

    def _paint_entry_ui(self):
        # Base all-off
        for i in range(12):
            self.mac.pixels[i] = 0x000000
        # Number keys dim steel-blue
        for k in self.NUM_KEYS:
            self.mac.pixels[k] = self.C_NUM_IDLE
        # K9 = dim white; K11 = green (pulsed by tick)
        self.mac.pixels[self.K_NEW] = self.C_NEW
        self.mac.pixels[self.K_ENTER] = self.C_ENTER
        try: self.mac.pixels.show()
        except AttributeError: pass

    # ---------- Display ----------
    def _build_display(self):
        W, H = self.mac.display.width, self.mac.display.height
        g = displayio.Group()

        # Background
        bg = displayio.Bitmap(W, H, 1)
        pal = displayio.Palette(1); pal[0] = self.C_BG
        g.append(displayio.TileGrid(bg, pixel_shader=pal))

        # --- Logo at the top (kept throughout the game) ---
        self.logo_tile = None
        logo_h = 0
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            x = max(0, (W - bmp.width) // 2)
            self.logo_tile = displayio.TileGrid(
                bmp,
                pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter()),
                x=x, y=0
            )
            g.append(self.logo_tile)
            logo_h = getattr(bmp, "height", 0)
        except Exception:
            # If the logo is missing, we just skip it
            logo_h = 0

        # Text sits just below the logo
        y0 = logo_h + 2  # small gap under the logo

        self.title = label.Label(
            terminalio.FONT, text="Hi / Lo",
            color=0xFFFFFF, anchor_point=(0.5, 0.0),
            anchored_position=(W // 2, y0)
        )
        g.append(self.title)

        self.status = label.Label(
            terminalio.FONT, text="Guess 0..99",
            color=0xA0A0A0, anchor_point=(0.5, 0.0),
            anchored_position=(W // 2, y0 + 14)
        )
        g.append(self.status)

        self.group = g

    # ---------- small helpers ----------
    def _scale(self, color, s):
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        r = int(r * s); g = int(g * s); b = int(b * s)
        return (r << 16) | (g << 8) | b
    
    def _show(self):
        try:
            self.mac.display.show(self.group)      # CP 8.x
        except AttributeError:
            self.mac.display.root_group = self.group  # CP 9.x
            
    def _set_status(self, text):
        # Safely update the status label
        if hasattr(self, "status") and self.status:
            self.status.text = text

    def _update_status_for_entry(self):
        # Show what the user has typed so far
        if not self.entry_digits:
            self._set_status("Guess 0..99")
        elif len(self.entry_digits) == 1:
            self._set_status(f"Guess: {self.entry_digits[0]}")
        else:
            val = self.entry_digits[0] * 10 + self.entry_digits[1]
            self._set_status(f"Guess: {val}")
            
    # ---------- sound helpers ----------
    def _play(self, freq, dur):
        try:
            self.mac.play_tone(freq, dur)
        except AttributeError:
            try:
                # fall back to first tone if available
                self.mac.play_tone(self.tones[0], dur)
            except Exception:
                pass

    def _tone_at(self, i, fallback):
        try:
            return self.tones[i]
        except Exception:
            return fallback[i % len(fallback)]

    def _click(self, key=None):
        # Default click pitch
        f = 523  # C5

        if key == self.K_NEW:          # New Game key
            f = 440                    # A4
        elif key == self.K_ENTER:      # Enter key
            f = 659                    # E5
        elif key is not None:
            try:
                if isinstance(self.tones, (list, tuple)) and len(self.tones) > 0:
                    f = self.tones[key % len(self.tones)]
            except Exception:
                pass

        self._play(f, 0.03)

    def _sound_win(self):
        fallback = [262, 330, 392, 523, 392, 523]  # C4 E4 G4 C5 G4 C5
        seq = [0, 2, 4, 6, 4, 6]
        for i in seq:
            self._play(self._tone_at(i, fallback), 0.2)

    def _sound_lost(self):
        fallback = [523, 392, 330, 262]  # C5 G4 E4 C4
        seq = [6, 4, 2, 0]
        for i in seq:
            self._play(self._tone_at(i, fallback), 0.3)

    def _sound_tie(self):
        fallback = [262, 330]  # C4 E4
        seq = [0]
        for i in seq:
            self._play(self._tone_at(i, fallback), 0.15)
    
    def _sound_error(self):
        self._play(220, 0.05)  # A3 low blip