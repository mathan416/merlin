# echo.py — Merlin-style memory sequence game for Adafruit MacroPad
# Class: echo
# Originally by Keith Tanner, updates by Iain Bennett
# Polished for Merlin Launcher compatibility by ChatGPT
#
# Controls:
# • Keys 1–9 choose puzzle length at start (sequence size).
# • During play, repeat the sequence (keys 1–9).
# • Key 9 repeats the same sequence (hint) mid-game.
# • Key 11 starts a brand-new game.
# • Encoder changes tempo (BPM).
#
# Notes:
# • Exposes .group for the launcher (Merlin logo + prompts).
# • Safe cleanup: tones off, LEDs off, display detached, GC.
# • Clamped tempo: 60–300 BPM.
# • No sub-loop blocking beyond tone durations; uses play_tone timing.

import time
import displayio
import terminalio
from random import randint

try:
    from adafruit_display_text import label
    HAVE_LABEL = True
except Exception:
    HAVE_LABEL = False


class echo:
    def __init__(self, macropad, tones):
        self.macropad = macropad
        self.tones = tones
        self.gameMode = "select"   # "select", "playing", "ended"
        self.puzzle = []
        self.player = []
        self.tempo = 150  # BPM (clamped in encoderChange)
        self._cleaned = False

        # 12-button palette (same as your launcher wipe colors, last two are control hints)
        self.clear = [
            0xF400FD, 0xD516ED, 0xB71EDC,
            0x9A21CB, 0x7F21B8, 0x651FA5,
            0x4C1C91, 0x34177D, 0x1D1268,
            0xFF9900, 0x000000, 0x00FF00,
        ]

        # ---- Optional display group for prompts/logo (launcher will show it if present) ----
        self.group = displayio.Group()
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile = displayio.TileGrid(
                bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            self.group.append(tile)
        except Exception:
            # No background is fine—text still shows
            pass

        self._title = None
        self._line1 = None
        self._line2 = None
        if HAVE_LABEL:
            self._title = label.Label(
                terminalio.FONT, text="Echo", color=0xFFFFFF,
                anchor_point=(0.5, 0.0),
                anchored_position=(self._cx(macropad), 2)
            )
            self._line1 = label.Label(
                terminalio.FONT, text="", color=0xFFFFFF,
                anchor_point=(0.5, 0.0),
                anchored_position=(self._cx(macropad), 31)
            )
            self._line2 = label.Label(
                terminalio.FONT, text="", color=0xFFFFFF,
                anchor_point=(0.5, 0.0),
                anchored_position=(self._cx(macropad), 45)
            )
            self.group.append(self._title)
            self.group.append(self._line1)
            self.group.append(self._line2)

        # Don’t auto-start; the launcher calls new_game()
        # self.new_game()

    # --- small helpers ---
    def _cx(self, mac):
        try:
            return mac.display.width // 2
        except Exception:
            return 64

    def _set_lines(self, l1="", l2=""):
        if self._line1:
            self._line1.text = l1
        if self._line2:
            self._line2.text = l2

    # --- lifecycle ---
    def new_game(self):
        print("new Echo game")
        self._safe_pixels_setup()
        self.puzzle.clear()
        self.player.clear()
        self.gameMode = "select"
        self.macropad.pixels.fill(0x000000)

        # Intro sweep across 1–9 (keys 0..8)
        for x in range(9):
            self.macropad.pixels[x] = 0x000099
            time.sleep(0.08)
            self.macropad.pixels[x] = self.clear[x]

        self._set_lines("Echo",
                        "Length: 1 to 9")

    def cleanup(self):
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True

        # Stop tones
        try:
            if hasattr(self.macropad, "stop_tone"):
                self.macropad.stop_tone()
        except Exception:
            pass
        try:
            spk = getattr(self.macropad, "speaker", None)
            if spk is not None:
                spk.enable = False
        except Exception:
            pass

        # LEDs off + normalize auto_write
        try:
            if hasattr(self.macropad, "pixels"):
                try:
                    self.macropad.pixels.auto_write = True
                except Exception:
                    pass
                self.macropad.pixels.fill(0x000000)
                self.macropad.pixels.show()
        except Exception:
            pass

        # Reset state
        try:
            self.gameMode = "select"
            self.puzzle.clear()
            self.player.clear()
        except Exception:
            pass

        # Detach group if the launcher doesn’t replace it first
        try:
            if getattr(self.macropad.display, "root_group", None) is self.group:
                self.macropad.display.root_group = None
        except Exception:
            pass

        # GC
        try:
            import gc
            gc.collect()
        except Exception:
            pass

    # --- core game flow ---
    def start_game(self, length):
        print("player has selected", length)
        self.macropad.pixels.fill(0x000000)
        time.sleep(0.2)

        self.puzzle.clear()
        self.player.clear()
        for _ in range(length):
            self.puzzle.append(randint(0, 8))  # keys 0..8

        self._set_lines(f"Now Playing",
                        "Echo")
        self.play_puzzle()

    def play_puzzle(self):
        delay = 60 / max(1, self.tempo)
        for idx in self.puzzle:
            self.macropad.pixels[idx] = 0x0A0014
            self.macropad.play_tone(self.tones[idx], delay)
            self.macropad.pixels[idx] = 0x000000
            time.sleep(0.05)

        self.clear_board()
        self.gameMode = "playing"

    def same_game(self):
        # Hint chime, then replay the puzzle
        self.gameMode = "playing"
        self.clear_board()
        try:
            self.macropad.play_tone(self.tones[4], 0.35)
            self.macropad.play_tone(self.tones[2], 0.35)
        except Exception:
            pass
        self.macropad.pixels.fill(0x000000)
        time.sleep(0.25)
        self.player.clear()
        self.play_puzzle()

    def end_game(self):
        self.gameMode = "ended"
        self.clear_board()
        print("END GAME OF ECHO")

        # Score the attempt (same length guarantee)
        score = 0
        for i in range(len(self.puzzle)):
            if self.puzzle[i] == self.player[i]:
                score += 1

        if score == len(self.puzzle):
            self.winner()
        else:
            # Visual score bar
            for i in range(score):
                self.macropad.pixels[i] = 0x009900
            for i in range(score, len(self.puzzle)):
                self.macropad.pixels[i] = 0x990000
            self._set_lines("Echo",
                            "Try again!")

    def winner(self):
        # Simple victorious arpeggio + green wash
        self.macropad.pixels.fill((0, 200, 0))
        seq = [0, 2, 4, 6, 4, 6]
        for s in seq:
            self.macropad.play_tone(self.tones[s], 0.18)
        print("you are a winner")
        self.clear_board()
        self._set_lines("",
                        "You Win!")

    # --- UI/inputs ---
    def clear_board(self):
        for i in range(12):
            self.macropad.pixels[i] = self.clear[i]

    def button(self, key):
        # Menu selection
        if self.gameMode == "select":
            if key < 9:
                # Choose length 1..9
                try:
                    self.macropad.play_tone(self.tones[key], 0.18)
                except Exception:
                    pass
                self.macropad.pixels[key] = 0x009900
                self.start_game(key + 1)
            else:
                return

        # Playing
        elif self.gameMode == "playing":
            if key == 9:
                self.same_game()
                return
            if key == 11:
                self.new_game()
                return
            if key < 9:
                # Show feedback for this press
                self.clear_board()
                expect = self.puzzle[len(self.player)]
                if key == expect:
                    self.macropad.pixels[key] = 0x000099
                    try:
                        self.macropad.play_tone(self.tones[key], 0.16)
                    except Exception:
                        pass
                else:
                    self.macropad.pixels[key] = 0x990000
                    # A distinct error tone (constant freq)
                    try:
                        self.macropad.play_tone(110, 0.5)
                    except Exception:
                        pass

                self.player.append(key)

                if len(self.player) == len(self.puzzle):
                    self.end_game()

        # Ended — allow controls
        else:
            if key == 9:
                self.same_game()
            elif key == 11:
                self.new_game()

    def encoderChange(self, newPosition, oldPosition):
        delta = (newPosition - oldPosition) * 5
        if delta == 0:
            return
        self.tempo = max(60, min(300, self.tempo + delta))
        print("new tempo", self.tempo, "bpm")
        if self.gameMode == "playing":
            self._set_lines(f"Now Playing",
                            "Echo")
        elif self.gameMode == "select":
            self._set_lines("Echo",
                            f"Tempo: {self.tempo} BPM")

    def tick(self):
        # No periodic logic needed; kept for launcher symmetry
        pass

    # --- internals ---
    def _safe_pixels_setup(self):
        try:
            old = self.macropad.pixels.auto_write
        except Exception:
            old = True
        try:
            self.macropad.pixels.auto_write = True
        except Exception:
            pass
        self.macropad.pixels.brightness = 0.30