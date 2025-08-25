# ---------------------------------------------------------------------------
# led_pinball.py — LED Pinball Simulation (Merlin Launcher compatible)
# ---------------------------------------------------------------------------
# Fast, single-ball pinball played entirely on the Adafruit MacroPad’s 12 LEDs,
# with a minimal OLED “playfield.” Designed for Merlin Launcher on
# CircuitPython 9.x (128×64 monochrome OLED).
# Written by Iain Bennett — 2025
#
# Core Features
#   • Title screen with Merlin chrome logo (loaded once via OnDiskBitmap)
#   • Real-time flippers (K9 left / K11 right) and a dedicated drain key (K10)
#   • Single-ball lane travel across K0..K8 with temporary “angled” shots (±2 lanes)
#   • Anti-“infinite volley”: rising fatigue fail chance on repeated edge flips
#   • Drop-to-drain animation when a flip is missed (lane → flipper → drain)
#   • Score updates are label-only (no full framebuffer redraw)
#
# Display & HUD
#   • OLED shows a framed mini-playfield with round “bumper” dots
#   • Title/ready/play/drop/drain states each paint a lightweight static frame
#   • Score text updates the label only for responsiveness
#
# LED Feedback (60 Hz, flicker-free)
#   • Lane LEDs are dim background; the current ball lane is bright/pulsed
#   • Flippers glow; pulse while held, dim when idle
#   • Drain key highlights during drop animation; strong cue while in DRAIN state
#   • Cadence-locked LED updates via a single .show() per frame (_LedSmooth)
#
# Implementation Notes
#   • Optional acceleration: bitmaptools.fill_region() when available
#   • Logo TileGrid is created once, toggled by .hidden (only visible on title)
#   • Game loop steps ball movement on its own cadence; LEDs are frame-timed
#   • Minimal allocations during play; incremental drawing to avoid tearing
#
# Controls (MacroPad)
#   ┌───────────────┐
#   │   K1          │   Move ball lane highlight (game logic driven)
#   │K3     K5      │
#   │   K7          │
#   └───────────────┘
#   K9   = Left Flipper        K10  = Drain / New Ball (after drain)
#   K11  = Right Flipper       Any key = Dismiss Title → READY
#
# Assets / Deps
#   • MerlinChrome.bmp (optional logo, same folder)
#   • adafruit_display_text.label (HUD labels)
#   • bitmaptools (optional; autodetected)
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

# ---------- Layout / States ----------
SCREEN_W, SCREEN_H = const(128), const(64)
PROMPT_Y1, PROMPT_Y2 = const(40), const(55)

STATE_TITLE, STATE_READY, STATE_PLAY, STATE_DROP_ANIM, STATE_DRAIN =  -1, 0, 1, 3, 2

LANE_KEYS = (0, 1, 2, 3, 4, 5, 6, 7, 8)  # lane across the top
LEFT_FLIP, DRAIN_KEY, RIGHT_FLIP = 9, 10, 11

# Fatigue base probability step (scaled by consecutive bounces, capped below)
FAIL_PROB = 0.20
FAIL_PROB_CAP = 0.36

# ---------- Drawing helpers ----------
def _clear(bmp):
    if _HAS_BT:
        try:
            bitmaptools.fill_region(bmp, 0, 0, SCREEN_W, SCREEN_H, 0)
            return
        except Exception:
            pass
    for y in range(SCREEN_H):
        for x in range(SCREEN_W):
            bmp[x,y] = 0

def _hline(bmp, x0, x1, y, c=1):
    if y<0 or y>=SCREEN_H: return
    if x0>x1: x0,x1=x1,x0
    x0=max(0,min(SCREEN_W-1,x0)); x1=max(0,min(SCREEN_W-1,x1))
    if x1<x0: return
    if _HAS_BT:
        try:
            bitmaptools.fill_region(bmp,x0,y,(x1-x0+1),1,c); return
        except Exception:
            pass
    for x in range(x0,x1+1): bmp[x,y]=c

def _vline(bmp, x, y0, y1, c=1):
    if x<0 or x>=SCREEN_W: return
    if y0>y1: y0,y1=y1,y0
    y0=max(0,min(SCREEN_H-1,y0)); y1=max(0,min(SCREEN_H-1,y1))
    if y1<y0: return
    if _HAS_BT:
        try:
            bitmaptools.fill_region(bmp,x,y0,1,(y1-y0+1),c); return
        except Exception:
            pass
    for y in range(y0,y1+1): bmp[x,y]=c

def _rect_fill(bmp, x, y, w, h, c=1):
    if w<=0 or h<=0: return
    x2,y2=x+w-1,y+h-1
    if x2<0 or y2<0 or x>=SCREEN_W or y>=SCREEN_H: return
    x0=max(0,min(SCREEN_W-1,x)); y0=max(0,min(SCREEN_H-1,y))
    x1=max(0,min(SCREEN_W-1,x2)); y1=max(0,min(SCREEN_H-1,y2))
    if x1<x0 or y1<y0: return
    if _HAS_BT:
        try:
            bitmaptools.fill_region(bmp,x0,y0,(x1-x0+1),(y1-y0+1),c); return
        except Exception:
            pass
    for yy in range(y0,y1+1):
        for xx in range(x0,x1+1): bmp[xx,yy]=c

def _dot(bmp, cx, cy, r=2, c=1):
    # tiny filled circle (integer midpoint)
    r2 = r*r
    x0 = max(0, cx - r); x1 = min(SCREEN_W-1, cx + r)
    y0 = max(0, cy - r); y1 = min(SCREEN_H-1, cy + r)
    for y in range(y0, y1+1):
        dy = y - cy
        for x in range(x0, x1+1):
            dx = x - cx
            if dx*dx + dy*dy <= r2:
                bmp[x,y] = c

def _cos01(t): return 0.5 - 0.5*math.cos(t)
def _scale_color(rgb, k):
    r=(rgb>>16)&0xFF; g=(rgb>>8)&0xFF; b=rgb&0xFF
    return (int(r*k)<<16)|(int(g*k)<<8)|int(b*k)

def _make_surface():
    # Base 1-bit surface only; logo is added separately and toggled visible on title.
    bmp = displayio.Bitmap(SCREEN_W, SCREEN_H, 2)
    pal = displayio.Palette(2); pal[0]=0x000000; pal[1]=0xFFFFFF
    g = displayio.Group()
    g.append(displayio.TileGrid(bmp, pixel_shader=pal))
    return g, bmp

# ---------- LED anti-flicker helper ----------
class _LedSmooth:
    def __init__(self, macropad, limit_hz=60):
        self.ok = bool(macropad and hasattr(macropad, "pixels"))
        self.px = macropad.pixels if self.ok else None
        self.buf = [0x000000]*12
        self._last = self.buf[:]
        self._last_show = 0.0
        self._min_dt = 1.0/float(limit_hz if limit_hz>0 else 60)
        if self.ok:
            try:
                if hasattr(self.px, "auto_write"):
                    self._saved_auto = self.px.auto_write
                    self.px.auto_write = False
                else:
                    self._saved_auto = True
                self.px.brightness = 0.35
                for i in range(12): self.px[i] = 0x000000
                try: self.px.show()
                except Exception: pass
            except Exception:
                self.ok = False
    def set(self, i, color):
        if self.ok and 0 <= i < 12:
            self.buf[i] = int(color) & 0xFFFFFF
    def fill(self, color):
        if self.ok:
            c = int(color) & 0xFFFFFF
            for i in range(12): self.buf[i] = c
    def show(self, now=None):
        if not self.ok: return
        t = now if (now is not None) else time.monotonic()
        if (t - self._last_show) < self._min_dt:
            return
        for i, c in enumerate(self.buf):
            if c != self._last[i]:
                self.px[i] = c
                self._last[i] = c
        try: self.px.show()
        except Exception: pass
        self._last_show = t
    def off(self):
        if not self.ok: return
        for i in range(12):
            self.buf[i] = 0x000000
            self._last[i] = 0x111111
        self.show()
    def restore(self):
        if self.ok and hasattr(self.px, "auto_write"):
            try: self.px.auto_write = getattr(self, "_saved_auto", True)
            except Exception: pass

# ---------- Main class ----------
class led_pinball:
    def __init__(self, macropad=None, *_tones, **_kwargs):
        self.macropad = macropad
        self.group, self.bmp = _make_surface()

        # Labels
        self.lbl1=self.lbl2=None
        if _HAVE_LABEL:
            self.lbl1 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=4, y=PROMPT_Y1)
            self.lbl2 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=4, y=PROMPT_Y2)
            self.group.append(self.lbl1); self.group.append(self.lbl2)

        # Create Merlin logo once; keep as back layer, hidden by default
        self.logo_tile = None
        try:
            _logo_bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            self.logo_tile = displayio.TileGrid(
                _logo_bmp,
                pixel_shader=getattr(_logo_bmp, "pixel_shader", displayio.ColorConverter())
            )
            self.group.insert(0, self.logo_tile)   # behind bitmap and labels
            self.logo_tile.hidden = True
        except Exception:
            self.logo_tile = None

        # LED cadence
        self._fps = 60.0
        self._frame_dt = 1.0/self._fps
        self._next_frame_t = time.monotonic()
        self._led_phase = 0.0
        self.led = _LedSmooth(self.macropad, limit_hz=int(self._fps))

        # Title / legend
        self._legend_shown_once = False  # show control legend on first boot

        # “Fatigue” for anti-infinite-volley
        self._left_combo = 0
        self._right_combo = 0

        self.new_game(show_title=True)

    # ---- sound ----
    def _blip(self,f):
        if self.macropad and hasattr(self.macropad,"play_tone"):
            try: self.macropad.play_tone(int(f))
            except Exception: pass

    # ---- state setup ----
    def new_game(self, mode=None, show_title=False):
        if show_title and not self._legend_shown_once:
            self.state = STATE_TITLE
            self._title_start_t = time.monotonic()
        else:
            self.state = STATE_READY
        self.score = 0
        self.ball_pos = 0
        self.ball_dir = 1          # sign of travel (+right / -left)
        self.ball_dx  = 1          # magnitude of travel in lanes/step (1 or 2)
        self._angle_decay_steps = 0 # how many steps until dx decays back to 1
        self.speed = 0.8
        self.left = False
        self.right = False

        # step timing for game movement
        self._last_step_t = 0.0
        self._step_interval = 0.15 / max(0.2, self.speed)

        # drop animation bookkeeping
        self._drop_path = []   # sequence of keys to light during drop
        self._drop_idx = 0
        self._drop_dt = 0.10
        self._drop_last_t = 0.0

        # drain UI timing
        self._drain_since = None
        self._drain_score_shown = False

        # combos
        self._left_combo = 0
        self._right_combo = 0

        self._draw_state_frame()  # paint static frame for current state
        self._stage_leds()        # staged; tick() will show
        self._score_dirty = True  # ensure score label prints first time

    # ---- drawing ----
    def _draw_outline_and_dots(self):
        # Border
        _hline(self.bmp,2,SCREEN_W-3,14,1); _hline(self.bmp,2,SCREEN_W-3,PROMPT_Y2-7,1)
        _vline(self.bmp,2,14,PROMPT_Y2-7,1); _vline(self.bmp,SCREEN_W-3,14,PROMPT_Y2-7,1)
        # Round “bumpers” (dots)
        for (cx, cy, r) in ((20,24,2), (40,31,2), (60,24,2), (80,31,2), (100,24,2)):
            _dot(self.bmp, cx, cy, r, 1)

    def _draw_title(self):
        _clear(self.bmp)
        if self.logo_tile:
            self.logo_tile.hidden = False
        if _HAVE_LABEL:
            self.lbl1.text = ""
            self.lbl2.text = "LED Pinball"  # simple title line

    def _draw_ready(self):
        _clear(self.bmp)
        self._draw_outline_and_dots()
        if _HAVE_LABEL:
            self.lbl1.text=""
            self.lbl2.text="LED Pinball"

    def _draw_play_frame(self):
        # draw static frame once; score/prompt labels update separately
        _clear(self.bmp)
        self._draw_outline_and_dots()
        if _HAVE_LABEL:
            self.lbl1.text=""
            self.lbl2.text="Score: {}".format(self.score)  # initial

    def _draw_drop(self):
        _clear(self.bmp)
        self._draw_outline_and_dots()
        if _HAVE_LABEL:
            self.lbl1.text=""
            self.lbl2.text="Dropping…"
            #self.lbl2.text=""

    def _draw_drain(self):
        _clear(self.bmp)
        self._draw_outline_and_dots()
        if _HAVE_LABEL:
            self.lbl1.text=""
            self.lbl2.text="Ball lost"
            #self.lbl2.text="Press to reset"

    def _draw_state_frame(self):
        # Ensure logo only visible on title
        if self.logo_tile:
            self.logo_tile.hidden = (self.state != STATE_TITLE)

        if self.state == STATE_TITLE:
            self._draw_title()
        elif self.state == STATE_READY:
            self._draw_ready()
        elif self.state == STATE_PLAY:
            self._draw_play_frame()
        elif self.state == STATE_DROP_ANIM:
            self._draw_drop()
        else:
            self._draw_drain()

    # label-only score update (no bitmap redraw)
    def _update_score_label(self):
        if _HAVE_LABEL and self.state == STATE_PLAY:
            self.lbl2.text = "Score: {}".format(self.score)
        self._score_dirty = False

    # ---- LED staging (single place; no .show() here) ----
    def _stage_leds(self):
        # Cosine pulse, phase-stepped at frame cadence
        t = self._led_phase % 1.6
        k = 0.35 + 0.65*_cos01(t/1.6)

        self.led.fill(0x000000)

        # High-visibility drain cue
        if self.state == STATE_DRAIN:
            td = (self._led_phase % 1.0) / 1.0           # ~1s period
            kd = _cos01(td); kd = kd*kd                   # gamma for pop
            b  = 0.10 + 0.90*kd
            self.led.set(DRAIN_KEY, _scale_color(0xFF3000, b))

            halo = 0.05 + 0.25*kd
            self.led.set(LEFT_FLIP,  _scale_color(0x803000, halo))
            self.led.set(RIGHT_FLIP, _scale_color(0x803000, halo))

            for kx in LANE_KEYS:
                self.led.set(kx, _scale_color(0x202020, 0.08))
            return

        # Lanes dim (background)
        for kx in LANE_KEYS:
            self.led.set(kx, _scale_color(0x808080, 0.15))

        # --- SINGLE BALL DISPLAY ---
        if self.state == STATE_PLAY:
            # Show only the current ball lane
            self.led.set(LANE_KEYS[self.ball_pos], _scale_color(0x00A0FF, 0.6 + 0.4*k))
        elif self.state == STATE_DROP_ANIM and self._drop_path:
            # During drop, show only the active drop segment
            seg = self._drop_path[self._drop_idx]
            self.led.set(seg, _scale_color(0xFFA000, 0.7))

        # Flippers (pulse when held, dim when idle)
        self.led.set(LEFT_FLIP,  _scale_color(0x00FF60, 0.3+0.7*k) if self.left  else _scale_color(0x004020, 0.15))
        self.led.set(RIGHT_FLIP, _scale_color(0x00FF60, 0.3+0.7*k) if self.right else _scale_color(0x004020, 0.15))

        # Drain indicator (subtle during drop only; off otherwise)
        if self.state == STATE_DROP_ANIM:
            self.led.set(DRAIN_KEY, _scale_color(0xFF2000, 0.5 + 0.5*k))
        else:
            self.led.set(DRAIN_KEY, _scale_color(0x401000, 0.12))

    # ---- game events ----
    def _serve(self):
        self.state = STATE_PLAY
        self.ball_pos = 0     # K0
        self.ball_dir = 1
        self.ball_dx  = 1
        self._angle_decay_steps = 0
        self.speed = random.uniform(0.45, 1.15)
        self._step_interval = 0.15/max(0.2, self.speed)
        self._last_step_t = 0.0
        self._left_combo = 0
        self._right_combo = 0
        self._blip(330)
        self._draw_state_frame()  # draw static frame once
        self._stage_leds()
        self._score_dirty = True

    def _hit(self):
        self.score += random.choice((10,20,50))
        self.speed = min(1.15, self.speed+0.08)
        self._step_interval = 0.15/max(0.2, self.speed)
        self._blip(440)
        self._score_dirty = True  # label-only update

    def _start_drop_anim(self, missed_right_edge):
        # Build a short drop path to drain (K10) depending on edge missed
        # Left miss:  K0  -> K9  -> K10
        # Right miss: K8  -> K11 -> K10
        self.state = STATE_DROP_ANIM
        self._drop_path = ([LANE_KEYS[0], LEFT_FLIP, DRAIN_KEY]
                           if not missed_right_edge
                           else [LANE_KEYS[-1], RIGHT_FLIP, DRAIN_KEY])
        self._drop_idx = 0
        self._drop_last_t = time.monotonic()
        self._blip(260)  # start of drop
        self._draw_state_frame()

    # ---- main loop ----
    def tick(self, dt=0.016):
        now = time.monotonic()

        if self.state == STATE_PLAY:
            # step the ball movement at its own cadence
            if (now - self._last_step_t) >= self._step_interval:
                self._last_step_t = now

                # small random lane reversal (reduced to 4% to avoid gifting saves)
                if random.random() < 0.04:
                    self.ball_dir *= -1
                    # when randomness flips us, snap to single-lane travel
                    self.ball_dx = 1 if self.ball_dir > 0 else -1
                    self._angle_decay_steps = 0

                # check for edge flips (with fatigue fail chance)
                if self.ball_pos == 0 and self.ball_dir < 0:
                    if self.left:
                        fail_p = min(FAIL_PROB_CAP, FAIL_PROB * self._left_combo)
                        if random.random() >= fail_p:
                            # successful LEFT flip → travel right with temporary angle (dx=+2)
                            self.ball_dir = 1
                            self.ball_dx  = 2
                            self._angle_decay_steps = random.randint(2, 4)
                            self._left_combo += 1
                            self._right_combo = 0
                            self._hit()
                        else:
                            # fail → drop right away
                            self._start_drop_anim(missed_right_edge=False)
                    # if not holding left, we’ll step off-lane next update

                elif self.ball_pos == (len(LANE_KEYS)-1) and self.ball_dir > 0:
                    if self.right:
                        fail_p = min(FAIL_PROB_CAP, FAIL_PROB * self._right_combo)
                        if random.random() >= fail_p:
                            # successful RIGHT flip → travel left with temporary angle (dx=-2)
                            self.ball_dir = -1
                            self.ball_dx  = -2
                            self._angle_decay_steps = random.randint(2, 4)
                            self._right_combo += 1
                            self._left_combo = 0
                            self._hit()
                        else:
                            self._start_drop_anim(missed_right_edge=True)

                # advance ball
                if self.state == STATE_PLAY:
                    self.ball_pos += self.ball_dx

                    # Decay angled travel back toward single-lane steps
                    if self._angle_decay_steps > 0:
                        self._angle_decay_steps -= 1
                        if self._angle_decay_steps == 0:
                            self.ball_dx = 1 if self.ball_dir > 0 else -1

                    # bounds / drop
                    if self.ball_pos < 0 or self.ball_pos >= len(LANE_KEYS):
                        missed_right = (self.ball_dx > 0)  # last motion was toward right
                        self.ball_pos = max(0, min(len(LANE_KEYS)-1, self.ball_pos))
                        self._start_drop_anim(missed_right_edge=missed_right)

        elif self.state == STATE_DROP_ANIM:
            # advance drop animation
            if (now - self._drop_last_t) >= self._drop_dt:
                self._drop_last_t = now
                self._drop_idx += 1
                if self._drop_idx >= len(self._drop_path):
                    # land in drain
                    self.state = STATE_DRAIN
                    self._blip(196)
                    self._drain_since = now
                    self._drain_score_shown = False
                    self._draw_state_frame()

        elif self.state == STATE_DRAIN:
            # After 2 seconds, replace "Ball lost" with the score text
            if (self._drain_since is not None
                and not self._drain_score_shown
                and (now - self._drain_since) >= 2.0):
                if _HAVE_LABEL:
                    self.lbl1.text = ""
                    self.lbl2.text = "Score: {}".format(self.score)
                self._drain_score_shown = True

        # LED frame cadence (single .show())
        if now >= self._next_frame_t:
            while now >= self._next_frame_t:
                self._next_frame_t += self._frame_dt
                self._led_phase += self._frame_dt
            # label-only score update just before staging LEDs
            if getattr(self, "_score_dirty", False):
                self._update_score_label()
            self._stage_leds()
            self.led.show(now=now)

    # ---- input ----
    def button(self, key, pressed=True):
        if not pressed:
            if key == LEFT_FLIP:  self.left = False
            if key == RIGHT_FLIP: self.right = False
            return

        # press events
        if self.state == STATE_TITLE:
            # any key → READY
            self.state = STATE_READY
            self._draw_state_frame()
            return

        if self.state == STATE_READY:
            self._serve()
        elif self.state == STATE_DRAIN:
            # Only the drain key (K10) starts a new game after a drain
            if key == DRAIN_KEY:
                self.new_game()  # returns to READY
        else:
            if key == LEFT_FLIP:  self.left = True
            if key == RIGHT_FLIP: self.right = True

    # ---- cleanup ----
    def cleanup(self):
        try:
            self.led.off()
            self.led.restore()
        except Exception:
            pass