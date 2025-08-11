# my_game.py
import time, displayio, terminalio
from adafruit_display_text import label

class my_game:
    def __init__(self, macropad, tones=None, **kwargs):
        self.mac = macropad
        self.tones = tones or ()
        # LEDs
        try: self.mac.pixels.auto_write = False
        except AttributeError: pass
        self.mac.pixels.brightness = 0.30
        # Display
        self.group = displayio.Group()
        self.title = label.Label(terminalio.FONT, text="My Game", color=0xFFFFFF,
                                 anchor_point=(0.5, 0.0),
                                 anchored_position=(self.mac.display.width//2, 0))
        self.group.append(self.title)
        # Timing/state
        self._interval = 0.15
        self._next_step = time.monotonic()

    def new_game(self):
        # reset state
        self._next_step = time.monotonic() + self._interval
        # draw initial LEDs
        for i in range(12): self.mac.pixels[i] = 0
        try: self.mac.pixels.show()
        except AttributeError: pass

    def button(self, key):
        # handle key down
        pass

    def tick(self):
        now = time.monotonic()
        if now >= self._next_step:
            self._step()
            self._next_step = now + self._interval
        # lightweight per-frame LED update (only if changed)

    def _step(self):
        # game logic step; update LEDs/display as needed
        pass

    def encoderChange(self, pos, last_pos):
        # optional
        pass

    def cleanup(self):
        # stop sounds/animations, clear LEDs, restore auto_write
        for i in range(12): self.mac.pixels[i] = 0
        try: self.mac.pixels.show()
        except AttributeError: pass
        try: self.mac.pixels.auto_write = True
        except AttributeError: pass