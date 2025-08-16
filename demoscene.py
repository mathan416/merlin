# ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 
# ▓  DDDD   EEEEE  M   M  OOO   SSS   CCCC  EEEEE  N   N  EEEEE        ▓ 
# ▓  D   D  E      MM MM O   O S     C      E      NN  N  E            ▓ 
# ▓  D   D  EEEE   M M M O   O  SSS  C      EEEE   N N N  EEEE         ▓ 
# ▓  D   D  E      M   M O   O     S C      E      N  NN  E            ▓ 
# ▓  DDDD   EEEEE  M   M  OOO   SSS   CCCC  EEEEE  N   N  EEEEE        ▓ 
# ▓                                                                    ▓ 
# ▓▒░  Demoscene — an Amiga demo-scene homage for Adafruit MacroPad  ░▒▓ 
# ▓▒░  License: MIT — see end of file for details                    ░▒▓ 
# ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  
# demoscene.py — 90s "demo scene" homage for Adafruit MacroPad (CircuitPython 9.x)
# Monochrome OLED line art + NeoPixel rainbow swirl + wild animations
#
# Inspired as an homage to the Amiga Demo Scene — real-time visuals, sync’d motion,
# and generative patterns squeezed into tiny hardware.
#
# License:
#   Released under the CC0 1.0 Universal (Public Domain Dedication).
#   You can copy, modify, distribute, and perform the work, even for commercial purposes,
#   all without asking permission. Attribution is appreciated but not required.
#
# Requires:
#   - CircuitPython 9.x
#   - Adafruit MacroPad
#   - displayio + bitmaptools (if available, for faster drawing)
#
# Scenes:
#   0 — Wireframe cube
#   1 — Lissajous figures (refined morphs, trails, optional twins/orbits)
#   2 — Pulse circles (freeze-able breathing rings + sweep line)
#   3 — Bouncing triangles
#
# NeoPixel animations:
#   - Rainbow swirl with brightness modulation
#   - Easily extendable with waveforms, sparkles, or pulse-based effects
#
# Keys:
#   0–3  Select scene
#   4    Cycle Lissajous preset
#   5    Change segments/frame
#   6    Toggle Lissajous morph
#   7    Toggle twin pens
#   8    Toggle orbit
#   9    Freeze pulse circles
#   10   Toggle Lissajous demo mode
#   11   Toggle frame rate (30 / 45 FPS)
#
# Date: 2025-08-15
# Author: Iain Bennett (adapted for MacroPad Battleship)

import time
import math
import displayio
import supervisor

# Try to use bitmaptools; fall back to pure-Python if missing
try:
    import bitmaptools
    _HAVE_BMT = True
except Exception:
    _HAVE_BMT = False

class demoscene:
    supports_double_encoder_exit = False

    def __init__(self, macropad, tones=None, **kwargs):
        self.macropad = macropad

        # ---- Display setup (monochrome) ----
        self.W = macropad.display.width
        self.H = macropad.display.height
        self.bitmap = displayio.Bitmap(self.W, self.H, 2)  # 0=black, 1=white
        self.palette = displayio.Palette(2)
        self.palette[0] = 0x000000
        self.palette[1] = 0xFFFFFF

        self.tilegrid = displayio.TileGrid(self.bitmap, pixel_shader=self.palette)
        self.group = displayio.Group()
        self.group.append(self.tilegrid)

        # Frame/scene timing
        self._prev_scene = -1
        self._frame = 0
        self._scene = 0
        self._scene_ticks = 0
        self.target_fps = 30
        self.dt_target = 1.0 / self.target_fps
        self._last = time.monotonic()

        # Lissajous
        # Lissajous presets & defaults (refined)
        self._liz_presets = [
            (3,2),(5,4),(5,3),(7,4),(9,8),
            (7,5),(8,3),(9,5),(11,7),(12,5),
            (4,3),(6,5),(7,3),(10,7)
        ]
        self._liz_preset_idx = 0

        # Refined look: slow, clean, no dotted, no demo
        self._liz_morph  = True
        self._liz_twins  = False
        self._liz_orbit  = False
        self._liz_dotted = False

        self._liz_phase_lfo = 0.0
        self._liz_phase_lfo_speed = 0.0025  # slower tilt wobble

        self._liz_demo = False              # turn off auto-mix for refined look
        self._liz_demo_next_s = 0.0

        # runtime
        self._liz_segments_per_frame = 1    # draw one short step per frame
        self._liz_dphase = 0.045            # small angular step => slow, smooth
        

        # NeoPixels
        try:
            self.macropad.pixels.auto_write = False
        except AttributeError:
            pass
        self.macropad.pixels.brightness = 0.30

        # --- NeoPixel animator state ---
        self._led_mode = 0              # 0: rainbow breathe, 1: comet, 2: twinkle, 3: sine-chase
        self._led_mode_auto = True
        self._led_next_switch = time.monotonic() + 8.0
        self._spark = [0] * 12          # twinkle intensities (0..255)
        self._comet_len = 4             # trail length in pixels (fractional distance shaped in calc)
        self._led_speed = 1.0           # global speed multiplier (used by some modes)

        # tiny LCG for cheap pseudo-random (no allocations)
        self._rng = 0xA5A5

        # Sine LUT for LED brightness modulation
        self._sin256 = [math.sin(2 * math.pi * i / 256.0) for i in range(256)]

        # Geometry scratch
        self._cx = self.W // 2
        self._cy = self.H // 2

        # Wireframe cube points/edges
        s = min(self.W, self.H) // 4
        self._cube_pts = [
            (-s, -s, -s), ( s, -s, -s), ( s,  s, -s), (-s,  s, -s),
            (-s, -s,  s), ( s, -s,  s), ( s,  s,  s), (-s,  s,  s),
        ]
        self._cube_edges = [
            (0,1),(1,2),(2,3),(3,0),
            (4,5),(5,6),(6,7),(7,4),
            (0,4),(1,5),(2,6),(3,7),
        ]

        self._scene_duration = 5.5  # seconds/scene

    # ------------- Launcher API -------------
    def new_game(self):
        self._frame = 0
        self._scene = 0
        self._scene_ticks = 0
        self._prev_scene = -1

    def cleanup(self):
        try:
            self.macropad.pixels.fill(0)
            self.macropad.pixels.show()
        except Exception:
            pass

    def button(self, key):
        # existing keys...
        if key in (0, 1, 2, 3):
            self._scene = key
            self._scene_ticks = 0
        elif key == 11:
            self.target_fps = 45 if self.target_fps == 30 else 30
            self.dt_target = 1.0 / self.target_fps
        elif key == 9:
            self._pulse_freeze = not getattr(self, "_pulse_freeze", False)

        # ---- Lissajous toys ----
        elif key == 4:
            if self._scene == 1:
                # Lissajous preset advance
                self._liz_preset_idx = (self._liz_preset_idx + 1) % len(self._liz_presets)
                a, b = self._liz_presets[self._liz_preset_idx]
                self._liz_a_target, self._liz_b_target = a, b
                if not self._liz_morph:
                    self._liz_a, self._liz_b = float(a), float(b)
                self._liz_reset_trail(clear=False)
            else:
                # LED mode cycle
                self._led_mode = (self._led_mode + 1) & 0x03
                self._led_mode_auto = False
                self._led_next_switch = time.monotonic() + 12.0  # pause auto for a bit

        elif key == 5:   # segments/frame 1→2→3
            self._liz_segments_per_frame = 1 + (self._liz_segments_per_frame % 3)
            # optional: self._liz_reset_trail(clear=False)

        elif key == 6:   # morph on/off
            self._liz_morph = not self._liz_morph
            self._liz_reset_trail(clear=False)

        elif key == 7:   # twin pens
            self._liz_twins = not self._liz_twins
            self._liz_reset_trail(clear=False)

        elif key == 8:   # center orbit
            self._liz_orbit = not self._liz_orbit
            self._liz_reset_trail(clear=False)

        elif key == 10:  # demo mode toggle
            self._liz_demo = not self._liz_demo
            self._liz_reset_trail(clear=False)

    def encoder_button(self, pressed):
        pass  # single-press exit handled by launcher

    def encoderChange(self, pos, last_pos):
        delta = pos - last_pos
        if not delta:
            return
        if self._scene == 1:  # Lissajous
            # narrow, gentle range for refined motion
            base = getattr(self, "_liz_dphase", 0.045)
            self._liz_dphase = max(0.01, min(0.12, base + delta * 0.005))
        else:
            # gentle LED speed nudge (0.5..2.0)
            self._led_speed = max(0.5, min(2.0, self._led_speed + delta * 0.05))
            self._frame += delta * 2  # keep your existing hue nudge too
    # ------------- Main tick -------------
    def tick(self):
        now = time.monotonic()
        if now - self._last < self.dt_target:
            return
        self._last = now

        # LEDs
        self._update_pixels(self._frame)
        try:
            self.macropad.pixels.show()
        except Exception:
            pass

        # Display
        self._draw_scene(self._frame)

        # Scene advance
        self._scene_ticks += 1
        if self._scene_ticks >= int(self._scene_duration * self.target_fps):
            self._scene = (self._scene + 1) & 0x03
            self._scene_ticks = 0

        self._frame += 1

    # ------------- NeoPixel swirl -------------
    def _wheel(self, pos):
        pos &= 255
        if pos < 85:
            return (pos * 3, 255 - pos * 3, 0)
        if pos < 170:
            pos -= 85
            return (255 - pos * 3, 0, pos * 3)
        pos -= 170
        return (0, pos * 3, 255 - pos * 3)

    def _rng8(self):
        # 16-bit LCG -> return low 8 bits
        self._rng = (1103515245 * self._rng + 12345) & 0xFFFF
        return (self._rng >> 8) & 0xFF

    def _scale_color(self, rgb, s):  # s in 0..1
        r, g, b = rgb
        return (int(r * s), int(g * s), int(b * s))

    def _circ_dist(self, i, j, n=12):
        # shortest circular distance between i and j on ring of n
        d = abs(i - j)
        return d if d <= n - d else n - d

    def _update_pixels(self, frame):
        # auto-cycle modes every ~8s unless manually overridden
        if self._led_mode_auto and time.monotonic() >= self._led_next_switch:
            self._led_mode = (self._led_mode + 1) & 0x03
            self._led_next_switch = time.monotonic() + 8.0

        mode = self._led_mode
        sines = self._sin256

        if mode == 0:
            # --- Rainbow Breathe (your original with subtle tweaks) ---
            base = int(frame * 3 * self._led_speed) & 255
            s = sines[(int(frame * 2 * self._led_speed)) & 255]  # -1..1
            scale = 0.80 + 0.20 * s                               # 0.60..1.00
            for i in range(12):
                r, g, b = self._wheel((base + i * 18) & 255)
                self.macropad.pixels[i] = (int(r * scale), int(g * scale), int(b * scale))

        elif mode == 1:
            # --- Comet: bright head with soft, smooth trail ---
            # head moves sub-pixel smoothly; trail via distance shaping
            head_f = (frame * 0.45 * self._led_speed) % 12.0
            base_hue = (int(frame * 2 * self._led_speed) & 255)
            trail = float(self._comet_len)
            for i in range(12):
                # circular fractional distance: approximate by checking both directions
                d0 = abs(i - head_f)
                d1 = 12.0 - d0
                d = d0 if d0 < d1 else d1
                # intensity falls off smoothly; clamp to [0,1]
                t = max(0.0, 1.0 - (d / trail))
                # soften (ease^2) for nicer falloff
                t *= t
                col = self._wheel((base_hue + int(i * 12)) & 255)
                self.macropad.pixels[i] = self._scale_color(col, t)

        elif mode == 2:
            # --- Twinkle: dim base + sparse sparkles that decay ---
            base_hue = (int(frame * 1.2 * self._led_speed) & 255)
            base_col = self._wheel(base_hue)
            base_scale = 0.12  # very dim base
            # random spark spawn
            if self._rng8() < 10:  # ~4% chance per frame to spawn one sparkle
                idx = self._rng8() % 12
                self._spark[idx] = 255
            for i in range(12):
                # decay sparkle
                if self._spark[i] > 0:
                    self._spark[i] = max(0, self._spark[i] - 32)
                spark_scale = self._spark[i] / 255.0
                # combine base + sparkle (simple additive clamp)
                br = min(1.0, base_scale + spark_scale)
                self.macropad.pixels[i] = self._scale_color(base_col, br)

        else:
            # --- Sine-chase: a single hue pulsing around the ring ---
            hue = (int(frame * 1.0 * self._led_speed) & 255)
            col = self._wheel(hue)
            phase = int(frame * 8 * self._led_speed)  # how fast the lobe travels
            for i in range(12):
                s = sines[((phase + i * 21) & 255)]  # -1..1
                br = 0.10 + 0.90 * (0.5 * (s + 1.0))  # 0.10..1.0
                self.macropad.pixels[i] = self._scale_color(col, br)

    # ------------- Drawing helpers (bitmaptools first) -------------
    def _clear(self):
        if _HAVE_BMT:
            try:
                bitmaptools.fill_region(self.bitmap, 0, 0, self.W, self.H, 0)
                return
            except Exception:
                pass
        self.bitmap.fill(0)

    def _pset(self, x, y):
        if 0 <= x < self.W and 0 <= y < self.H:
            self.bitmap[x, y] = 1

    def _line(self, x0, y0, x1, y1):
        if _HAVE_BMT:
            try:
                bitmaptools.draw_line(self.bitmap, x0, y0, x1, y1, 1)
                return
            except Exception:
                pass
        # Fallback: Bresenham
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self._pset(x0, y0)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def _circle(self, cx, cy, r):
        if _HAVE_BMT:
            try:
                bitmaptools.draw_circle(self.bitmap, cx, cy, r, 1)
                return
            except Exception:
                pass
        # Fallback: midpoint circle
        x = r
        y = 0
        err = 0
        while x >= y:
            self._pset(cx + x, cy + y)
            self._pset(cx + y, cy + x)
            self._pset(cx - y, cy + x)
            self._pset(cx - x, cy + y)
            self._pset(cx - x, cy - y)
            self._pset(cx - y, cy - x)
            self._pset(cx + y, cy - x)
            self._pset(cx + x, cy - y)
            y += 1
            if err <= 0:
                err += 2 * y + 1
            if err > 0:
                x -= 1
                err -= 2 * x + 1

    # ------------- Scenes -------------
    def _draw_scene(self, frame):
        if self._scene in (0, 2, 3):
            self._clear()

        if self._scene == 0:
            self._scene_wire_cube(frame)
        elif self._scene == 1:
            self._scene_lissajous(frame)
        elif self._scene == 2:
            self._scene_pulse_circles(frame)
        else:
            self._scene_bounce_tris(frame)

        self._prev_scene = self._scene

    def _scene_wire_cube(self, frame):
        t = frame * 0.06
        ca = math.cos(t)
        sa = math.sin(t)
        cb = math.cos(t * 0.7 + 1.1)
        sb = math.sin(t * 0.7 + 1.1)

        proj = []
        for (x, y, z) in self._cube_pts:
            xz = x * ca - y * sa
            yz = x * sa + y * ca
            y2 = yz * cb - z * sb
            z2 = yz * sb + z * cb
            d = 180.0 / (z2 + 260.0)
            px = int(self._cx + xz * d)
            py = int(self._cy + y2 * d)
            proj.append((px, py))

        for (a, b) in self._cube_edges:
            ax, ay = proj[a]
            bx, by = proj[b]
            self._line(ax, ay, bx, by)

    # ----- Lissajous helpers -----
    def _liz_reset_trail(self, clear=True):
        # Reset the ring buffer + last points to avoid cross-erasures
        self._liz_trail_len = getattr(self, "_liz_trail_len", 48)
        # store (x0, y0, x1, y1, is_dot)
        self._liz_buf = [(0,0,0,0,0)] * self._liz_trail_len
        self._liz_head = 0
        self._liz_filled = 0
        if clear:
            self._clear()
        # re-seed last points at current center & phase
        if not hasattr(self, "_liz_rx"):
            self._liz_rx = (self.W // 2) - 4
            self._liz_ry = (self.H // 2) - 6
        self._liz_last  = (int(self._cx + self._liz_rx * math.sin(getattr(self, "_liz_phase", 0.0))), int(self._cy))
        self._liz_last2 = self._liz_last

    def _scene_lissajous(self, frame):
        # ---- One-time init when entering this scene ----
        if self._prev_scene != 1:
            a0, b0 = self._liz_presets[self._liz_preset_idx]
            self._liz_a = float(a0); self._liz_b = float(b0)
            self._liz_a_target, self._liz_b_target = a0, b0

            self._liz_phase = 0.0
            self._liz_dphase = getattr(self, "_liz_dphase", 0.045)
            self._liz_rx = (self.W // 2) - 4
            self._liz_ry = (self.H // 2) - 6

            # longer, silkier trail
            self._liz_trail_len = 96
            self._liz_reset_trail(clear=True)

            self._liz_phase_lfo = 0.0
            self._prev_scene = 1
            self._liz_demo_next_s = time.monotonic() + 5.0

        # ---- Demo mode auto-mix ----
        if self._liz_demo:
            now_s = time.monotonic()
            if now_s >= self._liz_demo_next_s:
                # next preset
                self._liz_preset_idx = (self._liz_preset_idx + 1) % len(self._liz_presets)
                a_t, b_t = self._liz_presets[self._liz_preset_idx]
                self._liz_a_target, self._liz_b_target = a_t, b_t
                # pseudo-random toggles
                f = (frame // (self.target_fps or 1)) & 7
                if f & 1: self._liz_twins  = not self._liz_twins
                if f & 2: self._liz_orbit  = not self._liz_orbit
                if f & 4: self._liz_dotted = not self._liz_dotted
                # speed hop within bounds
                self._liz_dphase = max(0.05, min(0.30, self._liz_dphase + (0.03 if (f & 1) else -0.02)))
                # reset trail after this “step” so old geometry doesn’t carve new
                self._liz_reset_trail(clear=False)
                # next change in ~4–7 s
                self._liz_demo_next_s = now_s + 4.0 + (f % 4) * 0.75

        # ---- Gentle morph of a/b toward integer targets ----
        # gentle morph
        if self._liz_morph:
            self._liz_a += (self._liz_a_target - self._liz_a) * 0.02
            self._liz_b += (self._liz_b_target - self._liz_b) * 0.02

        # subtle wobble + tiny optional orbit
        self._liz_phase_lfo += self._liz_phase_lfo_speed
        wobble = 0.15 * math.sin(self._liz_phase_lfo)
        if self._liz_orbit:
            orb_r = 2
            ocx = self._cx + int(orb_r * math.cos(self._liz_phase_lfo * 0.7))
            ocy = self._cy + int(orb_r * math.sin(self._liz_phase_lfo * 0.9))
        else:
            ocx, ocy = self._cx, self._cy

        # ---- Phase wobble & optional center orbit ----
        self._liz_phase_lfo += self._liz_phase_lfo_speed
        wobble = 0.35 * math.sin(self._liz_phase_lfo)
        if self._liz_orbit:
            orb_r = 3
            ocx = self._cx + int(orb_r * math.cos(self._liz_phase_lfo * 0.7))
            ocy = self._cy + int(orb_r * math.sin(self._liz_phase_lfo * 0.9))
        else:
            ocx, ocy = self._cx, self._cy

        # ---- Fast locals for the hot loop ----
        segs   = self._liz_segments_per_frame
        step   = self._liz_dphase
        wrap   = 2 * math.pi
        linev  = self._line_val
        psetv  = self._pset_val
        rx, ry = self._liz_rx, self._liz_ry
        a, b   = self._liz_a,  self._liz_b
        dotted = self._liz_dotted

        # ---- One pen step (draw + trail ring buffer, dot-aware) ----
        def _step_pen(last_xy, phase_offset=0.0):
            t = (self._liz_phase + phase_offset + wobble)
            x = int(ocx + rx * math.sin(a * t))
            y = int(ocy + ry * math.sin(b * t))
            x0, y0 = last_xy

            if dotted and ((frame + int(phase_offset * 1000)) & 1):
                # draw one pixel and remember as a dot
                psetv(x, y, 1)
                seg = (x, y, x, y, 1)
            else:
                # draw line and remember as a line
                linev(x0, y0, x, y, 1)
                seg = (x0, y0, x, y, 0)

            # push to ring buffer; erase oldest exactly as drawn
            self._liz_buf[self._liz_head] = seg
            self._liz_head = (self._liz_head + 1) % self._liz_trail_len
            if self._liz_filled < self._liz_trail_len:
                self._liz_filled += 1
            else:
                ox0, oy0, ox1, oy1, odot = self._liz_buf[self._liz_head]
                if odot:
                    psetv(ox1, oy1, 0)
                else:
                    linev(ox0, oy0, ox1, oy1, 0)
            return (x, y)

        # ---- Advance several tiny segments per frame ----
        for _ in range(segs):
            self._liz_last = _step_pen(self._liz_last, 0.0)
            if self._liz_twins:
                self._liz_last2 = _step_pen(self._liz_last2, math.pi / 2)
            self._liz_phase = (self._liz_phase + step) % wrap

    def _scene_pulse_circles(self, frame):
        """
        Concentric rings that breathe without collapsing (integer math),
        with a working FREEZE toggle (Key 9).
        """
        MIN_SPACING = 4
        MIN_RINGS   = 4
        MAX_RINGS   = 7

        cx, cy = self._cx, self._cy
        circle = self._circle
        line   = self._line
        sines  = self._sin256

        # --- freeze support ---
        frozen = getattr(self, "_pulse_freeze", False)
        st = getattr(self, "_pulse_state", None)
        if st is None:
            st = self._pulse_state = {"maxr": 12, "radii": [6, 10], "ang": 0.0}

        if not frozen:
            # Outer radius (fast breathing)
            r_max_possible = (min(self.W, self.H) // 2) - 2
            s = sines[(frame * 6) & 255]  # -1..1
            maxr = int(r_max_possible * (0.62 + 0.30 * (0.5 * (1.0 + s))))
            if maxr < 8:
                maxr = 8

            # Desired rings (animated 5..7), clamped by available radius
            s2 = sines[(frame * 4) & 255]
            desired = 5 + int(2 * (0.5 * (1.0 + s2)))  # 5..7
            max_by_radius = max(1, (maxr - 1) // MIN_SPACING)
            rings = max(1, min(MAX_RINGS, desired, max_by_radius))
            if rings < MIN_RINGS and max_by_radius >= MIN_RINGS:
                rings = MIN_RINGS

            # nearest-int division helper (no floats)
            def _nint_div(n, d):
                return (n + (d // 2)) // d

            # Build radii with proportional slices and strict spacing
            def build_radii(rings_):
                denom = rings_ + 1
                radii = []
                last = 0
                for k in range(1, rings_ + 1):
                    r = _nint_div(k * maxr, denom)
                    if r <= last + MIN_SPACING:
                        r = last + MIN_SPACING
                    if r >= maxr:
                        r = maxr - 1
                    if r > last:
                        radii.append(r)
                        last = r
                return radii

            tries = 0
            radii = build_radii(rings)
            while len(radii) < max(1, rings - 1) and rings > 1 and tries < 3:
                rings -= 1
                radii = build_radii(rings)
                tries += 1

            # Save frame state for freeze
            st["maxr"]  = maxr
            st["radii"] = radii
            st["ang"]   = frame * 0.12

        # Use stored state (either just computed, or from freeze)
        maxr  = st["maxr"]
        radii = st["radii"]
        ang   = st["ang"]

        # Draw rings (thicken tight neighbors)
        THICKEN_THRESHOLD = 3
        prev = 0
        for r in radii:
            circle(cx, cy, r)
            if prev and (r - prev) < THICKEN_THRESHOLD and r > 1:
                circle(cx, cy, r - 1)
            prev = r

        # Sweep line (frozen when paused)
        x = int(cx + maxr * math.cos(ang))
        y = int(cy + maxr * math.sin(ang))
        line(cx, cy, x, y)

    def _scene_bounce_tris(self, frame):
        t = frame * 0.09
        r = min(self.W, self.H) // 3
        x1 = int(self._cx + (self.W//4) * math.sin(t * 0.9))
        y1 = int(self._cy + (self.H//5) * math.sin(t * 1.3))
        x2 = int(self._cx + (self.W//4) * math.sin(t * 1.1 + 1.7))
        y2 = int(self._cy + (self.H//5) * math.sin(t * 0.7 + 0.9))

        def tri(cx, cy, rot, rad):
            a1 = rot
            a2 = rot + 2.0944   # 120°
            a3 = rot + 4.18879  # 240°
            p1 = (int(cx + rad * math.cos(a1)), int(cy + rad * math.sin(a1)))
            p2 = (int(cx + rad * math.cos(a2)), int(cy + rad * math.sin(a2)))
            p3 = (int(cx + rad * math.cos(a3)), int(cy + rad * math.sin(a3)))
            self._line(p1[0], p1[1], p2[0], p2[1])
            self._line(p2[0], p2[1], p3[0], p3[1])
            self._line(p3[0], p3[1], p1[0], p1[1])

        tri(x1, y1, t * 0.9, int(r * 0.75))
        tri(x2, y2, -t * 1.2, int(r * 0.55))

    # ----- Color variants so we can erase with 0 or draw with 1 -----
    def _pset_val(self, x, y, v):
        if 0 <= x < self.W and 0 <= y < self.H:
            self.bitmap[x, y] = v

    def _line_val(self, x0, y0, x1, y1, v):
        if _HAVE_BMT:
            try:
                bitmaptools.draw_line(self.bitmap, x0, y0, x1, y1, v)
                return
            except Exception:
                pass
        # Fallback Bresenham with color
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self._pset_val(x0, y0, v)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy; x0 += sx
            if e2 <= dx:
                err += dx; y0 += sy