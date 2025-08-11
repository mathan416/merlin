# my_game.py — Standard game template for Adafruit MacroPad (CircuitPython 8.x/9.x)
# Features:
#   • Background logo (MerlinChrome.bmp) if present
#   • Two text lines under the logo (top/bottom) with helpers
#   • LED helpers with dirty-flag updates
#   • Simple named timers
#   • CircuitPython-safe random unique picker
#   • Small sound wrappers

import time, displayio, terminalio
from random import randint
from adafruit_display_text import label

LOGO_BMP = "MerlinChrome.bmp"   # change if your asset name differs
TEXT_LINE_SPACING = 12          # pixels between top and bottom lines
TEXT_MARGIN = 2                 # pixels below the logo

class my_game:
    def __init__(self, macropad, tones=None, **kwargs):
        self.mac = macropad
        self.tones = tones or ()

        # LEDs
        try:
            self.mac.pixels.auto_write = False
        except AttributeError:
            pass
        self.mac.pixels.brightness = 0.30
        self._led_dirty = False

        # Display group (launcher will adopt this if present)
        self.group = self._build_ui()

        # Timing/state
        self._interval = 0.15
        self._next_step = time.monotonic()
        self._timers = {}

        # Initial UI text
        self._set_status("Pick a level", "1 to 9")

    # ---------- Lifecycle ----------
    def new_game(self):
        # Reset timers/state
        self._next_step = time.monotonic() + self._interval
        self._timers.clear()
        self.pixels_clear()
        self.pixels_show_if_dirty()

    def cleanup(self):
        # Stop sounds/animations, clear LEDs, restore auto_write
        self.pixels_clear()
        self.pixels_show_if_dirty()
        try:
            self.mac.pixels.auto_write = True
        except AttributeError:
            pass

    # ---------- Input ----------
    def button(self, key):
        # handle key down
        pass

    def encoderChange(self, pos, last_pos):
        # optional
        pass

    # ---------- Main loop ----------
    def tick(self):
        now = time.monotonic()
        if now >= self._next_step:
            self._step()
            self._next_step = now + self._interval
        # If you buffer LED changes, show only when needed.
        self.pixels_show_if_dirty()

    def _step(self):
        # game logic step; update LEDs/display as needed
        pass

    # ---------- UI: logo + two-line text ----------
    def _build_ui(self):
        group = displayio.Group()
        w = self.mac.display.width

        base_y = 0
        # Background logo (optional)
        try:
            bmp = displayio.OnDiskBitmap(LOGO_BMP)
            tile = displayio.TileGrid(
                bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            group.append(tile)  # draw first so text is on top
            base_y = getattr(bmp, "height", 0) + TEXT_MARGIN
        except Exception:
            # No logo: start a bit down from top so it still looks nice
            base_y = 14

        # Two compact text lines under the logo
        self._lbl_top = label.Label(
            terminalio.FONT, text="", color=0xFFFFFF,
            anchor_point=(0.5, 0.0), anchored_position=(w // 2, base_y)
        )
        group.append(self._lbl_top)

        self._lbl_bottom = label.Label(
            terminalio.FONT, text="", color=0xFFFFFF,
            anchor_point=(0.5, 0.0),
            anchored_position=(w // 2, base_y + TEXT_LINE_SPACING)
        )
        group.append(self._lbl_bottom)

        return group

    def _set_top(self, text: str):
        try:
            self._lbl_top.text = text
        except Exception:
            pass

    def _set_bottom(self, text: str):
        try:
            self._lbl_bottom.text = text
        except Exception:
            pass

    def _set_status(self, top: str = "", bottom: str = ""):
        self._set_top(top)
        self._set_bottom(bottom)

    # ---------- LEDs: utilities ----------
    def pixels_fill(self, rgb: int):
        """Fill all 12 keys with a 24-bit RGB int (e.g., 0xRRGGBB)."""
        for i in range(12):
            self.mac.pixels[i] = rgb
        self._led_dirty = True

    def pixels_clear(self):
        self.pixels_fill(0x000000)

    def set_pixel(self, idx: int, rgb: int):
        """Set a single key (0..11) and mark dirty."""
        if 0 <= idx < 12:
            self.mac.pixels[idx] = rgb
            self._led_dirty = True

    def pixels_show_if_dirty(self):
        """Call pixels.show() only when something actually changed."""
        if self._led_dirty:
            try:
                self.mac.pixels.show()
            except AttributeError:
                pass
            self._led_dirty = False

    def flash_key(self, idx: int, rgb_on: int, dur: float = 0.05, rgb_off: int = 0x000000):
        """Quick visual blip on a key; blocking but tiny."""
        if 0 <= idx < 12:
            old = self.mac.pixels[idx]
            self.mac.pixels[idx] = rgb_on
            self.pixels_show_if_dirty()
            time.sleep(max(0.02, dur))
            self.mac.pixels[idx] = rgb_off if rgb_off is not None else old
            self.pixels_show_if_dirty()

    def _gradient_color_for_index(self, i: int) -> int:
        """K0..K8 mapped green→red (easy→hard); returns 0xRRGGBB."""
        t = 0.0 if i <= 0 else (1.0 if i >= 8 else (i / 8.0))  # clamp to [0,1]
        r = int(255 * t)
        g = int(255 * (1.0 - t))
        return (r << 16) | (g << 8)  # (r,g,0)

    def paint_skill_gradient(self):
        """Paint K0..K8 as green→red gradient, leave others untouched."""
        for i in range(9):
            self.set_pixel(i, self._gradient_color_for_index(i))
        # Hints (tweak per game)
        self.set_pixel(9,  0x202020)
        self.set_pixel(10, 0x000000)
        self.set_pixel(11, 0x000000)

    # ---------- Timing: simple named timers ----------
    def timer_set(self, name: str, seconds: float):
        """Start/replace a timer; check with timer_due(name)."""
        self._timers[name] = time.monotonic() + max(0.0, seconds)

    def timer_due(self, name: str) -> bool:
        """Return True if timer exists and is past due."""
        t = self._timers.get(name)
        return (t is not None) and (time.monotonic() >= t)

    def timer_cancel(self, name: str):
        self._timers.pop(name, None)

    # ---------- Random: CircuitPython-safe unique picker ----------
    def pick_unique(self, count: int, low: int = 0, high: int = 8):
        """Return up to `count` unique ints in [low..high] without replacement."""
        pool = list(range(low, high + 1))
        out = []
        for _ in range(min(count, len(pool))):
            i = randint(0, len(pool) - 1)
            out.append(pool.pop(i))
        return out

    # ---------- Sound: small wrappers ----------
    def click(self, freq: int = 440, ms: int = 60):
        """Short UI click."""
        try:
            self.mac.play_tone(int(freq), ms / 1000.0)
        except Exception:
            pass

    def buzz(self, freq: int = 110, ms: int = 200):
        """Short error buzz."""
        try:
            self.mac.play_tone(int(freq), ms / 1000.0)
        except Exception:
            pass

    def beep(self, freq: int, ms: int = 120):
        """General-purpose beep."""
        try:
            self.mac.play_tone(int(freq), ms / 1000.0)
        except Exception:
            pass