# match_it.py — Merlin "Match It" on MacroPad (K0..K8 only, symbols via key LEDs)
import time, math, random
import displayio, terminalio
from adafruit_display_text import label


class match_it:
    WILD = 99  # special wildcard symbol

    def __init__(self, macropad, tones):
        self.mac = macropad
        self.tones = tones
        try:
            self.mac.pixels.auto_write = False
        except AttributeError:
            pass
        self.BRIGHT = 0.30
        self.K_NEW   = 9   # restart to preview (no wipe)
        self.K_START = 11  # start from preview (with wipe)

        # animation timing (tweak to taste)
        self.ANIM_FRAME_DT     = 0.03   # ~25 FPS for grid anims (higher = slower)
        self.CROSSFADE_STEPS   = 14     # how many steps to blend between frames
        self.KEY_POP_DURATION  = 0.28   # seconds for single-key pop animation

        # preview encoder selection
        self.sel = 0
        self._enc_cool_until = 0.0

        # colors per symbol index
        self.palette = [
            0xFF4444, 0x33DDFF, 0x66FF66, 0xFFAA33,  # 0..3
            0xCC66FF, 0xFFFF66, 0x66FFFF, 0xFF66AA   # 4..7
        ]
        self.color_wild = 0xFFFFFF

        # unified map for name + 3×3 animation + sound motif
        self.symbols = {
            0: {"name": "propeller", "anim": "propeller", "motif": [(784, 0.05), (880, 0.06)]},
            1: {"name": "star",      "anim": "star",      "motif": [(392, 0.06), (659, 0.06)]},
            2: {"name": "conductor", "anim": "conductor", "motif": [(523, 0.08), (523, 0.04)]},
            3: {"name": "juggler",   "anim": "juggler",   "motif": [(740, 0.06), (523, 0.06)]},
            4: {"name": "explosion", "anim": "explosion", "motif": [(659, 0.05), (880, 0.05)]},
            5: {"name": "clock",     "anim": "clock",     "motif": [(440, 0.05), (880, 0.05)]},  # tick–tock
            6: {"name": "bat",       "anim": "bat",       "motif": [(523, 0.05), (659, 0.05)]},
            7: {"name": "trophy",    "anim": "trophy",    "motif": [(880, 0.05), (988, 0.05)]},
            self.WILD: {"name": "wild", "anim": "rainbow",
                        "motif": [(660, 0.04), (784, 0.04), (988, 0.04), (784, 0.04)]},
        }

        # game state
        self.mode = "starting"  # boot in starting mode
        self.layout = [0] * 9
        self.revealed = [False] * 9
        self.solved = [False] * 9
        self.first_pick = None
        self.tries = 0
        
        # Build UI, then do a boot wipe into preview
        self._build_display()
        try:
            self._start_game_wipe()   # blocking boot wipe once
        except Exception:
            pass

        # Show the persistent title screen, then land in preview
        self._show_title_screen()
        self._preview_setup()

    # ---------- symbol helpers ----------
    def _symbol_anim_name(self, symbol_id):
        entry = self.symbols.get(symbol_id)
        return entry["anim"] if entry else "propeller"

    def _preview_symbol_for_key(self, key):
        # show 8 symbols in preview + wild in center
        pattern = [0, 1, 2, 3, self.WILD, 4, 5, 6, 7]
        return pattern[key % 9]

    # ---------- public ----------
    def new_game(self):
        self._preview_setup()

    def button(self, key):
        if self.mode == "starting":
            return

        if self.mode == "preview":
            if 0 <= key <= 8:
                sym = self._preview_symbol_for_key(key)
                # pop the key, then play the 3×3 anim (both blocking)
                self._pop_key_blocking(key, sym)
                self._play_symbol_anim(self._symbol_anim_name(sym), self._color_for_symbol(sym))
                self._render_preview_cursor()
                return
            elif key == self.K_START:
                self.mode = "starting"
                self._start_game_wipe()   # blocking
                self._enter_play()
                return
            elif key == self.K_NEW:
                self._preview_setup()
            return

        if self.mode == "won":
            if key == self.K_NEW:
                self._preview_setup()
            return

        if self.mode == "play":
            if key == self.K_NEW:
                self._preview_setup()
                return
            if 0 <= key <= 8:
                self._handle_reveal(key)

    def encoderChange(self, new_pos, old_pos):
        if self.mode != "preview":
            return
        now = time.monotonic()
        if now < self._enc_cool_until:
            return
        self._enc_cool_until = now + 0.08

        self.sel = new_pos % 9
        self._render_preview_cursor()

        sym = self._preview_symbol_for_key(self.sel)
        self._play_symbol_anim(self._symbol_anim_name(sym), self._color_for_symbol(sym))
        self._render_preview_cursor()

    def tick(self):
        if self.mode == "preview":
            self._render_preview_cursor(refresh_only=True)

    # ---------- Game logic ----------
    def _enter_play(self):
        self.mode = "play"
        self._build_layout()
        self.revealed = [False] * 9
        self.solved   = [False] * 9
        self.first_pick = None
        self.tries = 0
        self.sel = 0

        # ensure labels exist, then restore full title lines
        self._ensure_title_screen()
        self._restore_title_texts()

        self._render_board()
        try:
            self.mac.pixels.show()
        except AttributeError:
            pass

    def _build_layout(self):
        # 4 pairs (0..3) + 1 wild (total 9)
        symbols = [0,0, 1,1, 2,2, 3,3, self.WILD]

        # Fisher–Yates shuffle using randrange (works in CircuitPython)
        try:
            for i in range(len(symbols) - 1, 0, -1):
                j = random.randrange(i + 1)   # 0..i
                symbols[i], symbols[j] = symbols[j], symbols[i]
        except AttributeError:
            # Ultra-fallback if randrange is missing (very unlikely)
            # Do a deterministic swap pattern so at least it's not all zeros
            for i in range(len(symbols) - 1, 0, -1):
                j = (i * 7 + 3) % (i + 1)
                symbols[i], symbols[j] = symbols[j], symbols[i]

        self.layout = symbols

        # Sanity check (optional): exactly 1 wild and the rest are pairs
        if self.layout.count(self.WILD) != 1:
            print("warn: layout wild count =", self.layout.count(self.WILD))
        # print("layout:", self.layout)  # enable if you want to see the deal

    def _handle_reveal(self, k):
        if self.solved[k] or self.revealed[k]:
            return

        sym_k = self.layout[k]
        
        # --- Special case: WILD is the only tile left ---
        if sym_k == self.WILD:
            # if every other index is already solved, this pick wins the game
            if all(self.solved[i] or i == k for i in range(9)):
                self._play_symbol_motif(self.WILD)
                self._play_symbol_anim("rainbow", self._color_for_symbol(self.WILD), dt=0.045)
                self.solved[k] = True
                self.revealed[k] = False
                self._on_win()
                return

        # Reveal the tile visually
        self.revealed[k] = True
        self._render_board_key(k)

        # Sound + key pop
        self._play_symbol_motif(sym_k)
        self._pop_key_blocking(k, sym_k)

        # 3×3 animation (use "rainbow" for WILD)
        anim_name = "rainbow" if sym_k == self.WILD else self._symbol_anim_name(sym_k)
        self._play_symbol_anim(anim_name, self._color_for_symbol(sym_k), dt=0.055)

        # IMPORTANT: restore per-tile visuals after the 3×3 grid animation
        self._render_board()

        # If this was the first pick, store it and stop
        if self.first_pick is None:
            self.first_pick = k
            return

        # Second pick -> one try
        a, b = self.first_pick, k
        self.first_pick = None
        self.tries += 1

        sym_a, sym_b = self.layout[a], self.layout[b]
        # --- Wild logic ---
        if sym_a == self.WILD or sym_b == self.WILD:
            wild_idx = a if sym_a == self.WILD else b
            sym = sym_b if sym_a == self.WILD else sym_a

            # all remaining copies of that symbol + the wild just flipped
            targets = [i for i in range(9) if self.layout[i] == sym and not self.solved[i]]
            if wild_idx not in targets:
                targets.append(wild_idx)

            # quick sparkle before clearing
            for i in targets:
                self.mac.pixels[i] = self._scale(self._color_for_symbol(self.layout[i]), 1.0)
            self._led_show(); time.sleep(0.10)

            for i in targets:
                self.solved[i] = True
                self.revealed[i] = False

            self._sound_match()
            self._render_board()
            if all(self.solved):
                self._on_win()
            return

        # --- Normal pair logic ---
        if sym_a == sym_b:
            self.solved[a] = True
            self.solved[b] = True
            self.revealed[a] = False
            self.revealed[b] = False
            self._sound_match()
            self._render_board()
            if all(self.solved):
                self._on_win()
        else:
            # brief show of the mismatch, then auto-hide
            time.sleep(0.65)
            self.revealed[a] = False
            self.revealed[b] = False
            self._render_board()

    # ---------- End state ----------
    def _on_win(self):
        # Show the score using the existing title labels (logo stays put)
        self._ensure_title_screen()
        self._set_title_texts(now_playing="Score", game_title=f"Tries: {self.tries}", status="")
        time.sleep(0.10)  # small nudge so text is drawn before LED blink

        # Celebratory cosine pulse on the keys (green)
        base_color = 0x00FF66
        pulse_steps = 30   # more steps = smoother
        pulse_loops = 2    # how many full fade in/out cycles

        for _ in range(pulse_loops):
            for i in range(pulse_steps):
                u = i / (pulse_steps - 1)        # 0..1
                b = 0.2 + 0.8 * self._ease_cos(u)  # eased brightness between 0.2 and 1.0
                col = self._scale(base_color, b)
                for k in range(9):
                    self.mac.pixels[k] = col
                self._led_show()
                time.sleep(0.02)  # frame delay

        # Leave LEDs in win state; show K9 (New) only
        for k in range(9):
            self.mac.pixels[k] = 0x00FF66
        self.mac.pixels[self.K_NEW]   = 0x202020
        self.mac.pixels[self.K_START] = 0x000000
        self._led_show()

        # Stay in 'won' mode with score visible until K9 is pressed
        self.mode = "won"

    # ---------- Preview visuals ----------
    def _preview_setup(self):
        self.mode = "preview"
        self.sel = 0
        self.first_pick = None

        self.mac.pixels.brightness = self.BRIGHT
        self.mac.pixels.fill((0,0,0))
        self.mac.pixels[self.K_NEW]   = 0x202020
        self.mac.pixels[self.K_START] = 0x009900
        for i in range(9):
            self.mac.pixels[i] = 0x050505
        self.mac.pixels[self.sel] = 0x303030
        try:
            self.mac.pixels.show()
        except AttributeError:
            pass

        # ensure labels exist, then restore full title lines
        self._ensure_title_screen()
        self._restore_title_texts()

    def _render_preview_cursor(self, refresh_only=False):
        for i in range(9):
            self.mac.pixels[i] = 0x050505
        self.mac.pixels[self.sel] = 0x303030
        if not refresh_only:
            self.mac.pixels[self.K_NEW]   = 0x202020
            self.mac.pixels[self.K_START] = 0x009900
        self._led_show()

    # ---------- Board visuals (play mode) ----------
    def _render_board(self):
        if self.mode != "play":
            return
        for i in range(9):
            self._render_board_key(i)
        self.mac.pixels[self.K_NEW]   = 0x202020
        self.mac.pixels[self.K_START] = 0x000000
        self._led_show()

    def _render_board_key(self, i):
        if self.solved[i]:
            col = self._color_for_symbol(self.layout[i])
            self.mac.pixels[i] = self._scale(col, 0.25)
        elif self.revealed[i]:
            col = self._color_for_symbol(self.layout[i])
            self.mac.pixels[i] = self._scale(col, 0.9)
        else:
            self.mac.pixels[i] = 0x000000

    # ---------- Blocking key pop + tones ----------
    def _pop_key_blocking(self, key, symbol_id):
        base = self._color_for_symbol(symbol_id)
        steps = max(6, int(self.KEY_POP_DURATION / self.ANIM_FRAME_DT))
        for i in range(steps):
            u = i / (steps - 1)
            # cosine pulse 0.30→1.00→0.90
            pulse = 0.30 + 0.70 * self._ease_cos(u)     # 0.30..1.00
            settle = 0.90
            b = pulse if i < steps - 1 else settle
            self.mac.pixels[key] = self._scale(base, b)
            self._led_show()
            time.sleep(self.ANIM_FRAME_DT)

    def _play_symbol_motif(self, symbol_id):
        try:
            motif = self.symbols.get(symbol_id, {}).get("motif") or [(660, 0.04), (880, 0.04)]
            for freq, dur in motif:
                self.mac.play_tone(freq, dur)
        except Exception:
            pass

    # ---------- 3×3 grid animations (blocking) ----------
    def _hsv_to_rgb(self, h, s, v):
        i = int(h * 6.0) % 6
        f = (h * 6.0) - i
        p = int(255 * v * (1 - s))
        q = int(255 * v * (1 - f * s))
        t = int(255 * v * (1 - (1 - f) * s))
        vv = int(255 * v)
        if i == 0: r, g, b = vv, t, p
        elif i == 1: r, g, b = q, vv, p
        elif i == 2: r, g, b = p, vv, t
        elif i == 3: r, g, b = p, q, vv
        elif i == 4: r, g, b = t, p, vv
        else:        r, g, b = vv, p, q
        return (r << 16) | (g << 8) | b

    def _ease_cos(self, u):
        if u <= 0.0: return 0.0
        if u >= 1.0: return 1.0
        return 0.5 - 0.5 * math.cos(math.pi * u)

    def _play_symbol_anim(self, name, base=0xFFFFFF, dt=0.06):
        # Special case: true rainbow effect for the wild
        if name == "rainbow":
            # Slower & smoother for emphasis
            self._play_rainbow_anim(dt=0.05, loops=1, steps=26)
            return

        # Otherwise use your existing two-frame patterns and show them a bit slower
        patterns = {
            "propeller": [
                [1,0,1, 0,1,0, 1,0,1],
                [0,1,0, 1,1,1, 0,1,0],
            ],
            "star": [
                [0,1,0, 1,1,1, 0,1,0],
                [1,0,1, 0,1,0, 1,0,1],
            ],
            "conductor": [
                [1,0,0, 0,1,1, 0,0,0],
                [0,0,0, 1,1,0, 0,0,1],
            ],
            "juggler": [
                [0,0,1, 1,1,0, 0,1,0],
                [1,0,0, 0,1,1, 0,0,1],
            ],
            "explosion": [
                [0,1,0, 1,1,1, 0,1,0],
                [1,1,1, 1,0,1, 1,1,1],
            ],
            "clock": [
                [0,1,0, 1,1,0, 0,1,0],
                [0,1,0, 1,1,1, 0,0,0],
            ],
            "bat": [
                [1,0,1, 0,1,0, 1,0,1],
                [0,1,0, 1,0,1, 0,1,0],
            ],
            "trophy": [
                [1,1,1, 0,1,0, 0,1,0],
                [1,1,1, 1,1,1, 0,1,0],
            ],
        }

        seq = patterns.get(name)
        if not seq:
            seq = patterns["propeller"]

        # Smooth cosine crossfade between frames, repeated a couple times
        loops = 2
        steps = self.CROSSFADE_STEPS  # crossfade smoothness (higher = smoother/slower)
        frame_dt = dt if dt is not None else 0.06

        for _ in range(loops):
            for i in range(len(seq)):
                A = seq[i]
                B = seq[(i + 1) % len(seq)]
                for s in range(steps + 1):
                    u = s / float(steps)
                    e = self._ease_cos(u)  # 0..1 eased
                    for idx in range(9):
                        a = A[idx]
                        b = B[idx]
                        level = a + (b - a) * e  # 0..1
                        # keep a small floor so lit squares glow even at low phases
                        bright = 0.10 + 0.90 * level
                        self.mac.pixels[idx] = self._scale(base, bright)
                    self._led_show()
                    time.sleep(frame_dt / steps)

    def _play_rainbow_anim(self, dt=0.03, loops=1, steps=12):
        # phase offsets per tile to create a diagonal traveling wave
        offsets = [
            0.00, 0.08, 0.16,
            0.08, 0.16, 0.24,
            0.16, 0.24, 0.32,
        ]

        for _ in range(loops):
            for s in range(steps):
                base_h = (s / float(steps)) % 1.0
                for i in range(9):
                    # Each tile gets a hue/brightness phase offset
                    h = (base_h + offsets[i]) % 1.0
                    # Cosine pulse (slow in/out), with a nice visible floor
                    u = (base_h + offsets[i]) % 1.0
                    b = 0.15 + 0.85 * (0.5 + 0.5 * math.cos(u * 2.0 * math.pi))
                    col = self._hsv_to_rgb(h, 1.0, 1.0)
                    self.mac.pixels[i] = self._scale(col, b)
                self._led_show()
                time.sleep(dt)
            
    # ---------- Color + wipe + utils ----------
    def _color_for_symbol(self, sym):
        if sym == self.WILD:
            return self.color_wild
        return self.palette[sym % len(self.palette)]

    def _start_game_wipe(self):
        wipe = [
            0xF400FD, 0xDE04EE, 0xC808DE, 0xB20CCF, 0x9C10C0, 0x8614B0,
            0x6F19A1, 0x591D91, 0x432182, 0x2D2573, 0x172963, 0x012D54
        ]
        self.mac.pixels.brightness = self.BRIGHT
        for x in range(12):
            self.mac.pixels[x] = 0x000099
            self._led_show(); time.sleep(0.06)
            self.mac.pixels[x] = wipe[x]
            self._led_show()
        for s in (0.4, 0.2, 0.1, 0.0):
            for i in range(12):
                c = wipe[i]
                r = int(((c >> 16) & 0xFF) * s)
                g = int(((c >> 8) & 0xFF) * s)
                b = int((c & 0xFF) * s)
                self.mac.pixels[i] = (r << 16) | (g << 8) | b
            self._led_show(); time.sleep(0.02)

    def _sound_match(self):
        for f in (660, 880):
            try: self.mac.play_tone(f, 0.04)
            except Exception: pass

    def _scale(self, color, s):
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        return (int(r * s) << 16) | (int(g * s) << 8) | int(b * s)

    def _led_show(self):
        try:
            self.mac.pixels.show()
        except AttributeError:
            pass

    # ---------- minimal score display ----------
    def _build_display(self):
        # Defer building UI until we show the title screen,
        # so nothing appears before the logo is ready.
        self.group = None
        self.logo_tile = None
        self.now_playing = None
        self.game_title = None
        self.status = None


    def _show_title_screen(self):
        W = self.mac.display.width

        g = displayio.Group()

        # Defaults if logo load fails
        logo_h = 0
        top_margin = 0

        # Try to load and center the bitmap at the top
        self.logo_tile = None
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            x = max(0, (W - bmp.width) // 2)
            self.logo_tile = displayio.TileGrid(
                bmp,
                pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter()),
                x=x, y=0
            )
            g.append(self.logo_tile)
            logo_h = getattr(bmp, "height", 0)
            top_margin = 4  # small gap under logo
        except Exception as e:
            print("Error loading logo:", e)

        # Layout text below the logo (or from top if no logo)
        y0 = logo_h + top_margin

        # Save defaults so we can temporarily show score and restore later
        self.DEFAULT_NOW_PLAYING = "Now Playing"
        self.DEFAULT_GAME_TITLE  = "Match It"

        self.now_playing = label.Label(
            terminalio.FONT, text=self.DEFAULT_NOW_PLAYING,
            color=0xA0A0A0,
            anchor_point=(0.5, 0.0), anchored_position=(W//2, y0 + 4)
        )
        g.append(self.now_playing)

        self.game_title = label.Label(
            terminalio.FONT, text=self.DEFAULT_GAME_TITLE,
            color=0xFFFFFF,
            anchor_point=(0.5, 0.0), anchored_position=(W//2, y0 + 18)
        )
        g.append(self.game_title)

        # Status line (used for score/messages). Keep a handle to update later.
        self.status = label.Label(
            terminalio.FONT, text="",
            color=0xFFFFFF,
            anchor_point=(0.5, 0.0), anchored_position=(W//2, y0 + 32)
        )
        g.append(self.status)

        # Swap the whole group onto the display at once
        self.group = g
        self._show()

    def _show(self):
        # Prefer the show() method; it’s the most compatible
        try:
            self.mac.display.show(self.group)
        except AttributeError:
            # Fallback in case .show() isn’t present
            self.mac.display.root_group = self.group
        # If the display supports explicit refresh, do it
        try:
            self.mac.display.refresh()
        except Exception:
            pass
        # Tiny yield to let the display catch up
        time.sleep(0.01)

    def cleanup(self):
        try:
            self.mac.pixels.auto_write = True
        except AttributeError:
            pass
        self.mac.pixels.fill((0,0,0))
        self._led_show()
        
    def _ensure_title_screen(self):
        need_build = (
            self.group is None or
            self.now_playing is None or
            self.game_title is None or
            self.status is None
        )
        if need_build:
            self._show_title_screen()
        else:
            self._show()
            
    def _set_title_texts(self, now_playing=None, game_title=None, status=None):
        if now_playing is not None and self.now_playing:
            self.now_playing.text = now_playing
        if game_title is not None and self.game_title:
            self.game_title.text = game_title
        if status is not None and self.status:
            self.status.text = status
        self._show()

    def _restore_title_texts(self):
        self._set_title_texts(
            now_playing=self.DEFAULT_NOW_PLAYING,
            game_title=self.DEFAULT_GAME_TITLE,
            status=""
    )