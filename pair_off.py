# pair_off.py — Master Merlin "Pair Off" for Adafruit MacroPad
# CircuitPython 8.x / 9.x compatible with LED animations, sound effects, and on-screen status
# Written by Iain Bennett — 2025
# Inspired by Keith Tanner's Merlin for the Macropad
#
# "Pair Off" is a competitive two-player-style game where you face off against
# Merlin in a battle of number selection. Ten numbered keys (1–10) start in play.
# On each round:
#   • You pick a number from the remaining pool.
#   • Merlin secretly picks a different number from the same pool.
#   • The winner of the round scores points equal to (player_guess + merlin_pick).
#   • The picked numbers are removed from play (both yours and Merlin’s if enabled).
#
# Gameplay:
#   • The game continues until no numbers remain.
#   • The player with the highest score at the end wins.
#
# Controls:
#   • K0..K8 = Numbers 1–9
#   • K10    = Number 10
#   • K9     = New Game (dim white when available)
#   • K11    = Enter / Computer Turn (pulses green when ready)
#
# Features:
#   • Per-key LED color coding: available, removed, round flashes, and final outcome colors
#   • Round result animations (flash colors for win, lose, tie)
#   • Configurable scoring rule to remove both picks or only Merlin’s pick
#   • On-screen title and status updates
#   • Distinct click sounds for keypresses, plus win/lose/tie melodies
#   • Error tones and visual feedback for invalid actions

import time, random, math
import displayio, terminalio
from adafruit_display_text import label

class pair_off:
    def __init__(self, macropad, tones):
        self.mac = macropad
        self.tones = tones

        # Visual style (borrowed from hi_lo)
        self.BRIGHT     = 0.30
        self.C_BG       = 0x000000
        self.C_NUM_IDLE = 0x102040  # available numbers (idle)
        self.C_NUM_OFF  = 0x000000  # removed
        self.C_NEW      = 0x202020  # K9 (New) dim white
        self.C_ENTER    = 0x009900  # K11 pulse green
        self.C_WIN_ALL  = 0x00AA00  # final: player wins => green keypad
        self.C_LOSE_ALL = 0xAA0000  # final: Merlin wins => red keypad
        self.C_TIE_ALL  = 0x0044FF  # final: tie => blue keypad
        self.C_FLASH_P  = 0x00FF66  # per-round flash if player round win
        self.C_FLASH_M  = 0xFF4444  # per-round flash if Merlin round win
        self.C_FLASH_T  = 0x3399FF  # per-round flash on tie

        # Keys
        self.K_NEW   = 9
        self.K_ENTER = 11
        self.KEY_FOR_NUM = {n: (n-1 if 1 <= n <= 9 else 10) for n in range(1, 11)}
        self.NUM_FOR_KEY = {v: k for k, v in self.KEY_FOR_NUM.items()}
        self.PLAY_KEYS = tuple(self.KEY_FOR_NUM.values())

        # Game behavior:
        # Set True to remove BOTH Merlin's pick and your guess each round.
        # This caps the maximum possible final score at 110 as requested.
        self.REMOVE_PLAYER_GUESS = True

        # State
        self.mode = "entry"   # "entry" | "reveal" | "won"
        self.remaining = set(range(1, 11))
        self.player_guess = None
        self.merlin_pick = None
        self.player_score = 0
        self.merlin_score = 0
        self.flash_until = 0.0

        # LEDs batched
        try: self.mac.pixels.auto_write = False
        except AttributeError: pass
        self.mac.pixels.brightness = self.BRIGHT

        self._build_display()

    # ---------- Public ----------
    def new_game(self):
        self.remaining = set(range(1, 11))
        self.player_guess = None
        self.merlin_pick = None
        self.player_score = 0
        self.merlin_score = 0
        self.mode = "entry"
        self.title.text = "Pair Off"
        self._set_status("Pick 1 to 10")
        self._paint_numbers()
        self._show()

    def button(self, key):
        now = time.monotonic()

        # New game any time
        if key == self.K_NEW:
            self._click(key)
            self.new_game()
            return

        # Ignore input during brief reveal flash
        if self.mode == "reveal" and now < self.flash_until:
            return

        if self.mode == "won":
            return  # wait for K9

        if self.mode == "entry":
            # number selection
            if key in self.NUM_FOR_KEY:
                n = self.NUM_FOR_KEY[key]
                
                if n in self.remaining:
                    self.player_guess = n
                    self._click(key)
                    self._set_status(f"Picked: {n}")
                    # brief highlight
                    self._flash_key(self.KEY_FOR_NUM[n], 0x3060A0, 0.07)
                    self._paint_numbers()
                    return
                else:
                    self._sound_error(key)

            # reveal / score
            if key == self.K_ENTER:
                if self.player_guess is None:
                    self._sound_error(self.K_ENTER) 
                    self._set_status("Choose number first")
                    return
                self._click(key)
                self._reveal_and_score()
                return

    def tick(self):
        now = time.monotonic()

        # After reveal flash ends, return to entry mode (or finish)
        if self.mode == "reveal" and now >= self.flash_until:
            if len(self.remaining) == 0:
                # Game ends
                self._end_game()
                return
            # next round
            self.mode = "entry"
            self.player_guess = None
            self.merlin_pick = None
            self._paint_numbers()
            self._set_status(f"Pick 1 to 10")
            return

        # Pulse Enter only while in entry mode and not yet chosen? (always OK)
        if self.mode == "entry":
            pulse = 0.35 + 0.65 * (0.5 + 0.5 * math.cos(now * 2 * math.pi * 0.9))
            self.mac.pixels[self.K_ENTER] = self._scale(self.C_ENTER, pulse)
            self.mac.pixels[self.K_NEW]   = self.C_NEW
            try: self.mac.pixels.show()
            except AttributeError: pass

    def cleanup(self):
        try: self.mac.pixels.auto_write = True
        except AttributeError: pass
        self.mac.pixels.fill((0,0,0))
        try: self.mac.pixels.show()
        except AttributeError: pass

    # ---------- Internals ----------
    def _reveal_and_score(self):
        # Merlin secretly picks from remaining (uniform)
        self.merlin_pick = random.choice(tuple(self.remaining))

        pg = self.player_guess
        mp = self.merlin_pick

        if pg > mp:
            # Player wins the round
            self.player_score += (pg + mp)
            self._round_flash(self.C_FLASH_P, f"You got it!")
        elif pg < mp:
            # Merlin wins the round
            self.merlin_score += (pg + mp)
            self._round_flash(self.C_FLASH_M, f"Merlin got it!")
        else:
            # Tie
            self._round_flash(self.C_FLASH_T, f"Tie!")

        # Remove Merlin's pick from the pool
        if mp in self.remaining:
            self.remaining.remove(mp)

        # Optionally also remove player's guess (to enforce 110 max)
        if self.REMOVE_PLAYER_GUESS and pg in self.remaining:
            self.remaining.remove(pg)

        # Mark removed keys dark
        self._paint_numbers()

        # Brief reveal phase
        self.mode = "reveal"
        self.flash_until = time.monotonic() + 0.9

    def _round_flash(self, color, msg):
        # Light only the board keys with a uniform color for a moment
        for k in self.PLAY_KEYS:
            # hide played keys
            self.mac.pixels[k] = self.C_NUM_OFF
        # Flash both chosen keys brighter so the round is clear
        if self.player_guess is not None:
            self.mac.pixels[self.KEY_FOR_NUM[self.player_guess]] = color
        if self.merlin_pick is not None:
            self.mac.pixels[self.KEY_FOR_NUM[self.merlin_pick]] = color
        # keep K9 dim
        self.mac.pixels[self.K_NEW] = self.C_NEW
        try: self.mac.pixels.show()
        except AttributeError: pass
        self._set_status(msg)

    def _end_game(self):
        self.mode = "won"

        # Decide final keypad color
        if self.player_score > self.merlin_score:
            col = self.C_WIN_ALL    # player wins -> green
        elif self.player_score < self.merlin_score:
            col = self.C_LOSE_ALL   # Merlin wins -> red
        else:
            col = self.C_TIE_ALL    # tie -> blue

        # Paint keypad (K0..K8, K10) with the result color
        for i in range(12):
            self.mac.pixels[i] = 0x000000
        for k in self.PLAY_KEYS:
            self.mac.pixels[k] = col
        self.mac.pixels[self.K_NEW]   = self.C_NEW      # K9 dim white (New)
        self.mac.pixels[self.K_ENTER] = 0x000000        # K11 off in final state

        try:
            self.mac.pixels.show()
        except AttributeError:
            pass

        # Put scores on the two text lines
        self.title.text  = f"You: {self.player_score}"
        self.status.text = f"Merlin: {self.merlin_score}"

        # Anim and text first then sound
        if col == self.C_WIN_ALL:
            self._sound_win() 
        elif col == self.C_LOSE_ALL:
            self._sound_lost() 
        else:
            self._sound_tie() 

    def _paint_numbers(self):
        # Base off
        for i in range(12):
            self.mac.pixels[i] = 0x000000
        # Show remaining numbers as idle steel-blue
        for n in self.remaining:
            self.mac.pixels[self.KEY_FOR_NUM[n]] = self.C_NUM_IDLE
        # Controls
        self.mac.pixels[self.K_NEW] = self.C_NEW
        # (K11 animation handled in tick)
        try: self.mac.pixels.show()
        except AttributeError: pass

    def _flash_key(self, key, color, dur):
        old = self.mac.pixels[key]
        self.mac.pixels[key] = color
        try: self.mac.pixels.show()
        except AttributeError: pass
        time.sleep(max(0.02, dur))
        self.mac.pixels[key] = old
        try: self.mac.pixels.show()
        except AttributeError: pass

    # ---------- Display (same pattern as hi_lo) ----------
    def _build_display(self):
        W, H = self.mac.display.width, self.mac.display.height
        g = displayio.Group()

        bg = displayio.Bitmap(W, H, 1)
        pal = displayio.Palette(1); pal[0] = self.C_BG
        g.append(displayio.TileGrid(bg, pixel_shader=pal))

        # Logo
        y0 = 0
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            x = max(0, (W - bmp.width)//2)
            g.append(displayio.TileGrid(
                bmp,
                pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter()),
                x=x, y=0
            ))
            y0 = bmp.height + 2
        except Exception:
            y0 = 0

        self.title = label.Label(
            terminalio.FONT, text="Pair Off",
            color=0xFFFFFF, anchor_point=(0.5,0.0), anchored_position=(W//2, y0)
        )
        g.append(self.title)

        self.status = label.Label(
            terminalio.FONT, text="Pick 1 to 10",
            color=0xA0A0A0, anchor_point=(0.5,0.0), anchored_position=(W//2, y0+14)
        )
        g.append(self.status)

        self.group = g
        self._show()

    def _show(self):
        try:
            self.mac.display.show(self.group)      # CP 8.x
        except AttributeError:
            self.mac.display.root_group = self.group  # CP 9.x

    def _set_status(self, text):
        if hasattr(self, "status") and self.status:
            self.status.text = text

    # ---------- tiny helpers ----------
    def _scale(self, color, s):
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        r = int(r * s); g = int(g * s); b = int(b * s)
        return (r << 16) | (g << 8) | b
    
    # ---------- sound helpers ----------
    def _play(self, freq, dur):
        try:
            self.mac.play_tone(freq, dur)
        except AttributeError:
            try:
                # fall back to first tone if available
                self.mac.play_tone(self.tones[0], dur)
            except Exception:
                pass

    def _tone_at(self, i, fallback):
        try:
            return self.tones[i]
        except Exception:
            return fallback[i % len(fallback)]

    def _click(self, key=None):
        # Default click pitch
        f = 523  # C5

        if key == self.K_NEW:          # New Game key
            f = 440                    # A4
        elif key == self.K_ENTER:      # Enter key
            f = 659                    # E5
        elif key is not None:
            try:
                if isinstance(self.tones, (list, tuple)) and len(self.tones) > 0:
                    f = self.tones[key % len(self.tones)]
            except Exception:
                pass

        self._play(f, 0.03)

    def _sound_win(self):
        fallback = [262, 330, 392, 523, 392, 523]  # C4 E4 G4 C5 G4 C5
        seq = [0, 2, 4, 6, 4, 6]
        for i in seq:
            self._play(self._tone_at(i, fallback), 0.2)

    def _sound_lost(self):
        fallback = [523, 392, 330, 262]  # C5 G4 E4 C4
        seq = [6, 4, 2, 0]
        for i in seq:
            self._play(self._tone_at(i, fallback), 0.3)

    def _sound_tie(self):
        fallback = [262, 330]  # C4 E4
        seq = [0, 2, 0, 2]
        for i in seq:
            self._play(self._tone_at(i, fallback), 0.15)
    
    def _sound_error(self, key=None):
        self._play(220, 0.05)  # low blip

        if key == self.K_ENTER:
            # Brief warning pulse on Enter (yellow)
            old = self.mac.pixels[self.K_ENTER]
            self.mac.pixels[self.K_ENTER] = 0xCCCC00
            try: self.mac.pixels.show()
            except AttributeError: pass
            time.sleep(0.07)
            self.mac.pixels[self.K_ENTER] = old
            try: self.mac.pixels.show()
            except AttributeError: pass

        elif key is not None:
            # Red flash on the pressed key (already-used number, etc.)
            self._flash_key(key, 0xFF0000, 0.07)