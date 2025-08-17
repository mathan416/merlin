# 🎼 MUSICAL LADDER — for Adafruit MacroPad (CircuitPython 8.x / 9.x)
#
# HOW TO PLAY
# ─────────────────────────────────────────────────────────────────────────────
# ░ Climb the Solfège Scale: DO → RE → MI → FA → SO → LA → TI → DO
# ░ Each “step” is a group of flashing LEDs. Strike them *all* in time!
# ░ Windows shrink as skill increases — Merlin-style 1…9 difficulty levels.
# ░ If you succeed, you ascend one rung up the ladder toward the TOP DO.
# ░ Miss the window? You slip down, but never below the first DO.
# ░ Reach the top and you WIN with a triumphant scale & LED flourish!
# ░ Fail at the bottom and you LOSE with a sour crash and red fade.
#
# THE VIBE
# ─────────────────────────────────────────────────────────────────────────────
# ░ A game of reflex and rhythm, where memory meets music.
# ░ Every press is rewarded with a note of the scale and solfège lyric,
#   making your climb *sing* as you play.
# ░ It feels like an Amiga demoscene tune fused with “Simon” & “Merlin.”
# ░ LED gradients pulse, tones climb, and victory feels earned.
#
# License:
#   Released under the CC0 1.0 Universal (Public Domain Dedication).
#   You can copy, modify, distribute, and perform the work, even for commercial
#   purposes, all without asking permission. Attribution is appreciated but not
#   required.
#
# ─────────────────────────────────────────────────────────────────────────────
import time
from random import randint

import displayio
import terminalio
from adafruit_display_text import label

# ----- GAME TIMING CONSTANTS -----
START_PAUSE = 3 
WINDOW_START = 3.0   # Level 1 window (seconds)
WINDOW_END   = 2   # Level 9 window (seconds)
SKILL_LEVELS = 9     # 1..9 (Merlin-style)

LEVEL_TO_WINDOW = {
    i: WINDOW_START - ((i - 1) / (SKILL_LEVELS - 1))**1.5 * (WINDOW_START - WINDOW_END)
    for i in range(1, SKILL_LEVELS + 1)
}

# ----- GROUP SIZE CONSTANTS -----
# Inclusive ranges; linearly scale from Level 1 to Level 9.
GROUP_MIN_START = 2
GROUP_MIN_END   = 4
GROUP_MAX_START = 3
GROUP_MAX_END   = 5

LEVEL_TO_GROUP_RANGE = {
    i: (
        int(round(GROUP_MIN_START + (GROUP_MIN_END - GROUP_MIN_START) * ((i - 1) / (SKILL_LEVELS - 1)))),
        int(round(GROUP_MAX_START + (GROUP_MAX_END - GROUP_MAX_START) * ((i - 1) / (SKILL_LEVELS - 1)))),
    )
    for i in range(1, SKILL_LEVELS + 1)
}


class musical_ladder:
    def __init__(self, macropad, tones):
        self.macropad = macropad

        # Tones from launcher (e.g., (196, 220, 247, 262, 294, 330, 349, 392, 440, 494, 523, 587))
        self._scale_idx = [3, 4, 5, 6, 7, 8, 9, 10]          # C D E F G A B C
        self._solfege   = ["DO - A deer!", "RE - A drop of", "MI - A name", "FA - A long long", "SO - A needle", "LA - A note to", "TI - A drink with", "That will bring"]
        self._solfege2   = ["A female deer", "golden sun", "I call myself", "way to run", "pulling thread", "follows SO", "jam and bread ", "us back to DO!"] 

        self.tones = list(tones)

        # State
        self.mode = "skill_select"    # "skill_select", "pause", "running", "ended"
        self.skill = None             # 1..9
        self.ladder_pos = 0           # 0..7 (0 = bottom do, 7 = top do)
        self.group_keys = set()       # subset of 0..8
        self.deadline = 0.0           # monotonic deadline
        self._pending_win = False
        self._pending_lose = False
        self._window_active = False
        self.last_skill = None
        self.now = time.monotonic()

        # Tables
        self.level_to_window = dict(LEVEL_TO_WINDOW)
        self.level_to_group_range = dict(LEVEL_TO_GROUP_RANGE)

        # Display group (launcher adopts this)
        self.group = self._build_ui()

        self._claim_leds()
        self._set_top("Pick a level")
        self._set_bottom("1 to 9")

    # ---------- Lifecycle ----------
    def new_game(self):
        print("new MUSICAL LADDER")
        self._claim_leds()
        self.now = time.monotonic()
        self._enter_skill_select()

    def cleanup(self):
        # Stop game loop
        self.mode = "ended"
        self.group_keys.clear()
        self._window_active = False
        self._pending_win = False
        self._pending_lose = False

        # Clear LEDs
        try:
            self.macropad.pixels.fill((0, 0, 0))
            self.macropad.pixels.show()
        except Exception:
            pass

        # Reset OLED
        try:
            self._set_top("")
            self._set_bottom("")
        except Exception:
            pass

    # ---------- Input ----------
    def button(self, key):
        # K9 always returns to skill select (NEW GAME)
        if self.mode == "skill_select":
            if 0 <= key <= 8:
                self.skill = key + 1
                print("skill =", self.skill)
                self._start_after_pause()
            return
        
        # K9: always return to skill select
        if key == 9:
            self.now = time.monotonic()
            self._enter_skill_select()
            return

        # K11: start a game with the same skill level as previously selected
        if key == 11 and self.last_skill is not None:
            self.skill = self.last_skill
            self._start_after_pause()
            return
        
        if self.mode == "running":
            if key in self.group_keys:
                self._flash_press(key)
                self.group_keys.remove(key)
                self.macropad.pixels[key] = 0x000000
                if not self.group_keys:
                    self._window_active = False

                    # If we were at the top on a final group → WIN
                    if getattr(self, "_pending_win", False):
                        self._pending_win = False
                        self._win()
                        return

                    # If we were at the bottom on a lifeline group → step up and continue
                    if getattr(self, "_pending_lose", False):
                        self._pending_lose = False
                        self._advance_ladder(+1)
                        if self.mode != "running":
                            return
                        self._spawn_group()
                        return

                    # Normal mid-ladder advance
                    self._advance_ladder(+1)
                    if self.mode != "running":
                        return
                    self._spawn_group()
            return

        if self.mode == "ended":
            # K11 is handled by the global hotkey above; ignore other keys here.
            return

    def encoderChange(self, newPosition, oldPosition):
        pass

    def tick(self):
        self.now = time.monotonic()

        if self.mode == "pause":
            if self.now >= self.deadline:
                self._play_scale_note()  # bottom do
                self._spawn_group()
                self.mode = "running"
                self._update_oled_play()
            return

        if self.mode == "running":
            self._update_oled_play()
            if self.now >= self.deadline and self.group_keys and self._window_active:
                self._window_active = False

                # If we were at the top and failed the final group → step down and continue
                if self._pending_win:
                    self._pending_win = False
                    self._advance_ladder(-1)
                    if self.mode != "running":
                        return
                    self._spawn_group()
                    return

                # If we were at the bottom and failed the lifeline → LOSE
                if self._pending_lose:
                    self._pending_lose = False
                    self._lose()
                    return

                # Normal mid-ladder miss → step down and continue
                self._advance_ladder(-1)
                if self.mode != "running":
                    return
                self._spawn_group()
            return

    # ---------- Core mechanics ----------
    def _enter_skill_select(self):
        self.mode = "skill_select"
        self.skill = None
        self.ladder_pos = 0
        self.group_keys.clear()
        self.macropad.pixels.fill((0, 0, 0))
        self._paint_skill_gradient()              # <-- draw gradient
        self._set_top("Pick a level")
        self._set_bottom("1 to 9")
        self._window_active = False
        self._pending_win = False
        self._pending_lose = False
        

    def _start_after_pause(self):
        self.mode = "pause"
        self.last_skill = self.skill  
        self.ladder_pos = 0
        self.group_keys.clear()
        self.macropad.pixels.fill((0, 0, 0))
        self.now = time.monotonic()
        self._window_active = False
        self._pending_win = False
        self._pending_lose = False
        
        # Blocking 3-2-1 countdown with tones (0.5s between steps)
        # Simple ascending ticks: 660 Hz, 770 Hz, 880 Hz
        ticks = {3: 660, 2: 770, 1: 880}
        for n in range(START_PAUSE, 0, -1):
            self._set_top(f"Starting in {n}")
            self._set_bottom("")
            try:
                self.macropad.play_tone(ticks.get(n, 700), 0.2)
            except Exception:
                pass
            time.sleep(0.5)

        # Start: play bottom DO, spawn first group, enter running
        self._play_scale_note(dur=0.15)   # bottom DO
        self._spawn_group()
        self.mode = "running"
        self._update_oled_play()

    def _spawn_group(self):
        # Window for this level
        self.now = time.monotonic()
        self._window_active = True
        window = self.level_to_window.get(self.skill, 2.0)
        self.deadline = self.now + window

        # Level-scaled group size
        min_size, max_size = self.level_to_group_range.get(self.skill, (2, 3))
        min_size = max(1, min(min_size, 9))
        max_size = max(min_size, min(max_size, 9))

        size = randint(min_size, max_size)
        # keys = sample(range(0, 9), k=size)   # <-- remove this
        keys = self._unique_keys(size, 0, 8)     # <-- use this
        self.group_keys = set(keys)

        # Clear LEDs
        self.macropad.pixels.fill((0, 0, 0))

        # Light functional hints
        self.macropad.pixels[9]  = 0x202020  # NEW GAME
        self.macropad.pixels[11] = 0x202020  # SAME GAME

        # Paint the group
        for k in keys:
            self.macropad.pixels[k] = self._gradient_color_for_index(k)

    def _advance_ladder(self, delta):
        prev = self.ladder_pos
        self.ladder_pos = max(0, min(7, self.ladder_pos + delta))
        self._play_scale_note()
        if self.mode == "running":
            self._update_oled_play()

        # Reaching top: spawn a final playable group at the top
        if delta > 0 and self.ladder_pos == 7:
            self._pending_win = True
            self._pending_lose = False
            self._spawn_group()
            return

        # Reaching bottom: spawn a “lifeline” group at the bottom
        if delta < 0 and prev > 0 and self.ladder_pos == 0:
            self._pending_lose = True
            self._pending_win = False
            self._spawn_group()
            return

    # ---------- Sounds / feedback ----------
    def _play_scale_note(self, dur=0.22):
        idx = self._scale_idx[self.ladder_pos]
        freq = self.tones[idx] if 0 <= idx < len(self.tones) else 440
        self.macropad.play_tone(freq, max(0.05, dur))

    def _win(self):
        self.mode = "ended"
        self._set_top("You reached the top!")
        self._set_bottom("Press NEW/SAME")
        
        # Green sweep across K0..K8            
        for k in range(0, 9):
            self.macropad.pixels.fill((0, 0, 0))
            self.macropad.pixels[k] = 0x00AA00
            time.sleep(0.05)
        # Ascending jingle
        for hop in [0, 2, 4, 7, 12]:
            base = self.tones[self._scale_idx[0]]
            self.macropad.play_tone(int(base * (2 ** (hop / 12.0))), 0.10)
            time.sleep(0.02)
        # Green flash
        for _ in range(3):
            self.macropad.pixels.fill(0x00AA00); time.sleep(0.06)
            self.macropad.pixels.fill((0, 0, 0));     time.sleep(0.06)

        # ✨ Ensure no leftover LEDs (this clears K8) and show end-state hints
        self.macropad.pixels.fill((0, 0, 0))
        self.macropad.pixels[9]  = 0x202020  # NEW GAME (dim hint)
        self.macropad.pixels[11] = 0x202020 # SAME GAME
        self.group_keys.clear()
        self._window_active = False
        self._pending_win = False
        self._pending_lose = False

    def _lose(self):
        self.mode = "ended"
        self._set_top("You're at the bottom!")
        self._set_bottom("Press NEW/SAME")
        # Red flash
        for _ in range(3):
            self.macropad.pixels.fill((0xAA, 0, 0)); time.sleep(0.06)
            self.macropad.pixels.fill((0, 0, 0));     time.sleep(0.06)
        # Descending tones
        for hop in [7, 5, 3, 2, 0]:
            base = self.tones[self._scale_idx[0]]
            self.macropad.play_tone(int(base * (2 ** (hop / 12.0))), 0.10)
            time.sleep(0.02)

        # ✨ End-state hints (match win behavior)
        self.macropad.pixels[9]  = 0x202020  # NEW GAME (dim hint)
        self.macropad.pixels[11] = 0x202020  # SAME GAME
        self.group_keys.clear()
        self._window_active = False
        self._pending_win = False
        self._pending_lose = False

    def _flash_press(self, key):
        old = self.macropad.pixels[key]
        self.macropad.pixels[key] = 0x009900
        try: self.macropad.pixels.show()
        except AttributeError: pass
        time.sleep(0.04)
        self.macropad.pixels[key] = old

    # ---------- OLED UI ----------
    def _build_ui(self):
        group = displayio.Group()
        w = self.macropad.display.width

        base_y = 0
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile = displayio.TileGrid(
                bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            group.append(tile)  # draw logo first (background)
            # Put text a couple pixels below the logo
            base_y = getattr(bmp, "height", 0) + 2
        except Exception:
            # No logo? Start a bit down from the top so it still looks nice
            base_y = 14

        # Two compact text lines under the logo
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

    def _update_oled_play(self):
        if self.skill is None:
            return
        note = self._solfege[self.ladder_pos]
        addl_note = self._solfege2[self.ladder_pos]
        self._set_top(f"{note}")
        self._set_bottom(f"{addl_note}")

    # ---------- LEDs ----------
    def _claim_leds(self):
        try: self.macropad.pixels.auto_write = True
        except AttributeError: pass
        self.macropad.pixels.brightness = 0.30
        self.macropad.pixels.fill((0, 0, 0))
        try: self.macropad.pixels.show()
        except AttributeError: pass
    
    def _paint_skill_gradient(self):
        for i in range(9):
            self.macropad.pixels[i] = self._gradient_color_for_index(i)
        self.macropad.pixels[9]  = 0x000000  # NEW: keep K9 off in skill select
        self.macropad.pixels[10] = 0x000000
        self.macropad.pixels[11] = 0x000000
    
    def _gradient_color_for_index(self, i):
        """K0..K8 mapped green→red; returns 24-bit RGB."""
        t = max(0.0, min(1.0, i / 8.0))  # 0 at K0 → 1 at K8
        r = int(255 * t)
        g = int(255 * (1.0 - t))
        return (r << 16) | (g << 8)  # (r,g,0)

    # ---------- Utility ----------
    def _unique_keys(self, count, low=0, high=8):
        """Pick `count` unique ints between low..high inclusive (no replacement)."""
        pool = list(range(low, high + 1))
        out = []
        for _ in range(min(count, len(pool))):
            i = randint(0, len(pool) - 1)
            out.append(pool.pop(i))
        return out