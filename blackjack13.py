# blackjack13.py — Merlin-style Blackjack 13 for Adafruit MacroPad
# CircuitPython 8.x / 9.x compatible, non-blocking animations
# Written by Iain Bennett — 2025
# Inspired by Keith Tanner's Merlin for the Macropad
#
# Blackjack 13 is a fast-paced, simplified variant of Blackjack where the goal
# is to get as close to 13 as possible without going over.
# 
# Controls:
#   • K9  – New Game
#   • K10 – Stand (end your turn, dealer draws)
#   • K11 – Hit (draw another card)
# 
# Features:
#   • Animated LED sweeps for card deals
#   • Pulsing LED indicators during endgame
#   • Non-blocking state machine for smooth gameplay
#   • Distinct sound cues for clicks, wins, losses, and ties

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

        # Pulsing/frame timings
        self.PULSE_FRAME_DT   = 0.03
        self.PULSE_PHASE_STEP = 0.05

        # Deal animation (non-blocking)
        self.DEAL_FRAME_DT = 0.06

        # Controls
        self.BTN_NEW   = 9   # K9  : New
        self.BTN_STAND = 10  # K10 : Stand
        self.BTN_HIT   = 11  # K11 : Hit
        
        # Wave animation (dealt-number) tuning
        self.WAVE_FRAME_DT = 0.02     # 50 FPS target
        self.WAVE_SPEED    = 10.0     # LEDs per second (crest speed)
        self.WAVE_SPAN     = 1.4      # crest half-width in LEDs (larger = thicker wave)
        self.TRAIL_DECAY   = 0.85     # per-frame decay of the trail (0.8–0.9 looks good)
        self.MIN_GLOW      = 0.03     # floor so the trail is faint but visible

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
                    self.status.text = "Bust! You win."
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
        #self.deal_for = None      # "player" or "dealer"
        self.deal_value = 0
        #self.deal_idx = 0
        #self.deal_last = 0.0

        # dealer state machine
        self.dealer_phase = "idle"  # "idle" | "drawing" | "resolve" | "done"
        self.dealer_target = 0
        self.dealer_next_time = 0.0
        
        # wave-sweep state
        self.wave_active = False
        self.wave_buf = [0.0] * 9     # per-LED intensity (0..1) for keys 0..8
        self.wave_pos = 0.0           # crest position in LED units
        self.wave_end_pos = 0.0       # when crest has gone past last LED + span
        self.wave_last = 0.0
        self.wave_color = self.COLOR_HUMAN

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
        # value is how many LEDs to sweep over (1..9)
        self.deal_anim_active = True
        self.deal_for = who
        self.deal_value = max(1, min(9, value))

        # wave setup
        self.wave_color = self.COLOR_HUMAN if who == "player" else self.COLOR_CPU
        self.wave_buf = [0.0] * 9
        # start just before K0 so the crest eases in
        self.wave_pos = -self.WAVE_SPAN
        # finish when crest is past the last lit LED + span
        self.wave_end_pos = (self.deal_value - 1) + self.WAVE_SPAN
        self.wave_last = time.monotonic()
        self.wave_active = True


    def _run_deal_anim(self, now):
        # Frame cap
        if not self.wave_active:
            # legacy safety; stop anim if something’s off
            self.deal_anim_active = False
            return

        dt = now - self.wave_last
        if dt < self.WAVE_FRAME_DT:
            return
        self.wave_last = now

        # Advance crest
        self.wave_pos += self.WAVE_SPEED * dt

        # Decay existing intensities (smooth trailing glow)
        # Raising decay to the power of (dt/frame_dt) keeps speed-independent feel
        decay = self.TRAIL_DECAY ** (dt / self.WAVE_FRAME_DT)
        for i in range(self.deal_value):
            self.wave_buf[i] *= decay

        # Add new cosine crest contribution
        # Only within +/- WAVE_SPAN contributes; amplitude 0..1
        span = self.WAVE_SPAN
        for i in range(self.deal_value):
            dist = i - self.wave_pos
            if -span <= dist <= span:
                # cosine lobe: 1 at crest, 0 at edges (±span)
                amp = 0.5 * (1.0 + math.cos((dist / span) * math.pi))
                # keep the brighter of the current trail and the new crest
                if amp > self.wave_buf[i]:
                    self.wave_buf[i] = amp

        # Paint LEDs: only the first deal_value keys participate
        for i in range(9):
            if i < self.deal_value:
                b = self.wave_buf[i]
                if b > 0.001:
                    level = self.MIN_GLOW + (1.0 - self.MIN_GLOW) * b  # keep a faint floor
                    self.mac.pixels[i] = self._scale(self.wave_color, level)
                else:
                    self.mac.pixels[i] = 0x000000
            else:
                self.mac.pixels[i] = 0x000000

        # End condition: crest passed end and trail faded out
        if (self.wave_pos > self.wave_end_pos) and all(v < 0.02 for v in self.wave_buf[:self.deal_value]):
            self.wave_active = False
            self.deal_anim_active = False
            # leave board dark after the sweep
            for i in range(9):
                self.mac.pixels[i] = 0x000000

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