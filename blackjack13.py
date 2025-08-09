# blackjack13.py — Merlin-style Blackjack 13 for Adafruit MacroPad
# CircuitPython 8.x / 9.x compatible, non-blocking where it counts
# Written by Iain Bennett — 2025

import time
import math
import random
import displayio
import terminalio
from adafruit_display_text import label

class blackjack13:
    def __init__(self, macropad, tones):
        self.mac = macropad
        self.tones = tones

        # ---- Config ----
        self.BRIGHT = 0.30
        self.COLOR_BG = 0x000000
        self.COLOR_HUMAN = 0xFF0000  # RED player
        self.COLOR_CPU   = 0x0000FF  # BLUE dealer

        # Wipe palette (Simon-style)
        self.WIPE_COLORS = [
            0xF400FD, 0xDE04EE, 0xC808DE,
            0xB20CCF, 0x9C10C0, 0x8614B0,
            0x6F19A1, 0x591D91, 0x432182,
            0x2D2573, 0x172963, 0x012D54
        ]

        # Pulsing/frame timings
        self.PULSE_FRAME_DT   = 0.03
        self.PULSE_PHASE_STEP = 0.05

        # Deal animation (non-blocking)
        self.DEAL_FRAME_DT = 0.06

        # Controls
        self.BTN_NEW   = 9   # K9  : New
        self.BTN_STAND = 10  # K10 : Stand
        self.BTN_HIT   = 11  # K11 : Hit

        # Game state
        self.reset_state()

        # build UI
        self._build_display()

    # ---------------- UI ----------------
    def _build_display(self):
        W, H = self.mac.display.width, self.mac.display.height
        self.group = displayio.Group()

        bg_bitmap = displayio.Bitmap(W, H, 1)
        pal = displayio.Palette(1)
        pal[0] = self.COLOR_BG
        self.group.append(displayio.TileGrid(bg_bitmap, pixel_shader=pal))

        self.status = label.Label(
            terminalio.FONT, text="Blackjack 13",
            color=0xFFFFFF, anchor_point=(0.5, 0.0), anchored_position=(W//2, 0)
        )
        self.you_line = label.Label(
            terminalio.FONT, text="You: 0",
            color=0xFFFFFF, anchor_point=(0.0, 0.0), anchored_position=(4, 12)
        )
        self.cpu_line = label.Label(
            terminalio.FONT, text="CPU: —",
            color=0xFFFFFF, anchor_point=(0.0, 0.0), anchored_position=(4, 22)
        )
        self.controls = label.Label(
            terminalio.FONT, text="New   Stand   Hit",
            color=0xAAAAAA, anchor_point=(0.5, 0.0), anchored_position=(W//2, 34)
        )
        self.group.append(self.status)
        self.group.append(self.you_line)
        self.group.append(self.cpu_line)
        self.group.append(self.controls)

    def _show(self):
        try:
            self.mac.display.root_group = self.group
        except AttributeError:
            self.mac.display.show(self.group)

    # -------------- Public API --------------
    def new_game(self):
        print("new Blackjack 13")
        self.reset_state()
        self._lights_clear()
        # Start-game wipe (Simon-style), then show UI
        self._start_game_wipe()
        self._show()

    def button(self, key_number):
        if self.game_over:
            # Allow immediate restart via K9 (New)
            if key_number == self.BTN_NEW:
                self._reset_new()
            return

        if key_number == self.BTN_NEW:
            self._reset_new()

        elif key_number == self.BTN_STAND:
            if self.player_turn and not self.deal_anim_active:
                self.player_turn = False
                self.status.text = "Dealer's turn…"
                # arm non-blocking dealer state machine
                self.dealer_target = max(10, self.player_total)
                self.dealer_phase = "drawing"           # "idle" | "drawing" | "resolve" | "done"
                self.dealer_next_time = time.monotonic()  # draw ASAP

        elif key_number == self.BTN_HIT:
            if self.player_turn and not self.deal_anim_active:
                self._deal_to_player()

    def encoderChange(self, position, last_position):
        return

    def tick(self):
        now = time.monotonic()

        # Run endgame pulses if active
        if self.anim_mode == "endgame":
            self._run_end_anim(now)
            self._render_controls(pulse=self._pulse(now), endgame=True)
            return

        # Run deal animation if active
        if self.deal_anim_active:
            self._run_deal_anim(now)
            # controls still render during animation
            self._render_controls(pulse=self._pulse(now), endgame=False)
            return

        # Advance non-blocking dealer state (only when not animating)
        if (not self.game_over) and (self.dealer_phase in ("drawing", "resolve")):
            if self.dealer_phase == "drawing" and now >= self.dealer_next_time:
                # Decide whether to draw another card
                if self.dealer_total < 13 and self.dealer_total < self.dealer_target:
                    v = self._deal_card()
                    self.dealer_total += v
                    self.cpu_line.text = "CPU: {}".format(self.dealer_total)

                    # Kick off a deal animation for the dealer
                    self._start_deal_anim("dealer", v)

                    # Schedule a small pause before possibly drawing again
                    self.dealer_next_time = now + self.DEAL_FRAME_DT * (v + 2)

                    # If this draw reaches target or busts, resolve after this anim
                    if self.dealer_total > 13 or self.dealer_total >= self.dealer_target:
                        self.dealer_phase = "resolve"
                else:
                    # No more draws needed; resolve immediately
                    self.dealer_phase = "resolve"

            if self.dealer_phase == "resolve":
                # Decide outcome
                if self.dealer_total > 13:
                    self.status.text = "Dealer busts! You win."
                    self._end_round(winner="you")
                else:
                    if self.dealer_total > self.player_total:
                        self.status.text = "CPU wins."
                        self._end_round(winner="cpu")
                    elif self.dealer_total < self.player_total:
                        self.status.text = "You win!"
                        self._end_round(winner="you")
                    else:
                        self.status.text = "Tie game."
                        self._end_round(winner="tie")
                self.dealer_phase = "done"

        # Normal refresh
        if now - self._last_blink >= 0.03:
            self._last_blink = now
            pulse = self._pulse(now)
            self._render_idle_leds()  # clear board keys unless a deal just happened
            self._render_controls(pulse=pulse, endgame=self.game_over)

    # -------------- State & internals --------------
    def reset_state(self):
        self.player_total = 0
        self.dealer_total = 0
        self.player_turn = True
        self.game_over = False

        self._last_blink  = time.monotonic()

        # endgame anim
        self.anim_mode = None
        self.anim_colors = []
        self.anim_idx = 0
        self.anim_last = 0.0
        self.anim_pulses_per_color = 1
        self.anim_pulse_phase = 0.0

        # deal anim
        self.deal_anim_active = False
        self.deal_for = None      # "player" or "dealer"
        self.deal_value = 0
        self.deal_idx = 0
        self.deal_last = 0.0

        # dealer state machine
        self.dealer_phase = "idle"  # "idle" | "drawing" | "resolve" | "done"
        self.dealer_target = 0
        self.dealer_next_time = 0.0

    def _lights_clear(self):
        self.mac.pixels.brightness = self.BRIGHT
        for i in range(12):
            self.mac.pixels[i] = 0x000000

    def _scale(self, color, s):
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        r = int(r * s); g = int(g * s); b = int(b * s)
        return (r << 16) | (g << 8) | b

    def _blend(self, c1, c2, t):
        r1, g1, b1 = (c1 >> 16) & 0xFF, (c1 >> 8) & 0xFF, c1 & 0xFF
        r2, g2, b2 = (c2 >> 16) & 0xFF, (c2 >> 8) & 0xFF, c2 & 0xFF
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return (r << 16) | (g << 8) | b

    def _pulse(self, now):
        # Cosine pulse directly on wall time
        return 0.5 + 0.5 * math.cos(now * 2 * math.pi * 1.4)

    def _render_idle_leds(self):
        # During idle (no deal anim), keep board keys off
        for i in range(9):
            self.mac.pixels[i] = 0x000000

    def _render_controls(self, pulse, endgame: bool):
        if endgame or self.game_over:
            # Endgame: only invite restart on K9, others off
            self.mac.pixels[self.BTN_NEW]   = self._blend(0xFFFFFF, self.COLOR_HUMAN, pulse)
            self.mac.pixels[self.BTN_STAND] = 0x000000  # does nothing now
            self.mac.pixels[self.BTN_HIT]   = 0x000000
        else:
            # During play:
            # K9 dim white, K10 pulse blue, K11 pulse red on player's turn
            self.mac.pixels[self.BTN_NEW]   = self._scale(0xFFFFFF, 0.12)
            self.mac.pixels[self.BTN_STAND] = self._scale(self.COLOR_CPU, 0.35 + 0.65 * pulse)
            if self.player_turn:
                self.mac.pixels[self.BTN_HIT] = self._scale(self.COLOR_HUMAN, 0.35 + 0.65 * pulse)
            else:
                self.mac.pixels[self.BTN_HIT] = 0x000000

    # --------- Game mechanics ----------
    def _deal_card(self):
        # Values 1..7 keeps the pace toward 13
        return random.randint(1, 7)

    def _sound_click(self, ix):
        # reuse tones for delightful clicks
        try:
            f = self.tones[ix % len(self.tones)]
        except Exception:
            f = 523
        try:
            self.mac.play_tone(f, 0.03)
        except Exception:
            pass

    def _sound_error(self):
        try:
            self.mac.play_tone(140, 0.08)
        except Exception:
            pass

    def _sound_win(self):
        for f in (660, 880, 990):
            try: self.mac.play_tone(f, 0.05)
            except Exception: pass

    def _sound_lose(self):
        for f in (440, 330, 220):
            try: self.mac.play_tone(f, 0.06)
            except Exception: pass

    def _sound_tie(self):
        for f in (523, 523):
            try: self.mac.play_tone(f, 0.05)
            except Exception: pass

    def _deal_to_player(self):
        v = self._deal_card()
        self.player_total += v
        self.you_line.text = "You: {}".format(self.player_total)
        # start non-blocking deal anim showing value v on keys 0..v-1 in red
        self._start_deal_anim("player", v)
        self._sound_click(v)

        if self.player_total > 13:
            self.status.text = "Bust! CPU wins."
            self._end_round(winner="cpu")

    # --------- Deal animation (non-blocking) ----------
    def _start_deal_anim(self, who, value):
        self.deal_anim_active = True
        self.deal_for = who              # "player" or "dealer"
        self.deal_value = max(1, min(9, value))  # cap at 9 LEDs visible
        self.deal_idx = 0
        self.deal_last = time.monotonic()

    def _run_deal_anim(self, now):
        if now - self.deal_last < self.DEAL_FRAME_DT:
            return
        self.deal_last = now

        # clear board area
        for i in range(9):
            self.mac.pixels[i] = 0x000000

        color = self.COLOR_HUMAN if self.deal_for == "player" else self.COLOR_CPU

        # light up from 0..deal_idx
        upto = min(self.deal_idx, self.deal_value - 1)
        for i in range(upto + 1):
            self.mac.pixels[i] = color

        self.deal_idx += 1
        if self.deal_idx > self.deal_value + 1:
            # one extra frame to "hold" then stop
            self.deal_anim_active = False
            # leave the board cleared after the anim
            for i in range(9):
                self.mac.pixels[i] = 0x000000
            # tick() will handle any pending dealer resolve immediately

    # --------- Start Game Wipe (Simon-style) ----------
    def _start_game_wipe(self):
        self.mac.pixels.brightness = self.BRIGHT
        # Blue dot sweep; then reveal palette; then triad (0.5s each to match Simon/TTT); then fade
        for x in range(12):
            self.mac.pixels[x] = 0x000099
            time.sleep(0.06)
            self.mac.pixels[x] = self.WIPE_COLORS[x]

        # triad — match simon.py & tictactoe.py timing
        try:
            if len(self.tones) >= 5:
                self.mac.play_tone(self.tones[0], 0.5)
                self.mac.play_tone(self.tones[2], 0.5)
                self.mac.play_tone(self.tones[4], 0.5)
        except Exception:
            pass

        # fade palette to black
        for s in (0.4, 0.2, 0.1, 0.0):
            for i in range(12):
                c = self.WIPE_COLORS[i]
                r = int(((c >> 16) & 0xFF) * s)
                g = int(((c >> 8) & 0xFF) * s)
                b = int((c & 0xFF) * s)
                self.mac.pixels[i] = (r << 16) | (g << 8) | b
            time.sleep(0.02)
        self._lights_clear()

    # --------- Endgame animation ----------
    def _start_end_anim(self, colors, pulses_per_color=1):
        self.anim_mode = "endgame"
        self.anim_colors = colors
        self.anim_pulses_per_color = pulses_per_color
        self.anim_idx = 0
        self.anim_pulse_phase = 0.0
        self.anim_last = time.monotonic()

    def _run_end_anim(self, now):
        if self.anim_idx >= len(self.anim_colors):
            self._stop_anim()
            self._render_idle_leds()
            return

        if now - self.anim_last >= self.PULSE_FRAME_DT:
            self.anim_last = now
            self.anim_pulse_phase += self.PULSE_PHASE_STEP
            pulse = 0.5 + 0.5 * math.cos(self.anim_pulse_phase * 2 * math.pi * 1.2)
            scaled_color = self._scale(self.anim_colors[self.anim_idx], 0.35 + 0.65 * pulse)
            for i in range(9):
                self.mac.pixels[i] = scaled_color

            if self.anim_pulse_phase >= self.anim_pulses_per_color:
                self.anim_pulse_phase = 0.0
                self.anim_idx += 1

    def _reset_new(self):
        if self.anim_mode is not None:
            self._stop_anim()
        self.reset_state()
        self.you_line.text = "You: 0"
        self.cpu_line.text = "CPU: —"
        self.status.text = "Blackjack 13"
        self._lights_clear()
        self._start_game_wipe()
        self._show()

    def _end_round(self, winner):
        """Finish the round and kick off endgame pulses."""
        self.game_over = True
        if winner == "you":
            self._sound_win()
            self._start_end_anim([self.COLOR_HUMAN], pulses_per_color=3)
        elif winner == "cpu":
            self._sound_lose()
            self._start_end_anim([self.COLOR_CPU], pulses_per_color=3)
        else:
            self._sound_tie()
            self._start_end_anim([0xFFFFFF, self.COLOR_CPU, self.COLOR_HUMAN], pulses_per_color=1)
        
    def _stop_anim(self):
        self.anim_mode = None
        self.anim_colors = []
        self.anim_idx = 0
        # visuals are handled by tick()