# ---------------------------------------------------------------------------
# whack_a_mole.py — Whack-A-Mole for Adafruit MacroPad
# CircuitPython 9.x — Merlin Launcher Compatible
# Written by Iain Bennett — 2025
#
# OVERVIEW
# ────────────────────────────────────────────────
# ░ A fast-paced reflex game inspired by arcade “mole” cabinets and Merlin.
# ░ Random moles pop up on the MacroPad’s 12 keys — hit them before they vanish!
# ░ Solo mode = timed challenge. Versus mode = alternating levels with score duel.
# ░ Includes difficulty scaling, optional decoys, combos, penalties, and themes.
#
# STATES
# ────────────────────────────────────────────────
# • "mode"     → Title menu; pick 1P, 2P, or enter Settings.
# • "settings" → Adjust tunables (speed, decoys, cap, penalty, timer, colour).
# • "swap"     → Versus only; waits for the next player to press a key.
# • "playing"  → Active game; keys light as moles (hit to score).
# • "gameover" → Results screen; K9 returns to menu.
#
# CONTROLS
# ────────────────────────────────────────────────
# • Mode Menu:   K3 = 1P   |   K5 = 2P   |   K10 = Settings
# • Settings:    K9 = –    |   K11 = +   |   K10 = Back
# • In-Play:     Hit lit keys to score; miss may trigger penalty
# • Game Over:   K9 = Back to menu
#
# GAMEPLAY
# ────────────────────────────────────────────────
# ░ Randomly timed moles light keys for a short window; hit before expiry.
# ░ Decoys (flashes) appear at higher levels to trick players.
# ░ Combos: rapid consecutive hits multiply score.
# ░ Solo: timed run (90s default, or Infinity if set).
# ░ Versus: two players alternate segments; higher score wins the match.
#
# FEATURES / TECH NOTES
# ────────────────────────────────────────────────
# • HUD: compact 2-line text (y=34,48); optional MerlinChrome.bmp logo backdrop.
# • Levels: baseline pacing defined in BASE_LEVELS; tweaked via Settings.
# • LEDs: anti-flicker shadow buffer, atomic map updates, 30 Hz throttle.
# • Sound: minimal tones via MacroPad play_tone (safe fallbacks included).
# • Settings persistence: stored in /whack_a_mole_settings.json if json+storage available.
#
# ---------------------------------------------------------------------------
import time, random
import displayio, terminalio
from micropython import const

try:
    import json
except Exception:
    json = None

try:
    import storage, os
except Exception:
    storage = None

try:
    from adafruit_display_text import label
    HAVE_LABEL = True
except Exception:
    HAVE_LABEL = False

# -------- Debugging --------
DEBUG = False               # flip to False to silence debug
DEBUG_MIN_INTERVAL = 0.15  # seconds between repeated debug prints

# ---------- Tunables ----------
SCREEN_W, SCREEN_H = const(128), const(64)

# HUD lines (centered, compact for 128x64)
HUD_Y1 = const(34)
HUD_Y2 = const(48)

# spawn pacing (between spawns)
SPAWN_PAUSE_MIN = 0.20  # seconds
SPAWN_PAUSE_MAX = 2.00  # seconds

# Levels / pacing (baseline; adjusted by settings)
HITS_TO_CLEAR_BASE = const(10)
HITS_TO_CLEAR_STEP = const(0)
LEVEL_TIME_CAP     = 25.0
SOLO_TOTAL_TIME    = 90.0        # None => infinite
VERSUS_LEVELS      = 5
MISS_PENALTY       = 0           # may be overridden by settings

# Base level template — color/theme applied at runtime
BASE_LEVELS = [
    dict(vis_min=1.20, vis_max=1.60, simultaneous=1, decoy_chance=0.00, combo_window=0.80, color=( 32,  32,255)),  # 1
    dict(vis_min=1.00, vis_max=1.40, simultaneous=1, decoy_chance=0.05, combo_window=0.70, color=( 64, 255, 64)),  # 2
    dict(vis_min=0.85, vis_max=1.20, simultaneous=1, decoy_chance=0.08, combo_window=0.60, color=(255, 128, 32)), # 3
    dict(vis_min=0.75, vis_max=1.10, simultaneous=2, decoy_chance=0.10, combo_window=0.55, color=(255,  64, 64)),  # 4
    dict(vis_min=0.65, vis_max=1.00, simultaneous=2, decoy_chance=0.12, combo_window=0.50, color=(255,  32,128)), # 5
    dict(vis_min=0.55, vis_max=0.90, simultaneous=2, decoy_chance=0.15, combo_window=0.45, color=(255, 255, 32)), # 6
]

# Launcher key mapping (0..11)
K_SETTINGS = const(10)  # open/close Settings
K_START    = const(11)  # Start / also used as (+) in Settings
K_MINUS    = const(9)   # used as (-) in Settings — we also use this as "Back" on Game Over
K_1P       = const(3)
K_2P       = const(5)

# UI colors
COL_CYAN       = (0, 200, 220)
COL_CYAN_DIM   = (0, 80,  90)
COL_WHITE_DIM  = (30, 30, 30)

# Settings color themes (applied to LEVELS at runtime)
THEMES = {
    "Brown":  [(139,  69, 19)]*6,
    "Cyan":   [( 32,  32,255)]*6,
    "Green":  [( 64, 255, 64)]*6,
    "Orange": [(255, 128, 32)]*6,
    "Red":    [(255,  64, 64)]*6,
    "Pink":   [(255,  64,160)]*6,
    "Yellow": [(255, 255, 32)]*6,
}

# Friendly display names for settings (module-level so all methods can see it)
SETTING_NAMES = {
    "SPD":  "Spawn",
    "DEC":  "Decoy",
    "SIM":  "Moles Cap",
    "MISS": "Penalty",
    "TIME": "Timer",
    "COL":  "Colour",
}

# Settings persistence file
SETTINGS_PATH = "/whack_a_mole_settings.json"

# ---------- Optional discovery fallback ----------
def _discover_io():
    """Only used if no macropad is provided by the launcher."""
    pixels, beeper, mac = None, None, None
    try:
        import adafruit_macropad
        mac = adafruit_macropad.MacroPad()
        pixels = mac.pixels
        def _beep(freq, dur):
            try:
                mac.play_tone(freq, dur); return
            except Exception: pass
            try:
                mac.speaker.play_tone(freq, dur); return
            except Exception: pass
            try:
                mac.start_tone(freq); time.sleep(dur); mac.stop_tone()
            except Exception: pass
        beeper = _beep
    except Exception:
        pass
    return mac, pixels, beeper

# ---------- Game Class ----------
class whack_a_mole:
    supports_double_encoder_exit = False

    def __init__(self, macropad=None, tones=None, **kwargs):
        # If your launcher passes macropad, use that (prevents double instantiation)
        self.mac = macropad
        if self.mac is None:
            self.mac, px, bp = _discover_io()
            self.pixels = px
            self.beeper = bp
        else:
            self.pixels = getattr(self.mac, "pixels", None)
            def _beep(freq, dur):
                try:
                    self.mac.play_tone(freq, dur)
                except Exception:
                    try:
                        spk = getattr(self.mac, "speaker", None)
                        if spk: spk.play_tone(freq, dur)
                    except Exception:
                        try:
                            self.mac.start_tone(freq); time.sleep(dur); self.mac.stop_tone()
                        except Exception:
                            pass
            self.beeper = _beep

        # Set LED brightness & use buffered updates
        try:
            if self.pixels: self.pixels.auto_write = False
        except Exception:
            pass
        try:
            if self.pixels: self.pixels.brightness = 0.30
        except Exception:
            pass

        # --- Display group: logo + centered HUD labels ---
        self.group = displayio.Group()
        self._logo_tile = None
        self._ensure_logo()

        self.lbl_top = self._make_centered_label("", HUD_Y1)
        self.lbl_mid = self._make_centered_label("", HUD_Y2)
        if self.lbl_top: self.group.append(self.lbl_top)
        if self.lbl_mid: self.group.append(self.lbl_mid)

        # --- State ---
        self.state = "mode"      # mode | settings | swap(wait-key) | playing | gameover
        self._state_last = None  # for change-only logging
        self.mode  = "SOLO"      # SOLO | VERSUS
        self.player = 0
        self.scores = [0, 0]

        # Settings (short names) — defaults
        self.settings_idx = 0
        self.settings = {
            "SPD": 1,   # 0=Slow, 1=Norm, 2=Fast
            "DEC": 1,   # 0=Off,  1=Some, 2=More
            "SIM": 1,   # 0 => "1", 1 => "2"
            "MISS": 0,  # 0 -> 0, 1 -> -1
            "TIME": 1,  # 0=90s, 1=Infinity
            "COL": 0,   # theme index from THEMES order
        }
        self._setting_names = ["SPD","DEC","SIM","MISS","TIME","COL"]
        self._setting_values = {
            "SPD":  ["Slow","Norm","Fast"],
            "DEC":  ["Off","Some","More"],
            "SIM":  ["1","2"],
            "MISS": ["0","-1"],
            "TIME": ["90s","Infinity"],
            "COL":  list(THEMES.keys()),
        }

        # Persistence: load & apply
        self._load_settings()
        self._apply_loaded_settings()

        # derived level table (colored / tweaked by settings)
        self.LEVELS = None
        self._rebuild_levels_from_settings()

        # Timing / level
        self.timer_end = None
        self.level_idx = 0
        self.level_hits = 0
        self.level_time_end = None
        self.next_spawn_at = 0.0

        # Actives: list[(idx, expires_ts)] ; decoys are idx|0x80
        self.active = []
        self.combo = 0
        self.last_hit_time = 0.0

        # LED shadow buffer (anti-flicker)
        self._led = [0]*12
        self._led_dirty = False
        self._last_led_show = 0.0     # allow immediate first show (no throttle)
        self.LED_FRAME_DT = 1/30

        # Debug throttle
        self._last_dbg = 0.0

        self._led_all_off_immediate()
        self._draw_mode_menu()
        self._dbg_once("INIT complete; state=mode")

    # ---------- Debug helpers ----------
    def _dbg(self, msg, every=DEBUG_MIN_INTERVAL, force=False):
        if not DEBUG:
            return
        try:
            now = time.monotonic()
            if force or (now - self._last_dbg) >= every:
                self._last_dbg = now
                print("[{:.2f}] [{}] {}".format(now, self.state, msg))
        except Exception:
            pass

    def _dbg_once(self, msg):
        if DEBUG:
            try:
                now = time.monotonic()
                print("[{:.2f}] [{}] {}".format(now, self.state, msg))
            except Exception:
                pass

    # ---------- Persistence ----------
    def _load_settings(self):
        if not json:
            return
        try:
            with open(SETTINGS_PATH, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in self._setting_names:
                    if k in data:
                        try: self.settings[k] = int(data[k])
                        except Exception: pass
            self._dbg_once("Loaded settings: {}".format(self.settings))
        except Exception as e:
            self._dbg_once("No settings file (ok): {}".format(e))

    def _save_settings(self):
        if not (json and storage):
            return
        try:
            storage.remount("/", readonly=False)
            with open(SETTINGS_PATH, "w") as f:
                json.dump(self.settings, f)
            self._dbg_once("Saved settings: {}".format(self.settings))
        except Exception as e:
            try: print("Failed to save settings:", e)
            except Exception: pass
        finally:
            try: storage.remount("/", readonly=True)
            except Exception: pass

    def _apply_loaded_settings(self):
        globals()["MISS_PENALTY"] = 0 if self.settings.get("MISS",0) == 0 else -1

    # ---------- Launcher API ----------
    def new_game(self, mode=None):
        if mode is not None:
            self.mode = "VERSUS" if str(mode).upper().startswith("V") else "SOLO"
        self.state = "mode"
        self._state_change_log()
        self.player = 0
        self.scores = [0, 0]
        self._led_all_off_immediate()
        self._draw_mode_menu()
        self._dbg_once("new_game -> mode={}, LEDs set for menu".format(self.mode))

    def _state_change_log(self):
        if self._state_last != self.state:
            self._dbg_once("STATE -> {}".format(self.state))
            self._state_last = self.state

    def tick(self):
        self._state_change_log()
        now = time.monotonic()

        if self.state == "mode":
            self._render_mode(now)
            return

        if self.state == "settings":
            self._render_settings(now)
            return

        if self.state == "swap":
            # WAIT for a key press (no auto-advance)
            self._dbg("waiting for start key (swap)")
            return

        if self.state == "playing":
            remaining_global = None
            if self.mode == "SOLO" and self.timer_end is not None:
                remaining_global = self.timer_end - now
                if remaining_global <= 0:
                    self._dbg_once("SOLO time expired; end_segment")
                    self._end_segment(); return

            remaining_level = self.level_time_end - now
            if remaining_level <= 0:
                self._dbg_once("Level time expired; advance")
                self._advance_level(); return

            # Spawn gate
            if now >= self.next_spawn_at:
                self._dbg("spawn window open (now={:.2f} >= next={:.2f})".format(now, self.next_spawn_at))
                self._spawn_mole(now)
            else:
                self._dbg("spawn window closed (now={:.2f} < next={:.2f})".format(now, self.next_spawn_at))

            self._despawn_expired(now)

            self._update_hud(remaining_global)
            return

        if self.state == "gameover":
            # Idle on game-over screen; wait for K9 press
            return

    # Accepts both 1-arg (key) and 2-arg (key, pressed) styles
    def button(self, k, pressed=None):
        if pressed is None: pressed = True
        if not pressed: return
        self._dbg_once("button k={} in state={}".format(k, self.state))

        if self.state == "mode":
            if k == K_1P:
                self.mode = "SOLO";   self._begin(); return
            if k == K_2P:
                self.mode = "VERSUS"; self._begin(); return
            if k == K_SETTINGS:
                self._to_settings();  return
            return

        if self.state == "settings":
            if k == K_SETTINGS:
                # save & exit
                self._rebuild_levels_from_settings()
                self._apply_loaded_settings()
                self._save_settings()
                self._draw_mode_menu()
                self.state = "mode"
                self._state_change_log()
                return
            if k == K_MINUS:
                self._change_setting(-1); return
            if k == K_START:
                self._change_setting(+1); return
            return

        if self.state == "swap":
            # Any key starts the round for current player
            self._dbg_once("swap -> start playing")
            self._go_playing()
            return

        if self.state == "playing":
            for (idx, _) in list(self.active):
                if (idx & 0x80) == 0 and (idx == k):
                    self._dbg_once("HIT key={} (removing and scoring)".format(k))
                    self.active = [(i,e) for (i,e) in self.active if i != idx]
                    self._hit_mole()
                    return
            self._dbg("press on empty/decoy: k={}".format(k))
            return

        if self.state == "gameover":
            # Only K9 returns to the mode menu
            if k == K_MINUS:
                self._dbg_once("gameover: K9 pressed -> back to mode")
                self.new_game(self.mode)
            else:
                self._dbg("gameover: ignored key {}".format(k))
            return

    def encoderChange(self, new, old):
        if self.state == "settings":
            delta = int(new - old)
            if delta != 0:
                n = len(self._setting_names)
                self.settings_idx = (self.settings_idx + delta) % n
                self._dbg("encoder moved; settings_idx={}".format(self.settings_idx))

    def cleanup(self):
        self._led_all_off_immediate()
        self._dbg_once("cleanup -> all off")

    # ---------- Flow ----------
    def _go_playing(self):
        """Common path for SOLO start and VS 'any key to start'."""
        self.level_idx = 0
        self.level_hits = 0
        self.combo = 0
        self.last_hit_time = 0.0
        self._start_level_timer()
        self._hud_playing()
        self.state = "playing"
        self._state_change_log()
        self._dbg_once("_go_playing -> timers set; next_spawn_at={:.2f}".format(self.next_spawn_at))

    def _begin(self):
        self.scores = [0, 0]
        self.player = 0
        self.combo = 0
        self.last_hit_time = 0.0
        self._led_all_off_immediate()
        if self.mode == "SOLO":
            self.timer_end = (time.monotonic() + SOLO_TOTAL_TIME) if (self.settings["TIME"]==0) else None
            self._dbg_once("_begin SOLO, timer_end={}".format(self.timer_end))
            self._go_playing()              # unified start path
        else:
            self._hud_text("P1 Ready", "Any key to start")
            self._ping()
            self.state = "swap"             # wait for key
            self._state_change_log()
            self._dbg_once("_begin VS -> swap")

    def _start_level_timer(self):
        now = time.monotonic()
        self.level_hits = 0
        self.level_time_end = now + LEVEL_TIME_CAP
        self.active = []
        self.next_spawn_at = now + self._rand_pause()  # first spawn randomized
        self._led_all_off_immediate()
        self._dbg_once("_start_level_timer: level_time_end={:.2f}, next_spawn_at={:.2f}".format(self.level_time_end, self.next_spawn_at))

    def _render_gameover(self):
        """Show final results and light K9 as 'Back to Menu'."""
        if self.mode == "SOLO":
            self._hud_text("Game Over", "S:{}  L:{}".format(self.scores[0], self.level_idx))
        else:
            a, b = self.scores
            if a > b:
                top = "P1 wins"; mid = "{}–{}".format(a, b)
            elif b > a:
                top = "P2 wins"; mid = "{}–{}".format(b, a)
            else:
                top = "Draw";    mid = "{}–{}".format(a, b)
            self._hud_text(top, mid)

        # LEDs: only K9 lit as the “Back/Menu” button
        self._led_apply_map({ K_MINUS: COL_CYAN }, force=True)

    def _end_segment(self):
        self._led_all_off_immediate()
        self.active = []
        if self.mode == "VERSUS" and self.player == 0:
            self.player = 1
            self._hud_text("P2 Ready", "Any key to start")
            self._ping()
            self.state = "swap"
            self._state_change_log()
            self._dbg_once("end_segment -> P2 swap")
        else:
            self.state = "gameover"
            self._state_change_log()
            # Play the sting + render results screen with K9 prompt
            if self.mode == "SOLO":
                self._sting_neutral()
            else:
                a, b = self.scores
                if a > b:   self._sting_win()
                elif b > a: self._sting_lose()
                else:       self._sting_draw()
            self._render_gameover()
            self._dbg_once("end_segment -> gameover (press K9 to return)")

    def _advance_level(self):
        self.active = []
        self._led_all_off_immediate()
        self.level_idx += 1
        max_levels = VERSUS_LEVELS if self.mode == "VERSUS" else len(self.LEVELS)
        if self.level_idx >= max_levels:
            self._dbg_once("advance_level -> finished segment")
            self._end_segment(); return
        self.combo = 0
        self.last_hit_time = 0.0
        self._start_level_timer()
        self._hud_playing()
        self._arpeggio_levelup()
        self._dbg_once("advance_level -> L{}".format(self.level_idx+1))

    # ---------- Settings helpers ----------
    def _rebuild_levels_from_settings(self):
        levels = []
        theme_name = self._setting_values["COL"][self.settings["COL"]]
        theme_color = THEMES[theme_name][0]
        dec_scale = (0.0, 1.0, 1.6)[self.settings["DEC"]]
        sim_cap = 1 if self.settings["SIM"] == 0 else 2

        for base in BASE_LEVELS:
            d = dict(base)
            d["decoy_chance"] = base["decoy_chance"] * dec_scale
            d["simultaneous"] = min(base["simultaneous"], sim_cap)
            d["color"] = theme_color
            levels.append(d)
        self.LEVELS = levels
        self._dbg_once("levels rebuilt w/ theme={} sim_cap={} dec_scale={}".format(theme_name, sim_cap, dec_scale))

    def _setting_line(self):
        key = self._setting_names[self.settings_idx]
        val_idx = self.settings[key]
        val_name = self._setting_values[key][val_idx]
        display = SETTING_NAMES.get(key, key)
        return display, val_name

    def _change_setting(self, delta):
        key = self._setting_names[self.settings_idx]
        vals = self._setting_values[key]
        idx = self.settings[key]
        if key == "SIM":
            idx = (idx + delta) % 2
            self.settings[key] = idx
        else:
            idx = (idx + delta) % len(vals)
            self.settings[key] = idx

        if key == "MISS":
            globals()["MISS_PENALTY"] = 0 if self.settings["MISS"] == 0 else -1

        if key in ("DEC","SIM","COL"):
            self._rebuild_levels_from_settings()
        self._dbg(
            "setting changed {} -> {}".format(SETTING_NAMES.get(key, key),
                                            self._setting_values[key][self.settings[key]]),
            every=0.01, force=True
        )
    # ---------- UI / HUD ----------
    def _ensure_logo(self):
        if self._logo_tile is not None:
            return
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile = displayio.TileGrid(
                bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            self.group.append(tile)
            self._logo_tile = tile
        except Exception:
            self._logo_tile = None

    def _make_centered_label(self, text, y):
        if not HAVE_LABEL:
            return None
        return label.Label(
            terminalio.FONT, text=text, color=0xFFFFFF,
            anchor_point=(0.5, 0.0), anchored_position=(SCREEN_W//2, y)
        )

    def _set_center(self, which, text):
        if not HAVE_LABEL: return
        t = str(text)
        if which == "top" and self.lbl_top:
            self.lbl_top.text = t
        elif which == "mid" and self.lbl_mid:
            self.lbl_mid.text = t

    def _draw_mode_menu(self):
        self._set_center("top", "Whack-A-Mole")
        self._set_center("mid", "1P   Settings   2P")
        self._led_apply_map({
            K_1P: COL_CYAN,
            K_2P: COL_CYAN,
            K_SETTINGS: COL_CYAN_DIM
        }, force=True)
        self._dbg_once("mode menu drawn; LEDs set")

    def _render_mode(self, now):
        import math
        pulse = 0.5 + 0.5 * math.sin(now * 2.0)
        self._led_apply_map({
            K_1P: self._scale(COL_CYAN, 0.35 + 0.45 * pulse),
            K_2P: self._scale(COL_CYAN, 0.35 + 0.45 * pulse),
            K_SETTINGS: COL_CYAN_DIM
        })

    def _to_settings(self):
        self.state = "settings"
        self._state_change_log()
        self._set_center("top", "Settings")
        self._set_center("mid", "")
        self._render_settings(time.monotonic())

    def _render_settings(self, now):
        key, val = self._setting_line()
        self._set_center("mid", "{} : {}".format(key, val))
        self._led_apply_map({
            K_MINUS:    COL_WHITE_DIM,  # (-)
            K_START:    COL_WHITE_DIM,  # (+)
            K_SETTINGS: COL_CYAN_DIM,   # back
        }, force=True)

    def _hud_playing(self):
        if self.mode == "SOLO":
            self._set_center("top", "L{}  S{}   --:--".format(self.level_idx+1, self.scores[0]))
        else:
            p = self.player + 1
            self._set_center("top", "L{}  P{}  {}–{}".format(self.level_idx+1, p, self.scores[0], self.scores[1]))
        hits_needed = HITS_TO_CLEAR_BASE + self.level_idx * HITS_TO_CLEAR_STEP
        self._set_center("mid", "H{}/{}   x{}".format(self.level_hits, hits_needed, max(1, self.combo+1)))

    def _hud_text(self, top, mid):
        self._set_center("top", str(top))
        self._set_center("mid", str(mid))

    def _update_hud(self, remaining_global):
        lvl_num = self.level_idx + 1
        hits_needed = HITS_TO_CLEAR_BASE + self.level_idx * HITS_TO_CLEAR_STEP
        if self.mode == "SOLO":
            t = "--:--" if remaining_global is None else "{:02d}:{:02d}".format(int(remaining_global)//60, int(remaining_global)%60)
            self._set_center("top", "L{}  S{}   {}".format(lvl_num, self.scores[0], t))
        else:
            self._set_center("top", "L{}  P{}  {}–{}".format(lvl_num, self.player+1, self.scores[0], self.scores[1]))
        self._set_center("mid", "H{}/{}   x{}".format(self.level_hits, hits_needed, max(1, self.combo+1)))

    # ---------- Mole mechanics (keys only) ----------
    def _level_cfg(self):
        return self.LEVELS[self.level_idx if self.level_idx < len(self.LEVELS) else -1]

    def _rand_pause(self):
        # scale by SPD setting: Slow=1.35x, Norm=1.0x, Fast=0.70x
        spd_scale = (1.35, 1.00, 0.70)[self.settings["SPD"]]
        v = random.uniform(SPAWN_PAUSE_MIN, SPAWN_PAUSE_MAX) * spd_scale
        self._dbg("rand_pause -> {:.2f}s".format(v))
        return v

    def _shuffle_copy(self, seq):
        """CircuitPython-safe shuffle (Fisher–Yates), returns a new list."""
        lst = list(seq)
        n = len(lst)
        for i in range(n - 1, 0, -1):
            j = random.randint(0, i)
            lst[i], lst[j] = lst[j], lst[i]
        return lst

    def _maybe_spawn(self, now):
        lvl = self._level_cfg()
        need = lvl["simultaneous"] - len(self.active)
        if need <= 0:
            self._dbg("no spawn (already {} active)".format(len(self.active)))
            return
        active_indices = {i & 0x7F for (i, _) in self.active}
        pool = [i for i in range(12) if i not in active_indices]
        choices = self._shuffle_copy(pool)
        spawned = 0
        for _ in range(need):
            if not choices:
                break
            idx = choices.pop()
            if random.random() < lvl["decoy_chance"]:
                self.active.append((idx | 0x80, now + 0.45))
                spawned += 1
            else:
                vis = random.uniform(lvl["vis_min"], lvl["vis_max"])
                self.active.append((idx, now + vis))
                spawned += 1
        self._dbg_once("_maybe_spawn -> spawned {}, active={}".format(spawned, len(self.active)))
        self._pixels_refresh(force=True)  # show spawns immediately

    def _despawn_expired(self, now):
        # If nothing is active, only schedule if there is no upcoming spawn
        if not self.active:
            if now >= self.next_spawn_at:
                self.next_spawn_at = now + self._rand_pause()
                self._dbg("no actives; scheduled next_spawn_at={:.2f}".format(self.next_spawn_at))
            else:
                self._dbg("no actives; keeping next_spawn_at={:.2f}".format(self.next_spawn_at))
            return

        keep, missed_any = [], False
        for (idx, exp_at) in self.active:
            if now < exp_at:
                keep.append((idx, exp_at))
            else:
                if (idx & 0x80) == 0:  # real mole missed
                    if MISS_PENALTY:
                        self.scores[self.player] += MISS_PENALTY
                    missed_any = True

        if len(keep) != len(self.active):
            self._dbg("despawned {} items".format(len(self.active)-len(keep)))

        self.active = keep
        if missed_any:
            self._thud()

        # Just redraw; do NOT touch next_spawn_at here
        self._pixels_refresh()

    def _spawn_mole(self, now):
        self._dbg_once("spawn_mole called")
        self._maybe_spawn(now)
        self.next_spawn_at = now + self._rand_pause()
        self._dbg("spawn_mole scheduled next_spawn_at={:.2f}".format(self.next_spawn_at))

    def _hit_mole(self):
        now = time.monotonic()
        lvl = self._level_cfg()
        if now - self.last_hit_time <= lvl["combo_window"]:
            self.combo = min(self.combo + 1, 9)
        else:
            self.combo = 0
        self.last_hit_time = now

        self.level_hits += 1
        self.scores[self.player] += (1 + self.combo)
        self._blip()

        # Clear remaining actives and refresh immediately (no leftover light)
        self._dbg_once("HIT: combo={}, level_hits={}, score={}".format(self.combo, self.level_hits, self.scores[self.player]))
        self.active = []
        self._pixels_refresh(force=True)

        hits_needed = HITS_TO_CLEAR_BASE + self.level_idx * HITS_TO_CLEAR_STEP
        if self.level_hits >= hits_needed:
            self._dbg_once("level cleared (needed={})".format(hits_needed))
            self._advance_level()

    # ---------- LED helpers (anti-flicker) ----------
    def _led_set(self, idx, color):
        if 0 <= idx < 12 and self._led[idx] != color:
            self._led[idx] = color
            self._led_dirty = True

    def _led_fill(self):
        """Clear local LED shadow buffer to off (no show here)."""
        ch = False
        for i in range(12):
            if self._led[i] != 0:
                self._led[i] = 0
                ch = True
        if ch:
            self._led_dirty = True

    def _led_apply_map(self, mapping, default=(0,0,0), force=False):
        """
        Atomically apply a whole LED layout:
          mapping: {index: (r,g,b), ...}
        No intermediate blank frame; single .show() at the end.
        """
        ch = False
        for i in range(12):
            c = mapping.get(i, default)
            if self._led[i] != c:
                self._led[i] = c
                ch = True
        if ch:
            self._led_dirty = True
        self._led_show(force=force)

    def _led_show(self, force=False):
        if not self.pixels:
            return
        now = time.monotonic()
        if not self._led_dirty:
            return
        if (not force) and ((now - self._last_led_show) < self.LED_FRAME_DT):
            return
        for i, c in enumerate(self._led):
            self.pixels[i] = c
        self._last_led_show = now
        self._led_dirty = False
        try:
            self.pixels.show()
        except Exception:
            pass

    def _pixels_refresh(self, force=False):
        # reflect current actives using cached color; otherwise off
        col = self._level_cfg()["color"]
        layout = {}
        for (idx, _) in self.active:
            k = idx & 0x7F
            if 0 <= k < 12:
                layout[k] = col
        if not layout:
            self._dbg("pixels_refresh -> all off")
        else:
            self._dbg("pixels_refresh -> keys {}".format(sorted(list(layout.keys()))))
        self._led_apply_map(layout, force=force)

    def _led_all_off(self):
        self._led_fill()
        self._led_show()

    def _led_all_off_immediate(self):
        self._led_fill()
        self._led_show(force=True)

    # ---------- Sound helpers ----------
    def _beep(self, f, d):
        if self.beeper:
            self.beeper(f, d)
    def _ping(self): self._beep(1200, 0.06)
    def _blip(self): self._beep(1600, 0.045)
    def _thud(self): self._beep(220, 0.06)
    def _arpeggio_levelup(self):
        self._beep(900, 0.04);  self._beep(1150, 0.04); self._beep(1400, 0.06)
    def _sting_win(self):
        self._beep(880, 0.06); self._beep(1175, 0.08); self._beep(1568, 0.10)
    def _sting_lose(self):
        self._beep(330, 0.10); self._beep(247, 0.10)
    def _sting_draw(self):
        self._beep(660, 0.07); self._beep(660, 0.07)
    def _sting_neutral(self):
        self._beep(700, 0.08)

    # ---------- Small utils ----------
    def _scale(self, rgb, s):
        """Return a DIMMED COLOR AS A TUPLE, never an int (NeoPixel-friendly)."""
        if s <= 0: return (0,0,0)
        if s >= 1:
            return rgb if isinstance(rgb, tuple) else ((rgb>>16)&0xFF, (rgb>>8)&0xFF, rgb&0xFF)
        if isinstance(rgb, tuple):
            r,g,b = rgb
        else:
            r = (rgb>>16)&0xFF; g = (rgb>>8)&0xFF; b = rgb&0xFF
        return (int(r*s), int(g*s), int(b*s))