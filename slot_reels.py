# ---------------------------------------------------------------------------
# slot_reels.py — 3-Reel Slots (Merlin Launcher compatible, layered redraw)
# ---------------------------------------------------------------------------
# Classic 3-reel slot machine game for the Adafruit MacroPad, designed for
# Merlin Launcher on CircuitPython 9.x (128×64 monochrome OLED).
# Written by Iain Bennett — 2025
#
# Core Features
#   • Two-layer display system:
#       - Background bitmap: static reel frame & borders
#       - Foreground bitmap: glyph symbols (cleared & redrawn each spin)
#   • Title screen: clean logo presentation (gameplay layers hidden)
#   • Simple 6-symbol set: A, B, C, 7, $, *
#   • Three stop buttons: K3 / K4 / K5 control reels 0 / 1 / 2
#   • Credit system with payouts:
#       - Three of a kind = 20 (7’s), 10 ($), or 5 (others)
#       - Two of a kind   = 2
#   • Bank updated after every spin, winnings displayed on result screen
#
# Display & HUD
#   • Symbols drawn from compact 5×7 glyphs, scaled ×3 and centered
#   • Reel frames aligned with pixel-precise borders
#   • Title, idle, spin, and result prompts displayed via anchored labels
#   • Logo (MerlinChrome.bmp) shown behind reels in TITLE/IDLE states
#
# LED Feedback
#   • While spinning: keys K3/K4/K5 animate with rotating red→orange→yellow pulse
#   • On result: first 3 keys glow green (win) or red (loss) with breathing effect
#   • Idle: LEDs off for clarity
#
# Implementation Notes
#   • Uses dual Bitmaps (BG + FG) for efficient redraws
#   • Transparent foreground palette enables overlay of reel symbols
#   • _LedSmooth wrapper provides anti-flicker updates (rate-limited show)
#   • Minimal allocations during gameplay; symbols blitted each frame
#
# Controls (MacroPad)
#   K3  = Stop Reel 1      K4  = Stop Reel 2      K5  = Stop Reel 3
#   Any key in TITLE → IDLE
#   Any key in IDLE  → Begin spin (cost 1 credit)
#   After RESULT     → Any key resets back to IDLE
#
# Assets / Deps
#   • MerlinChrome.bmp (optional logo)
#   • adafruit_display_text.label (HUD prompts)
#   • bitmaptools (optional; autodetected for blitting)
# ---------------------------------------------------------------------------

import time, math, random
import displayio, terminalio
from micropython import const
try:
    import bitmaptools
    _HAS_BT = True
except Exception:
    _HAS_BT = False

try:
    from adafruit_display_text import label
    _HAVE_LABEL = True
except Exception:
    _HAVE_LABEL = False

SCREEN_W, SCREEN_H = const(128), const(64)
PROMPT_Y1, PROMPT_Y2 = const(40), const(55)
STATE_TITLE, STATE_IDLE, STATE_SPIN, STATE_RESULT = 0, 1, 2, 3

GLYPHS = {
    "A":[0b01110,0b10001,0b10001,0b11111,0b10001,0b10001,0b10001],
    "B":[0b11110,0b10001,0b11110,0b10001,0b10001,0b10001,0b11110],
    "C":[0b01110,0b10001,0b10000,0b10000,0b10000,0b10001,0b01110],
    "7":[0b11111,0b00001,0b00010,0b00100,0b01000,0b01000,0b01000],
    "$":[0b00100,0b01111,0b10100,0b01110,0b00101,0b11110,0b00100],
    "*":[0b00100,0b10101,0b01110,0b11111,0b01110,0b10101,0b00100],
}
SYMS = ("A","B","C","7","$","*")

def _rect_fill(bmp, x, y, w, h, c=1):
    if w <= 0 or h <= 0: return
    if _HAS_BT:
        try:
            bitmaptools.fill_region(bmp, x, y, w, h, c); return
        except Exception: pass
    for yy in range(y, y+h):
        for xx in range(x, x+w):
            if 0 <= xx < SCREEN_W and 0 <= yy < SCREEN_H:
                bmp[xx,yy] = c

def _blit_glyph(bmp, gx, gy, ch, scale=2):
    pattern = GLYPHS.get(ch)
    if not pattern: return
    for row, bits in enumerate(pattern):
        for col in range(5):
            if bits & (1 << (4 - col)):
                _rect_fill(bmp, gx + col*scale, gy + row*scale, scale, scale, 1)

def _make_bitmap_layer(transparent_zero=False):
    bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
    pal = displayio.Palette(2)
    pal[0] = 0x000000; pal[1] = 0xFFFFFF
    if transparent_zero:
        try: pal.make_transparent(0)
        except Exception: pass
    tile = displayio.TileGrid(bmp, pixel_shader=pal)
    return bmp, tile

def _cos01(t): return 0.5 - 0.5*math.cos(t)
def _scale_color(rgb, k):
    r=(rgb>>16)&0xFF; g=(rgb>>8)&0xFF; b=rgb&0xFF
    return (int(r*k)<<16)|(int(g*k)<<8)|int(b*k)

class _LedSmooth:
    def __init__(self, macropad, limit_hz=30):
        self.ok = bool(macropad and hasattr(macropad,"pixels"))
        self.px = macropad.pixels if self.ok else None
        self.buf = [0x000000]*12
        self._last = self.buf[:]
        self._last_show = 0.0
        self._min_dt = 1.0/float(limit_hz if limit_hz>0 else 30)
        if self.ok:
            try:
                if hasattr(self.px,"auto_write"):
                    self._saved_auto = self.px.auto_write
                    self.px.auto_write = False
                else:
                    self._saved_auto = True
                self.px.brightness = 0.30
                for i in range(12): self.px[i]=0x000000
                self.px.show()
            except Exception: self.ok=False
    def set(self,i,c): 
        if self.ok and 0<=i<12: self.buf[i]=c&0xFFFFFF
    def fill(self,c):
        if self.ok: 
            c=int(c)&0xFFFFFF
            for i in range(12): self.buf[i]=c
    def show(self,now=None):
        if not self.ok: return
        import time as _t
        t=now if now is not None else _t.monotonic()
        if (t-self._last_show)<self._min_dt: return
        changed=False
        for i,c in enumerate(self.buf):
            if c!=self._last[i]:
                self.px[i]=c; self._last[i]=c; changed=True
        if changed: 
            try:self.px.show()
            except Exception: pass
        self._last_show=t
    def off(self):
        if not self.ok: return
        for i in range(12): self.buf[i]=0; self._last[i]=0x111111
        self.show()
    def restore(self):
        if self.ok and hasattr(self.px,"auto_write"):
            self.px.auto_write=getattr(self,"_saved_auto",True)

class slot_reels:
    __slots__=("macropad","group","bg_bmp","bg_tile","fg_bmp","fg_tile","_logo_tile",
               "lbl1","lbl2","led","state","credits","reels","spd","lock","last",
               "_payout","_payout_text","t0")
    def __init__(self,macropad=None,*_tones,**_kw):
        self.macropad=macropad
        self.group=displayio.Group()

        # Logo (bottom layer)
        self._logo_tile=None
        try:
            obmp=displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile=displayio.TileGrid(obmp,pixel_shader=getattr(obmp,"pixel_shader",displayio.ColorConverter()))
            self.group.append(tile); self._logo_tile=tile
        except Exception: self._logo_tile=None

        # BG = frame, FG = symbols
        self.bg_bmp,self.bg_tile=_make_bitmap_layer(False)
        self.fg_bmp,self.fg_tile=_make_bitmap_layer(True)
        self.group.append(self.bg_tile)
        self.group.append(self.fg_tile)

        if _HAVE_LABEL:
            self.lbl1=label.Label(terminalio.FONT,text="",color=0xFFFFFF)
            self.lbl2=label.Label(terminalio.FONT,text="",color=0xFFFFFF)
            self.lbl1.anchor_point=(0.5,0.5); self.lbl2.anchor_point=(0.5,0.5)
            self.lbl1.anchored_position=(SCREEN_W//2,PROMPT_Y1)
            self.lbl2.anchored_position=(SCREEN_W//2,PROMPT_Y2)
            self.group.append(self.lbl1); self.group.append(self.lbl2)
        else: self.lbl1=self.lbl2=None

        self.led=_LedSmooth(self.macropad,limit_hz=30)
        self.new_game()

    def _set_logo_visible(self,show):
        if self._logo_tile: self._logo_tile.hidden=not show
    def _set_layers_visible(self,show):
        self.bg_tile.hidden=self.fg_tile.hidden=not show

    def _blip(self,f):
        if self.macropad and hasattr(self.macropad,"play_tone"):
            try:self.macropad.play_tone(int(f))
            except Exception:pass

    def new_game(self,mode=None):
        self.state=STATE_TITLE
        self.credits=100
        self.reels=[0,2,4]; self.spd=[0.0]*3; self.lock=[False]*3
        self._payout=0; self._payout_text=""
        self.t0=time.monotonic()
        self._draw_frame()
        self._set_logo_visible(True); self._set_layers_visible(False)
        self._draw()

    def _draw_frame(self):
        # Draw static reel frame to BG
        FRAME_TOP = 13
        FRAME_BOT = 49   # bottom border at 52, leaves PROMPT_Y2=54 free
        FRAME_W   = 36
        for xo in (6,46,86):
            # Clear interior (between borders)
            _rect_fill(self.bg_bmp, xo, FRAME_TOP, FRAME_W, (FRAME_BOT - FRAME_TOP + 1), 0)
            # Borders
            for i in range(FRAME_W):
                x = xo + i
                self.bg_bmp[x, FRAME_TOP] = 1
                self.bg_bmp[x, FRAME_BOT] = 1
            for y in range(FRAME_TOP, FRAME_BOT + 1):
                self.bg_bmp[xo, y] = 1
                self.bg_bmp[xo + FRAME_W - 1, y] = 1

    def _draw_reels(self):
        # clear FG
        _rect_fill(self.fg_bmp,0,0,SCREEN_W,SCREEN_H,0)
        centers=(11,51,91)
        # Vertically center glyphs in new interior height:
        # interior (non-border) is (FRAME_TOP+1) .. (FRAME_BOT-1) = 17..51 (35px tall)
        # glyph height at scale=3 is 7*3=21 -> top = 17 + (35-21)//2 = 24
        GLYPH_Y = 21
        for i in range(3):
            ch=SYMS[int(self.reels[i])%len(SYMS)]
            _blit_glyph(self.fg_bmp, centers[i]+6, GLYPH_Y, ch, scale=3)

    def _draw(self):
        if self.state in (STATE_IDLE,STATE_SPIN,STATE_RESULT):
            self._draw_reels()
        if _HAVE_LABEL:
            if self.state==STATE_TITLE:
                self.lbl1.text="Slots"; self.lbl2.text="Press to begin"
            elif self.state==STATE_IDLE:
                self.lbl1.text="Slots"; self.lbl2.text="Insert Credit:1"
            elif self.state==STATE_SPIN:
                self.lbl1.text=""; self.lbl2.text="Spinning"
            else:
                self.lbl1.text=""; self.lbl2.text=self._payout_text
        self._draw_leds()

    def _draw_leds(self):
        self.led.fill(0)
        if self.state==STATE_SPIN:
            # Animate K3/K4/K5 cycling through red→orange→yellow with a soft pulse.
            t = time.monotonic() - getattr(self, "t0", 0.0)
            trio = (0xFF0000, 0xFFA500, 0xFFFF00)  # red, orange, yellow
            keys = (3, 4, 5)
            # Rotate colors across keys over time
            rot = int((t / 0.6) % 3)  # change assignment ~every 0.6s
            for i, kidx in enumerate(keys):
                base_col = trio[(i + rot) % 3]
                # Gentle pulse on top of rotation
                k = 0.35 + 0.65 * _cos01((t + 0.18*i) / 1.1)
                self.led.set(kidx, _scale_color(base_col, k))
        elif self.state==STATE_RESULT:
            t=(time.monotonic()-self.t0)%1.5
            k=0.4+0.6*_cos01(t/1.5)
            col=_scale_color(0x00FF60 if self._payout>0 else 0xFF0040,k)
            for i in (0,1,2): self.led.set(i,col)
        self.led.show()

    def _begin_spin(self):
        if self.credits<=0:return
        self.credits-=1; self.state=STATE_SPIN
        self._set_logo_visible(False); self._set_layers_visible(True)
        self.lock=[False]*3
        self.reels=[random.randrange(0,len(SYMS)) for _ in range(3)]
        self.spd=[25.0,30.0,35.0]; self.last=time.monotonic()
        self.t0 = time.monotonic()
        self._blip(330); self._draw()

    def _stop_reel(self,idx):
        if self.state!=STATE_SPIN:return
        self.lock[idx]=True; self.spd[idx]=0.0
        self._blip(262+idx*40)

    def _score(self):
        a,b,c=[SYMS[int(i)%len(SYMS)] for i in self.reels]
        if a==b==c: return 20 if a=="7" else (10 if a=="$" else 5)
        if a==b or b==c or a==c: return 2
        return 0

    def tick(self,dt=0.016):
        if self.state==STATE_SPIN:
            now=time.monotonic(); dt=min(0.05,now-getattr(self,"last",now)); self.last=now
            for i in range(3):
                if self.spd[i]>0.0 and not self.lock[i]:
                    self.reels[i]+=self.spd[i]*dt
            for i in range(3):
                if not self.lock[i]:
                    self.spd[i]-=8.0*dt
                    if self.spd[i]<=0.0: self.spd[i]=0.0
            if all(s==0.0 for s in self.spd):
                self._payout=self._score(); self.credits+=self._payout
                self._payout_text="Winnings:{}  Bank:{}".format(self._payout,self.credits)
                self.state=STATE_RESULT; self.t0=time.monotonic()
                self._blip(523 if self._payout>0 else 196)
            self._draw()
        else: self._draw_leds()

    def button(self,key,pressed=True):
        if not pressed:return
        if self.state==STATE_TITLE:
            self.state=STATE_IDLE; self._set_logo_visible(True); self._set_layers_visible(False)
            self._blip(330); self._draw(); return
        if self.state==STATE_IDLE:
            self._begin_spin()
        elif self.state==STATE_SPIN:
            if key in (3,4,5): self._stop_reel({3:0,4:1,5:2}[key]); self._draw()
        elif self.state==STATE_RESULT:
            self.state=STATE_IDLE; self._set_logo_visible(True); self._set_layers_visible(False)
            self._blip(247); self._draw()

    def cleanup(self):
        try:self._set_logo_visible(False); self._set_layers_visible(True)
        except Exception: pass
        try:self.led.off(); self.led.restore()
        except Exception: pass