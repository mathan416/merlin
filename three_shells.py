# three_shells.py — Master Merlin "Three Shells" for Adafruit MacroPad
# K3, K4, K5 are the shells. Skill select uses K0..K8 with a rainbow.
# Auto-start the round immediately after selecting skill.
# Written by Iain Bennett - 2025

import time, math, random
import displayio, terminalio
from adafruit_display_text import label

class three_shells:
    def __init__(self, macropad, tones):
        self.mac = macropad
        self.tones = tones

        # Batch LED writes to prevent flicker
        try:
            self.mac.pixels.auto_write = False
        except AttributeError:
            pass

        # Keys
        self.K_NEW = 9
        self.SHELL_KEYS = (3, 4, 5)             # left, middle, right
        self.SKILL_KEYS = tuple(range(0, 9))     # K0..K8 -> skill 1..9

        # Colors
        self.BRIGHT = 0.30
        self.C_WHITE = 0xFFFFFF
        self.C_RED   = 0xFF0000
        self.C_BLUE  = 0x0000FF
        self.C_DIM   = 0x050505
        self.fade_outs = []

        # Timings
        self.SHOW_BALL_TIME    = 0.8
        self.SWAP_FLASH_TIME   = 0.13
        self.PAUSE_AFTER_ROUND = 0.6

        # Guess-phase pulse
        self.GUESS_PULSE_HZ   = 0.9
        self.GUESS_MIN_SCALE  = 0.18
        self.GUESS_MAX_SCALE  = 0.34

        # State
        self.mode = "skill"
        self.skill = 3
        self.ball_index = 1
        self.swap_plan = []
        self.swap_i = 0
        self.phase_until = 0.0
        self.score = 0
        self.rounds = 0

        # Display
        self._build_display()
        self._show()
        self._update_score_text()
        self._show_drawn = False

    # ---------- Cleanup ----------
    def cleanup(self):
        self.fade_outs = []
        try:
            self.mac.pixels.auto_write = True
        except AttributeError:
            pass
        for i in range(12):
            self.mac.pixels[i] = 0x000000
        self._led_show()

    # ---------- Public API ----------
    def new_game(self):
        self._enter_skill_select()
        self._show()

    def button(self, key):
        now = time.monotonic()

        if self.mode == "skill":
            if key in self.SKILL_KEYS:
                self.skill = key + 1  # K0=1 .. K8=9
                self._beep(659, 0.04)
                self._start_round()
            elif key == self.K_NEW:
                self._start_round()
            return

        if key == self.K_NEW:
            self._enter_skill_select()
            return

        if self.mode != "guess":
            return

        if key in self.SHELL_KEYS:
            guess_idx = self.SHELL_KEYS.index(key)
            self._handle_guess(guess_idx, now)

    def encoderChange(self, *_):
        return

    def tick(self):
        now = time.monotonic()

        # Reveal-mode red fades (non-blocking)
        if self.mode == "reveal" and self.fade_outs:
            to_remove = []
            for (idx, start, dur) in list(self.fade_outs):
                t = (now - start) / dur
                if t >= 1.0:
                    self.mac.pixels[idx] = 0x000000
                    to_remove.append((idx, start, dur))
                else:
                    # cosine ease-out for smoothness
                    s = 0.25 * (0.5 + 0.5 * math.cos(t * math.pi))
                    self.mac.pixels[idx] = self._scale(self.C_RED, max(0.0, s))
            for item in to_remove:
                self.fade_outs.remove(item)
            self._led_show()

        if self.mode == "skill":
            self._render_skill(now)
            return

        if self.mode == "show":
            if not getattr(self, "_show_drawn", False):  # <-- only once
                self._render_board(high_ball=True)
                self._show_drawn = True
            if now >= self.phase_until:
                self._enter_shuffle(now)
            return

        if self.mode == "shuffle":
            if now >= self.phase_until:
                self._next_swap(now)
            return

        if self.mode == "guess":
            self._render_guess_pulse(now)
            return

        if self.mode == "reveal":
            if now >= self.phase_until:
                self._start_round()
            return

    # ---------- Skill select ----------
    def _enter_skill_select(self):
        self.mode = "skill"
        self.score = 0
        self.rounds = 0
        self._show_drawn = False
        self._all_off()
        self.status.text = f"Skill: {self.skill}"
        self._render_skill(time.monotonic())
        self._show()

    def _skill_color(self, idx):
        # idx: 0..8 (K0..K8)
        if idx <= 2:
            t = idx / 2.0
            r, g, b = 0, int(255*t), int(255*(1-t))
        elif idx <= 5:
            t = (idx - 3) / 2.0
            r, g, b = int(255*t), 255, 0
        else:
            t = (idx - 6) / 2.0
            r, g, b = 255, int(255*(1 - t)), 0
        return (r << 16) | (g << 8) | b

    def _render_skill(self, now):
        self.mac.pixels.brightness = self.BRIGHT

        # gradient across K0..K8
        for i in range(9):
            self.mac.pixels[i] = self._skill_color(i)

        # blank K9..K11 during skill select
        for k in (9, 10, 11):
            self.mac.pixels[k] = 0x000000

        # pulse speed increases with skill
        if self.skill is not None:
            sel = self.skill - 1
            min_hz, max_hz = 0.6, 1.5
            freq = min_hz + (self.skill - 1) * (max_hz - min_hz) / 8.0
            pulse = 0.5 + 0.5 * math.cos(now * 2 * math.pi * freq)
            base = self._skill_color(sel)
            self.mac.pixels[sel] = self._scale(base, 0.5 + 0.5 * pulse)

        self._led_show()

    # ---------- Round flow ----------
    def _start_round(self):
        self.fade_outs = []
        self.rounds += 1
        self._all_off()
        self.ball_index = random.randrange(3)
        self.mode = "show"
        self._show_drawn = False          # <-- and reset here
        self.phase_until = time.monotonic() + self.SHOW_BALL_TIME
        self._update_score_text()
        # (tick() will render the high_ball frame once)

    def _enter_shuffle(self, now):
        self.mode = "shuffle"
        swap_count = 4 + self.skill * 2   # 6..22 swaps for skill 1..9
        self.swap_plan = self._make_swaps(swap_count)
        self.swap_i = 0
        self._next_swap(now)

    def _next_swap(self, now):
        if self.swap_i >= len(self.swap_plan):
            self.mode = "guess"
            self._render_board()
            return
        a, b = self.swap_plan[self.swap_i]
        self._swap_ball_if_needed(a, b)
        self._flash_swap(a, b, now)
        self.swap_i += 1

    def _handle_guess(self, guess_idx, now):
        self._all_off()
        correct = (guess_idx == self.ball_index)

        # Prepare fades for the two wrong shells
        self.fade_outs = []
        for i, shell_key in enumerate(self.SHELL_KEYS):
            if i != self.ball_index:
                self.mac.pixels[shell_key] = self._scale(self.C_RED, 0.25)
                self.fade_outs.append((shell_key, now, 0.4))

        if correct:
            self.score += 1
            self.mac.pixels[self.SHELL_KEYS[guess_idx]] = 0x00FF00
            self._beep(784, 0.06)
        else:
            self.mac.pixels[self.SHELL_KEYS[self.ball_index]] = self.C_BLUE
            self._beep(220, 0.07)

        self._update_score_text()
        self._led_show()
        self.mode = "reveal"
        self.phase_until = now + self.PAUSE_AFTER_ROUND

    # ---------- Visuals ----------
    def _render_board(self, high_ball=False):
        self.mac.pixels.brightness = self.BRIGHT

        # Everything off first
        for k in range(12):
            self.mac.pixels[k] = 0x000000

        # Reset key dim hint
        self.mac.pixels[self.K_NEW] = self._scale(self.C_WHITE, 0.10)

        # Shell keys dim gray
        for k in self.SHELL_KEYS:
            self.mac.pixels[k] = self.C_DIM

        # Highlight the ball if requested (batched with the above)
        if high_ball:
            self.mac.pixels[self.SHELL_KEYS[self.ball_index]] = self.C_WHITE

        self._led_show()

    def _render_guess_pulse(self, now):
        self.mac.pixels.brightness = self.BRIGHT

        # non-shell keys off, except K9 dim hint
        for k in range(12):
            if k == self.K_NEW:
                self.mac.pixels[k] = self._scale(self.C_WHITE, 0.10)
            elif k not in self.SHELL_KEYS:
                self.mac.pixels[k] = 0x000000

        # cosine pulse between MIN and MAX on shells
        u = 0.5 + 0.5 * math.cos(now * 2 * math.pi * self.GUESS_PULSE_HZ)
        s = self.GUESS_MIN_SCALE + (self.GUESS_MAX_SCALE - self.GUESS_MIN_SCALE) * u
        for k in self.SHELL_KEYS:
            self.mac.pixels[k] = self._scale(self.C_WHITE, s)

        self._led_show()

    def _flash_swap(self, a, b, now):
        keys = (self.SHELL_KEYS[a], self.SHELL_KEYS[b])
        self._render_board(high_ball=False)
        self.mac.pixels[keys[0]] = self.C_WHITE
        self.mac.pixels[keys[1]] = self.C_WHITE
        self._led_show()
        self.phase_until = now + self.SWAP_FLASH_TIME

    # ---------- Swap plan ----------
    def _make_swaps(self, n):
        pairs = [(0,1), (1,2), (0,2)]
        last = None
        plan = []
        for _ in range(n):
            a, b = random.choice(pairs)
            if last and (a,b) in (last, (last[1], last[0])):
                choices = [p for p in pairs if p not in (last, (last[1], last[0]))]
                a, b = random.choice(choices)
            plan.append((a, b))
            last = (a, b)
        return plan

    def _swap_ball_if_needed(self, a, b):
        if self.ball_index == a:
            self.ball_index = b
        elif self.ball_index == b:
            self.ball_index = a

    # ---------- Display ----------
    def _build_display(self):
        W, H = self.mac.display.width, self.mac.display.height
        self.group = displayio.Group()

        y = 0
        self.logo_tile = None
        try:
            logo_bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            self.logo_tile = displayio.TileGrid(
                logo_bmp,
                pixel_shader=logo_bmp.pixel_shader,
                x=(W - logo_bmp.width)//2,
                y=y
            )
            self.group.append(self.logo_tile)
            y += logo_bmp.height + 2
        except Exception as e:
            print("Logo load failed:", e)

        self.title = label.Label(
            terminalio.FONT, text="Three Shells",
            color=0xFFFFFF, anchor_point=(0.5, 0.0),
            anchored_position=(W//2, y)
        )
        self.group.append(self.title)
        y += 12 + 2

        self.status = label.Label(
            terminalio.FONT, text="",
            color=0xAAAAAA, anchor_point=(0.5, 0.0),
            anchored_position=(W//2, y)
        )
        self.group.append(self.status)

    def _show(self):
        try:
            self.mac.display.root_group = self.group
        except AttributeError:
            self.mac.display.show(self.group)

    def _update_score_text(self):
        self.status.text = f"Score: {self.score}"

    # ---------- LED helpers ----------
    def _all_off(self):
        self.mac.pixels.brightness = self.BRIGHT
        for i in range(12):
            self.mac.pixels[i] = 0x000000
        self._led_show()

    def _scale(self, color, s):
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        r = int(r * s); g = int(g * s); b = int(b * s)
        return (r << 16) | (g << 8) | b

    def _led_show(self):
        try:
            self.mac.pixels.show()
        except AttributeError:
            pass

    def _beep(self, f, d):
        try:
            self.mac.play_tone(f, d)
        except Exception:
            pass