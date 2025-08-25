# lights_out.py — LED-Only Lights Out
# CircuitPython 9.x / Adafruit MacroPad RP2040 (Merlin Launcher Compatible)
# Written by Iain Bennett — 2025
#
# Purpose:
# - A minimalist “Lights Out” puzzle using only the MacroPad’s 12 RGB keys.
# - OLED is used only for short status prompts; all gameplay is on the LEDs.
#
# Gameplay:
# - Menu:  Select mode with K3=Solo, K4=Versus, K5=Co-op (pulsing green).
# - Board: Keys K0..K8 form a 3×3 grid. Pressing toggles that LED and its neighbors.
# - Controls: K9=Menu, K11=New puzzle, K10 disabled (always dark).
# - Display prompts:
#     • Menu:           "Solo  Versus  Co-op" (y=40) ; blank line (y=53).
#     • Solo/Co-op:     "Moves: N" (y=40) ; "Menu  New" (y=53).
#     • Versus:         "P1:m  P2:m  S a-b" (y=40) ; "Menu  New" (y=53).
#     • Win:            "You Win!" (adds "Score a-b" for Versus) ; 
#                       "Press K9 for Menu" (y=53).
#
# Features:
# - Three play modes:
#     • Solo: solve in as few moves as possible.
#     • Versus: alternating turns, players race to solve; score kept across rounds.
#     • Co-op: shared move count, team play.
# - Cosine-pulsed LED animations on press and menu highlights.
# - Audio cues via macropad.play_tone only (short beeps, shuffle triads, win fanfares).
# - Complete cleanup on exit (resets LEDs, detaches display group, frees references).

import time, math, random
import displayio, terminalio
from micropython import const
try:
    from adafruit_display_text import label
    HAVE_LABEL = True
except Exception:
    HAVE_LABEL = False

# ---------- Grid & timings ----------
COLS, ROWS = const(3), const(3)  # 3×3 board -> K0..K8
FADE_DUR   = 0.35                # cosine pulse duration (seconds)

# ---------- Key map ----------
K_MODE_SOLO = const(3)   # menu only
K_MODE_VS   = const(4)   # menu only
K_MODE_COOP = const(5)   # menu only
K_BACK_MENU = const(9)   # in-game & win: return to menu
K_DISABLED  = const(10)  # does nothing, never lights
K_REFRESH   = const(11)  # in-game: reshuffle/new

BOARD_KEYS = tuple(range(0, 9))          # K0..K8
MENU_KEYS  = (K_MODE_SOLO, K_MODE_VS, K_MODE_COOP)

# ---------- Modes ----------
MODE_SOLO, MODE_VERSUS, MODE_COOP = const(0), const(1), const(2)

# ---------- Colors ----------
OFF   = (0, 0, 0)
WHITE = (255, 255, 255)
CYAN_DIM = (0, 50, 60)       # K9/K11 idle color in-game
GREEN_MENU = (0, 180, 0)     # pulsing for K3..K5 on menu

# ---------- Tones (fallback 12-tone scale) ----------
DEFAULT_TONES = (196,220,247,262,294,330,349,392,440,494,523,587)

class lights_out:
    def __init__(self, *args, **kwargs):
        # Flexible ctor (works with your launcher attempts)
        self.mac = None
        self.tones = None
        for a in args:
            if hasattr(a, "keys") and hasattr(a, "pixels"):
                self.mac = a
            elif isinstance(a, (tuple, list)) and len(a) >= 12 and all(isinstance(x, int) for x in a[:12]):
                self.tones = tuple(a)
        if "tones" in kwargs and isinstance(kwargs["tones"], (tuple, list)):
            self.tones = tuple(kwargs["tones"])
        if self.tones is None:
            self.tones = DEFAULT_TONES

        # --- Sound: ONLY play_tone ---
        self._has_play_tone = bool(self.mac and hasattr(self.mac, "play_tone"))

        # --- Display header: Merlin logo + text at y=40, y=53 ---
        self.group = displayio.Group()
        self.logo_group = displayio.Group()
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile = displayio.TileGrid(
                bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            self.logo_group.append(tile)
        except Exception:
            pass
        self.group.append(self.logo_group)
        if HAVE_LABEL:
            self.lbl1 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=40)
            self.lbl2 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=53)
            self.group.append(self.lbl1); self.group.append(self.lbl2)
        else:
            self.lbl1 = self.lbl2 = None

        # --- Game state ---
        self.state   = "menu"     # "menu" | "playing" | "won"
        self.mode    = MODE_SOLO
        self.board   = [0]*9      # only K0..K8 are game cells
        self.moves   = 0          # Solo/Co-op shared moves (per round)
        self.p_moves = [0, 0]     # Versus per-player moves (current round)
        self.player  = 0          # Versus current player (0=P1, 1=P2)
        self.score   = [0, 0]     # Versus match score (P1 wins, P2 wins)
        self.winner_last = None   # 0 or 1 when a round ends in Versus

        # Per-key press timestamps for cosine pulses (board + K9/K11)
        self._press_t = {k: -999.0 for k in range(12)}

        # Pixels batched
        try: self.mac.pixels.auto_write = False
        except Exception: pass

        # Keep launcher default: single encoder press exits
        self.supports_double_encoder_exit = False

    # ---------- Launcher API ----------
    def new_game(self):
        self._to_menu()

    def tick(self):
        if self.state == "menu":
            self._render_menu_leds()
        elif self.state in ("playing", "won"):
            self._render_game_leds()

    def button(self, key):
        # We rely on button_up for actions; keep for parity
        pass

    def button_up(self, key):
        now = time.monotonic()

        if self.state == "menu":
            if key == K_MODE_SOLO: self.mode = MODE_SOLO;   self._start_fresh_puzzle(); return
            if key == K_MODE_VS:   self.mode = MODE_VERSUS; self._start_fresh_puzzle(); return
            if key == K_MODE_COOP: self.mode = MODE_COOP;   self._start_fresh_puzzle(); return
            return

        # If WON: only K9 returns to menu; everything else ignored (K11 disabled)
        if self.state == "won":
            if key == K_BACK_MENU:
                self._to_menu()
                self._press_t[K_BACK_MENU] = now
                self._beep(self._tone_for_key(1), 0.04)
            return

        # In-game:
        if key == K_BACK_MENU:
            self._to_menu()
            self._press_t[K_BACK_MENU] = now
            self._beep(self._tone_for_key(1), 0.04)
            return
        if key == K_REFRESH:
            self._start_fresh_puzzle()
            self._press_t[K_REFRESH] = now
            self._beep(self._tone_for_key(10), 0.05)
            return
        if key == K_DISABLED:
            # Do nothing; stays unlit
            return

        # Board keys only
        if key in BOARD_KEYS:
            self._apply_press(key)
            self._press_t[key] = now
            self._beep(self._tone_for_key(key), 0.045)

            if self.mode == MODE_VERSUS:
                # Count move for current player
                self.p_moves[self.player] += 1
                # Check win BEFORE swapping turns (so winner is current player)
                if self._all_clear():
                    self._on_win_versus(self.player)
                    return
                # No win: swap turns
                self.player ^= 1
            else:
                # Solo / Co-op move
                self.moves += 1
                if self._all_clear():
                    self._on_win_generic()
                    return

            self._update_header_ingame()

    def cleanup(self):
        """Blank LEDs, restore display, and free heavy refs. (No audio APIs used here.)"""
        # --- LEDS: blank and reset local pulse timers/cache ---
        try:
            if hasattr(self, "mac") and hasattr(self.mac, "pixels"):
                prev_auto = getattr(self.mac.pixels, "auto_write", True)
                try: self.mac.pixels.auto_write = False
                except Exception: pass
                try:
                    self.mac.pixels.fill((0, 0, 0))
                    self.mac.pixels.show()
                except Exception:
                    pass
                try: self.mac.pixels.auto_write = prev_auto
                except Exception: pass
        except Exception:
            pass
        # Push press timestamps far in the past so pulses don't resume if reused
        try:
            if hasattr(self, "_press_t"):
                for k in self._press_t: self._press_t[k] = -999.0
        except Exception:
            pass

        # --- DISPLAY: detach our group and restore auto_refresh for launcher ---
        try:
            disp = getattr(self.mac, "display", None)
            if disp is not None:
                if getattr(disp, "root_group", None) is self.group:
                    disp.root_group = None
                try:
                    disp.auto_refresh = True
                except Exception:
                    pass
        except Exception:
            pass

        # --- RELEASE heavy references so GC can reclaim RAM ---
        try:
            if getattr(self, "group", None) is not None:
                try:
                    while len(self.group):
                        self.group.pop()
                except Exception:
                    pass
        except Exception:
            pass

        # Drop object refs
        self.logo_group = None
        self.lbl1 = None
        self.lbl2 = None

        # Optionally reset simple game state
        self.state = "menu"
        self.board = [0] * 9

        # --- Encourage garbage collection ---
        try:
            import gc
            gc.collect()
        except Exception:
            pass

    # ---------- States ----------
    def _to_menu(self):
        self.state = "menu"
        self.board = [0]*9
        self.moves = 0
        self.p_moves = [0, 0]
        self.player = 0
        self.winner_last = None
        # Reset scoreboard when returning to menu for a fresh match:
        self.score = [0, 0]
        try:
            self.mac.pixels.fill((0,0,0)); self.mac.pixels.show()
        except Exception:
            pass
        self._update_header_menu()

    def _start_fresh_puzzle(self):
        self.state = "playing"
        self.board = [0]*9
        self.moves = 0
        self.p_moves = [0, 0]
        self.player = 0
        self.winner_last = None
        # Create solvable puzzle by applying random valid presses to an empty board
        for _ in range(18):
            k = random.randrange(9)     # only board keys
            self._apply_press(k)
        t0 = time.monotonic() - 2.0
        for k in range(12): self._press_t[k] = t0
        self._update_header_ingame()
        self._cue_shuffle()

    # ---------- Core game logic ----------
    def _neighbors(self, k):
        r, c = divmod(k, COLS)  # k in 0..8
        out = [k]
        if r > 0: out.append((r-1)*COLS + c)       # up
        if r < ROWS-1: out.append((r+1)*COLS + c)  # down
        if c > 0: out.append(r*COLS + (c-1))       # left
        if c < COLS-1: out.append(r*COLS + (c+1))  # right
        return out

    def _apply_press(self, k):
        for i in self._neighbors(k):
            self.board[i] ^= 1
            self._press_t[i] = time.monotonic()

    def _all_clear(self):
        for v in self.board:
            if v:
                return False
        return True

    # ---------- Win handling ----------
    def _on_win_generic(self):
        # Solo / Co-op
        self.state = "won"
        self._cue_win()
        self._update_header_won_generic()

    def _on_win_versus(self, winner):
        # Update scoreboard, enter won state
        if 0 <= winner <= 1:
            self.score[winner] += 1
            self.winner_last = winner
        self.state = "won"
        self._cue_win()
        self._update_header_won_versus()

    # ---------- Header ----------
    def _update_header_menu(self):
        if not HAVE_LABEL: return
        self.lbl1.text = "Solo  Versus  Co-op"
        self.lbl2.text = ""

    def _update_header_ingame(self):
        if not HAVE_LABEL: return
        if self.mode == MODE_VERSUS:
            # P1/P2 moves this round + match Score a-b
            self.lbl1.text = "P1:{}  P2:{}  S {}-{}".format(
                self.p_moves[0], self.p_moves[1], self.score[0], self.score[1]
            )
        else:
            self.lbl1.text = "Moves: {}".format(self.moves)
        self.lbl2.text = "Menu  New"

    def _update_header_won_generic(self):
        if not HAVE_LABEL: return
        self.lbl1.text = "You Win!  Moves: {}".format(self.moves)
        self.lbl2.text = "Press K9 for Menu"

    def _update_header_won_versus(self):
        if not HAVE_LABEL: return
        who = "P{}".format((self.winner_last or 0) + 1)
        self.lbl1.text = "You Win!  {}  Score {}-{}".format(who, self.score[0], self.score[1])
        self.lbl2.text = "Press K9 for Menu"

    # ---------- LED Rendering ----------
    def _render_menu_leds(self):
        try:
            now = time.monotonic()
            pulse = 0.5 + 0.5 * math.cos(now * 2 * math.pi * 0.8)  # slow pulse
            s = 0.15 + 0.65 * pulse
            color = (int(GREEN_MENU[0]*s), int(GREEN_MENU[1]*s), int(GREEN_MENU[2]*s))
            self.mac.pixels.fill(OFF)
            # Only K3..K5 glow on menu
            self.mac.pixels[K_MODE_SOLO] = color
            self.mac.pixels[K_MODE_VS]   = color
            self.mac.pixels[K_MODE_COOP] = color
            # K10 remains off; K9/K11 off in menu
            self.mac.pixels.show()
        except Exception:
            pass

    def _render_game_leds(self):
        try:
            now = time.monotonic()

            # Base: draw board (K0..K8) in white scheme with per-key cosine pulses
            for k in BOARD_KEYS:
                if self.board[k]:
                    pulse = self._fade_mult(now - self._press_t[k])
                    b = min(1.0, 0.65 + 0.35 * pulse)
                    color = (int(WHITE[0]*b), int(WHITE[1]*b), int(WHITE[2]*b))
                else:
                    pulse = self._fade_mult(now - self._press_t[k])
                    v = int(80 * pulse)  # neutral grey pulse after toggling off
                    color = (v, v, v)
                self.mac.pixels[k] = color

            # K9 / K11: cyan with their own cosine pulse when recently pressed
            # If WON: emphasize K9 and disable/turn off K11
            if self.state == "won":
                # K9 bright pulse invite
                pulse_k9 = self._fade_mult(now - self._press_t[K_BACK_MENU])
                s = min(1.0, 0.55 + 0.45 * pulse_k9)  # 0.55..1.0
                c9 = (int(CYAN_DIM[0]*s), int(CYAN_DIM[1]*s), int(CYAN_DIM[2]*s))
                self.mac.pixels[K_BACK_MENU] = c9
                # K11 off while won
                self.mac.pixels[K_REFRESH] = OFF
            else:
                for ctrl in (K_BACK_MENU, K_REFRESH):
                    base = CYAN_DIM
                    pulse = self._fade_mult(now - self._press_t[ctrl])
                    s = min(1.0, 0.45 + 0.45 * pulse)  # 0.45..0.90
                    c = (int(base[0]*s), int(base[1]*s), int(base[2]*s))
                    self.mac.pixels[ctrl] = c

            # K10 strictly off
            self.mac.pixels[K_DISABLED] = OFF

            self.mac.pixels.show()
        except Exception:
            pass

    def _fade_mult(self, dt):
        if dt < 0.0: return 0.0
        if dt >= FADE_DUR: return 0.0
        x = dt / FADE_DUR
        return 0.5 * (1.0 + math.cos(x * math.pi))  # 1→0 cosine

    # ---------- Sound (ONLY play_tone) ----------
    def _tone_for_key(self, key):
        if 0 <= key < len(self.tones): return int(self.tones[key])
        return DEFAULT_TONES[key % 12]

    def _play_tone(self, f, d):
        if not self._has_play_tone: return
        if f and d and f > 0 and d > 0:
            try:
                self.mac.play_tone(int(f), float(d))
            except Exception:
                pass

    # ---- Cues ----
    def _beep(self, f, d=0.05):
        self._play_tone(f, d)

    def _cue_shuffle(self):
        # short descending triad
        seq = [(self._tone_for_key(9), 0.04),
               (self._tone_for_key(6), 0.04),
               (self._tone_for_key(3), 0.06)]
        for f, d in seq:
            self._play_tone(f, d)

    def _cue_win(self):
        # short ascending triad
        seq = [(self._tone_for_key(8), 0.07),
               (self._tone_for_key(10), 0.07),
               (self._tone_for_key(11), 0.12)]
        for f, d in seq:
            self._play_tone(f, d)