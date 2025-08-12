# tempo.py — “TEMPO” (1-Player) for Adafruit MacroPad
# CircuitPython 8.x / 9.x compatible
#
# Inspired by the original Master Merlin “Tempo” game:
#   The classic handheld let you compose a tune (up to 47 notes, including
#   rests) and then have it played back, controlling how long each note
#   was held. This MacroPad version preserves the core idea but adapts it
#   for modern hardware, with RGB key lighting, adjustable playback tempo,
#   and LED animations for feedback.
#
# Game Objective:
#   Compose a short tune (up to 47 notes) using the MacroPad’s keys, then
#   have MASTER MERLIN play it back to you at your chosen tempo. You can
#   edit notes, insert rests, and replay the tune at any time. A single
#   press of K9 deletes the last note; a double press starts a brand-new
#   tune. K9 includes LED pulse/flash animations for visual feedback.
#
# Controls (0-based key numbering, adapted from 1-based in Merlin manual):
#   • K0        = Low “sol” (tones[0])
#   • K1..K8    = Musical scale do..do (tones[3]..tones[10])
#                 Keys are lit in a gradient red→yellow→green→blue.
#   • K9        = Edit / New Game
#                 - Single click: Remove last note (LED pulse)
#                 - Double click: Start new game (two LED flashes)
#   • K10       = Rest (LED blue)
#   • K11       = “Computer Turn” – playback once at current tempo
#                 (LED red idle, green during playback)
#
# Gameplay:
#   1. Use K0–K8 to compose notes, K10 for rests, K9 to edit.
#   2. Use encoder to adjust tempo BPM (40–240).
#   3. Press K11 to hear the full tune played back once.
#   4. K9 double click clears and starts a new composition.
#
# LED Behavior:
#   • All note keys are dimmed according to LED_DIM (gamma-corrected).
#   • K9 pulses or flashes based on single/double press.
#   • During playback, the played note’s key is lit grey temporarily.
#     K10 (rest) highlights for rest duration.
#   • K11 turns green for the duration of playback, then back to idle red.
#
# Display:
#   Top line    = Status (e.g., “Tempo”, “Playback”, BPM)
#   Bottom line = Control hints (“Edit  Rest  Play”)
#
# Constants:
#   MAX_TUNE_LEN   – Maximum notes in composition (47)
#   REST           – Marker for rests in tune list
#   DOUBLE_CLICK_S – Time window for K9 double-click
#   LED_DIM        – Brightness scaling factor (0–1), gamma-corrected
#   _COL_*         – Color constants for various keys and states
#   DEFAULT_TONES  – Frequencies (Hz) for low sol + diatonic scale
#
# Notes:
#   • All LED updates are dim-aware via _apply_dim().
#   • Playback timing uses 75% of the beat for tone, 25% gap.
#   • The encoder adjusts tempo in ±2 BPM steps (±5 BPM for fast turns).
#   • Original Master Merlin mapping was 1-based; this implementation
#     uses MacroPad’s 0-based key numbering for code clarity.
#
# --- Button Mapping: Master Merlin (1-based) → MacroPad (0-based) ---
#
# Merlin #   MacroPad Key   Function
# --------   ------------   ------------------------------------------
#    1            K0        Low “sol”  (tones[0])
#    2            K1        do         (tones[3])
#    3            K2        re         (tones[4])
#    4            K3        mi         (tones[5])
#    5            K4        fa         (tones[6])
#    6            K5        sol        (tones[7])
#    7            K6        la         (tones[8])
#    8            K7        ti         (tones[9])
#    9            K8        do         (tones[10])
#   10            K9        Edit (single) / New Game (double)
#   11           K10        Rest
#   12           K11        Computer Turn (playback)

import time
import displayio, terminalio
from adafruit_display_text import label

MAX_TUNE_LEN   = 47
REST           = None
DOUBLE_CLICK_S = 0.35  # seconds: max gap for a double-press on K9

# --- Colors
_COL_K9_BASE    = 0x7A00CC  # purple (base)
_COL_K9_BRIGHT  = 0xFFFFFF  # white
_COL_REST       = 0x0044AA  # K10 blue (compose/rest)
_COL_PLAY_IDLE  = 0xAA0000  # K11 red (idle)
_COL_PLAY_ON    = 0x00AA00  # K11 green (during playback)
_HILITE         = 0x808080
_GAMMA          = 2.2
LED_DIM         = 0.5 

# --- Tones
DEFAULT_TONES = (196,220,247,262,294,330,349,392,440,494,523,587)

class tempo:
    def __init__(self, macropad, tones=DEFAULT_TONES):
        self.mac = macropad
        self.tones = list(tones)

        # Note map (indices into self.tones)
        # Example tones: (196,220,247,262,294,330,349,392,440,494,523,587)
        # We use:
        #   K0 -> low sol  -> tones[0]
        #   K1..K8 -> do..do -> tones[3..10]
        self._low_sol_idx = 0
        self._scale_idx   = [3,4,5,6,7,8,9,10]
        
        if len(self.tones) <= max(self._scale_idx):
            raise ValueError("tones[] is too short for configured scale indices")

        # State
        self.mode = "compose"   # "compose"
        self.tune = []          # list of ints (tone indices) or REST(None)
        self.tempo_bpm = 120
        self._min_bpm  = 40
        self._max_bpm  = 240
        self._pending_new_game = False
        self._is_playing = False

        # K9 single/double detection
        self._k9_click_armed = False
        self._k9_first_time  = 0.0

        # K9 LED animation state
        self._k9_anim = None  # {"mode":"single"|"double", "t0":..., ...}
        

        # LEDs
        try: self.mac.pixels.auto_write = True
        except AttributeError: pass
        self.mac.pixels.brightness = 1.0
        self._paint_idle_keys()

        # Display
        self.group = self._build_ui()
        self._set_top("Tempo")
        self._set_bottom("Edit  Rest  Play")

    # ---------- Lifecycle ----------
    def new_game(self):
        self.tune.clear()
        self.mode = "compose"
        self._paint_idle_keys()
        self._set_top("Tempo")
        self._set_bottom("Edit  Rest  Play")

    def cleanup(self):
        pass

    # ---------- Input ----------
    def button(self, key):
        if getattr(self, "_is_playing", False):
            return
        # K11 = Computer Turn (playback once)
        if key == 11:
            if not self.tune:
                self._set_top("No tune yet")
                self._set_bottom("Edit  Rest  Play")
                return
            self._computer_turn()
            # Stay in compose after playback
            self._update_compose_status()
            return

        # K10 = REST
        if key == 10 and self.mode == "compose":
            self._append_note(REST)
            self._dit()
            self._flash_key(10, 0x222222)
            return

        # K9 = Edit (single), New Game (double)
        if key == 9 and self.mode == "compose":
            now = time.monotonic()
            if self._k9_click_armed and (now - self._k9_first_time) <= DOUBLE_CLICK_S:
                # Double -> New Game + double animation
                self._k9_click_armed = False
                self._start_k9_anim("double")
                self._pending_new_game = True  
                # self.new_game()
            else:
                # Arm single; show single animation right away
                self._k9_click_armed = True
                self._k9_first_time = now
                self._start_k9_anim("single")
            return

        if self.mode == "compose":
            # K0 = low sol
            if key == 0:
                self._append_note(self._low_sol_idx)
                return
            # K1..K8 = do..do
            if 1 <= key <= 8:
                idx = self._scale_idx[key - 1]  # key 1 → scale[0]
                self._append_note(idx)
                return

        # Ignore other keys

    def encoderChange(self, newPosition, oldPosition):
        if getattr(self, "_is_playing", False):
            return
        delta = newPosition - oldPosition
        if delta == 0:
            return
        step = 2 if abs(delta) == 1 else 5
        self.tempo_bpm = self._clamp_bpm(self.tempo_bpm + step * (1 if delta > 0 else -1))
        if self.mode == "compose":
            self._set_top(f"{self.tempo_bpm} BPM")
            self._set_bottom(f"Edit  Rest  Play")

    def tick(self):
        now = time.monotonic()

        # Drive K9 animation smoothly
        self._update_k9_anim(now)

        # Resolve K9 single-click if no second press arrived in time
        if self.mode == "compose" and self._k9_click_armed:
            if now - self._k9_first_time > DOUBLE_CLICK_S:
                self._k9_click_armed = False
                # Single -> Edit (remove last)
                if self.tune:
                    self.tune.pop()
                    self._dit()
                self._update_compose_status()

    # ---------- Compose helpers ----------
    def _append_note(self, idx_or_rest):
        if len(self.tune) >= MAX_TUNE_LEN:
            self._set_top(f"Tune is full ({MAX_TUNE_LEN})")
            self._set_bottom("Edit  Rest  Play")
            self._buzz()
            return
        self.tune.append(idx_or_rest)
        if idx_or_rest is REST:
            # visual feedback already done by caller for REST
            pass
        else:
            self._play_idx(idx_or_rest, 0.12)
            k = self._key_for_idx(idx_or_rest)
            if k >= 0: self._flash_key(k, 0x008000)
        self._update_compose_status()

    def _key_for_idx(self, idx):
        if idx == self._low_sol_idx:
            return 0  # K0
        try:
            pos = self._scale_idx.index(idx)  # 0..7
            return 1 + pos                    # K1..K8
        except ValueError:
            return -1

    def _update_compose_status(self):
        n = len(self.tune)
        self._set_top(f"N: {n} T: {self.tempo_bpm} BPM ")
        self._set_bottom(f"Edit  Rest  Play")

    # ---------- Computer Turn (full playback) ----------
    def _computer_turn(self):
        """Play the composed tune back once at the current tempo_bpm."""
        if not self.tune:
            self._set_top("No tune yet")
            self._set_bottom("Edit  Rest  Play")
            try:
                self.mac.play_tone(440, 0.12)
            except Exception:
                pass
            return

        self._is_playing = True
        prev_k11 = self.mac.pixels[11]
        prev_auto = getattr(self.mac.pixels, "auto_write", True)
        try:
            self._set_top("Playback")
            self._set_bottom(f"{self.tempo_bpm} BPM")

            # K11 green during playback (dim-aware)
            self._set_pixel_dimmed(11, _COL_PLAY_ON)
            try:
                self.mac.pixels.show()
            except AttributeError:
                pass

            try:
                self.mac.pixels.auto_write = True
            except Exception:
                pass

            beat = 60.0 / max(1, self.tempo_bpm)
            note_fraction = 0.75
            note_dur = max(0.08, beat * note_fraction)
            gap = max(0.02, beat * (1 - note_fraction))

            for ev in self.tune:
                if ev is REST:
                    try:
                        old10 = self.mac.pixels[10]
                        self._set_pixel_dimmed(10, _HILITE)
                        time.sleep(note_dur)
                        self.mac.pixels[10] = old10
                    except Exception:
                        time.sleep(note_dur)
                    time.sleep(gap)
                    continue

                if isinstance(ev, int) and 0 <= ev < len(self.tones):
                    freq = self.tones[ev]
                    k = self._key_for_idx(ev)
                    old_rgb = self.mac.pixels[k] if 0 <= k <= 11 else None
                    if 0 <= k <= 11:
                        self._set_pixel_dimmed(k, _HILITE)
                    try:
                        self.mac.play_tone(int(freq), note_dur)
                    except Exception:
                        time.sleep(note_dur)
                    if 0 <= k <= 11:
                        self.mac.pixels[k] = old_rgb
                    time.sleep(gap)
                else:
                    time.sleep(note_dur + gap)

            self._set_top("Playback done")
            self._set_bottom("Edit  Rest  Play")

        finally:
            # Always restore hardware state
            try:
                self.mac.pixels.auto_write = prev_auto
            except Exception:
                pass
            self.mac.pixels[11] = prev_k11
            try:
                self.mac.pixels.show()
            except AttributeError:
                pass
            self._is_playing = False

    # ---------- Sound helpers ----------
    def _play_idx(self, idx, dur=0.20):
        if idx is REST:
            time.sleep(max(0.01, dur))
            return
        freq = self.tones[idx] if 0 <= idx < len(self.tones) else 440
        try: self.mac.play_tone(freq, max(0.05, dur))
        except Exception: pass

    def _dit(self):
        try: self.mac.play_tone(880, 0.05)
        except Exception: pass

    def _buzz(self):
        try: self.mac.play_tone(110, 0.15)
        except Exception: pass

    # ---------- Display ----------
    def _build_ui(self):
        group = displayio.Group()
        w = self.mac.display.width

        base_y = 0
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile = displayio.TileGrid(
                bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            group.append(tile)
            base_y = getattr(bmp, "height", 0) + 2
        except Exception:
            base_y = 14

        self._lbl_top = label.Label(
            terminalio.FONT, text="", color=0xFFFFFF,
            anchor_point=(0.5, 0.0), anchored_position=(w // 2, base_y)
        )
        group.append(self._lbl_top)

        self._lbl_bottom = label.Label(
            terminalio.FONT, text="", color=0xFFFFFF,
            anchor_point=(0.5, 0.0), anchored_position=(w // 2, base_y + 12)
        )
        group.append(self._lbl_bottom)
        return group

    def _set_top(self, text):
        try: self._lbl_top.text = text
        except Exception: pass

    def _set_bottom(self, text):
        try: self._lbl_bottom.text = text
        except Exception: pass

    # ---------- LEDs ----------
    def _gamma_scale(self, v, factor):
        # v: 0..255, factor: 0..1 perceived brightness
        # map factor to linear space, scale, then back to device space
        # keeps 0 and 255 stable
        if factor <= 0: return 0
        if factor >= 1: return v
        return int(round(( (v/255.0)**_GAMMA * factor )**(1/_GAMMA) * 255))

    def _apply_dim(self, rgb):
        f = LED_DIM
        r = self._gamma_scale((rgb >> 16) & 0xFF, f)
        g = self._gamma_scale((rgb >> 8)  & 0xFF, f)
        b = self._gamma_scale(rgb & 0xFF, f)
        return (r << 16) | (g << 8) | b

    def _set_pixel_dimmed(self, idx, rgb):
        """Set pixel idx to rgb after applying dim factor."""
        try:
            self.mac.pixels[idx] = self._apply_dim(rgb)
        except Exception:
            pass
    
    
    def _paint_idle_keys(self):
        prev_auto = getattr(self.mac.pixels, "auto_write", True)
        try: self.mac.pixels.auto_write = False
        except Exception: pass

        try:
            self.mac.pixels.fill(0x000000)

            grad_colors = [
                (255,0,0),
                (255,64,0),
                (255,128,0),
                (255,192,0),
                (255,255,0),
                (128,255,0),
                (0,255,0),
                (0,128,128),
                (0,0,255)
            ]
            for k,(r,g,b) in enumerate(grad_colors):
                self._set_pixel_dimmed(k, (r<<16)|(g<<8)|b)

            self._set_pixel_dimmed(9,  _COL_K9_BASE)
            self._set_pixel_dimmed(10, _COL_REST)
            self._set_pixel_dimmed(11, _COL_PLAY_IDLE)

            try: self.mac.pixels.show()
            except AttributeError: pass
        finally:
            try: self.mac.pixels.auto_write = prev_auto
            except Exception: pass

    def _flash_key(self, idx, rgb, dur=0.05):
        if not (0 <= idx < 12):
            return
        old = self.mac.pixels[idx]
        self._set_pixel_dimmed(idx, rgb)  # dim-aware flash
        try:
            self.mac.pixels.show()
        except AttributeError:
            pass
        time.sleep(max(0.02, dur))
        self.mac.pixels[idx] = old
        try:
            self.mac.pixels.show()
        except AttributeError:
            pass

    # ---------- K9 animation ----------
    def _rgb_lerp(self, c1, c2, t):
        r1, g1, b1 = (c1>>16)&0xFF, (c1>>8)&0xFF, c1&0xFF
        r2, g2, b2 = (c2>>16)&0xFF, (c2>>8)&0xFF, c2&0xFF
        r = int(r1 + (r2 - r1)*t)
        g = int(g1 + (g2 - g1)*t)
        b = int(b1 + (b2 - b1)*t)
        return (r<<16)|(g<<8)|b

    def _start_k9_anim(self, mode="single"):
        now = time.monotonic()
        if mode == "double":
            # Two bright flashes separated by a 0.5s gap
            self._k9_anim = {
                "mode": "double2",
                "t0": now,
                "flash_dur": 0.12,
                "gap": 0.50
            }
        else:
            # Subtle brighten-then-fade total ~1.0s
            self._k9_anim = {"mode":"single", "t0":now, "up":0.15, "down":0.85}

    def _update_k9_anim(self, now=None):
        if not self._k9_anim:
            return
        if now is None:
            now = time.monotonic()

        a = self._k9_anim
        k = 9
        base_dimmed = self._apply_dim(_COL_K9_BASE)
        bright_dim  = self._apply_dim(_COL_K9_BRIGHT)   # was raw color; now dim-aware
        dt = now - a["t0"]

        if a["mode"] == "single":
            up = a["up"]; down = a["down"]; total = up + down
            if dt >= total:
                self.mac.pixels[k] = base_dimmed
                self._k9_anim = None
                try: self.mac.pixels.show()
                except AttributeError: pass
                return
            if dt <= up:
                t = dt / up
                self.mac.pixels[k] = self._rgb_lerp(base_dimmed, bright_dim, t)
            else:
                t = (dt - up) / down
                self.mac.pixels[k] = self._rgb_lerp(bright_dim, base_dimmed, t)

        elif a["mode"] == "double2":
            f = a["flash_dur"]; g = a["gap"]
            if dt < f:
                self.mac.pixels[k] = bright_dim
            elif dt < f + g:
                self.mac.pixels[k] = base_dimmed
            elif dt < (2*f + g):
                self.mac.pixels[k] = bright_dim
            else:
                self.mac.pixels[k] = base_dimmed
                self._k9_anim = None
                if self._pending_new_game:
                    self._pending_new_game = False
                    self.new_game()

        try: self.mac.pixels.show()
        except AttributeError: pass

    # ---------- Utils ----------
    def _clamp_bpm(self, v):
        return max(self._min_bpm, min(self._max_bpm, int(v)))