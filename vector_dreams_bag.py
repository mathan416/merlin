# ---------------------------------------------------------------------------
# vector_dreams_bag.py — 1970s "Vector Dreams" Demo Scene
# CircuitPython 9.x — Merlin Launcher Compatible (Adafruit MacroPad RP2040)
# Written by Iain Bennett — 2025
#
# OVERVIEW
# ────────────────────────────────────────────────
# A retro demo-scene homage in the style of late-1970s vector displays
# and oscilloscopes. Runs on the MacroPad’s 128×64 OLED in stark 1-bit
# white-on-black, evoking Tektronix scopes and Vectrex-like effects.
#
# MODES
# ────────────────────────────────────────────────
# • Scope:
#     ░ Scrolling oscilloscope traces of sine, triangle, and sawtooth waves.
#     ░ Occasionally drifts into animated Lissajous figures.
# • Pong:
#     ░ AI vs AI vector Pong with trailing ball path and faint midline court.
#     ░ Ball speed, angle, and trail randomized on shuffle.
# • Disco:
#     ░ Pulsing circle with clipped checkerboard grid and sparkles.
#     ░ Palette can invert for strobe-like bursts.
#
# CONTROLS
# ────────────────────────────────────────────────
# • Encoder: cycle through menu items (Scope / Pong / Disco).
# • Encoder press (single): enter selected demo.
# • Encoder press (again): return to menu.
# • Keys:
#     – K3 / K5: Adjust demo speed (left/right).
#     – K7: Shuffle demo parameters (e.g., waveform type, Pong angle, disco FX).
#
# FEATURES
# ────────────────────────────────────────────────
# • Double-press timing window for robust menu selection.
# • Defensive drawing functions: hline, rect, fill_region fallback.
# • LEDs:
#     – Menu: all LEDs cleared.
#     – In-demo: movement keys (K3/K5) glow green; shuffle key (K7) glows red.
# • Launcher compatibility: exposes .group, .new_game(), .tick(),
#   .button(), .button_up(), .cleanup().
#
# NOTES
# ────────────────────────────────────────────────
# • Written to capture the 70s “vector dreams” aesthetic — oscilloscopes,
#   minimalism, and glowing lines on black.
# • Efficient 1-bit drawing; heavy use of bitmaptools, but safe fallbacks
#   allow graceful degradation on limited builds.
# ---------------------------------------------------------------------------
import time, math, random
import displayio, terminalio
import bitmaptools
from adafruit_display_text import label

SCREEN_W, SCREEN_H = 128, 64
CX, CY = SCREEN_W//2, SCREEN_H//2
K_LEFT, K_RIGHT, K_FIRE = 3, 5, 7
DOUBLE_PRESS_WINDOW = 0.35
# Some CircuitPython builds don't define math.tau
TAU = getattr(math, "tau", 2.0 * math.pi)

def make_surface():
    bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
    pal = displayio.Palette(2); pal[0]=0x000000; pal[1]=0xFFFFFF
    return bmp, pal

def clear(bmp):
    try: bmp.fill(0)
    except AttributeError:
        for y in range(SCREEN_H):
            for x in range(SCREEN_W): bmp[x,y]=0

def plot(bmp, x, y, c=1):
    if 0<=x<SCREEN_W and 0<=y<SCREEN_H: bmp[x,y]=c

def line(bmp, x0,y0,x1,y1,c=1):
    dx=abs(x1-x0); dy=-abs(y1-y0); sx=1 if x0<x1 else -1; sy=1 if y0<y1 else -1; err=dx+dy
    while True:
        plot(bmp,x0,y0,c)
        if x0==x1 and y0==y1: break
        e2=2*err
        if e2>=dy: err+=dy; x0+=sx
        if e2<=dx: err+=dx; y0+=sy

def hline(bmp,x0,x1,y,c=1):
    if y<0 or y>=SCREEN_H: return
    if x0>x1: x0,x1=x1,x0
    x0=max(0,x0); x1=min(SCREEN_W-1,x1)
    for x in range(x0,x1+1): bmp[x,y]=c

def rect(bmp, x,y,w,h,c=1):
    x2,y2=x+w,y+h
    for yy in range(y,y2):
        if 0<=yy<SCREEN_H:
            for xx in range(x,x2):
                if 0<=xx<SCREEN_W: bmp[xx,yy]=c

# -------- Demos --------
class OscilloscopeDemo:
    def __init__(self):
        self.mode = 0  # 0 sine, 1 triangle, 2 saw, 3 lissajous
        self.speed = 1.0
        self.t = 0.0
        self.a, self.b = 3, 2   # Lissajous
        self.phase = 0.0

    def shuffle(self):
        if self.mode < 3:
            self.mode = (self.mode + 1) % 3
        else:
            # rotate Lissajous pair
            choices = [(3,2),(5,4),(5,3),(7,5)]
            self.a, self.b = random.choice(choices)
        if random.random() < 0.25:
            self.mode = 3  # occasionally hop into lissajous

    def tweak(self, d):
        self.speed = max(1, min(5.0, self.speed + d))

    def _wavey(self, x):
        if self.mode == 0:
            return math.sin(x)
        if self.mode == 1:
            # triangle
            p = (x / TAU) % 1.0
            return 4*abs(p-0.5)-1.0
        if self.mode == 2:
            # saw
            p = (x / TAU) % 1.0
            return 2.0*p-1.0
        return math.sin(x)  # default

    def draw(self, bmp):
        clear(bmp)
        if self.mode < 3:
            # scroll a scope trace across width
            amp = (SCREEN_H//2)-6
            mid = CY
            # draw baseline grid
            for gy in range(8, SCREEN_H, 8): hline(bmp, 0, SCREEN_W-1, gy, 1)
            last_y = mid + int(self._wavey(self.t)*amp)
            for x in range(SCREEN_W):
                y = mid + int(self._wavey(self.t + x*0.08)*amp)
                line(bmp, x-1, last_y, x, y, 1)
                last_y = y
            self.t += 0.06 * self.speed
        else:
            # lissajous
            ampX, ampY = (SCREEN_W//2)-6, int((SCREEN_H//2)-6)
            steps = 220
            last = None
            ph = self.phase
            for i in range(steps):
                t = ph + i*0.02
                x = int(CX + ampX * math.sin(self.a * t))
                y = int(CY + ampY * math.sin(self.b * t))
                if last: line(bmp, last[0], last[1], x, y, 1)
                last = (x, y)
            self.phase += 0.03 * self.speed

class PongDemo:
    def __init__(self):
        self.w, self.h = SCREEN_W, SCREEN_H
        self.bx, self.by = CX, CY
        self.vx, self.vy = 1.3, 0.9
        self.pxL, self.pxR = 3, self.w-4
        self.pyL, self.pyR = CY-6, CY-6
        self.paddle_h = 13
        self.speed = 1.0
        self._trail = []

    def shuffle(self):
        # randomize ball direction/speed
        ang = random.uniform(0.35, 2.8)
        spd = random.uniform(1.0, 1.8)
        self.vx, self.vy = math.cos(ang)*spd, math.sin(ang)*spd
        self._trail.clear()

    def tweak(self, d):
        self.speed = max(1, min(5.0, self.speed + d))

    def draw(self, bmp):
        # faint court lines
        clear(bmp)
        for y in range(0, SCREEN_H, 4): plot(bmp, CX, y, 1)
        # AI tracks ball
        targetL = self.by - self.paddle_h//2
        targetR = self.by - self.paddle_h//2
        self.pyL += max(-1.2, min(1.2, (targetL - self.pyL) * 0.2 * self.speed))
        self.pyR += max(-1.2, min(1.2, (targetR - self.pyR) * 0.2 * self.speed))
        # paddles
        rect(bmp, self.pxL, int(self.pyL), 2, self.paddle_h, 1)
        rect(bmp, self.pxR-1, int(self.pyR), 2, self.paddle_h, 1)
        # move ball
        self.bx += self.vx * self.speed
        self.by += self.vy * self.speed
        # wall bounce
        if self.by < 2 or self.by >= self.h-2: self.vy = -self.vy
        # paddle bounce
        if int(self.bx) <= self.pxL+2 and self.pyL-1 <= self.by <= self.pyL+self.paddle_h+1: self.vx = abs(self.vx)
        if int(self.bx) >= self.pxR-2 and self.pyR-1 <= self.by <= self.pyR+self.paddle_h+1: self.vx = -abs(self.vx)
        # reset if out
        if self.bx < -6 or self.bx > self.w+6:
            self.bx, self.by = CX, CY
        # trail
        self._trail.append((int(self.bx), int(self.by)))
        if len(self._trail) > 20: self._trail.pop(0)
        # draw trail
        last = None
        for (x,y) in self._trail:
            if last: line(bmp, last[0], last[1], x, y, 1)
            last = (x,y)
        # ball
        rect(bmp, int(self.bx)-1, int(self.by)-1, 3, 3, 1)

class DiscoGridDemo:
    def __init__(self, palette=None):
        self.t = 0.0
        self.speed = 1.0
        self.base_r = min(SCREEN_W, SCREEN_H)//2 - 6   # average radius
        self.breath = 6                                 # pulse amplitude (px)
        self.grid   = 6                                 # grid spacing (px)
        self.phase  = 0                                 # checkerboard phase

        # new: palette + FX state
        self.pal = palette
        self._invert_until = 0.0
        self._sparkle_frames = 0

    def shuffle(self):
        # More dramatic changes
        self.breath = random.randint(5, 10)                    # bigger pulse
        self.grid   = random.choice((4, 5, 6, 7))              # wider range
        self.phase ^= 1                                        # flip checkerboard phase

        # small radius jitter (stay inside screen)
        max_r = min(SCREEN_W, SCREEN_H)//2 - 4
        self.base_r = max(10, min(max_r, self.base_r + random.randint(-2, 2)))

        # palette invert burst
        if self.pal is not None:
            # swap colors now; set timer to swap back
            self.pal[0], self.pal[1] = self.pal[1], self.pal[0]
            self._invert_until = time.monotonic() + 0.35

        # sparkle burst for ~18 frames
        self._sparkle_frames = 18

    def tweak(self, d):
        # same clamp as before (adjust if you want it spicier)
        self.speed = max(0.3, min(2.0, self.speed + d))

    def _clear(self, bmp):
        bitmaptools.fill_region(bmp, 0, 0, SCREEN_W, SCREEN_H, 0)

    def draw(self, bmp):
        # end invert burst?
        now = time.monotonic()
        if self.pal is not None and self._invert_until and now > self._invert_until:
            self.pal[0], self.pal[1] = self.pal[1], self.pal[0]  # swap back
            self._invert_until = 0.0

        self._clear(bmp)

        # --- breathing radius ---
        r_f = self.base_r + self.breath * math.sin(self.t * 1.25)
        r   = max(8, int(r_f))

        # --- circle outline ---
        steps = max(36, int(r * 6))
        lastx = lasty = None
        for i in range(steps + 1):
            ang = (i / steps) * TAU
            x = CX + int(r * math.cos(ang))
            y = CY + int(r * math.sin(ang))
            if lastx is not None:
                bitmaptools.draw_line(bmp, lastx, lasty, x, y, 1)
            lastx, lasty = x, y

        # --- grid clipped to circle ---
        for xi in range(-r, r + 1, self.grid):
            yext = int((r*r - xi*xi) ** 0.5)
            x = CX + xi
            bitmaptools.draw_line(bmp, x, CY - yext, x, CY + yext, 1)
        for yi in range(-r, r + 1, self.grid):
            xext = int((r*r - yi*yi) ** 0.5)
            y = CY + yi
            bitmaptools.draw_line(bmp, CX - xext, y, CX + xext, y, 1)

        # --- checkerboard tiles clipped per scanline ---
        phase = (int(self.t * 3) + self.phase) & 1
        g = self.grid
        for rj in range(-(r // g) - 1, (r // g) + 2):
            y0 = CY + rj * g
            y1 = y0 + g
            y_start = max(y0, CY - r, 0)
            y_stop  = min(y1, CY + r, SCREEN_H)
            for ci in range(-(r // g) - 1, (r // g) + 2):
                if ((ci + rj + phase) & 1) != 0:
                    continue
                x0 = CX + ci * g
                x1 = x0 + g
                for y in range(y_start, y_stop):
                    dy = y - CY
                    xext = int((r*r - dy*dy) ** 0.5)
                    left  = max(x0, CX - xext, 0)
                    right = min(x1 - 1, CX + xext, SCREEN_W - 1)
                    if left <= right:
                        bitmaptools.draw_line(bmp, left, y, right, y, 1)

        # --- sparkle burst overlay (inside circle) ---
        if self._sparkle_frames > 0:
            n = 40  # sprinkle density per frame
            for _ in range(n):
                ang = random.random() * TAU
                rr  = random.uniform(0, r - 1)
                x = CX + int(rr * math.cos(ang))
                y = CY + int(rr * math.sin(ang))
                if 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
                    bmp[x, y] = 1
            self._sparkle_frames -= 1

        self.t += 0.06 * self.speed

# -------- Wrapper --------
class vector_dreams_bag:
    def __init__(self, macropad, *_, **__):
        self.supports_double_encoder_exit = True
        self.macropad = macropad
        self.group = displayio.Group()
        self.bmp, self.pal = make_surface()
        self.tile = displayio.TileGrid(self.bmp, pixel_shader=self.pal)
        self.group.append(self.tile)

        clear(self.bmp)
        self.title = label.Label(terminalio.FONT, text="70s Vector Dreams", color=0xFFFFFF,
                                 anchor_point=(0.5,0), anchored_position=(CX,1))
        self.menu_lbl   = label.Label(terminalio.FONT, text="Select:", color=0xFFFFFF,
                                      anchor_point=(0,0), anchored_position=(2,18))
        self.choice_lbl = label.Label(terminalio.FONT, text="Scope", color=0xFFFFFF,
                                      anchor_point=(0.5,0), anchored_position=(CX,30))
        self.hint_lbl   = label.Label(terminalio.FONT, text="", color=0xFFFFFF,
                                      anchor_point=(0.5,0), anchored_position=(CX,46))
        for w in (self.title, self.menu_lbl, self.choice_lbl, self.hint_lbl): self.group.append(w)

        self.hud = label.Label(terminalio.FONT, text="", color=0xFFFFFF,
                               anchor_point=(0.5,0), anchored_position=(CX,1))
        self._hud_last = None

        self._menu_items = ("Scope","Pong","Disco")
        self._menu_index = 0
        self.state = "menu"
        self.demo = None
        self._last = 0.0
        self._menu_press_t = None

        self.COL_OFF  = (0,0,0); self.COL_MOVE=(0,25,0); self.COL_FIRE=(40,0,0)
        self._led_all_off()

    # ---- LEDs ----
    def _led_set(self, idx, col):
        try:
            self.macropad.pixels[idx] = col
            self.macropad.pixels.show()
        except Exception: pass
    def _led_all_off(self):
        try:
            for i in range(len(self.macropad.pixels)): self.macropad.pixels[i]=(0,0,0)
            self.macropad.pixels.show()
        except Exception: pass
    def _set_menu_lights(self): self._led_all_off()
    def _set_demo_lights(self, name):
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
        if name=="Scope": self.state="scope"; self.demo=OscilloscopeDemo()
        elif name=="Pong": self.state="pong"; self.demo=PongDemo()
        else: self.state="disco"; self.demo=DiscoGridDemo(self.pal)
        self._set_demo_lights(name)
        try: self.macropad.display.refresh(minimum_frames_per_second=0)
        except Exception: pass

    def tick(self):
        now=time.monotonic()
        if now - self._last < 0.016: return
        self._last = now
        if self.state == "menu" and self._menu_press_t is not None:
            if (now - self._menu_press_t) > DOUBLE_PRESS_WINDOW:
                self._menu_press_t = None
                sel = self._menu_items[self._menu_index]
                self._enter(sel); return
        if self.state == "menu" or self.demo is None: return
        self.demo.draw(self.bmp)
        try: self.macropad.display.refresh(minimum_frames_per_second=0)
        except Exception: pass

    def button(self, key):
        if self.state == "menu" or self.demo is None: return

        if key in (K_LEFT, K_RIGHT):
            base = -1 if key == K_LEFT else +1
            # Bigger step for Scope & Disco; keep a gentler step for Pong
            if isinstance(self.demo, (OscilloscopeDemo, DiscoGridDemo)):
                step = 0.25
            else:  # Pong
                step = 0.08
            getattr(self.demo, "tweak", lambda d: None)(base * step)
        
        elif key==K_FIRE: getattr(self.demo, "shuffle", lambda :None)()

    def button_up(self, key): pass

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