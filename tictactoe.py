# tictactoe.py — Merlin-style Tic Tac Toe for Adafruit MacroPad
# CircuitPython 8.x / 9.x compatible, non-blocking animations

import time
import math
import displayio
import terminalio
from adafruit_display_text import label

class tictactoe:
    def __init__(self, macropad, tones):
        self.mac = macropad
        self.tones = tones

        # ---- Config ----
        self.BRIGHT = 0.30
        self.COLOR_BG = 0x000000
        self.COLOR_HUMAN = 0xFF0000  # RED (human)
        self.COLOR_CPU   = 0x0000FF  # BLUE (CPU)

        # Endgame pulse tuning (cosine pulses)
        self.PULSE_FRAME_DT   = 0.03  # seconds between pulse frames
        self.PULSE_PHASE_STEP = 0.05  # phase added per frame (higher = faster pulse)

        # Startup sweep tuning (column sweeps)
        self.STARTUP_FRAME_DT = 0.10  # seconds between startup frames

        self.CELL_KEYS = list(range(9))  # 0..8 map to board cells
        self.BTN_NEW   = 9               # K9
        self.BTN_SWAP  = 10              # K10
        self.BTN_CPU   = 11              # K11

        # ---- Game State ----
        self.board = [0] * 9  # 0 empty, 1 human, 2 cpu
        self.human_to_move = True
        self.game_over = False
        self.starter = 1  # who starts on reset; toggled by Swap

        # Blink timing (game-time rendering)
        self._blink_phase = 0.0
        self._last_blink  = time.monotonic()

        # Animation mode: None | "startup" | "endgame"
        self.anim_mode = None

        # Endgame anim state
        self.anim_colors = []
        self.anim_idx = 0
        self.anim_last = 0.0
        self.anim_pulses_per_color = 1
        self.anim_pulse_phase = 0.0

        # Startup anim state (column sweeps)
        self.startup_phase = None   # "red_sweep" | "blue_sweep"
        self.startup_col = 0        # which column 0..2

        # Build OLED UI
        self._build_display()

    # ---------- Display ----------
    def _build_display(self):
        W, H = self.mac.display.width, self.mac.display.height
        self.group = displayio.Group()

        # Background
        bg_bitmap = displayio.Bitmap(W, H, 1)
        bg_pal = displayio.Palette(1)
        bg_pal[0] = self.COLOR_BG
        self.group.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_pal))

        # Status + legends
        self.status = label.Label(
            terminalio.FONT, text="Human to move",
            color=0xFFFFFF, anchor_point=(0.5, 0.0), anchored_position=(W//2, 0)
        )
        self.legend1 = label.Label(
            terminalio.FONT, text="You: RED (blink)",
            color=0xFFFFFF, anchor_point=(0.5, 0.0), anchored_position=(W//2, 12)
        )
        self.legend2 = label.Label(
            terminalio.FONT, text="CPU: BLUE (steady)",
            color=0xFFFFFF, anchor_point=(0.5, 0.0), anchored_position=(W//2, 22)
        )
        self.controls = label.Label(
            terminalio.FONT, text="New   Swap   CPU",
            color=0xAAAAAA, anchor_point=(0.5, 0.0), anchored_position=(W//2, 34)
        )
        self.group.append(self.status)
        self.group.append(self.legend1)
        self.group.append(self.legend2)
        self.group.append(self.controls)

    def _show_legends(self, show: bool):
        self.legend1.hidden = not show
        self.legend2.hidden = not show

    def _big_status(self, text: str):
        self.status.scale = 2
        self.status.text = text
        self.status.anchored_position = (self.mac.display.width//2, 10)

    def _normal_status(self, text: str):
        self.status.scale = 1
        self.status.text = text
        self.status.anchored_position = (self.mac.display.width//2, 0)

    # ---------- Public API ----------
    def new_game(self):
        self.board = [0]*9
        self.game_over = False
        self.starter = 1
        self.human_to_move = True
        self._blink_phase = 0.0
        self._last_blink  = time.monotonic()
        self._lights_clear()
        self._stop_anim()
        self._show_legends(True)
        self._normal_status("Human to move")
        try:
            self.mac.display.root_group = self.group  # CP 9.x
        except AttributeError:
            self.mac.display.show(self.group)         # CP 8.x
        # Kick off startup animation (column sweeps)
        self._start_startup_anim()

    def button(self, key_number):
        if key_number in self.CELL_KEYS:
            self._handle_human_press(key_number)
        elif key_number == self.BTN_NEW:
            self._reset_new()
        elif key_number == self.BTN_SWAP:
            self._reset_swap()
        elif key_number == self.BTN_CPU:
            self._computer_turn_button()

    def encoderChange(self, position, last_position):
        return

    def tick(self):
        now = time.monotonic()

        # Run any active animation mode
        if self.anim_mode == "startup":
            self._run_startup_anim(now)
            pulse = 0.5 + 0.5 * math.cos((now % 10) * 2 * math.pi * 1.4)
            self._render_controls(pulse, endgame=False)
            return
        elif self.anim_mode == "endgame":
            self._run_end_anim(now)
            pulse = 0.5 + 0.5 * math.cos((now % 10) * 2 * math.pi * 1.4)
            self._render_controls(pulse, endgame=True)
            return

        # Normal / game-over steady rendering
        if now - self._last_blink >= 0.03:
            self._last_blink = now
            self._blink_phase += 0.03
            pulse = 0.5 + 0.5 * math.cos(self._blink_phase * 2 * math.pi * 1.4)

            if self.game_over:
                self._render_final_board()
                self._render_controls(pulse, endgame=True)
            else:
                self._render_board(pulse)
                self._render_controls(pulse, endgame=False)

    # ---------- Internals ----------
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

    def _render_board(self, pulse):
        for i, v in enumerate(self.board):
            if v == 1:
                self.mac.pixels[i] = self._scale(self.COLOR_HUMAN, 0.35 + 0.65 * pulse)
            elif v == 2:
                self.mac.pixels[i] = self.COLOR_CPU
            else:
                self.mac.pixels[i] = 0x000000

    def _render_final_board(self):
        for i, v in enumerate(self.board):
            if v == 1:
                self.mac.pixels[i] = self.COLOR_HUMAN
            elif v == 2:
                self.mac.pixels[i] = self.COLOR_CPU
            else:
                self.mac.pixels[i] = 0x000000

    def _render_controls(self, pulse, endgame: bool):
        if endgame or self.game_over:
            self.mac.pixels[self.BTN_NEW]  = self._blend(0xFFFFFF, self.COLOR_HUMAN, pulse)
            self.mac.pixels[self.BTN_SWAP] = self._blend(0xFFFFFF, self.COLOR_CPU,   pulse)
            self.mac.pixels[self.BTN_CPU]  = 0x000000
        else:
            self.mac.pixels[self.BTN_NEW]  = self._scale(0xFFFFFF, 0.12)
            self.mac.pixels[self.BTN_SWAP] = self._scale(0xFFFFFF, 0.12)
            # K11 pulses RED on human turn, BLUE on CPU turn
            if self.human_to_move:
                self.mac.pixels[self.BTN_CPU] = self._scale(self.COLOR_HUMAN, 0.35 + 0.65 * pulse)
            else:
                self.mac.pixels[self.BTN_CPU] = self._scale(self.COLOR_CPU,   0.35 + 0.65 * pulse)

    def _winner(self, b):
        lines = (
            (0,1,2),(3,4,5),(6,7,8),
            (0,3,6),(1,4,7),(2,5,8),
            (0,4,8),(2,4,6)
        )
        for a, bb, c in lines:
            if b[a] and b[a] == b[bb] == b[c]:
                return b[a]
        if all(v != 0 for v in b):
            return 3
        return 0

    def _try_win_or_block(self, mark):
        lines = (
            (0,1,2),(3,4,5),(6,7,8),
            (0,3,6),(1,4,7),(2,5,8),
            (0,4,8),(2,4,6)
        )
        for a, b2, c in lines:
            trio = (self.board[a], self.board[b2], self.board[c])
            if trio.count(mark) == 2 and trio.count(0) == 1:
                if self.board[a] == 0: return a
                if self.board[b2] == 0: return b2
                if self.board[c] == 0: return c
        return None

    def _cpu_move(self):
        if self.game_over:
            return
        ix = self._try_win_or_block(2)
        if ix is None:
            ix = self._try_win_or_block(1)
        if ix is None and self.board[4] == 0:
            ix = 4
        if ix is None:
            for k in (0,2,6,8):
                if self.board[k] == 0:
                    ix = k; break
        if ix is None:
            for k in (1,3,5,7):
                if self.board[k] == 0:
                    ix = k; break
        if ix is None:
            return
        self.board[ix] = 2
        self.mac.pixels[ix] = self.COLOR_CPU
        # CPU click sound to mirror human feedback
        self._sound_click(ix)

    def _check_state(self):
        w = self._winner(self.board)
        if w == 1:
            self._show_legends(False)
            self._big_status("You Win!")
            self._sound_win()
            self.game_over = True
            self._start_end_anim([self.COLOR_HUMAN], pulses_per_color=3)
        elif w == 2:
            self._show_legends(False)
            self._big_status("CPU Wins!")
            self._sound_lose()
            self.game_over = True
            self._start_end_anim([self.COLOR_CPU], pulses_per_color=3)
        elif w == 3:
            self._show_legends(False)
            self._big_status("Tie Game!")
            self._sound_tie()
            self.game_over = True
            self._start_end_anim([0xFFFFFF, self.COLOR_CPU, self.COLOR_HUMAN], pulses_per_color=1)
        else:
            self.human_to_move = not self.human_to_move
            self._normal_status("Human to move" if self.human_to_move else "CPU to move")

    def _handle_human_press(self, ix):
        if self.anim_mode is not None:
            return
        if self.game_over or not self.human_to_move:
            return
        if self.board[ix] != 0:
            self._sound_error()
            return
        self.board[ix] = 1
        self.mac.pixels[ix] = self.COLOR_HUMAN
        self._sound_click(ix)
        self._check_state()

    def _computer_turn_button(self):
        # No thinking animation — move immediately
        if self.anim_mode is not None:
            return
        if self.game_over or self.human_to_move:
            return
        self._cpu_move()
        self._check_state()

    # ---------- Sounds ----------
    def _play(self, freq, dur):
        try:
            self.mac.play_tone(freq, dur)
        except Exception:
            pass

    def _sound_click(self, ix):
        try:
            f = self.tones[ix % len(self.tones)]
        except Exception:
            f = 523
        self._play(f, 0.03)

    def _sound_error(self):
        self._play(140, 0.08)

    def _sound_win(self):
        for f in (660, 880, 990):
            self._play(f, 0.05)

    def _sound_lose(self):
        for f in (440, 330, 220):
            self._play(f, 0.06)

    def _sound_tie(self):
        for f in (523, 523):
            self._play(f, 0.05)

    # ---------- Startup Animation (column sweeps: red L→R, blue R→L) ----------
    def _start_startup_anim(self):
        self.anim_mode = "startup"
        self.startup_phase = "red_sweep"
        self.startup_col = 0
        self.anim_last = time.monotonic()

    def _run_startup_anim(self, now):
        # Column sweeps over keys 0..8 only; controls are handled separately
        if now - self.anim_last < self.STARTUP_FRAME_DT:
            return
        self.anim_last = now

        # Clear board keys each frame
        for i in range(9):
            self.mac.pixels[i] = 0x000000

        def light_column(col_index, color):
            # columns: (0,3,6), (1,4,7), (2,5,8)
            base = col_index
            for r in (0, 1, 2):
                self.mac.pixels[base + 3*r] = color

        if self.startup_phase == "red_sweep":
            if self.startup_col <= 2:
                light_column(self.startup_col, self.COLOR_HUMAN)
                self.startup_col += 1
            else:
                self.startup_phase = "blue_sweep"
                self.startup_col = 2

        elif self.startup_phase == "blue_sweep":
            if self.startup_col >= 0:
                light_column(self.startup_col, self.COLOR_CPU)
                self.startup_col -= 1
            else:
                # End startup; board clears; normal rendering takes over
                for i in range(9):
                    self.mac.pixels[i] = 0x000000
                self._stop_anim()

    # ---------- Endgame Animation (cosine pulses, then final board) ----------
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
            self._render_final_board()
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

    # ---------- Reset helpers (K9 New / K10 Swap) ----------
    def _reset_new(self):
        if self.anim_mode is not None:
            self._stop_anim()
        self.board = [0]*9
        self.game_over = False
        self.starter = 1
        self.human_to_move = True
        self._normal_status("Human to move")
        self._show_legends(True)
        self._lights_clear()
        self._start_startup_anim()

    def _reset_swap(self):
        if self.anim_mode is not None:
            self._stop_anim()
        self.board = [0]*9
        self.game_over = False
        self.starter = 2 if self.starter == 1 else 1
        self.human_to_move = (self.starter == 1)
        self._normal_status("Human to move" if self.human_to_move else "CPU to move")
        self._show_legends(True)
        self._lights_clear()
        self._start_startup_anim()
        # After startup, press K11 for CPU to move if CPU starts.

    # ---------- Animation reset ----------
    def _stop_anim(self):
        self.anim_mode = None
        self.anim_colors = []
        self.anim_idx = 0
        self.startup_phase = None
        self.startup_col = 0
        # visuals are handled by tick()/anim runners