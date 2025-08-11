# patterns.py — Master Merlin "Patterns" for Adafruit MacroPad
# CircuitPython 8.x / 9.x, non-blocking LEDs/animation
# Written by Iain Bennett — 2025

import time, math, random
import displayio, terminalio
from adafruit_display_text import label

# Toggle verbose serial logging (target, stream, results) + ASCII grids
DEBUG = True

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
    K_NEW    = 10            # 2P: New Game/Back on K10
    K_NEW_1P = 9             # 1P: New Game/Back on K9
    K_COMP    = 11           # Computer Turn (start stream / stop in 1P)
    P1_BUZZ   = 9            # 2P: Player 1 buzzer (K9)
    P2_BUZZ   = 11           # 2P: Player 2 buzzer (K11)

    # timings
    LED_FRAME_DT = 1/30
    BLINK_HZ = 1.0           # blinking elements in preview/stream
    STREAM_SHOW = 1.00       # seconds a pattern shows
    STREAM_GAP  = 0.35       # seconds between patterns

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

    # ---------- Debug helpers ----------
    def _dbg(self, *args):
        if DEBUG:
            try:
                print("[DEBUG]", *args)
            except Exception:
                pass

    def _grid_ascii(self, solid, blink):
        # 3×3 ASCII grid; S=solid, B=blink, .=off
        s = set(solid); b = set(blink)
        rows = []
        for r in range(3):
            row = []
            for c in range(3):
                i = r*3 + c
                if i in s: row.append("S")
                elif i in b: row.append("B")
                else: row.append(".")
            rows.append("".join(row))
        return "\n".join(rows)

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

        # Two compact lines under the logo (like your launcher)
        self.line1 = label.Label(
            terminalio.FONT, text="",
            color=0xFFFFFF, anchor_point=(0.5, 0.0),
            anchored_position=(W//2, 31)   # top line under logo
        )
        self.line2 = label.Label(
            terminalio.FONT, text="",
            color=0xAAAAAA, anchor_point=(0.5, 0.0),
            anchored_position=(W//2, 45)   # second line under it
        )

        g.append(self.line1)
        g.append(self.line2)

        self.group = g
        # HUD text cache (two lines)
        self._t_cache = ("","")

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
        self._led_fill(0)
        self._led_show()
        try:
            self.mac.pixels.auto_write = True
        except AttributeError:
            pass

    # ---------- Key handling ----------
    def _key_same(self):
        # 1P: K9, 2P: K10
        return self.K_NEW_1P if self.players == 1 else self.K_NEW

    def button(self, key):
        # --- mode select ---
        if self.mode == "mode":
            if key == 3:
                self.players = 1
                self._to_level_select()
            elif key == 5:
                self.players = 2
                self._to_level_select()
            return

        # --- level select (K0–K3 => Level 1–4) ---
        if self.mode == "level":
            if key in (0,1,2,3):
                self.level = key + 1
                self._start_round()
            elif key == self._key_same():
                self._to_mode_select()
            return

        # --- in-round common "New Game/Back" (works in any sub-mode) ---
        if key == self._key_same():
            if self.players == 1:
                self.streak = 0
            self._to_level_select()
            return

        if self.mode == "preview":
            # 2P: either buzzer (K9 or K11) starts the stream
            if (self.players == 2 and key in (self.P1_BUZZ, self.P2_BUZZ)) \
            or (self.players == 1 and key == self.K_COMP):
                self._start_stream()
                return
            return

        if self.mode == "stream":
            if self.players == 2:
                if key == self.P1_BUZZ:     # Player 1 buzzer (K9)
                    self._on_stop(buzzer=1) # score for P1
                    return
                elif key == self.P2_BUZZ:   # Player 2 buzzer (K11)
                    self._on_stop(buzzer=2) # score for P2
                    return
            else:
                # 1-player mode: K11 to stop on match
                if key == self.K_COMP:
                    self._on_stop(buzzer=None)
                    return
            return

        if self.mode == "result":
            # 2P: either buzzer OR K11 advances to the next round
            if self.players == 2 and key in (self.P1_BUZZ, self.P2_BUZZ, self.K_COMP):
                self._start_round()
                return
            # 1P: K11 still advances
            if self.players == 1 and key == self.K_COMP:
                self._start_round()
            return

    def button_up(self, key):
        return

    def encoderChange(self, new, old):
        return

    # ---------- Main loop tick ----------
    def tick(self):
        now = time.monotonic()
        if self.mode in ("mode","level"):
            self._render_ui(now)
            return
        if self.mode == "preview":
            self._render_preview(now)
            return
        if self.mode == "stream":
            self._advance_stream(now)
            self._render_stream(now)
            return
        if self.mode == "result":
            self._render_result(now)
            return

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
        self._dbg("Mode Select")

    def _to_level_select(self):
        self.mode = "level"
        self.level = None
        self._led_fill(0); self._led_show()
        self._set_hud("Choose Level", "L1  L2  L3  L4")
        self._dbg("Level Select:", "1P" if self.players==1 else "2P")

    def _start_round(self):
        self._stopped = False
        self._gen_target_for_level()
        self._build_stream()
        self.mode = "preview"
        self._led_fill(0); self._led_show()
        self._hud_play()
        self._dbg(f"Round start — Level {self.level}, Players: {self.players}")

    def _start_stream(self):
        self._stopped = False
        self.mode = "stream"
        self.stream_idx = -1

        now = time.monotonic()
        # Start in GAP so first _advance_stream() immediately shows idx 0
        self._in_gap = True
        self._gap_until = now
        self._show_until = 0

        self._led_fill(0); self._led_show()
        self._hud_play(streaming=True)
        self._dbg("Stream start")

    def _to_result(self, outcome, buzzer=None):
        self.mode = "result"
        self._result = outcome
        self._result_buzzer = buzzer
        if self.players == 1:
            if outcome == "correct":
                self.streak += 1
                self._sound_win()
            else:
                self._sound_lose()
                self.streak = 0
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

        self._t_result = time.monotonic()
        self._hud_result()
        self._dbg("RESULT:", outcome, "buzzer:", buzzer, "scores:", (self.p1, self.p2), "streak:", self.streak)

    # ---------- Pattern utilities ----------
    # 90° rotation mapping for 3x3
    _ROT90 = {0:6,1:3,2:0,3:7,4:4,5:1,6:8,7:5,8:2}

    def _rot_set(self, cells, k):
        out = set(cells)
        for _ in range(k % 4):
            out = {self._ROT90[i] for i in out}
        return out

    def _sample_unique(self, pool, k):
        # CircuitPython-safe unique sampling (no random.sample)
        lst = list(pool)
        n = len(lst)
        if k >= n:
            return lst[:]
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
                cands.append( (tuple(sorted(self._rot_set(self.target_solid, r))),
                               tuple(sorted(self._rot_set(self.target_blink, r)))) )
            self._canon = min(cands)
        else:
            self._canon = (tuple(sorted(self.target_solid)), tuple(sorted(self.target_blink)))

        self._dbg("Target pattern:")
        self._dbg("  solid:", sorted(self.target_solid), "blink:", sorted(self.target_blink))
        self._dbg("\n" + self._grid_ascii(self.target_solid, self.target_blink))

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
                if on in s:
                    s.remove(on); s.add(off)
                else:
                    b.remove(on); b.add(off)
                pool_on = s | b
                pool_off = set(self.CELLS) - pool_on
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

        self._dbg(f"Stream length={L}, correct at index {correct_idx} (0-based)")

        for i in range(L):
            if i == correct_idx:
                s = set(match_s); b = set(match_b)
                self.stream.append( (s, b, True) )
                self._dbg(f"  [{i}] MATCH")
                self._dbg("\n" + self._grid_ascii(s, b))
            else:
                tries = 0
                while True:
                    tries += 1
                    s,b = self._nearby_variant(self.target_solid, self.target_blink,
                                               rot_choices if self.rot_ok else [0])
                    if not self._equal_match(s,b):
                        self.stream.append( (s,b,False) )
                        self._dbg(f"  [{i}] alt (tries={tries})")
                        self._dbg("\n" + self._grid_ascii(s, b))
                        break
                    if tries > 20:
                        off_pool = set(self.CELLS) - (s|b)
                        off = random.choice(tuple(off_pool)) if off_pool else random.choice(tuple(self.CELLS))
                        if s:
                            s.remove(next(iter(s)))
                        elif b:
                            b.pop()
                        else:
                            s.add(off)
                        s.add(off)
                        self.stream.append((s,b,False))
                        self._dbg(f"  [{i}] alt FORCED")
                        self._dbg("\n" + self._grid_ascii(s, b))
                        break

    # ---------- Streaming logic ----------
    def _advance_stream(self, now):
        # GAP phase -> move to SHOW when gap expires
        if self._in_gap:
            if now >= self._gap_until:
                self.stream_idx += 1
                if self.stream_idx >= len(self.stream):
                    self._dbg("Timeout: end of stream reached")
                    self._to_result("timeout", buzzer=None)
                    return
                self._in_gap = False
                self._show_until = now + self.STREAM_SHOW

                s, b, is_match = self.stream[self.stream_idx]
                self._dbg(f"SHOW idx={self.stream_idx} match={is_match}")
                self._dbg("\n" + self._grid_ascii(s, b))
            return

        # SHOW phase -> enter GAP when show time is over
        if now >= self._show_until:
            self._in_gap = True
            self._gap_until = now + self.STREAM_GAP

    def _on_stop(self, buzzer):
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        idx = max(0, self.stream_idx)
        if idx < len(self.stream):
            s,b,is_match = self.stream[idx]
            outcome = "correct" if is_match else "wrong"
        else:
            outcome = "wrong"
        self._dbg("STOP on idx", idx, "buzzer", buzzer, "=>", outcome)
        self._to_result(outcome, buzzer=buzzer)

    # ---------- HUD helpers ----------
    def _hud_play(self, streaming=False):
        if self.players == 1:
            if streaming:
                self._set_hud("Find the Match", "New    Stop")
            else:
                self._set_hud("Memorize Pattern", "New    Start")
        else:
            if streaming:
                self._set_hud("Buzz on the Match", "P1    New    P2")
            else:
                self._set_hud("Memorize Pattern", "P1    New    P2")

    def _hud_result(self):
        if self.players == 1:
            if self._result == "correct":
                self._set_hud(f"Correct — Streak {self.streak}", "New    Next")
            elif self._result == "timeout":
                self._set_hud("Timeout — Streak 0", "New    Next")
            else:
                self._set_hud("Wrong — Streak 0", "New    Next")
        else:
            score = f"P1 {self.p1}   P2 {self.p2}"
            if self._win_game_player:
                self._set_hud(f"Winner: P{self._win_game_player}", score)
            else:
                if self._result == "timeout":
                    self._set_hud("No Buzz", score)
                else:
                    side = f"P{self._result_buzzer}"
                    verdict = "Correct" if self._result == "correct" else "Wrong"
                    self._set_hud(f"{side}: {verdict}", score)

    # ---------- Rendering ----------
    def _render_ui(self, now):
        self._led_fill(0)
        pulse = self._pulse(now)
        if self.mode == "mode":
            self._led_set(3, self._scale(self.COLOR_HINT, 0.25 + 0.60*pulse))
            self._led_set(5, self._scale(self.COLOR_HINT, 0.25 + 0.60*pulse))
            self._set_hud("1P    2P", "Select Mode")
        else:
            for k in (0,1,2,3):
                self._led_set(k, self._scale(self.COLOR_UI, 0.15 + 0.70*pulse))
            self._led_set(self._key_same(), self._scale(self.COLOR_UI, 0.10))
            self._set_hud("Choose Level", "L1  L2  L3  L4")
        self._led_show()

    def _blink_on(self, now):
        # Clean 50% duty blinking
        phase = (now * self.BLINK_HZ) % 1.0
        return phase < 0.5

    def _render_preview(self, now):
        self._led_fill(0)
        blink_on = self._blink_on(now)
        for i in self.target_solid:
            self._led_set(i, self.COLOR_SOLID)
        for i in self.target_blink:
            self._led_set(i, self.COLOR_BLINK if blink_on else 0x000000)

        # UI keys
        self._led_set(self.K_COMP, self._scale(self.COLOR_UI, 0.12 + 0.30*self._pulse(now)))
        self._led_set(self._key_same(), self._scale(self.COLOR_UI, 0.10))
        if self.players == 2:
            self._led_set(self.P1_BUZZ, self._scale(self.COLOR_UI, 0.10))
            self._led_set(self.P2_BUZZ, self._scale(self.COLOR_UI, 0.10))
        self._led_show()
        self._hud_play(streaming=False)

    def _render_stream(self, now):
        self._led_fill(0)
        idx = max(0, min(self.stream_idx, len(self.stream)-1)) if self.stream else 0
        if 0 <= idx < len(self.stream) and not self._in_gap:
            s,b,_ = self.stream[idx]
            blink_on = self._blink_on(now)
            for i in s: self._led_set(i, self.COLOR_SOLID)
            for i in b: self._led_set(i, self.COLOR_BLINK if blink_on else 0x000000)

        # UI keys
        if self.players == 1:
            self._led_set(self.K_COMP, self._scale(self.COLOR_UI, 0.18 + 0.35*self._pulse(now)))
        else:
            self._led_set(self.P1_BUZZ, self._scale(self.COLOR_UI, 0.12 + 0.30*self._pulse(now)))
            self._led_set(self.P2_BUZZ, self._scale(self.COLOR_UI, 0.12 + 0.30*self._pulse(now)))
        self._led_set(self._key_same(), self._scale(self.COLOR_UI, 0.10))
        self._led_show()
        self._hud_play(streaming=True)

    def _render_result(self, now):
        self._led_fill(0)

        # --- Winner crown branch ---
        if self.players == 2 and self._win_game_player:
            pulse = 0.30 + 0.60 * self._pulse(now)
            gold  = self._scale(0xFFD200, pulse)

            # Clear 3x3 grid and both buzzer LEDs first
            for i in range(9): self._led_set(i, 0)
            self._led_set(self.P1_BUZZ, 0)
            self._led_set(self.P2_BUZZ, 0)

            winner_key = self.P1_BUZZ if self._win_game_player == 1 else self.P2_BUZZ
            loser_key  = self.P2_BUZZ if self._win_game_player == 1 else self.P1_BUZZ

            # Crown in gold
            for i in (1, 3, 4, 5, 7):
                self._led_set(i, gold)
            # Winner buzzer in gold
            self._led_set(winner_key, gold)
            # Loser buzzer shown like the "New" hint (dim white)
            self._led_set(loser_key, self._scale(self.COLOR_UI, 0.10))

            # UI hints, but don't overwrite winner or loser buzzers
            if self._key_same() not in (winner_key, loser_key):
                self._led_set(self._key_same(), self._scale(self.COLOR_UI, 0.10))
            if self.K_COMP not in (winner_key, loser_key):
                self._led_set(self.K_COMP, self._scale(self.COLOR_UI, 0.12 + 0.30 * self._pulse(now)))

            self._led_show()
            return

        # --- No winner yet: original result behavior ---

        # Show the correct pattern (pulsing)
        pulse = 0.55 + 0.35 * self._pulse(now * 0.6)
        for i in self.target_solid:
            self._led_set(i, self._scale(self.COLOR_SOLID, pulse))
        if self._blink_on(now):
            for i in self.target_blink:
                self._led_set(i, self._scale(self.COLOR_BLINK, pulse))

        if self.players == 2:
            if self._result_buzzer in (1, 2):
                k = self.P1_BUZZ if self._result_buzzer == 1 else self.P2_BUZZ
                self._led_set(k, self._scale(self.COLOR_UI, 0.20 + 0.60 * self._pulse(now)))
            # Score pips
            for i in range(min(self.p1, 3)): self._led_set(6 + i, 0x00FF40)
            for i in range(min(self.p2, 3)): self._led_set(i,       0x00FF40)
            if self.p1 >= 4: self._led_set(5, 0x00FF40)
            if self.p2 >= 4: self._led_set(3, 0x00FF40)

        self._led_set(self._key_same(), self._scale(self.COLOR_UI, 0.10))
        self._led_set(self.K_COMP, self._scale(self.COLOR_UI, 0.12 + 0.30 * self._pulse(now)))
        self._led_show()

    # ---------- Sound helpers ----------
    def _play(self, f, d):
        try: self.mac.play_tone(f, d)
        except Exception: pass

    def _sound_win(self):
        for f in (660, 880, 990): self._play(f, 0.05)

    def _sound_lose(self):
        for f in (196, 150): self._play(f, 0.07)

    # ---------- LED helpers ----------
    def _led_set(self, idx, color):
        if 0 <= idx < 12 and self._led[idx] != color:
            self._led[idx] = color
            self._led_dirty = True

    def _led_fill(self, color):
        ch = False
        for i in range(12):
            if self._led[i] != color:
                self._led[i] = color
                ch = True
        if ch: self._led_dirty = True

    def _led_show(self):
        now = time.monotonic()
        if not self._led_dirty or (now - self._last_led_show) < self.LED_FRAME_DT:
            return
        for i,c in enumerate(self._led):
            self.mac.pixels[i] = c
        self._last_led_show = now
        self._led_dirty = False
        try: self.mac.pixels.show()
        except AttributeError: pass

    def _pulse(self, now):
        return 0.5 + 0.5 * math.cos(now * 2 * math.pi * 0.8)

    def _scale(self, color, s):
        if s <= 0: return 0
        if s >= 1: return color
        r = (color>>16)&0xFF; g = (color>>8)&0xFF; b = color&0xFF
        return ((int(r*s)<<16) | (int(g*s)<<8) | int(b*s))