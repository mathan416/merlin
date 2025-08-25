# patterns.py — Master Merlin "Patterns" for Adafruit MacroPad
# CircuitPython 8.x / 9.x, non-blocking LEDs/animation
# Written by Iain Bennett — 2025
#
# 🎮 GAMEPLAY
# ░ Classic Merlin “Patterns” re-imagined on a 3×3 MacroPad grid.
# ░ The device streams a sequence of LED grids — one is the target pattern.
# ░ In 1-Player mode, stop the stream when the MATCH appears.
# ░ In 2-Player mode, buzz in first to claim the match — fastest wins!
# ░ Higher levels add rotations, extra cells, and blinking blue tricksters.
# ░ First to 4 points in 2P mode wins the crown 👑.
#
# 🌈 VISUALS
# ░ Red = solid target cells
# ░ Blue = blinking cells (level 4+)
# ░ White = UI hints & prompts
# ░ Green = score “pips” (2P mode)
#
# 🎵 AUDIO
# ░ Quick arpeggios for wins (660–880–990 Hz).
# ░ Low “buzz” for wrong answers (196 Hz / 150 Hz).
#
# 📜 LICENSE
# Released under the CC0 1.0 Universal (Public Domain Dedication).

import time, math, random
import displayio, terminalio
from adafruit_display_text import label


class patterns:
    # ---------- LED constants ----------
    BRIGHT = 0.30
    COLOR_BG    = 0x000000
    COLOR_SOLID = 0xFF0000   # red = solid light
    COLOR_BLINK = 0x00A0FF   # blue = blinking light (level 4, blinkers)
    COLOR_HINT  = 0x00FF00   # pulsing prompts in menus
    COLOR_UI    = 0xFFFFFF

    # keys
    CELLS = tuple(range(9))  # 0..8 grid
    # 0 1 2
    # 3 4 5
    # 6 7 8
    K_NEW     = 10           # 2P: New Game/Back on K10
    K_NEW_1P  = 9            # 1P: New Game/Back on K9
    K_COMP    = 11           # Computer Turn (start stream / stop in 1P)
    P1_BUZZ   = 9            # 2P: Player 1 buzzer (K9)
    P2_BUZZ   = 11           # 2P: Player 2 buzzer (K11)

    # timings
    LED_FRAME_DT = 1/30
    BLINK_HZ = 1.0
    STREAM_SHOW = 1.00
    STREAM_GAP  = 0.35

    # 2P match
    POINTS_TO_WIN = 4

    def __init__(self, macropad, tones):
        self.mac = macropad
        self.tones = tones

        try:
            self.mac.pixels.auto_write = False
        except AttributeError:
            pass
        self.mac.pixels.brightness = self.BRIGHT
        self._led = [0]*12
        self._led_dirty = False
        self._last_led_show = 0.0

        self._build_display()
        self._to_mode_select()
        try:
            self.mac.display.auto_refresh = True
            self.mac.display.refresh(minimum_frames_per_second=0)
        except Exception:
            pass

    # ---------- Display / HUD ----------
    def _build_display(self):
        W, H = self.mac.display.width, self.mac.display.height
        g = displayio.Group()

        # Merlin chrome background if available
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile = displayio.TileGrid(
                bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            g.append(tile)
        except Exception:
            bg = displayio.Bitmap(W, H, 1)
            pal = displayio.Palette(1)
            pal[0] = self.COLOR_BG
            g.append(displayio.TileGrid(bg, pixel_shader=pal))

        # Two compact lines under the logo
        self.line1 = label.Label(
            terminalio.FONT, text="",
            color=0xFFFFFF, anchor_point=(0.5, 0.0),
            anchored_position=(W//2, 31)
        )
        self.line2 = label.Label(
            terminalio.FONT, text="",
            color=0xAAAAAA, anchor_point=(0.5, 0.0),
            anchored_position=(W//2, 45)
        )

        g.append(self.line1)
        g.append(self.line2)

        # HUD text cache
        self._t_cache = ("","")
        self.group = g

    def _set_hud(self, l1=None, l2=None):
        old_l1, old_l2 = self._t_cache
        if l1 is not None and l1 != old_l1:
            self.line1.text = l1; old_l1 = l1
        if l2 is not None and l2 != old_l2:
            self.line2.text = l2; old_l2 = l2
        self._t_cache = (old_l1, old_l2)

    # ---------- Public API ----------
    def new_game(self):
        self._to_mode_select()

    def cleanup(self):
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True

        self.mode = "idle"
        self._stopped = True
        self._in_gap = False
        self.stream_idx = -1
        self._gap_until = 0.0
        self._show_until = 0.0

        try:
            if hasattr(self.mac, "stop_tone"):
                self.mac.stop_tone()
        except Exception:
            pass

        try:
            self.mac.pixels.fill(0x000000)
            self.mac.pixels.show()
            try: self.mac.pixels.auto_write = True
            except Exception: pass
        except Exception:
            pass

        try:
            disp = self.mac.display
            try: disp.auto_refresh = False
            except Exception: pass

            root = getattr(disp, "root_group", None)
            if root is self.group:
                try:
                    disp.root_group = None
                except Exception:
                    try:
                        disp.show(None)
                    except Exception:
                        pass

            try:
                if hasattr(self, "line1"): self.line1.text = ""
                if hasattr(self, "line2"): self.line2.text = ""
            except Exception:
                pass

            try: disp.auto_refresh = True
            except Exception: pass
        except Exception:
            pass

        try:
            self.group = None
            self.line1 = None
            self.line2 = None
        except Exception:
            pass

        try:
            import gc
            gc.collect()
        except Exception:
            pass

    # ---------- Key handling ----------
    def _key_same(self):
        return self.K_NEW_1P if self.players == 1 else self.K_NEW

    def button(self, key):
        if self.mode == "mode":
            if key == 3:
                self.players = 1
                self._to_level_select()
            elif key == 5:
                self.players = 2
                self._to_level_select()
            return

        if self.mode == "level":
            if key in (0,1,2,3):
                self.level = key + 1
                self._start_round()
            elif key == self._key_same():
                self._to_mode_select()
            return

        if key == self._key_same():
            if self.players == 1:
                self.streak = 0
            self._to_level_select()
            return

        if self.mode == "preview":
            if (self.players == 2 and key in (self.P1_BUZZ, self.P2_BUZZ)) \
            or (self.players == 1 and key == self.K_COMP):
                self._start_stream()
                return
            return

        if self.mode == "stream":
            if self.players == 2:
                if key == self.P1_BUZZ:
                    self._on_stop(buzzer=1)
                    return
                elif key == self.P2_BUZZ:
                    self._on_stop(buzzer=2)
                    return
            else:
                if key == self.K_COMP:
                    self._on_stop(buzzer=None)
                    return
            return

        if self.mode == "result":
            if self.players == 2 and key in (self.P1_BUZZ, self.P2_BUZZ, self.K_COMP):
                self._start_round()
                return
            if self.players == 1 and key == self.K_COMP:
                self._start_round()
            return

    def button_up(self, key): return
    def encoderChange(self, new, old): return

    # ---------- Main loop tick ----------
    def tick(self):
        now = time.monotonic()
        if self.mode in ("mode","level"):
            self._render_ui(now); return
        if self.mode == "preview":
            self._render_preview(now); return
        if self.mode == "stream":
            self._advance_stream(now); self._render_stream(now); return
        if self.mode == "result":
            self._render_result(now); return

    # ---------- State transitions ----------
    def _to_mode_select(self):
        self.mode = "mode"
        self.players = None
        self.level = None
        self.streak = 0
        self.p1 = 0
        self.p2 = 0
        self._led_fill(0); self._led_show()
        self._set_hud("1P    2P", "Select Mode")

    def _to_level_select(self):
        self.mode = "level"
        self.level = None
        self._led_fill(0); self._led_show()
        self._set_hud("Choose Level", "L1  L2  L3  L4")

    def _start_round(self):
        self._stopped = False
        self._gen_target_for_level()
        self._build_stream()
        self.mode = "preview"
        self._led_fill(0); self._led_show()
        self._hud_play()

    def _start_stream(self):
        self._stopped = False
        self.mode = "stream"
        self.stream_idx = -1
        now = time.monotonic()
        self._in_gap = True
        self._gap_until = now
        self._show_until = 0
        self._led_fill(0); self._led_show()
        self._hud_play(streaming=True)

    def _to_result(self, outcome, buzzer=None):
        self.mode = "result"
        self._result = outcome
        self._result_buzzer = buzzer
        if self.players == 1:
            if outcome == "correct":
                self.streak += 1; self._sound_win()
            else:
                self._sound_lose(); self.streak = 0
        else:
            if buzzer is None:
                self._sound_lose()
            else:
                if outcome == "correct":
                    if buzzer == 1: self.p1 += 1
                    else: self.p2 += 1
                    self._sound_win()
                else:
                    if buzzer == 1 and self.p1>0: self.p1 -= 1
                    if buzzer == 2 and self.p2>0: self.p2 -= 1
                    self._sound_lose()

        if self.players == 2 and (self.p1 >= self.POINTS_TO_WIN or self.p2 >= self.POINTS_TO_WIN):
            self._win_game_player = 1 if self.p1 >= self.POINTS_TO_WIN else 2
        else:
            self._win_game_player = None

        self._hud_result()

    # ---------- Pattern utilities ----------
    _ROT90_CCW = {0:6,1:3,2:0,3:7,4:4,5:1,6:8,7:5,8:2}
    _ROT90     = {0:2,1:5,2:8,3:1,4:4,5:7,6:0,7:3,8:6}

    def _rot_set(self, cells, k):
        out = set(cells)
        for _ in range(k % 4):
            out = {self._ROT90[i] for i in out}
        return out

    def _sample_unique(self, pool, k):
        lst = list(pool); n = len(lst)
        if k >= n: return lst[:]
        for i in range(k):
            j = random.randint(i, n - 1)
            lst[i], lst[j] = lst[j], lst[i]
        return lst[:k]

    def _gen_target_for_level(self):
        lvl = self.level
        if lvl == 1:
            n = random.choice((2,3)); rot_ok = False; blinking = False
        elif lvl == 2:
            n = random.choice((4,5)); rot_ok = False; blinking = False
        elif lvl == 3:
            n = random.choice((4,5)); rot_ok = True;  blinking = False
        else:
            n = random.choice((5,6,7)); rot_ok = True;  blinking = True

        cells = set(self._sample_unique(self.CELLS, n))
        blink = set()
        if blinking:
            max_blink = max(1, min(3, n-1))
            k = random.randint(1, max_blink)
            blink = set(self._sample_unique(cells, k))
            cells = cells - blink

        self.target_solid = set(cells)
        self.target_blink = set(blink)
        self.rot_ok = rot_ok

        if self.rot_ok:
            cands = []
            for r in range(4):
                cands.append((tuple(sorted(self._rot_set(self.target_solid, r))),
                              tuple(sorted(self._rot_set(self.target_blink, r)))))
            self._canon = min(cands)
        else:
            self._canon = (tuple(sorted(self.target_solid)), tuple(sorted(self.target_blink)))

    def _equal_match(self, solid, blink):
        if not self.rot_ok:
            return (tuple(sorted(solid)), tuple(sorted(blink))) == self._canon
        for r in range(4):
            if (tuple(sorted(self._rot_set(solid, r))),
                tuple(sorted(self._rot_set(blink, r)))) == self._canon:
                return True
        return False

    def _nearby_variant(self, base_s, base_b, rot_choices):
        s = set(base_s); b = set(base_b)
        tweaks = random.choice((1,1,2))
        pool_on = s | b
        pool_off = set(self.CELLS) - pool_on
        for _ in range(tweaks):
            if pool_on and pool_off and random.random()<0.7:
                off = random.choice(tuple(pool_off)); on = random.choice(tuple(pool_on))
                if on in s: s.remove(on); s.add(off)
                else: b.remove(on); b.add(off)
                pool_on = s | b; pool_off = set(self.CELLS) - pool_on
            else:
                if b and s and random.random()<0.5:
                    x = random.choice(tuple(b)); b.remove(x); s.add(x)
                elif b:
                    x = random.choice(tuple(b)); b.remove(x); s.add(x)
                elif s and self.level==4 and random.random()<0.3:
                    x = random.choice(tuple(s)); s.remove(x); b.add(x)

        if rot_choices:
            r = random.choice(rot_choices)
            s = self._rot_set(s, r); b = self._rot_set(b, r)
        return s, b

    def _build_stream(self):
        L = random.randint(7, 11)
        self.stream = []
        correct_idx = random.randint(2, L-2) if L >= 5 else random.randint(1, L-1)

        rot_choices = [0] if not self.rot_ok else [0,1,2,3]
        match_rot = 0 if not self.rot_ok else random.choice([0,1,2,3])
        match_s = self._rot_set(self.target_solid, match_rot)
        match_b = self._rot_set(self.target_blink, match_rot)

        for i in range(L):
            if i == correct_idx:
                s = set(match_s); b = set(match_b)
                self.stream.append((s,b,True))
            else:
                while True:
                    s,b = self._nearby_variant(self.target_solid, self.target_blink,
                                               rot_choices if self.rot_ok else [0])
                    if not self._equal_match(s,b):
                        self.stream.append((s,b,False))
                        break

        self._correct_idx = correct_idx

    # ---------- Streaming logic ----------
    def _advance_stream(self, now):
        if self._in_gap:
            if now >= self._gap_until:
                self.stream_idx += 1
                if self.stream_idx >= len(self.stream):
                    self._to_result("timeout", buzzer=None)
                    return
                self._in_gap = False
                self._show_until = now + self.STREAM_SHOW
            return

        if now >= self._show_until:
            self._in_gap = True
            self._gap_until = now + self.STREAM_GAP

    def _on_stop(self, buzzer):
        if self._in_gap and self.stream_idx < 0: return
        if getattr(self, "_stopped", False): return
        self._stopped = True

        idx = max(0, self.stream_idx)
        if 0 <= idx < len(self.stream):
            _, _, is_match = self.stream[idx]
            outcome = "correct" if is_match else "wrong"
        else:
            outcome = "wrong"
        self._to_result(outcome, buzzer=buzzer)

    # ---------- UI renderers (unchanged) ----------
    # ... [unchanged _render_ui, _render_preview, _render_stream, _render_result, HUD helpers, sound, LED helpers as in your original]