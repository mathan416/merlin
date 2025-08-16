# tempo.py — “TEMPO” (1‑Player) for Adafruit MacroPad
# CircuitPython 8.x / 9.x
# Written by Iain Bennett — 2025
# Inspired by the original Master Merlin “Tempo” game.
#
# License:
#   Released under the CC0 1.0 Universal (Public Domain Dedication).
#   You can copy, modify, distribute, and perform the work, even for commercial purposes,
#   all without asking permission. Attribution is appreciated but not required.
#
# Gameplay summary
# ----------------
# • Compose mode (default):
#     - K0..K8: append notes (low-sol on K0, then scale degrees on K1..K8)
#     - K10:   append REST
#     - K9:    single = undo last note, double = start a new tune
#     - Encoder: change tempo (fine/coarse by step)
#     - K11:   short press = playback; long press = enter Edit mode
#
# • Edit mode:
#     - Encoder: move cursor through existing events
#     - Encoder button: toggle Length select (“durselect”) for current event
#     - K0..K8 / K10: replace the event at the cursor (note or rest)
#     - K11: long press = return to Compose; short press = playback
#
# • Length select (“durselect”):
#     - Encoder: change length of current event (Sixteenth..Whole)
#     - Footer shows “Length      Play”; exiting returns to “Edit      Play”
#     - K0..K8 / K10: still replace current event (handy for quick fixes)
#
# LEDs & UI
# ---------
# • K0..K8 show a color gradient; K10 is REST blue; K11 is red idle / green during playback.
# • Edit cursor key subtly “breathes”; K11 does a one‑shot pulse entering/leaving Edit,
#   and “glows” while held for long‑press detection.
# • Top line shows edit position and current length (E:x/y  L:Name).
# • Bottom line shows mode hints: “Compose     Play”, “Edit        Play”, or “Length      Play”.
#
# Notes
# -----
# • MAX_TUNE_LEN limits events; each event has an independent length index.
# • `supports_double_encoder_exit` is a capability flag for the host shell (not used internally).
# • `group` holds the display group for hosts that attach it to the Display root.

import time
import displayio, terminalio
import math
from adafruit_display_text import label

MAX_TUNE_LEN   = 47
REST           = None
DOUBLE_CLICK_S = 0.35   # seconds: max gap for a double-press on K9

# --- Colors
_COL_K9_BASE    = 0x7A00CC  # purple (base)
_COL_K9_BRIGHT  = 0xFFFFFF  # white
_COL_REST       = 0x0044AA  # K10 blue (compose/rest)
_COL_PLAY_IDLE  = 0xAA0000  # K11 red (idle)
_COL_PLAY_ON    = 0x00AA00  # K11 green (during playback)
_HILITE         = 0x808080
_GAMMA          = 2.2
LED_DIM         = 0.5

# K11 long-press
LONG_PRESS_S    = 0.60   # seconds to trigger long-press
K11_GLOW_PERIOD = 1.6    # seconds per breathe cycle

# --- Tones
DEFAULT_TONES = (196,220,247,262,294,330,349,392,440,494,523,587)

class tempo:
    def __init__(self, macropad, tones=DEFAULT_TONES):
        self.mac = macropad
        self.tones = list(tones)

        # Note map (indices into self.tones)
        self._low_sol_idx = 0
        self._scale_idx   = [3,4,5,6,7,8,9,10]
        if len(self.tones) <= max(self._scale_idx):
            raise ValueError("tones[] is too short for configured scale indices")

        # State
        self.mode = "compose"              # "compose" | "edit" | "durselect"
        self.tune = []                     # list of ints (tone indices) or REST(None)
        self.length_idx = []               # per-note duration index (0..4); aligns with self.tune
        self._len_names = ("Sixteenth","Eighth","Quarter","Half","Whole")
        self._len_beats = (0.25, 0.5, 1.0, 2.0, 4.0)  # beats at current tempo
        self._default_len = 2              # Quarter by default

        self.cur = 0                       # edit cursor into tune (0..len-1)
        self.tempo_bpm = 120
        self._min_bpm  = 40
        self._max_bpm  = 240

        self._pending_new_game = False
        self._is_playing = False
        self.supports_double_encoder_exit = True

        # K9 single/double detection
        self._k9_click_armed = False
        self._k9_first_time  = 0.0

        # K11 long-press detection
        self._k11_down_at = None        # None or time.monotonic() when pressed
        self._k11_hold_handled = False  # True once we toggled mode on this press
        self._k11_glow = None           # {"t0": float} when glowing
        self._k11_base_rgb = None       # cached base color while glowing

        # K9 LED animation state
        self._k9_anim = None  # {"mode":"single"|"double", "t0":...}
        
        # K11 LED animation state
        self._k11_pulse = None          # {"t0": float, "dur": float}
        self._cursor_blink = None       # {"t0": float, "period": float, "on": bool}
        self._blink_last_key = None     # int or None
        self._idle_colors = [0] * 12    # capture base dimmed colors per key

        # LEDs
        try: self.mac.pixels.auto_write = True
        except AttributeError: pass
        self.mac.pixels.brightness = 1.0
        self._paint_idle_keys()

        # Display
        self.group = self._build_ui()
        self._set_top("Tempo")
        self._set_bottom("Compose     Play")

    # ---------- Lifecycle ----------
    def new_game(self):
        self.tune.clear()
        self.length_idx.clear()
        self.mode = "compose"
        self.cur = 0
        self._paint_idle_keys()
        self._set_top("Tempo")
        self._set_bottom("Compose     Play")

    def cleanup(self):
        """Gracefully stop audio/animations and restore LEDs/UI before exit."""
        # 1) Stop any sound and mark playback off
        self._is_playing = False
        try:
            self.mac.stop_tone()  # MacroPad API (safe if not playing)
        except Exception:
            pass

        # 2) Cancel all transient states/animations
        self._k9_anim = None
        self._k11_pulse = None
        self._k11_glow = None
        self._k11_base_rgb = None
        self._k11_down_at = None
        self._k11_hold_handled = False
        self._k9_click_armed = False
        self._pending_new_game = False

        # 3) Stop cursor blink and restore the last blinked key color
        self._stop_cursor_blink(restore=True)

        # 4) Restore LEDs to cached idle colors (or off if not cached)
        try:
            prev_auto = getattr(self.mac.pixels, "auto_write", True)
            try:
                self.mac.pixels.auto_write = False
            except Exception:
                pass

            for i in range(12):
                base = self._idle_colors[i] if i < len(self._idle_colors) else 0x000000
                self.mac.pixels[i] = base

            try:
                self.mac.pixels.show()
            except Exception:
                pass

            try:
                self.mac.pixels.auto_write = prev_auto
            except Exception:
                pass
        except Exception:
            pass

        # 5) (Optional) Clear footer hints so the next app paints fresh
        try:
            self._set_bottom("")
        except Exception:
            pass

    # ---------- Input ----------
    def button(self, key):
        # IGNORE inputs during playback
        if getattr(self, "_is_playing", False):
            return

        # K11 = Playback on short release, Edit-mode toggle on long-press
        if key == 11:
            self._k11_down_at = time.monotonic()
            self._k11_hold_handled = False
            self._start_k11_glow()
            return

        # K10 = REST (only while composing appends a rest)
        if key == 10 and self.mode == "compose":
            self._append_note(REST)
            self._dit()
            self._flash_key(10, 0x222222)
            return

        # K9 = Edit (single removes last), New (double) — only in compose
        if key == 9 and self.mode == "compose":
            now = time.monotonic()
            if self._k9_click_armed and (now - self._k9_first_time) <= DOUBLE_CLICK_S:
                self._k9_click_armed = False
                self._start_k9_anim("double")
                self._pending_new_game = True
            else:
                self._k9_click_armed = True
                self._k9_first_time = now
                self._start_k9_anim("single")
            return

        # --- Compose mode: append notes with K0..K8 ---
        if self.mode == "compose":
            if key == 0:
                self._append_note(self._low_sol_idx)
                return
            if 1 <= key <= 8:
                idx = self._scale_idx[key - 1]
                self._append_note(idx)
                return

        # --- Edit & Durselect: replace current event with K0..K8 or K10 ---
        if self.mode in ("edit", "durselect") and self.tune:
            # K10 -> REST
            if key == 10:
                self.tune[self.cur] = REST
                self._update_edit_status()
                self._hilite_cursor()           # nudge blink to refresh
                self._audition_current(quick=True)
                return

            # K0 -> low sol
            if key == 0:
                self.tune[self.cur] = self._low_sol_idx
                self._update_edit_status()
                self._hilite_cursor()
                self._audition_current(quick=True)
                return

            # K1..K8 -> scale degrees
            if 1 <= key <= 8:
                idx = self._scale_idx[key - 1]
                self.tune[self.cur] = idx
                self._update_edit_status()
                self._hilite_cursor()
                self._audition_current(quick=True)
                return

    def button_up(self, key):
        if key != 11:
            return
        # Ignore during playback
        if getattr(self, "_is_playing", False):
            return

        # Stop the glow
        self._stop_k11_glow()

        if self._k11_down_at is not None:
            if not self._k11_hold_handled:
                # Short press -> playback (if we have a tune)
                if not self.tune:
                    self._set_top("No tune yet")
                    self._set_bottom("Compose     Play")
                else:
                    self._computer_turn()
                    if self.mode == "compose":
                        self._update_compose_status()
                    elif self.mode == "durselect":
                        self._show_dur_footer()
                    else:
                        self._update_edit_status()
            else:
                # Long-press handled in tick(); just refresh footer.
                if self.mode == "compose":
                    self._set_bottom("Compose     Play")
                elif self.mode == "durselect":
                    self._show_dur_footer()
                else:
                    self._update_edit_status()

        # Clear press state
        self._k11_down_at = None
        self._k11_hold_handled = False

    def encoder_button(self, pressed):
        # Only used in Edit/Duration selection
        if getattr(self, "_is_playing", False):
            return
        if not pressed:
            return
        if self.mode == "edit" and self.tune:
            self.mode = "durselect"
            self._show_dur_footer()
            # cursor blink remains on the same event
        elif self.mode == "durselect":
            self.mode = "edit"
            self._update_edit_status()

    def encoderChange(self, newPosition, oldPosition):
        # IGNORE inputs during playback
        if getattr(self, "_is_playing", False):
            return

        delta = newPosition - oldPosition
        if delta == 0:
            return

        if self.mode == "compose":
            step = 2 if abs(delta) == 1 else 5
            self.tempo_bpm = self._clamp_bpm(self.tempo_bpm + step * (1 if delta > 0 else -1))
            # Keep your existing compose BPM readout behavior:
            self._set_top(f"{self.tempo_bpm} BPM")
            self._set_bottom("Compose     Play")
            return

        if self.mode == "edit":
            if not self.tune:
                return
            prev = self.cur
            move = 1 if delta > 0 else -1
            self.cur = max(0, min(len(self.tune)-1, self.cur + move))
            self._update_edit_status()
            self._hilite_cursor()  # nudges blink refresh
            if self.cur != prev:              # only play if we actually moved
                self._audition_current(quick=True)
            return
        
        if self.mode == "durselect":
            if not self.tune:
                return
            li = self.length_idx[self.cur]
            li = (li + (1 if delta > 0 else -1)) % len(self._len_names)
            self.length_idx[self.cur] = li
            self._show_dur_footer()
            self._audition_current()

    def tick(self):
        # Ignore everything during playback
        if getattr(self, "_is_playing", False):
            return

        now = time.monotonic()

        # 1) Long-press detection (toggle compose <-> edit exactly once)
        if self._k11_down_at is not None:
            held_s = now - self._k11_down_at
            if (not self._k11_hold_handled) and (held_s >= LONG_PRESS_S):
                if self.mode == "compose":
                    self._enter_edit_mode()
                else:
                    self._exit_edit_mode()
                self._k11_hold_handled = True  # handled this press

        # 2) Update K11 pulse (if active) — runs every frame
        pulse_active = False
        if getattr(self, "_k11_pulse", None):
            pulse_active = self._update_k11_pulse(now)

        # 3) K11 glow while the key is held — only if pulse didn’t draw this frame
        if (self._k11_down_at is not None) and (not pulse_active) and self._k11_glow:
            self._update_k11_glow(now)

        # 4) Subtle cursor blink while editing / duration select
        if self.mode in ("edit", "durselect"):
            self._update_cursor_blink(now)
        else:
            if getattr(self, "_cursor_blink", None):
                self._stop_cursor_blink(restore=True)

        # 5) Drive K9 animation and resolve single-click timeout
        self._update_k9_anim(now)
        if self.mode == "compose" and self._k9_click_armed:
            if now - self._k9_first_time > DOUBLE_CLICK_S:
                self._k9_click_armed = False
                if self.tune:
                    self.tune.pop()
                    self.length_idx.pop()
                    self._dit()
                self._update_compose_status()

    # ---------- Mode helpers ----------
    def _enter_edit_mode(self):
        if self.mode == "edit":
            return
        self.mode = "edit"
        n = len(self.tune)
        if n == 0:
            self.cur = 0
        else:
            if self.cur >= n:
                self.cur = n - 1
        self._update_edit_status()

        # One-shot pulse on K11 + start cursor blink
        self._start_k11_pulse(dur=0.9)
        self._start_cursor_blink(period=0.60)

    def _exit_edit_mode(self):
        if self.mode == "compose":
            return
        self.mode = "compose"

        # Stop the cursor blink and any lingering edit highlight
        self._stop_cursor_blink(restore=True)

        # Kick a matching one-shot pulse on K11
        self._k11_pulse = None
        self._start_k11_pulse(dur=0.9)

        # Update the compose footer/topline
        self._update_compose_status()

    def _update_edit_status(self):
        if self.mode == "durselect":
            self._show_dur_footer()
        else:
            self._show_edit_top()
            

    def _show_edit_top(self):
        n = len(self.tune)
        if n == 0:
            self._set_top("E: 0/0  L: —")
            return
        li = self.length_idx[self.cur]
        self._set_top(f"E: {self.cur+1}/{n}  L: {self._len_names[li]}")
        self._set_bottom("Edit        Play")

    def _show_dur_footer(self):
        n = len(self.tune)
        if n == 0:
            self._set_top("E: 0/0  L: —")
            return
        li = self.length_idx[self.cur]
        self._set_top(f"E: {self.cur+1}/{n}  L: {self._len_names[li]}")       
        self._set_bottom("Length      Play")

    def _audition_current(self, quick=False):
        ev = self.tune[self.cur]
        li = self.length_idx[self.cur]
        beats = self._len_beats[li]
        beat = 60.0 / max(1, self.tempo_bpm)
        total = max(0.05, beats * beat)

        if quick:
            # Short, snappy preview while editing
            play_dur = min(0.12, max(0.04, total * 0.50))
            gap = 0.0
        else:
            note_fraction = 0.75
            play_dur = max(0.05, total * note_fraction)
            gap = max(0.01, total - play_dur)

        if ev is REST:
            try:
                old10 = self.mac.pixels[10]
                self._set_pixel_dimmed(10, _HILITE)
                time.sleep(play_dur)
                self.mac.pixels[10] = old10
                try: self.mac.pixels.show()
                except AttributeError: pass
            except Exception:
                time.sleep(play_dur)
            if gap > 0: time.sleep(gap)
            return

        if isinstance(ev, int) and 0 <= ev < len(self.tones):
            freq = self.tones[ev]
            k = self._key_for_idx(ev)
            old_rgb = self.mac.pixels[k] if 0 <= k <= 11 else None
            if 0 <= k <= 11:
                self._set_pixel_dimmed(k, _HILITE)
                try: self.mac.pixels.show()
                except AttributeError: pass
            try:
                self.mac.play_tone(int(freq), play_dur)
            except Exception:
                time.sleep(play_dur)
            if 0 <= k <= 11:
                self.mac.pixels[k] = old_rgb
                try: self.mac.pixels.show()
                except AttributeError: pass
            if gap > 0: time.sleep(gap)

    # ---------- Compose helpers ----------
    def _append_note(self, idx_or_rest):
        if len(self.tune) >= MAX_TUNE_LEN:
            self._set_top(f"Tune is full ({MAX_TUNE_LEN})")
            self._set_bottom("Compose     Play")
            self._buzz()
            return
        self.tune.append(idx_or_rest)
        self.length_idx.append(self._default_len)
        if idx_or_rest is REST:
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
        self._set_top(f"N: {n} T: {self.tempo_bpm} BPM")
        self._set_bottom("Compose     Play")

    # ---------- Computer Turn (full playback) ----------
    def _computer_turn(self):
        """Play the composed tune back once at the current tempo_bpm, honoring per-note lengths."""
        if not self.tune:
            self._set_top("No tune yet")
            self._set_bottom("Compose     Play")
            try:
                self.mac.play_tone(440, 0.12)
            except Exception:
                pass
            return

        # Block inputs and disarm any pending K9 click/anim during playback
        self._is_playing = True
        self._k9_click_armed = False
        self._k9_anim = None

        prev_k11 = self.mac.pixels[11]
        prev_auto = getattr(self.mac.pixels, "auto_write", True)
        try:
            self._set_top("Playback")
            self._set_bottom(f"{self.tempo_bpm} BPM")

            self._set_pixel_dimmed(11, _COL_PLAY_ON)
            try: self.mac.pixels.show()
            except AttributeError: pass

            try: self.mac.pixels.auto_write = True
            except Exception: pass

            beat = 60.0 / max(1, self.tempo_bpm)

            for i, ev in enumerate(self.tune):
                li = self.length_idx[i] if i < len(self.length_idx) else self._default_len
                beats = self._len_beats[li]
                total = max(0.06, beats * beat)
                note_fraction = 0.75
                play_dur = max(0.05, total * note_fraction)
                gap = max(0.01, total - play_dur)

                if ev is REST:
                    try:
                        old10 = self.mac.pixels[10]
                        self._set_pixel_dimmed(10, _HILITE)
                        time.sleep(play_dur)
                        self.mac.pixels[10] = old10
                    except Exception:
                        time.sleep(play_dur)
                    time.sleep(gap)
                    continue

                if isinstance(ev, int) and 0 <= ev < len(self.tones):
                    freq = self.tones[ev]
                    k = self._key_for_idx(ev)
                    old_rgb = self.mac.pixels[k] if 0 <= k <= 11 else None

                    if 0 <= k <= 11:
                        self._set_pixel_dimmed(k, _HILITE)

                    try:
                        self.mac.play_tone(int(freq), play_dur)
                    except Exception:
                        time.sleep(play_dur)

                    if 0 <= k <= 11:
                        self.mac.pixels[k] = old_rgb

                    time.sleep(gap)
                else:
                    time.sleep(total)

            self._set_top("Playback done")
            # restore footer according to current mode
            if self.mode == "compose":
                self._set_bottom("Compose     Play")
            elif self.mode == "durselect":
                self._show_dur_footer()
            else:
                self._update_edit_status()
            # Re-apply blink, etc...
            self._blink_last_key = None

        finally:
            try: self.mac.pixels.auto_write = prev_auto
            except Exception: pass
            self.mac.pixels[11] = prev_k11
            try: self.mac.pixels.show()
            except AttributeError: pass
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
        if factor <= 0: return 0
        if factor >= 1: return v
        return int(round(((v/255.0)**_GAMMA * factor )**(1/_GAMMA) * 255))

    def _apply_dim(self, rgb):
        f = LED_DIM
        r = self._gamma_scale((rgb >> 16) & 0xFF, f)
        g = self._gamma_scale((rgb >> 8)  & 0xFF, f)
        b = self._gamma_scale(rgb & 0xFF, f)
        return (r << 16) | (g << 8) | b

    def _set_pixel_dimmed(self, idx, rgb):
        if not (0 <= idx < 12):
            return
        try:
            self.mac.pixels[idx] = self._apply_dim(rgb)
        except Exception:
            pass

    def _paint_idle_keys(self):
        """Paint all keys for idle state and cache their dimmed base colors."""
        prev_auto = getattr(self.mac.pixels, "auto_write", True)
        try:
            self.mac.pixels.auto_write = False
        except Exception:
            pass

        try:
            # Clear & init cache
            self.mac.pixels.fill(0x000000)
            for i in range(12):
                self._idle_colors[i] = 0x000000

            # K0..K8 gradient (dim-aware)
            grad_colors = [
                (255, 0, 0),
                (255, 64, 0),
                (255, 128, 0),
                (255, 192, 0),
                (255, 255, 0),
                (128, 255, 0),
                (0, 255, 0),
                (0, 128, 128),
                (0, 0, 255),
            ]
            for k, (r, g, b) in enumerate(grad_colors):
                c = (r << 16) | (g << 8) | b
                dc = self._apply_dim(c)
                self.mac.pixels[k] = dc
                self._idle_colors[k] = dc

            # K9 (Edit), K10 (Rest), K11 (Play) — base idle colors (dim-aware)
            c9  = self._apply_dim(_COL_K9_BASE)
            c10 = self._apply_dim(_COL_REST)
            c11 = self._apply_dim(_COL_PLAY_IDLE)

            self.mac.pixels[9]  = c9;  self._idle_colors[9]  = c9
            self.mac.pixels[10] = c10; self._idle_colors[10] = c10
            self.mac.pixels[11] = c11; self._idle_colors[11] = c11

            try:
                self.mac.pixels.show()
            except AttributeError:
                pass
        finally:
            try:
                self.mac.pixels.auto_write = prev_auto
            except Exception:
                pass

    def _flash_key(self, idx, rgb, dur=0.05):
        if not (0 <= idx < 12):
            return
        old = self.mac.pixels[idx]
        self._set_pixel_dimmed(idx, rgb)
        try: self.mac.pixels.show()
        except AttributeError: pass
        time.sleep(max(0.02, dur))
        self.mac.pixels[idx] = old
        try: self.mac.pixels.show()
        except AttributeError: pass

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
            self._k9_anim = {"mode":"double2", "t0": now, "flash_dur": 0.12, "gap": 0.50}
        else:
            self._k9_anim = {"mode":"single", "t0":now, "up":0.15, "down":0.85}

    def _update_k9_anim(self, now=None):
        if not self._k9_anim:
            return
        if now is None:
            now = time.monotonic()

        a = self._k9_anim
        k = 9
        base_dimmed = self._apply_dim(_COL_K9_BASE)
        bright_dim  = self._apply_dim(_COL_K9_BRIGHT)
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

    # ----- K11 pulse (one-shot) on entering edit mode -----
    def _start_k11_pulse(self, dur=0.35):
        # Cancel any running glow; pulse has priority
        self._k11_glow = None
        self._k11_pulse = {"t0": time.monotonic(), "dur": float(dur)}

    def _update_k11_pulse(self, now):
        """Return True if we drew this frame (so glow should skip), else False."""
        if not self._k11_pulse:
            return False  # inactive

        t0  = self._k11_pulse["t0"]
        dur = self._k11_pulse["dur"]
        dt  = now - t0

        base = self._idle_colors[11]          # device-space idle
        bright = self._apply_dim(0xFFFFFF)    # device-space bright white

        if dt >= dur:
            # End pulse -> restore idle (solid)
            try:
                self.mac.pixels[11] = base
                self.mac.pixels.show()
            except Exception:
                pass
            self._k11_pulse = None
            return False

        # Cosine envelope 0..1..0 across the pulse duration
        phase = dt / dur
        amt = 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)

        # Lerp device-space base -> bright
        r1, g1, b1 = (base >> 16) & 0xFF, (base >> 8) & 0xFF, base & 0xFF
        r2, g2, b2 = (bright >> 16) & 0xFF, (bright >> 8) & 0xFF, bright & 0xFF
        r = int(r1 + (r2 - r1) * amt)
        g = int(g1 + (g2 - g1) * amt)
        b = int(b1 + (b2 - b1) * amt)
        try:
            self.mac.pixels[11] = (r << 16) | (g << 8) | b
            self.mac.pixels.show()
        except Exception:
            pass
        return True

    # ----- Subtle blink on the current edit cursor key -----
    def _start_cursor_blink(self, period=0.60):
        """Begin subtle blink on the key under the edit cursor."""
        self._cursor_blink = {"t0": time.monotonic(), "period": float(period)}
        self._blink_last_key = None  # force a refresh on first update

    def _stop_cursor_blink(self, restore=True):
        if restore and self._blink_last_key is not None:
            k = self._blink_last_key
            try:
                self.mac.pixels[k] = self._idle_colors[k]
                self.mac.pixels.show()
            except Exception:
                pass
        self._cursor_blink = None
        self._blink_last_key = None

    def _cursor_key_for_current(self):
        """Return the key index for the current edit cursor event."""
        if not self.tune or not (0 <= self.cur < len(self.tune)):
            return None
        ev = self.tune[self.cur]
        if ev is REST:
            return 10
        idx = self._key_for_idx(ev)
        return idx if 0 <= idx < 12 else None

    def _update_cursor_blink(self, now):
        if not self._cursor_blink:
            return
        blink = self._cursor_blink
        k = self._cursor_key_for_current()

        # Restore previous key if cursor moved
        if k != self._blink_last_key and self._blink_last_key is not None:
            try:
                self.mac.pixels[self._blink_last_key] = self._idle_colors[self._blink_last_key]
            except Exception:
                pass
        self._blink_last_key = k
        if k is None:
            return

        # Cosine subtle blink: base → slightly brighter → base (uses period)
        period = blink["period"]
        phase = ((now - blink["t0"]) % period) / period
        amt = 0.5 - 0.5 * math.cos(2 * math.pi * phase)  # 0..1..0
        amt *= 0.20  # keep subtle (only 0..20% toward white)

        base = self._idle_colors[k]
        bright = self._apply_dim(0xFFFFFF)
        try:
            self.mac.pixels[k] = self._rgb_lerp(base, bright, amt)
            self.mac.pixels.show()
        except Exception:
            pass

    # ---------- Utils ----------
    def _clamp_bpm(self, v):
        return max(self._min_bpm, min(self._max_bpm, int(v)))

    def on_exit_hint(self):
        if self.mode == "compose":
            self._set_bottom("Press again to exit")

    def on_exit_hint_clear(self):
        if self.mode == "compose":
            self._set_bottom("Compose     Play")
        elif self.mode in ("edit", "durselect"):
            self._update_edit_status()

    # ----- K11 glow (breathe) while held -----
    def _start_k11_glow(self):
        # capture current pixel color so we can fade from/to it
        try:
            self._k11_base_rgb = self.mac.pixels[11]
        except Exception:
            self._k11_base_rgb = self._apply_dim(_COL_PLAY_IDLE)
        self._k11_glow = {"t0": time.monotonic()}

    def _stop_k11_glow(self):
        self._k11_glow = None
        # restore captured base color for K11
        try:
            base = self._k11_base_rgb if self._k11_base_rgb is not None else self._apply_dim(_COL_PLAY_IDLE)
            self.mac.pixels[11] = base
            self.mac.pixels.show()
        except Exception:
            pass

    def _update_k11_glow(self, now):
        """Breathe K11 between its captured base color and a brighter green."""
        if not self._k11_glow:
            return
        t = (now - self._k11_glow["t0"]) % K11_GLOW_PERIOD
        phase = t / K11_GLOW_PERIOD
        amt = 0.5 - 0.5 * math.cos(2 * math.pi * phase)  # 0..1..0

        # base (captured) → bright (dimmed green)
        base = self._k11_base_rgb if self._k11_base_rgb is not None else self._apply_dim(_COL_PLAY_IDLE)
        bright = self._apply_dim(_COL_PLAY_ON)

        r1, g1, b1 = (base >> 16) & 0xFF, (base >> 8) & 0xFF, base & 0xFF
        r2, g2, b2 = (bright >> 16) & 0xFF, (bright >> 8) & 0xFF, bright & 0xFF
        r = int(r1 + (r2 - r1) * amt)
        g = int(g1 + (g2 - g1) * amt)
        b = int(b1 + (b2 - b1) * amt)
        try:
            self.mac.pixels[11] = (r << 16) | (g << 8) | b
            self.mac.pixels.show()
        except Exception:
            pass

    # ----- Edit-cursor highlight helpers -----
    def _hilite_cursor(self):
        """Nudge the blink to refresh for the current cursor key."""
        # We no longer paint directly here to avoid fighting the blink.
        # Force a refresh next frame:
        self._blink_last_key = None
