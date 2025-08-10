# hi_lo.py — Master Merlin "Hi/Lo" for Adafruit MacroPad
# Guess 0..99. K0..K8 = 1..9, K10 = 0, K11 = Enter, K9 = New
# Shows red UP/DOWN arrows; green double arrow on win. Displays tries.

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
            self.new_game()
            return

        # Ignore inputs during hint flash (very short)
        if self.mode == "hint" and now < self.hint_until:
            return

        # Enter
        if key == self.K_ENTER:
            if self.mode == "entry":
                self._commit_guess()
            return

        # Number keys while entering
        if self.mode == "entry":
            d = self._digit_for_key(key)
            if d is not None:
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
        try:
            self.mac.pixels.auto_write = True
        except AttributeError:
            pass
        for i in range(12):
            self.mac.pixels[i] = 0x000000
        try: self.mac.pixels.show()
        except AttributeError: pass

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
        elif guess > self.target:
            self._flash_arrow(self.ARROW_DOWN, self.C_HINT, 1)
            self._set_status(f"{guess} — Lower")
        else:
            # Win!
            self._win_cleared = False
            self._flash_arrow(self.ARROW_WIN, self.C_WIN, 3)
            self._set_status(f"Correct! Tries: {self.tries}")
            self.mode = "won"
            
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