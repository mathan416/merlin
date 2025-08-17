# music_machine.py — Simple step recorder/sequencer for Adafruit MacroPad
# Class: music_machine
# Originally by Keith Tanner, Updates by Iain Bennett
#
# Overview:
#   Record a sequence of notes and rests on the MacroPad, then play it back.
#   Starts in recording mode with K9 dim white, K11 red, others off. Each note
#   press is appended to the sequence; playback flashes keys and sounds tones.
#
# Controls:
#   • K0–K8  : Notes (low to high). Adds that note to the sequence and beeps it.
#   • K10    : Rest (silence). Adds a rest step to the sequence.
#   • K9     : Reset sequence (does not wipe UI state). Returns to recording.
#   • K11    : Play the recorded sequence, then return to recording.
#   • Encoder: Adjust tempo in 5 BPM steps (≈30–300 BPM).
#
# Notes:
#   • Uses an internal simple scale (C-ish) and a silent “rest.”
#   • Playback briefly lights the corresponding key per step for visual timing.
#   • Designed for CircuitPython 8.x / 9.x on Adafruit MacroPad.

import time

class music_machine():
    def __init__(self, macropad, tones):
        # Ignore provided tones; use our own simple scale + rest
        self.tones = [196, 262, 294, 330, 350, 392, 440, 494, 523, 587, 0]
        # Fun palette to flash keys during playback (optional)
        self.colors = [
            0xF400FD, 0xD516ED, 0xB71EDC,
            0x9A21CB, 0x7F21B8, 0x651FA5,
            0x4C1C91, 0x34177D, 0x1D1268,
            0x010C54, 0x000000, 0x009900,
        ]
        self.macropad = macropad
        self.sequence = []
        self.gameMode = "recording"
        self.tempo = 150  # bpm
        self._ready = False  # block input until new_game() finishes

    def cleanup(self):
        # Make safe to call more than once
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True

        # Signal any in-progress playback loop to stop
        setattr(self, "_abort", True)
        self._ready = False

        # Stop any tone / quiet the speaker (best-effort)
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

        # LEDs off and restore auto_write
        try:
            px = self.macropad.pixels
            for i in range(12):
                px[i] = 0x000000
            try: px.show()
            except Exception: pass
            try: px.auto_write = True
            except Exception: pass
        except Exception:
            pass

        # (No display groups to detach in this game)

        # Encourage GC on small boards
        try:
            import gc
            gc.collect()
        except Exception:
            pass

    # ---------- Public API ----------
    def new_game(self):
        print("new Music Machine game")
        self._claim_leds()
        self.sequence.clear()
        self.gameMode = "recording"
        self._led_state_recording()   # K9 white, K11 red, others black
        self._ready = True            # <- enable playback now that UI is ready

    # ---------- Core actions ----------
    def play(self):
        if not self._ready:
            return
        self._abort = False

        if not self.sequence:
            self._blink_key(11, 0x999900, 0.18)
            self._led_state_recording()
            return

        self.macropad.pixels.fill((0, 0, 0))
        self.macropad.pixels[11] = 0x009900

        delay = 60.0 / max(1, self.tempo)
        for k in self.sequence:
            if getattr(self, "_abort", False):
                break
            if 0 <= k <= 11:
                self.macropad.pixels[k] = self.colors[k]
            f = self.tones[k] if 0 <= k < len(self.tones) else 0
            if f > 0:
                try: self.macropad.play_tone(f, delay)
                except Exception: time.sleep(delay)
            else:
                time.sleep(delay)
            if 0 <= k <= 11:
                self.macropad.pixels[k] = 0x000000

        # Return to recording UI (unless we were aborted mid-play)
        self.gameMode = "recording"
        self._led_state_recording()

    # ---------- Input ----------
    def button(self, key):
        if key == 9:
            # Green flash to acknowledge reset
            self.macropad.pixels[9] = 0x009900
            try: self.macropad.pixels.show()
            except AttributeError: pass
            time.sleep(0.08)
            self.sequence.clear()
            self.gameMode = "recording"
            self._led_state_recording()
            return

        if self.gameMode == "recording":
            if key < 10:  # notes 0..9
                self.macropad.pixels[key] = 0x009900
                self.macropad.play_tone(self.tones[key], 0.2)
                self.macropad.pixels[key] = 0x000000
                self.sequence.append(key)
            elif key == 10:  # REST key: visual ack, no tone
                self.macropad.pixels[10] = 0x303030
                try: self.macropad.pixels.show()
                except AttributeError: pass
                time.sleep(0.08)
                self.macropad.pixels[10] = 0x000000
                self.sequence.append(key)

        if key == 11:
            self.gameMode = "playing"
            self.play()

    def encoderChange(self, newPosition, oldPosition):
        # Adjust tempo in 5 bpm steps
        self.tempo = max(30, min(300, self.tempo + (newPosition - oldPosition) * 5))
        print("new tempo", self.tempo, "bpm")

    # ---------- UI helpers ----------
    def _led_state_recording(self):
        # Explicit paint + show so the first start always displays immediately
        self.macropad.pixels.fill((0, 0, 0))  # all black
        self.macropad.pixels[9]  = 0x202020   # K9 = dim white (New)
        self.macropad.pixels[11] = 0x990000   # K11 = red (record)
        try:
            self.macropad.pixels.show()
        except AttributeError:
            pass

    def _blink_key(self, key, color, dur):
        if not (0 <= key <= 11):
            return
        old = self.macropad.pixels[key]
        self.macropad.pixels[key] = color
        time.sleep(max(0.02, dur))
        self.macropad.pixels[key] = old
        
    def _claim_leds(self):
        # Make sure this game controls pixel writes from the very first frame
        try:
            self.macropad.pixels.auto_write = True
        except AttributeError:
            pass
        self.macropad.pixels.brightness = 0.30
        self.macropad.pixels.fill((0, 0, 0))
        try:
            self.macropad.pixels.show()
        except AttributeError:
            pass