# sinclair_demo_bag.py — Sinclair Demo Bag for Merlin Launcher (MacroPad / CircuitPython 9.x)
# Written by Iain Bennett — 2025
#
# Inspired by simple but mesmerizing programs you could type into
# the Timex Sinclair 1000 / Sinclair ZX81 — my first computer. Back then,
# everything was monochrome: green screens, orange phosphor, or stark
# black-and-white. The MacroPad’s 128×64 OLED has far higher resolution,
# but these demos try to capture that feeling of past simple graphics magic
# and nostalgia.
#
# Encoder:
#   - In menu: rotate to select; single press starts after a short window;
#              double-press within the window is reserved for the launcher.
#   - In demo: single press returns to menu.
#
# Keys in demos:
#   - Starfield / Maze:  K3/K5 tweak speed, K7 shuffle
#   - Kaleido:           K7 shuffle
#
# LEDs:
#   - K3/K5 green, K7 red during demos; all off in menu.
#
# Demos included:
#   - Starfield: pseudo-3D stars rushing toward you
#   - Kaleidoscope text: rotating patterns of “TS1000”
#   - Endless scrolling maze walls

import time, math, random
import displayio, terminalio
from adafruit_display_text import label

SCREEN_W, SCREEN_H = 128, 64
CX, CY = SCREEN_W//2, SCREEN_H//2

K_LEFT, K_RIGHT, K_FIRE = 3, 5, 7

# UX / timing
DOUBLE_PRESS_WINDOW = 0.35  # seconds to defer starting in menu (lets launcher detect double-press)

def make_surface():
    bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
    pal = displayio.Palette(2); pal[0]=0x000000; pal[1]=0xFFFFFF
    return bmp, pal

def clear(bmp):
    try: bmp.fill(0)
    except AttributeError:
        for y in range(SCREEN_H):
            for x in range(SCREEN_W): bmp[x,y]=0

def hline(bmp, x0, x1, y, c=1):
    if y<0 or y>=SCREEN_H: return
    if x0>x1: x0,x1=x1,x0
    x0=max(0,min(SCREEN_W-1,x0)); x1=max(0,min(SCREEN_W-1,x1))
    for x in range(x0,x1+1): bmp[x,y]=c

def rect(bmp, x, y, w, h, c=1):
    x2,y2=x+w,y+h
    for yy in range(y,y2):
        if 0<=yy<SCREEN_H:
            for xx in range(x,x2):
                if 0<=xx<SCREEN_W: bmp[xx,yy]=c

def plot(bmp, x, y, c=1):
    if 0<=x<SCREEN_W and 0<=y<SCREEN_H: bmp[x,y]=c

def text_label(txt, y, anchor_x=0.5):
    return label.Label(
        terminalio.FONT, text=txt, color=0xFFFFFF,
        anchor_point=(anchor_x, 0.0),
        anchored_position=(int(SCREEN_W*anchor_x), y)
    )

# ---- Tiny 3x5 microfont ----
FONT_3x5 = {
    "T":[0b111,0b010,0b010,0b010,0b010],
    "S":[0b110,0b100,0b010,0b001,0b110],
    "1":[0b010,0b110,0b010,0b010,0b111],
    "0":[0b111,0b101,0b101,0b101,0b111],
    "X":[0b101,0b101,0b010,0b101,0b101],
}
def stamp_text_3x5(bmp, text, x, y, scale=1):
    cx=x
    for ch in text:
        pat=FONT_3x5.get(ch)
        if not pat:
            cx += (1*scale+scale); continue
        for ry,row in enumerate(pat):
            for rx in range(3):
                if row & (1<<(2-rx)):
                    rect(bmp, cx+rx*scale, y+ry*scale, scale, scale, 1)
        cx += (3*scale+scale)

# ----------------- Demos -----------------
class StarfieldDemo:
    def __init__(self, n=85):
        self.n = n
        self.f = 38.0
        self.depth_min = 0.55
        self.depth_max = 5.5
        self.speed = 0.055
        self.spread = min(
            (CX - 2) * self.depth_min / self.f * 0.97,
            (CY - 2) * self.depth_min / (self.f * 0.6) * 0.97
        )
        self.shuffle()

    # -- public controls (used by button()) --
    def shuffle(self):
        # (Re)populate; ensure each star starts projected on-screen
        self.stars = [self._spawn_star() for _ in range(self.n)]

    def tweak(self, d):
        self.speed = max(0.005, min(0.14, self.speed + d))

    # -- internals --
    def _project(self, s):
        x, y, z = s
        invz = 1.0 / max(0.01, z)
        px = int(CX + x * self.f * invz)
        py = int(CY + y * self.f * 0.6 * invz)
        return px, py

    def _on_screen(self, px, py):
        return 0 <= px < SCREEN_W and 0 <= py < SCREEN_H

    def _spawn_star(self):
        # Try a few times to spawn something that projects on-screen
        for _ in range(8):
            x = random.uniform(-self.spread, self.spread)
            y = random.uniform(-self.spread, self.spread)
            z = random.uniform(self.depth_min, self.depth_max)
            px, py = self._project((x, y, z))
            if self._on_screen(px, py):
                return [x, y, z]
        # Fallback near center if projection misses
        return [random.uniform(-0.2, 0.2),
                random.uniform(-0.2, 0.2),
                random.uniform(self.depth_min, self.depth_max)]

    def draw(self, bmp):
        for i, s in enumerate(self.stars):
            # advance in depth; tiny per-star variance adds life
            s[2] -= self.speed * (0.9 + random.random() * 0.2)

            # respawn if too close or off-screen
            px, py = self._project(s)
            if s[2] <= self.depth_min * 0.25 or not self._on_screen(px, py):
                self.stars[i] = self._spawn_star()
                px, py = self._project(self.stars[i])

            # small → bigger as they approach; guarantee 2px near camera
            z = self.stars[i][2]
            t = 1 if z > 3.5 else (2 if z > 1.6 else 3)
            if z < 1.0:
                t = max(t, 2)
            rect(bmp, px - t // 2, py - t // 2, t, t, 1)
            
            
class KaleidoTextDemo:
    def __init__(self):
        self.theta=0.0; self.omega=0.035; self.rad=10; self.scale=1; self.sym=8
    def shuffle(self):
        self.omega=random.choice([-0.05,-0.035,0.035,0.05])
        self.rad=random.randint(8,18); self.scale=random.choice([1,1,2]); self.sym=random.choice([4,6,8])
    def draw(self,bmp):
        self.theta+=self.omega
        bx=CX+math.cos(self.theta)*self.rad
        by=CY+math.sin(self.theta)*(self.rad*0.6)
        for i in range(self.sym):
            ang=(2*math.pi/self.sym)*i
            dx,dy=bx-CX,by-CY
            rx=dx*math.cos(ang)-dy*math.sin(ang)
            ry=dx*math.sin(ang)+dy*math.cos(ang)
            stamp_text_3x5(bmp,"TS1000",int(CX+rx),int(CY+ry),self.scale)
        for i in range(self.sym):
            a=(2*math.pi/self.sym)*i + self.theta*0.5
            x2=int(CX+math.cos(a)*(SCREEN_W//2))
            y2=int(CY+math.sin(a)*(SCREEN_H//2))
            steps=32
            for k in range(0,steps,2):
                t=k/steps
                plot(bmp,int(CX+(x2-CX)*t),int(CY+(y2-CY)*t),1)

class RoadWallsDemo:
    def __init__(self):
        self.speed=0.05; self.t=0.0; self._reshuffle()
    def _reshuffle(self):
        self.w1=random.uniform(0.6,1.2); self.w2=random.uniform(0.2,0.6)
        self.a1=random.uniform(0.8,1.6); self.a2=random.uniform(1.6,2.8)
    def shuffle(self):
        self._reshuffle(); self.t=0.0
    def tweak(self,d):
        self.speed=max(0.01,min(0.16,self.speed+d))
    def draw(self,bmp):
        self.t+=self.speed
        horizon=20; hline(bmp,0,SCREEN_W-1,horizon,1)
        offset=int((math.sin(self.t*self.a1)*self.w1 + math.sin(self.t*self.a2)*self.w2)*18)
        cx=CX+offset
        for y in range(horizon+1,SCREEN_H):
            d=(y-horizon)/(SCREEN_H-horizon)
            half=int(5 + (SCREEN_W//2 - 7) * (d**1.18))  
            lx,rx=cx-half,cx+half
            plot(bmp,lx,y,1); plot(bmp,rx,y,1)
            if int((y + int(self.t*30)) % 9) == 0:
                hline(bmp,lx+1,rx-1,y,1)

# -------------- Wrapper with encoder menu --------------
class sinclair_demo_bag:
    def __init__(self, macropad, *_, **__):
        self.supports_double_encoder_exit = True
        self.macropad = macropad

        self.group = displayio.Group()
        self.bmp, self.pal = make_surface()
        self.tile = displayio.TileGrid(self.bmp, pixel_shader=self.pal)
        self.group.append(self.tile)

        # Menu screen starts blank; divider is drawn in new_game()
        clear(self.bmp)

        self.title = text_label("80s Demo Scene", 1)
        self.group.append(self.title)

        self.menu_lbl   = text_label("Select:", 18, anchor_x=0.0)
        self.choice_lbl = text_label("Starfield", 30)
        self.hint_lbl   = text_label("", 46)
        self.group.append(self.menu_lbl)
        self.group.append(self.choice_lbl)
        self.group.append(self.hint_lbl)

        # HUD created; added only while a demo is running
        self.hud = text_label("", 1)
        self._hud_last = None

        self._menu_items = ("Starfield","Kaleido","Road")
        self._menu_index = 0
        self.state = "menu"    # or "star","kaleido","road"
        self.demo = None
        self._last = 0.0

        # menu press timing (for double-press window)
        self._menu_press_t = None

        # LED colors (match mix_bag)
        self.COL_OFF  = (0, 0, 0)
        self.COL_MOVE = (0, 25, 0)   # K3/K5 movement = green
        self.COL_FIRE = (40, 0, 0)   # K7 fire/shuffle = red
        self._led_all_off()

    # ---------- LED helpers ----------
    def _led_set(self, idx, col):
        try:
            self.macropad.pixels[idx] = col
            self.macropad.pixels.show()
        except Exception:
            pass

    def _led_all_off(self):
        try:
            for i in range(len(self.macropad.pixels)):
                self.macropad.pixels[i] = self.COL_OFF
            self.macropad.pixels.show()
        except Exception:
            pass

    def _set_menu_lights(self):
        self._led_all_off()

    def _set_demo_lights(self, name):
        # K3/K5 green for tweak (if used), K7 red for shuffle
        self._led_all_off()
        if name in ("Starfield","Road"):
            self._led_set(K_LEFT,  self.COL_MOVE)
            self._led_set(K_RIGHT, self.COL_MOVE)
        self._led_set(K_FIRE, self.COL_FIRE)

    # ---------- HUD ----------
    def _set_hud(self, s: str):
        if s != self._hud_last:
            self.hud.text = s
            self._hud_last = s

    def new_game(self):
        clear(self.bmp)
        hline(self.bmp, 0, SCREEN_W-1, 10, 1)
        self.choice_lbl.text = self._menu_items[self._menu_index]
        self._set_menu_lights()
        self._menu_press_t = None        # ensure clean slate after launcher return
        try: self.macropad.display.auto_refresh = True
        except Exception: pass

    def encoderChange(self, pos, last_pos):
        if self.state != "menu" or pos == last_pos:
            return
        self._menu_index = pos % len(self._menu_items)
        self.choice_lbl.text = self._menu_items[self._menu_index]

    def encoder_button(self, pressed):
        # In menu: single press (after window) starts demo; double-press is for launcher
        # In demo: single press returns to menu
        if not pressed:
            return
        now = time.monotonic()
        if self.state == "menu":
            if self._menu_press_t is None:
                self._menu_press_t = now  # arm single-press; tick() will start after window
            else:
                # second press within window -> let launcher handle exiting
                if (now - self._menu_press_t) <= DOUBLE_PRESS_WINDOW:
                    self._menu_press_t = None
                else:
                    # too late; treat as new first press
                    self._menu_press_t = now
        else:
            self._to_menu()

    def _to_menu(self):
        # draw everything with auto_refresh off to avoid flicker
        try: self.macropad.display.auto_refresh = False
        except Exception: pass

        clear(self.bmp)
        for w in (self.title, self.menu_lbl, self.choice_lbl, self.hint_lbl):
            if w not in self.group: self.group.append(w)
        try:
            if self.hud in self.group: self.group.remove(self.hud)
        except Exception: pass

        hline(self.bmp, 0, SCREEN_W-1, 10, 1)
        self.choice_lbl.text = self._menu_items[self._menu_index]
        self.state = "menu"
        self.demo = None
        self._set_menu_lights()
        self._menu_press_t = None

        try:
            self.macropad.display.refresh(minimum_frames_per_second=0)
            self.macropad.display.auto_refresh = True
        except Exception: pass

    def _enter(self, name):
        # Remove menu labels and title; show HUD
        for w in (self.menu_lbl, self.choice_lbl, self.hint_lbl, self.title):
            try: self.group.remove(w)
            except Exception: pass
        if self.hud not in self.group: self.group.append(self.hud)

        try: self.macropad.display.auto_refresh = False
        except Exception: pass

        clear(self.bmp)

        if name == "Starfield":
            self.state="star"; self.demo=StarfieldDemo()
            #self._set_hud("Starfield  K3/K5 speed · K7 shuffle")
        elif name == "Kaleido":
            self.state="kaleido"; self.demo=KaleidoTextDemo()
            #self._set_hud("Kaleido  K7 shuffle")
        else:
            self.state="road"; self.demo=RoadWallsDemo()
            #self._set_hud("Road  K3/K5 speed · K7 shuffle")

        self._set_demo_lights(name)

        try: self.macropad.display.refresh(minimum_frames_per_second=0)
        except Exception: pass

    def tick(self):
        now = time.monotonic()
        if now - self._last < 0.016:
            return
        self._last = now

        # Handle deferred single-press start in menu (leaves time for double-press)
        if self.state == "menu" and self._menu_press_t is not None:
            if (now - self._menu_press_t) > DOUBLE_PRESS_WINDOW:
                self._menu_press_t = None
                sel = self._menu_items[self._menu_index]
                self._enter(sel)
                return

        if self.state == "menu" or self.demo is None:
            return  # static; only label text changes on encoderChange

        clear(self.bmp)
        self.demo.draw(self.bmp)
        try: self.macropad.display.refresh(minimum_frames_per_second=0)
        except Exception: pass

    def button(self, key):
        if self.state == "menu" or self.demo is None:
            return
        if self.state == "star":
            if key==K_LEFT:   self.demo.tweak(-0.008)
            elif key==K_RIGHT:self.demo.tweak(+0.008)
            elif key==K_FIRE: self.demo.shuffle()
        elif self.state == "kaleido":
            if key==K_FIRE:   self.demo.shuffle()
        elif self.state == "road":
            if key==K_LEFT:   self.demo.tweak(-0.01)
            elif key==K_RIGHT:self.demo.tweak(+0.01)
            elif key==K_FIRE: self.demo.shuffle()

    def button_up(self, key):
        pass

    # ---- double-press exit hints (launcher calls these) ----
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
            self._set_hud(s.replace("  Press again to exit", ""))
            try: self.macropad.display.refresh(minimum_frames_per_second=0)
            except Exception: pass

    def cleanup(self):
        # Make our tick() inert
        self.state = "menu"
        self.demo = None
        self._menu_press_t = None

        # Best-effort: stop any tone
        try:
            if hasattr(self.macropad, "stop_tone"):
                self.macropad.stop_tone()
        except Exception:
            pass

        # LEDs off
        try:
            self._led_all_off()
        except Exception:
            pass

        # Restore menu UI on our surface and detach HUD
        try:
            disp = getattr(self.macropad, "display", None)
            if disp:
                try: disp.auto_refresh = False
                except Exception: pass

                # Ensure menu widgets are present; remove HUD
                clear(self.bmp)
                for w in (self.title, self.menu_lbl, self.choice_lbl, self.hint_lbl):
                    if w not in self.group:
                        self.group.append(w)
                try:
                    if self.hud in self.group:
                        self.group.remove(self.hud)
                except Exception:
                    pass

                # Redraw divider and current menu choice
                hline(self.bmp, 0, SCREEN_W-1, 10, 1)
                self.choice_lbl.text = self._menu_items[self._menu_index]

                # Push a clean frame
                try: disp.refresh(minimum_frames_per_second=0)
                except Exception: pass
                try: disp.auto_refresh = True
                except Exception: pass
        except Exception:
            pass