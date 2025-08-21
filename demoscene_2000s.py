# shader_bag.py — 2000s "Club Shader Bag" for Merlin Launcher
# Target: Adafruit MacroPad (CircuitPython 9.x)
# Written by Iain Bennett — 2025
#
# Overview:
#   A retro shader “demo scene” bag inspired by 2000s club visuals.
#   Renders classic plasma, spectrum bars, tunnel warp, and matrix rain
#   effects on the 128×64 monochrome OLED. Paired with synchronized
#   MacroPad LED mappings for extra vibe.
#
# Controls:
#   • Encoder → cycle menu items
#   • Encoder press (single) → select demo
#   • Encoder press (double) → exit demo
#   • K3 (←)  → tweak speed/tempo down
#   • K5 (→)  → tweak speed/tempo up
#   • K7 (Fire) → shuffle / randomize parameters
#
# Visual Modes:
#   • Plasma     — oldschool blobby plasma with LED rainbow copper
#   • Spectrum   — beat-driven bars, tempo-sync’d LED spectrum mapper
#   • Tunnel     — twisting warp rings, LEDs breathe with depth bands
#   • Matrix     — digital rain (bitmap + LEDs, flicker-free persistence)
#
# LED Mapping:
#   • Auto-detects 3×4 layout (MacroPad 12 keys)
#   • Plasma: rainbow copper stripes
#   • Spectrum: LED bar graph (green→yellow→red) with kick “pump”
#   • Tunnel: depth-band breathing colors
#   • Matrix: green code rain (LED trails, flicker-free)
#   • Menu:   all LEDs off; highlights active controls
#
# Display:
#   • Menu: title, "Select:", demo name, and hint line
#   • HUD overlays in demo modes (tempo, exit hint, etc.)
#
# Sound:
#   • No audio output (visualizer only; LED “pump” mirrors kick env)
#
# Integration:
#   • Fully compatible with Merlin Launcher
#   • Defensive use of bitmaptools (clamped fills/lines)
#   • Cleanup() restores LEDs, display group, and stops tones

import time, math, random
import displayio, terminalio
import bitmaptools
from adafruit_display_text import label

SCREEN_W, SCREEN_H = 128, 64
CX, CY = SCREEN_W//2, SCREEN_H//2
K_LEFT, K_RIGHT, K_FIRE = 3, 5, 7
DOUBLE_PRESS_WINDOW = 0.35
TAU = getattr(math, "tau", 2.0 * math.pi)

def make_surface():
    bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
    pal = displayio.Palette(2); pal[0]=0x000000; pal[1]=0xFFFFFF
    return bmp, pal

def clear(bmp):
    # Fast clear via bitmaptools
    bitmaptools.fill_region(bmp, 0, 0, SCREEN_W, SCREEN_H, 0)

def hline(bmp,x0,x1,y,c=1):
    if y<0 or y>=SCREEN_H: return
    if x0>x1: x0,x1=x1,x0
    x0=max(0,x0); x1=min(SCREEN_W-1,x1)
    bitmaptools.draw_line(bmp, x0, y, x1, y, c)

def rect(bmp, x, y, w, h, c=1):
    if w <= 0 or h <= 0: return
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(SCREEN_W, x + w)   # end-exclusive
    y1 = min(SCREEN_H, y + h)   # end-exclusive
    if x1 > x0 and y1 > y0:
        bitmaptools.fill_region(bmp, x0, y0, x1, y1, c)

def _hsv_to_rgb(h, s, v):
    # h in [0,1), s,v in [0,1]
    i = int(h*6.0) % 6
    f = h*6.0 - i
    p = v*(1.0 - s)
    q = v*(1.0 - f*s)
    t = v*(1.0 - (1.0 - f)*s)
    if i == 0: r,g,b = v,t,p
    elif i == 1: r,g,b = q,v,p
    elif i == 2: r,g,b = p,v,t
    elif i == 3: r,g,b = p,q,v
    elif i == 4: r,g,b = t,p,v
    else:        r,g,b = v,p,q
    return (int(r*255+0.5), int(g*255+0.5), int(b*255+0.5))

def _scale_rgb(col, k):
    r,g,b = col
    k = 1.0 if k>1.0 else (0.0 if k<0.0 else k)
    return (min(255, int(r*k)), min(255, int(g*k)), min(255, int(b*k)))

# -------- Demos --------
class PlasmaDemo:
    DT_BASE  = 0.12
    LUT_BITS = 8
    LUT_SIZE = 1 << LUT_BITS

    def __init__(self):
        self.speed = 3.0
        self.step  = 2

        # Random spatial frequencies (radians per pixel)
        self.ax, self.ay = random.uniform(0.04, 0.09), random.uniform(0.05, 0.10)
        self.bx, self.by = random.uniform(0.07, 0.12), random.uniform(0.03, 0.08)

        # Precompute fixed-point increments (phase index per pixel)
        scale = self.LUT_SIZE / TAU
        self.inc_x1 = int(self.ax * scale)           & (self.LUT_SIZE - 1)
        self.inc_y2 = int(self.ay * scale)           & (self.LUT_SIZE - 1)
        self.inc_x3 = int(self.bx * 0.7 * scale)     & (self.LUT_SIZE - 1)
        self.inc_y3 = int(self.by * 0.7 * scale)     & (self.LUT_SIZE - 1)
        self._scale_t = self.LUT_SIZE / TAU   # precomputed once per instance

        # Time phases (LUT indices)
        self.px1 = 0
        self.py2 = 0
        self.p3  = 0

        # Ink threshold
        self.thresh = 90

    def shuffle(self):
        # Pick new spatial frequencies, recompute increments
        self.ax, self.ay = random.uniform(0.04, 0.09), random.uniform(0.05, 0.10)
        self.bx, self.by = random.uniform(0.07, 0.12), random.uniform(0.03, 0.08)
        scale = self.LUT_SIZE / TAU
        self.inc_x1 = int(self.ax * scale)           & (self.LUT_SIZE - 1)
        self.inc_y2 = int(self.ay * scale)           & (self.LUT_SIZE - 1)
        self.inc_x3 = int(self.bx * 0.7 * scale)     & (self.LUT_SIZE - 1)
        self.inc_y3 = int(self.by * 0.7 * scale)     & (self.LUT_SIZE - 1)

    def tweak(self, d):
        # Wider top end; stays very smooth with bitmaptools
        self.speed = max(3.0, min(30.0, self.speed + d))
        # auto switch to 1×1 when fast
        self.step = 1 if self.speed >= 3.0 else 2

    def draw(self, bmp):
        # Clear with bitmaptools
        bitmaptools.fill_region(bmp, 0, 0, SCREEN_W, SCREEN_H, 0)

        step = self.step
        lut  = self.LUT
        mask = self.LUT_SIZE - 1

        # Phase increments per frame (convert from dt to LUT ticks)
        dt = self.DT_BASE * self.speed
        d1 = int(dt * self._scale_t)         & mask   # +t
        d2 = int(dt * 0.9 * self._scale_t)   & mask   # +0.9t
        d3 = int(dt * 1.3 * self._scale_t)   & mask   # +1.3t

        # Cache for inner loop (per step)
        inc_x1_s = (self.inc_x1 * step) & mask
        inc_x3_s = (self.inc_x3 * step) & mask

        for y in range(0, SCREEN_H, step):
            # Per-row starting phases
            ix1 = self.px1
            iy2 = (self.py2 + (y * self.inc_y2)) & mask
            i23 = (self.p3  + (y * self.inc_y3)) & mask

            for x in range(0, SCREEN_W, step):
                v = lut[ix1] + lut[iy2] + lut[i23]
                if v > self.thresh:
                    rect(bmp, x, y, step, step, 1)

                ix1 = (ix1 + inc_x1_s) & mask
                i23 = (i23 + inc_x3_s) & mask

        # advance time
        self.px1 = (self.px1 + d1) & mask
        self.py2 = (self.py2 + d2) & mask
        self.p3  = (self.p3  + d3) & mask

PlasmaDemo.LUT = [
    int(127 * math.sin(i * (TAU / PlasmaDemo.LUT_SIZE)))
    for i in range(PlasmaDemo.LUT_SIZE)
]

class SpectrumBarsDemo:
    """Dance-y spectrum bars with beat-driven envelopes and kick pump."""
    def __init__(self, n=16):
        self.n = n
        self.bars = [5] * n  # smoothed pixel heights (for your LED mapper too)

        # Animation pacing
        self.speed = 1.0
        self.t = 0.0

        # Beat model
        self.tempo_bpm = 128.0   # tweak with encoder via tweak()
        self.swing = 0.08        # 0..~0.2: delay the off-beat a hair (house-y feel)
        self._last_beat_i = -1
        self._last_hat_i2 = -1

        # Percussion envelopes (0..1) — exposed so LEDs can read kick_env for pump
        self.kick_env = 0.0
        self.snare_env = 0.0
        self.hat_env = 0.0

        # Per-band phases for motion
        self._ph = [random.random() * TAU for _ in range(n)]

        # Bar geometry
        self._w = SCREEN_W // self.n
        self._x0 = [i * self._w + 1 for i in range(self.n)]
        self._w_draw = max(1, self._w - 2)

    def shuffle(self):
        # Quick variation
        self._ph = [random.random() * TAU for _ in range(self.n)]

    def tweak(self, d):
        # Encoder nudges tempo like a DJ pitch bend
        self.tempo_bpm = max(80.0, min(160.0, self.tempo_bpm + d * 40.0))

    # --- beat & envelope helpers ---------------------------------------------
    def _advance_envelopes(self, dt):
        # Envelope decays (exp): slower kick decay = more “thump”
        self.kick_env  *= math.exp(-6.0  * dt)  # thumpy
        self.snare_env *= math.exp(-5.0  * dt)  # a bit slower than hats
        self.hat_env   *= math.exp(-12.0 * dt)  # fast ticks

        bps = self.tempo_bpm / 60.0
        beats = self.t * bps

        # Kick each beat
        beat_i = int(beats)
        if beat_i != self._last_beat_i:
            self._last_beat_i = beat_i
            self.kick_env = 1.0
            # Snare on the backbeat (2 & 4), slightly “late” with swing
            if (beat_i % 2) == 1:
                self.snare_env = 1.0 * math.exp(-2.5 * self.swing)

        # Closed hats on 8ths; add swing on the off-8ths
        i2 = int(beats * 2.0)
        if i2 != self._last_hat_i2:
            self._last_hat_i2 = i2
            is_off = (i2 % 2) == 1
            swing_pre = math.exp(-14.0 * self.swing) if is_off else 1.0
            self.hat_env = max(self.hat_env, 0.85 * swing_pre)

    # --- rendering ------------------------------------------------------------
    def draw(self, bmp):
        # Fixed-ish timestep to keep cost predictable (syncs with your 0.06 loop)
        dt = 0.06 * self.speed
        self.t += dt
        self._advance_envelopes(dt)

        # Clear frame
        bitmaptools.fill_region(bmp, 0, 0, SCREEN_W, SCREEN_H, 0)
        base = SCREEN_H - 3

        # Sidechain “pump” keyed by kick
        pump = 0.85 + 0.25 * (1.0 - min(1.0, self.kick_env))  # 0.85..1.10

        # Small helper
        def gauss(x, mu, sigma):
            d = (x - mu) / sigma
            return math.exp(-0.5 * d * d)

        for i in range(self.n):
            # 0..1 across bars (low→high)
            p = (i + 0.5) / self.n

            # Envelope weighting across spectrum
            kick_w  = gauss(p, 0.12, 0.28)
            snare_w = gauss(p, 0.55, 0.22)
            hat_w   = gauss(p, 0.88, 0.14)

            # Musical motion: two layered sines + a breath of noise
            ph = self._ph[i]
            base_move = (0.55
                         + 0.45 * math.sin(self.t * 1.25 + ph) * 0.7
                         + 0.45 * math.sin(self.t * 0.63 + i * 0.45) * 0.5)
            s = abs(base_move) + 0.10 * (random.random() - 0.5)

            # Add percussion hits
            s += 0.95 * kick_w  * self.kick_env
            s += 0.75 * snare_w * self.snare_env
            s += 0.60 * hat_w   * self.hat_env

            # Sidechain duck (global pump)
            s *= pump

            # Clamp → pixels
            s = 0.0 if s < 0.0 else (1.0 if s > 1.0 else s)
            h = int(s * (SCREEN_H - 14))

            # Smooth bars to reduce jitter
            self.bars[i] = int(0.78 * self.bars[i] + 0.22 * h)

            # Draw the bar
            rect(bmp, self._x0[i], base - self.bars[i], self._w_draw, self.bars[i], 1)

        # HUD grid lines
        for y in range(12, SCREEN_H, 8):
            bitmaptools.draw_line(bmp, 0, y, SCREEN_W - 1, y, 1)

class TunnelDemo:
    """Warp portal: solid concentric rings that fly inward, twist, and randomly bend."""
    def __init__(self):
        self.t = 0.0
        self.speed = 2.2
        self.travel = 1.8
        self._zphase = 0.0

        # Ring look / spacing
        self.base_gap = 4
        self.gap_breathe = 0.05
        self.twist_rate = 1.6
        self.twist_wave = 0.20
        self.twist_freq = 4.5

        # Stroke / sampling
        self.stroke_thickness = 2
        self.step_density = 14.0
        self.max_rings = 6

        # Bend / wander
        self.bend_pow = 1.2
        self.bend_speed = 2.4
        self._bend_amp_now = 0.0
        self._bend_dir_now = 0.0
        self._bend_amp_target = 0.0
        self._bend_dir_target = 0.0
        self._bend_next_change = 0.0

        # Center wobble
        self.center_wobble_amp = 3.5
        self.center_wobble_a = 0.7
        self.center_wobble_b = 1.1

    # --- Controls -------------------------------------------------------------

    def shuffle(self):
        """Randomize twist and pick new bend targets immediately."""
        self.twist_rate = random.uniform(0.45, 1.0)
        self.twist_wave = random.uniform(0.08, 0.18)
        self._pick_new_bend_targets(now=True)

    def tweak(self, d):
        """Encoder hook: adjust overall speed."""
        self.speed = max(0.4, min(2.5, self.speed + d))

    def tweak_bend(self, d):
        """Optional control for bend speed (bind to encoder or key if you like)."""
        self.bend_speed = max(0.2, min(3.0, self.bend_speed + d))

    # --- Bend logic -----------------------------------------------------------

    def _pick_new_bend_targets(self, now=False):
        if now:
            self._bend_next_change = self.t
        if self.t >= self._bend_next_change:
            self._bend_amp_target = random.uniform(2.0, 6.0)
            self._bend_dir_target = random.uniform(0.0, getattr(math, "tau", 2*math.pi))
            base_min, base_max = 3.0, 6.0
            scale = max(0.3, min(1.0, 1.0 / self.bend_speed))
            self._bend_next_change = self.t + random.uniform(base_min*scale, base_max*scale)

    def _ease_bend_toward_targets(self):
        k = 0.02 + 0.06 * max(0.0, min(1.0, (self.bend_speed - 0.2) / (3.0 - 0.2)))
        self._bend_amp_now += k * (self._bend_amp_target - self._bend_amp_now)
        TAU = getattr(math, "tau", 2*math.pi)
        d = (self._bend_dir_target - self._bend_dir_now + math.pi) % TAU - math.pi
        self._bend_dir_now += k * d

    # --- Drawing --------------------------------------------------------------

    def _draw_warped_ring(self, bmp, r, cx, cy, maxr):
        TAU = getattr(math, "tau", 2*math.pi)
        bend_dir = self._bend_dir_now
        bend_scale = self._bend_amp_now * ((r / maxr) ** self.bend_pow)

        # Bend: shift ring center
        ox = bend_scale * math.cos(bend_dir)
        oy = bend_scale * math.sin(bend_dir)

        twist_angle = self.t * self.twist_rate

        # Many segments for smoothness
        steps = max(36, int(r * self.step_density))

        # Draw multiple adjacent polylines to make the ring thicker/solid
        for s in range(self.stroke_thickness):
            r_off = r + (s - (self.stroke_thickness-1)/2) * 0.8
            lastx = lasty = None
            for i in range(steps + 1):
                ang = (i / steps) * TAU + twist_angle
                radial_gain = (r_off / maxr)
                r_warp = r_off * (1.0 + self.twist_wave * radial_gain *
                                  math.sin(self.twist_freq * ang + 0.6 * self.t))
                x = int(cx + ox + r_warp * math.cos(ang))
                y = int(cy + oy + r_warp * math.sin(ang))
                if lastx is not None:
                    bitmaptools.draw_line(bmp, lastx, lasty, x, y, 1)
                lastx, lasty = x, y

    def draw(self, bmp):
        clear(bmp)
        self._pick_new_bend_targets()
        self._ease_bend_toward_targets()

        cx = CX + int(self.center_wobble_amp * math.sin(self.t * self.center_wobble_a))
        cy = CY + int(self.center_wobble_amp * math.cos(self.t * self.center_wobble_b))

        maxr = min(SCREEN_W, SCREEN_H)//2 - 2
        if maxr <= 3:
            return

        gap = self.base_gap * (1.0 + self.gap_breathe * (0.5 + 0.5 * math.cos(self.t * 0.9)))
        self._zphase = (self._zphase + self.travel * 0.9 * self.speed) % gap

        # Build candidate radii from outside→in
        r_start = maxr - self._zphase
        radii = []
        r = r_start
        while r > 3:
            radii.append(r)
            r -= gap

        # Limit how many rings we actually draw
        if len(radii) > self.max_rings:
            radii = radii[:self.max_rings]

        for rr in radii:
            self._draw_warped_ring(bmp, rr, cx, cy, maxr)

        self.t += 0.06 * self.speed

class MatrixRainDemo:
    """Code rain overlay (bitmaptools-only), with full-frame clear (no stale pixels)."""
    def __init__(self):
        # Glyph grid / geometry
        self.col_w = 4                  # horizontal spacing per column (px)
        self.cell_h = 6                 # glyph cell height (px)
        self.cols = SCREEN_W // self.col_w
        self.rows = SCREEN_H // self.cell_h

        # Per-column state: starting row index (top=0; negative starts above screen)
        self.drops = [random.randint(-10, self.rows) for _ in range(self.cols)]

        # Animation controls
        self.speed = 1.0
        self.enabled = True

        # Column X positions (centered a bit)
        self._x = [i * self.col_w + 1 for i in range(self.cols)]

        # Per-column jitter phases
        self.streak_len = 3
        self.spawn_prob = 0.30
        self.col_jitter = 0.6
        self._ph = [random.random() * TAU for _ in range(self.cols)]

        # Render style
        self._streak_w = 2

    def shuffle(self):
        self.enabled = not self.enabled

    def tweak(self, d):
        self.speed = max(0.5, min(2.5, self.speed + d))

    def draw(self, bmp):
        if not self.enabled:
            return

        # Full wipe each frame so old pixels don’t linger as drops fall
        bitmaptools.fill_region(bmp, 0, 0, SCREEN_W, SCREEN_H, 0)

        base = SCREEN_H  # bottom boundary (exclusive)

        for i in range(self.cols):
            # Per-column motion jitter (slowly varying so it’s not flickery)
            self._ph[i] += 0.05
            jitter = 0.5 + self.col_jitter * (0.5 + 0.5 * math.sin(self._ph[i]))

            # Step this drop down a cell with some probability
            if random.random() < (self.spawn_prob * self.speed * jitter):
                self.drops[i] += 1

            # Wrap to a random position above the top once it passes the bottom
            if self.drops[i] * self.cell_h >= base:
                self.drops[i] = -random.randint(3, 10)

            # Draw head + short tail (fresh each frame after the full wipe)
            x = self._x[i]
            yhead = self.drops[i] * self.cell_h
            for k in range(self.streak_len):
                y = yhead - k * self.cell_h
                if 0 <= y < base:
                    rect(bmp, x, y, self._streak_w, self.cell_h - 1, 1)

# -------- Wrapper --------
class shader_bag:
    def __init__(self, macropad, *_, **__):
        self.supports_double_encoder_exit = True
        self.macropad = macropad

        # Detect 4-row layout if possible (e.g., 12 LEDs -> 3x4)
        try:
            npx = len(self.macropad.pixels)
            self._led_rows = 4 if (npx % 4) == 0 else 1
        except Exception:
            self._led_rows = 4

        # Rainbow/copper animation state (used by _update_copper)
        self._rainbow_phase = 0.0
        self._rainbow_speed = 0.6
        self._rainbow_drift = 0.0

        # Spectrum LED mapper
        self.spec_led_rise = 20.0
        self.spec_led_fall = 18.0
        self._spec_led_levels = None

        # Matrix LEDs (flicker-free persistence)
        self._mx_led_v = None
        self._mx_decay_per_s = 3.0

        # Matrix rain column physics
        self._mx_drops = None
        self._mx_spawn_rate = 0.9
        self._mx_speed_min = 2.0
        self._mx_speed_max = 4.0
        self._mx_trail_len = 3
        self._mx_head_v = 1.0
        self._mx_tail_v0 = 0.55
        self._mx_tail_fall = 0.55
        self._mx_head_desat = 0.35

        # Tunnel LEDs
        self._tunnel_phase = 0.0
        self._tunnel_speed = 1.0

        self.group = displayio.Group()
        self.bmp, self.pal = make_surface()
        self.tile = displayio.TileGrid(self.bmp, pixel_shader=self.pal)
        self.group.append(self.tile)

        clear(self.bmp)
        self.title = label.Label(terminalio.FONT, text="2000s Shader Bag", color=0xFFFFFF,
                                 anchor_point=(0.5,0), anchored_position=(CX,1))
        self.menu_lbl   = label.Label(terminalio.FONT, text="Select:", color=0xFFFFFF,
                                      anchor_point=(0,0), anchored_position=(2,18))
        self.choice_lbl = label.Label(terminalio.FONT, text="Plasma", color=0xFFFFFF,
                                      anchor_point=(0.5,0), anchored_position=(CX,30))
        self.hint_lbl   = label.Label(terminalio.FONT, text="", color=0xFFFFFF,
                                      anchor_point=(0.5,0), anchored_position=(CX,46))
        for w in (self.title, self.menu_lbl, self.choice_lbl, self.hint_lbl):
            self.group.append(w)

        self.hud = label.Label(terminalio.FONT, text="", color=0xFFFFFF,
                               anchor_point=(0.5,0), anchored_position=(CX,1))
        self._hud_last = None

        self._menu_items = ("Plasma","Spectrum","Tunnel","Matrix")
        self._menu_index = 0
        self.state = "menu"
        self._menu_press_t = None
        self._last = time.monotonic()

        # Kick mirror for LED pumping (owned by wrapper)
        self.kick_env = 0.0

        self.demo = None
        self.matrix = MatrixRainDemo()

        self.COL_MOVE=(0,25,0); self.COL_FIRE=(40,0,0)
        self._led_all_off()

    # LED helpers
    def _led_set(self, idx, col):
        try:
            self.macropad.pixels[idx] = col; self.macropad.pixels.show()
        except Exception: pass

    def _led_all_off(self):
        try:
            for i in range(len(self.macropad.pixels)): self.macropad.pixels[i]=(0,0,0)
            self.macropad.pixels.show()
        except Exception: pass

    def _update_matrix_leds(self, dt):
        """Matrix-style falling green 'digital rain' on the 3×4 MacroPad (flicker-free)."""
        try:
            if self.state != "matrix":
                return

            px = getattr(self.macropad, "pixels", None)
            if not px:
                return

            # Clamp huge dt spikes so physics doesn't jump
            if dt > 0.08:
                dt = 0.08

            n = len(px)
            rows = self._led_rows if getattr(self, "_led_rows", 0) else 1
            cols = n // rows if rows > 0 else n

            # Fallback: simple breathing green if not 3×4
            if rows != 4 or cols != 3 or rows * cols != n:
                t = (time.monotonic() * 0.35) % 1.0
                breath = 0.25 + 0.75 * (0.5 + 0.5 * math.cos(TAU * t))
                col = _hsv_to_rgb(1.0/3.0, 1.0, breath)
                for i in range(n):
                    px[i] = col
                px.show()
                return

            # Lazily allocate per-column drops and the per-LED persistence buffer
            if self._mx_drops is None or len(self._mx_drops) != cols:
                self._mx_drops = [None] * cols
            if self._mx_led_v is None or len(self._mx_led_v) != n:
                self._mx_led_v = [0.0] * n

            # Smoothly decay previous frame's brightness (no hard clear)
            decay = math.exp(-self._mx_decay_per_s * dt)
            for i in range(n):
                self._mx_led_v[i] *= decay

            # Spawn/move/paint each column into the persistence buffer
            for c in range(cols):
                d = self._mx_drops[c]

                # Poisson-ish spawn
                if d is None and random.random() < (self._mx_spawn_rate * dt):
                    speed = random.uniform(self._mx_speed_min, self._mx_speed_max)
                    start_y = -random.uniform(0.0, float(self._mx_trail_len))  # start above view
                    self._mx_drops[c] = d = {"y": start_y, "v": speed, "trail": self._mx_trail_len}

                if d is None:
                    continue

                # Move
                d["y"] += d["v"] * dt

                # Cull after trail fully exited
                if d["y"] - d["trail"] > (rows - 1):
                    self._mx_drops[c] = None
                    continue

                # Sub-pixel head: split brightness between two rows to avoid row-flip flicker
                y = d["y"]
                r0 = int(math.floor(y))
                frac = y - r0
                r1 = r0 + 1

                # Head is slightly desaturated (whitish)
                head_v = self._mx_head_v
                if 0 <= r0 < rows:
                    i0 = r0 * cols + c
                    self._mx_led_v[i0] = max(self._mx_led_v[i0], head_v * (1.0 - frac))
                if 0 <= r1 < rows:
                    i1 = r1 * cols + c
                    self._mx_led_v[i1] = max(self._mx_led_v[i1], head_v * frac)

                # Trail samples behind the head; exponential falloff
                tail_v = self._mx_tail_v0
                max_k = d["trail"]
                for k in range(1, max_k + 1):
                    yt = y - k
                    r0t = int(math.floor(yt))
                    fract = yt - r0t
                    soften = 0.5 + 0.5 * math.cos(min(1.0, k / float(max_k)) * math.pi)
                    v = max(0.0, min(1.0, tail_v * soften))

                    if 0 <= r0t < rows:
                        i0t = r0t * cols + c
                        self._mx_led_v[i0t] = max(self._mx_led_v[i0t], v * (1.0 - fract))
                    r1t = r0t + 1
                    if 0 <= r1t < rows:
                        i1t = r1t * cols + c
                        self._mx_led_v[i1t] = max(self._mx_led_v[i1t], v * fract)

                    tail_v *= self._mx_tail_fall

            # Write LEDs once (green hue; desaturate slightly when very bright)
            for i in range(n):
                v = 0.0 if self._mx_led_v[i] < 0.002 else (1.0 if self._mx_led_v[i] > 1.0 else self._mx_led_v[i])
                s = 1.0 - self._mx_head_desat * (v ** 1.5)
                px[i] = _hsv_to_rgb(1.0/3.0, s, v)

            px.show()

        except Exception:
            pass

    def _update_spectrum_leds(self, dt=None):
        try:
            if self.state != "spectrum" or not isinstance(self.demo, SpectrumBarsDemo):
                return
            px = getattr(self.macropad, "pixels", None)
            if not px: return
            n = len(px);  rows = self._led_rows if getattr(self, "_led_rows", 0) else 1
            cols = n // rows if rows > 0 else n
            if rows != 4 or cols != 3:
                return

            # target levels from bars
            bars = getattr(self.demo, "bars", None)
            if not bars: return
            nb = len(bars)
            maxh = (SCREEN_H - 14) if (SCREEN_H > 14) else SCREEN_H

            def bar_level_for_col(c):
                idx = int((c + 0.5) * nb / cols)
                idx = 0 if idx < 0 else (nb-1 if idx >= nb else idx)
                lvl = int(round((bars[idx] / maxh) * rows))
                return 0 if lvl < 0 else (rows if lvl > rows else lvl)

            targets = [bar_level_for_col(c) for c in range(cols)]

            # allocate current levels once
            if self._spec_led_levels is None or len(self._spec_led_levels) != cols:
                self._spec_led_levels = [0]*cols

            # move current levels toward targets with rise/fall rates
            up_step   = max(1, int(self.spec_led_rise * (dt or 0.016)))
            down_step = max(1, int(self.spec_led_fall * (dt or 0.016)))
            for c in range(cols):
                cur = self._spec_led_levels[c]
                tgt = targets[c]
                if tgt > cur:
                    cur = min(tgt, cur + up_step)
                elif tgt < cur:
                    cur = max(tgt, cur - down_step)
                self._spec_led_levels[c] = cur

            # paint LEDs bottom→top with green→yellow→orange→red
            for c in range(cols):
                lvl = self._spec_led_levels[c]
                for r_bottom in range(rows):
                    r_top = (rows - 1) - r_bottom
                    i = r_top * cols + c
                    if r_bottom < lvl:
                        t = r_bottom / (rows - 1) if rows > 1 else 1.0  # 0 bottom .. 1 top
                        # hue: 120° (green) -> 0° (red)
                        h = (1.0/3.0) * (1.0 - t)
                        # brightness with kick pump mirrored from SpectrumBarsDemo
                        pump = 0.90 + 0.20 * self.kick_env  # 0.90..1.10
                        v = (0.35 + 0.65 * (0.6*t + 0.4*(lvl/rows))) * pump
                        v = 1.0 if v > 1.0 else v
                        px[i] = _hsv_to_rgb(h, 1.0, v)
                    else:
                        px[i] = (0,0,0)
            px.show()
        except Exception:
            pass

    def _update_tunnel_leds(self, dt):
        """Tunnel LEDs: depth bands (bottom=far/dark, top=near/bright) with smooth cosine breathing."""
        try:
            if self.state != "tunnel":
                return
            px = getattr(self.macropad, "pixels", None)
            if not px:
                return
            n = len(px)
            if n <= 0:
                return

            # Advance a phase; tie to demo speed if present so the LEDs sync with visuals
            speed = getattr(self.demo, "speed", 1.0) if self.demo else 1.0
            self._tunnel_phase = (self._tunnel_phase + dt * self._tunnel_speed * speed) % 1.0

            rows = self._led_rows if getattr(self, "_led_rows", 0) else 1
            cols = n // rows if rows > 0 else n

            def c01(x):
                return 0.5 + 0.5 * math.cos(TAU * x)

            if rows != 4 or cols != 3:
                breath = 0.25 + 0.75 * c01(self._tunnel_phase)
                col = _hsv_to_rgb(0.50, 0.5, breath)
                for i in range(n):
                    px[i] = col
                px.show()
                return

            for r_top in range(rows):
                r_bottom = (rows - 1) - r_top
                depth = r_bottom / (rows - 1) if rows > 1 else 0.0
                base = 0.15 + 0.75 * depth
                breath = c01(self._tunnel_phase + 0.22 * depth)
                v_row = max(0.0, min(1.0, 0.20 + 0.80 * base * breath))
                h = 0.50
                s = 0.65 * (1.0 - 0.6 * depth)
                for c in range(cols):
                    v = v_row * (0.85 + 0.15 * c01(self._tunnel_phase * 1.4 + 0.20 * c + 0.10 * r_top))
                    i = r_top * cols + c
                    px[i] = _hsv_to_rgb(h, s, v)

            for idx in (K_LEFT, K_RIGHT, K_FIRE):
                if 0 <= idx < n:
                    px[idx] = _scale_rgb(px[idx], 1.15)

            px.show()
        except Exception:
            pass

    def _update_copper(self, dt):
        """Plasma LEDs: psychedelic rainbow with smooth cosine shading + gentle diagonal drift."""
        try:
            px = getattr(self.macropad, "pixels", None)
            if not px:
                return
            n = len(px)
            if n <= 0:
                return

            self._rainbow_phase = (self._rainbow_phase + self._rainbow_speed * dt) % 1.0
            self._rainbow_drift = (self._rainbow_drift + 0.45 * dt) % 1000.0

            rows = self._led_rows if getattr(self, "_led_rows", 0) else 1
            cols = n // rows if rows > 0 else n

            def c01(x):
                return 0.5 + 0.5 * math.cos(TAU * x)

            if rows * cols != n or rows <= 0 or cols <= 0:
                for i in range(n):
                    h = (self._rainbow_phase + i / max(1, n)) % 1.0
                    v = 0.35 + 0.65 * c01(self._rainbow_phase * 1.2 + self._rainbow_drift * 0.2 + i * 0.12)
                    px[i] = _hsv_to_rgb(h, 1.0, v)
            else:
                gp = self._rainbow_phase
                drift = self._rainbow_drift
                for r in range(rows):
                    for c in range(cols):
                        i = r * cols + c
                        h = (gp + 0.10 * r + 0.08 * c + 0.04 * math.sin(TAU * (gp + 0.2 * c))) % 1.0
                        v = 0.30 + 0.70 * c01(gp * 1.2 + 0.25 * c + 0.15 * r + 0.20 * drift)
                        px[i] = _hsv_to_rgb(h, 1.0, v)

            for idx in (K_LEFT, K_RIGHT, K_FIRE):
                if 0 <= idx < n:
                    px[idx] = _scale_rgb(px[idx], 1.20)

            px.show()
        except Exception:
            pass

    def _set_menu_lights(self): self._led_all_off()
    def _set_demo_lights(self):
        self._led_all_off()
        self._led_set(K_LEFT, self.COL_MOVE); self._led_set(K_RIGHT, self.COL_MOVE)
        self._led_set(K_FIRE, self.COL_FIRE)

    def _set_hud(self, s):
        if s != self._hud_last:
            self.hud.text = s; self._hud_last = s

    def new_game(self):
        clear(self.bmp)
        hline(self.bmp,0,SCREEN_W-1,10,1)
        self.choice_lbl.text = self._menu_items[self._menu_index]
        self._set_menu_lights()
        self._menu_press_t = None
        try: self.macropad.display.auto_refresh = True
        except Exception: pass

    def encoderChange(self, pos, last_pos):
        if self.state != "menu" or pos == last_pos: return
        self._menu_index = pos % len(self._menu_items)
        self.choice_lbl.text = self._menu_items[self._menu_index]

    def encoder_button(self, pressed):
        if not pressed: return
        now = time.monotonic()
        if self.state == "menu":
            if self._menu_press_t is None:
                self._menu_press_t = now
            else:
                if (now - self._menu_press_t) <= DOUBLE_PRESS_WINDOW:
                    self._menu_press_t = None
                else:
                    self._menu_press_t = now
        else:
            self._to_menu()

    def _to_menu(self):
        try: self.macropad.display.auto_refresh = False
        except Exception: pass
        clear(self.bmp)
        for w in (self.title, self.menu_lbl, self.choice_lbl, self.hint_lbl):
            if w not in self.group: self.group.append(w)
        try:
            if self.hud in self.group: self.group.remove(self.hud)
        except Exception: pass
        hline(self.bmp,0,SCREEN_W-1,10,1)
        self.choice_lbl.text = self._menu_items[self._menu_index]
        self.state="menu"; self.demo=None
        self._set_menu_lights(); self._menu_press_t=None
        try:
            self.macropad.display.refresh(minimum_frames_per_second=0)
            self.macropad.display.auto_refresh = True
        except Exception: pass

    def _enter(self, name):
        for w in (self.menu_lbl, self.choice_lbl, self.hint_lbl, self.title):
            try: self.group.remove(w)
            except Exception: pass
        if self.hud not in self.group: self.group.append(self.hud)
        try: self.macropad.display.auto_refresh = False
        except Exception: pass
        clear(self.bmp)
        if name=="Plasma":     self.state="plasma";   self.demo=PlasmaDemo()
        elif name=="Spectrum": self.state="spectrum"; self.demo=SpectrumBarsDemo()
        elif name=="Tunnel":   self.state="tunnel";   self.demo=TunnelDemo()
        else:                  self.state="matrix";   self.demo=None  # matrix-only mode
        self._set_demo_lights()
        try: self.macropad.display.refresh(minimum_frames_per_second=0)
        except Exception: pass

    def tick(self):
        now = time.monotonic()
        if now - self._last < 0.016: return
        dt = now - self._last
        self._last = now

        # keep a decaying fallback so it's valid even when not in spectrum
        self.kick_env *= math.exp(-6.0 * dt)

        # if we're running SpectrumBarsDemo, mirror its live envelope
        if isinstance(self.demo, SpectrumBarsDemo):
            self.kick_env = float(getattr(self.demo, "kick_env", 0.0))

        if dt > 0.08:
            dt = 0.08

        if self.state == "menu" and self._menu_press_t is not None:
            if (now - self._menu_press_t) > DOUBLE_PRESS_WINDOW:
                self._menu_press_t = None
                sel = self._menu_items[self._menu_index]
                self._enter(sel); return

        if self.state == "menu": return

        if self.demo: self.demo.draw(self.bmp)

        # after drawing the bitmap demo...
        if self.state == "plasma":
            self._update_copper(dt)
        elif self.state == "spectrum":
            self._update_spectrum_leds(dt)
        elif self.state == "tunnel":
            self._update_tunnel_leds(dt)
        elif self.state == "matrix":
            self.matrix.draw(self.bmp)
            self._update_matrix_leds(dt)

        try:
            self.macropad.display.refresh(minimum_frames_per_second=0)
        except Exception:
            pass

    def button(self, key):
        if self.state == "menu": return
        if key==K_LEFT:
            target = self.demo if self.demo else self.matrix
            getattr(target, "tweak", lambda d:None)(-0.06)
        elif key==K_RIGHT:
            target = self.demo if self.demo else self.matrix
            getattr(target, "tweak", lambda d:None)(+0.06)
        elif key == K_FIRE:
            if self.demo:
                getattr(self.demo, "shuffle", lambda: None)()
            if self.state == "matrix":
                self.matrix.shuffle()

    def button_up(self, key): pass

    def on_exit_hint(self):
        if self.state != "menu":
            s = self._hud_last or self.hud.text or ""
            if "Press again to exit" not in s:
                self._set_hud((s + "  Press again to exit").strip())
                try: self.macropad.display.refresh(minimum_frames_per_second=0)
                except Exception: pass

    def on_exit_hint_clear(self):
        if self.state != "menu":
            s = self._hud_last or self.hud.text or ""
            self._set_hud(s.replace("  Press again to exit",""))
            try: self.macropad.display.refresh(minimum_frames_per_second=0)
            except Exception: pass

    def cleanup(self):
        self.state="menu"; self.demo=None; self._menu_press_t=None
        try:
            if hasattr(self.macropad, "stop_tone"): self.macropad.stop_tone()
        except Exception: pass
        try: self._led_all_off()
        except Exception: pass
        try:
            disp = getattr(self.macropad, "display", None)
            if disp:
                try: disp.auto_refresh = False
                except Exception: pass
                clear(self.bmp)
                for w in (self.title, self.menu_lbl, self.choice_lbl, self.hint_lbl):
                    if w not in self.group: self.group.append(w)
                try:
                    if self.hud in self.group: self.group.remove(self.hud)
                except Exception: pass
                hline(self.bmp,0,SCREEN_W-1,10,1)
                self.choice_lbl.text = self._menu_items[self._menu_index]
                try: disp.refresh(minimum_frames_per_second=0)
                except Exception: pass
                try: disp.auto_refresh = True
                except Exception: pass
        except Exception: pass