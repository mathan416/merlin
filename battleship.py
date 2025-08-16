# battleship.py — Battleship for Adafruit MacroPad
# -------------------------------------------------
# Main game logic module for the Battleship adaptation on the Adafruit MacroPad.
# Designed for the Merlin Launcher framework, exposing the required lifecycle methods:
#   __init__()      — Initialize game state and resources.
#   new_game()      — Reset game state and UI for a new match.
#   tick()          — Per-frame update loop for animations and logic.
#   button()        — Handle key press events from the MacroPad.
#   button_up()     — Handle key release events (optional).
#   encoderChange() — Handle rotary encoder input for in-game navigation.
#   cleanup()       — Release resources before returning to menu.
#
# Features:
# - 10×10 grid rendered on the MacroPad OLED.
# - Support for movement, ship placement, rotation, and firing.
# - Personality packs for themed palettes and UI styles.
# - Debug flag for selective logging during development.
#
# Dependencies:
# - CircuitPython displayio for rendering graphics.
# - `battleship_personalities.py` for palette/theme definitions.
#
# Date: 2025-08-15
# Author: Iain Bennett (adapted for MacroPad Battleship)

import time
import gc
from battleship_config import DEBUG, debug_print, _vis
        
ppl = None
def _load_profiles():
    global ppl
    if ppl is None:              # import only once, on demand
        import battleship_personalities as _ppl
        ppl = _ppl


# -------------------------- Game constants --------------------------
GRID_W = 10
GRID_H = 10
CELL   = 6  # px
GRID_PX = CELL * GRID_W  # 60
# ORIGIN_X = (128 - GRID_PX) # Center
ORIGIN_X = 128 - GRID_PX - 1 # Right aligned
ORIGIN_Y = 0

# Board cell values
EMPTY = 0
SHIP  = 1
HIT   = 2
MISS  = 3

# Pause for messages
MSG_PAUSE = 0.1

# State enum
TITLE, SETTINGS, PLACE, BATTLE, RESULTS, HANDOFF = range(6)

class RNG:
    __slots__ = ("s",)
    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def _next(self):
        # xorshift32
        x = self.s
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= (x >> 17)
        x ^= (x << 5) & 0xFFFFFFFF
        self.s = x & 0xFFFFFFFF
        return self.s

    def randrange(self, n):
        return self._next() % n

    def randint(self, a, b):
        # inclusive
        span = (b - a + 1)
        return a + (self._next() % span)

    def getrandbits(self, k):
        mask = (1 << k) - 1
        return self._next() & mask

# -------------------------- Board model --------------------------
class Board:
    __slots__ = ("grid", "ships", "ship_map", "remaining_hits")
    def __init__(self):
        # 0..3 (EMPTY, SHIP, HIT, MISS)
        self.grid = bytearray(100)  # starts all EMPTY (0)
        # ship_map: 0..N-1 = ship index, 255 = no ship
        self.ship_map = bytearray([255]) * 100
        # ships: list of [length, hits] (small, fixed-size lists are ok)
        self.ships = []
        self.remaining_hits = 0

    @staticmethod
    def _i(x, y):
        return (y * GRID_W) + x

    def can_place(self, x, y, length, horizontal=True):
        if horizontal:
            if x + length > GRID_W: return False
            base = self._i(x, y)
            for i in range(length):
                if self.grid[base + i] != EMPTY: return False
        else:
            if y + length > GRID_H: return False
            base = self._i(x, y)
            for i in range(length):
                if self.grid[base + i*GRID_W] != EMPTY: return False
        return True

    def place(self, x, y, length, horizontal=True):
        if not self.can_place(x, y, length, horizontal): return False
        sidx = len(self.ships)
        self.ships.append([length, 0])
        self.remaining_hits += length
        if horizontal:
            base = self._i(x, y)
            for i in range(length):
                ii = base + i
                self.grid[ii] = SHIP
                self.ship_map[ii] = sidx
        else:
            base = self._i(x, y)
            for i in range(length):
                ii = base + i*GRID_W
                self.grid[ii] = SHIP
                self.ship_map[ii] = sidx
        return True

    def fire(self, x, y):
        ii = self._i(x, y)
        cell = self.grid[ii]
        if cell == HIT or cell == MISS:
            return "repeat"

        if cell == SHIP:
            self.grid[ii] = HIT
            sidx = self.ship_map[ii]
            if sidx == 255:
                # Fallback so games can still end; also flag it for debugging
                try:
                    debug_print("WARN: ship_map=255 at", x, y)
                except Exception:
                    pass
                self.remaining_hits -= 1
                return "hit"

            ship = self.ships[sidx]
            ship[1] += 1
            self.remaining_hits -= 1
            return "sunk" if ship[1] == ship[0] else "hit"

        # MISS
        self.grid[ii] = MISS
        return "miss"

    def all_sunk(self):
        return self.remaining_hits == 0

# -------------------------- AI --------------------------
class AI:
    __slots__ = ("rng", "_target_stack", "_seen")
    def __init__(self, rng):
        self.rng = rng
        self._target_stack = []           # list[int] cell indexes 0..99
        self._seen = bytearray(100)       # 0/1 flags

    def _xy_to_i(self, x, y): return y*GRID_W + x
    def _i_to_xy(self, i): return (i % GRID_W, i // GRID_W)
    
    def random_place(self, board, ships):
        # Simple random placement respecting collisions/bounds
        for _, length in ships:
            placed = False
            for _ in range(200):  # try a bunch of times per ship
                horiz = bool(self.rng.getrandbits(1))
                if horiz:
                    x = self.rng.randint(0, GRID_W - length)
                    y = self.rng.randint(0, GRID_H - 1)
                else:
                    x = self.rng.randint(0, GRID_W - 1)
                    y = self.rng.randint(0, GRID_H - length)
                if board.can_place(x, y, length, horiz):
                    board.place(x, y, length, horiz)
                    placed = True
                    break
            if not placed:
                # Fallback: brute scan
                for y in range(GRID_H):
                    for x in range(GRID_W):
                        if board.can_place(x, y, length, True):
                            board.place(x, y, length, True)
                            placed = True
                            break
                    if placed:
                        break

    def reset(self):
        self._target_stack.clear()
        for i in range(100): self._seen[i] = 0

    def pick_shot(self, difficulty="Smart"):
        # 1) Use hunt targets first
        if difficulty == "Smart":
            while self._target_stack:
                i = self._target_stack.pop()
                if 0 <= i < 100 and not self._seen[i]:
                    self._seen[i] = 1
                    return self._i_to_xy(i)

        # 2) Parity-constrained search (Smart)
        if difficulty == "Smart":
            for _ in range(600):
                x = self.rng.randint(0, GRID_W - 1)
                y = self.rng.randint(0, GRID_H - 1)
                if ((x + y) & 1):   # skip wrong parity
                    continue
                i = self._xy_to_i(x, y)
                if not self._seen[i]:
                    self._seen[i] = 1
                    return (x, y)

        # 3) Fallback: no parity (ensures endgame closure)
        for _ in range(600):
            x = self.rng.randint(0, GRID_W - 1)
            y = self.rng.randint(0, GRID_H - 1)
            i = self._xy_to_i(x, y)
            if not self._seen[i]:
                self._seen[i] = 1
                return (x, y)

        # 4) Final linear scan (should rarely/never hit)
        for i in range(100):
            if not self._seen[i]:
                self._seen[i] = 1
                return self._i_to_xy(i)

        # Defensive default
        return (0, 0)
    
    def feed_result(self, x, y, result):
        # Record neighbors to try next when we get a hit/sunk
        if result in ("hit", "sunk"):
            base = self._xy_to_i(x, y)
            nbrs = []
            if (x + 1) < GRID_W:  nbrs.append(base + 1)
            if (x - 1) >= 0:      nbrs.append(base - 1)
            if (y + 1) < GRID_H:  nbrs.append(base + GRID_W)
            if (y - 1) >= 0:      nbrs.append(base - GRID_W)
            self._target_stack.extend(nbrs)
            if result == "sunk":
                # Clear hunt stack when a ship is confirmed sunk
                self._target_stack.clear()

# -------------------------- UI helpers --------------------------

# -------------------------- Game class --------------------------
class Battleship:
    __slots__ = (
        "mac","state","profile_id","profile","sfx_enabled","mode_2p","difficulty",
        "boards","to_place","placed_index","current_player","cursor","ghost",
        "_handoff_next","group","_last_ghost_state","_led_flash_until",
        "ui","ai","rng","_settings_items","_settings_index",
        "_post_win_until",              
    )

    def __init__(self, macropad, *args, **kwargs):
        self.mac = macropad
        self._cleaned = False
        self.state = TITLE

        self.profile_id = "default"
        self.profile = {
            "palette": {"bg":0,"grid":0,"ally":0,"hit":0,"miss":0,"cursor":0,"accent":0,"sunk":0,"text":0},
            "key_leds": {"idle":0, "confirm":0, "warn":0},
            "ships": [],
            "strings": {
                "title_1p":"1 Player", "title_2p":"2 Players",
                "place_prompt":"", "fire_prompt":"", "results_hint":""
            },
            "title":"Battleship","subtitle":""
        }

        self.sfx_enabled = True
        self.mode_2p = False
        self.difficulty = "Smart"

        self.boards = [Board(), Board()]
        self.to_place = []
        self.placed_index = 0
        self.current_player = 0
        self.cursor = [0, 0]
        self.ghost = {"length": 2, "horiz": True}
        self._handoff_next = None
        self.group = None
        self._last_ghost_state = None
        self._led_flash_until = 0
        self._post_win_until = 0

        self.ui = None
        self.ai = None
        self.rng = None

        self._settings_items = [
            ("Mode", ["1P", "2P"]),
            ("Difficulty", ["Easy", "Smart"]),
            ("Personality", ()),   # filled later
            ("SFX", ["on", "off"]),
        ]
        self._settings_index = 0

    # Launcher calls this after construction       
    def new_game(self):
        self._handoff_next = None
        _load_profiles()
        self.profile = ppl.PROFILES.get(self.profile_id, ppl.PROFILES[ppl.DEFAULT_PROFILE_ID])
        self._ensure_personality_items()

        self.boards = [Board(), Board()]
        self.to_place = self.profile["ships"][:]
        self.placed_index = 0
        self.current_player = 0
        self.cursor = [0, 0]
        self.ghost = {"length": self.to_place[0][1] if self.to_place else 2, "horiz": True}
        self.state = TITLE
        self._settings_index = 0

        # Lazy import UI here, when we’re about to use it
        if self.ui is None:
            from battleship_ui import UI
            self.ui = UI(self.mac, self.profile)
        else:
            self.ui.profile = self.profile

        self.group = self.ui.group
        self.ui.ensure_attached() 
        self.ui._set_game_layers_visible(grid=False, board=False, cursor=False)
        _vis(self.ui)
        self.ui.draw_title()
        self.ui.set_title_mode(self.mode_2p)
        self.ui.leds_title(self.mode_2p)

    # Clean up before returning to menu
    def cleanup(self):
        # Avoid double cleanup
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True

        try:
            # Remove UI group from display to free layers
            if getattr(self, "ui", None) and getattr(self.ui, "group", None):
                try:
                    if self.ui.group in self.mac.display.root_group:
                        self.mac.display.root_group.remove(self.ui.group)
                except Exception:
                    pass

            try:
                spk = getattr(self.mac, "speaker", None)
                if spk is not None:
                    spk.enable = False
            except Exception:
                pass

            # Clear out UI object
            self.ui = None

            # Clear any game/session data that might hold references
            #self.session = None

            # Force garbage collection
            gc.collect()
        except Exception as e:
            debug_print("Cleanup error:", e)
            try:
                gc.collect()
            except Exception:
                pass
            
    # --- SFX helpers (super lightweight, no samples) ---
    def _beep(self, freq, dur=0.08):
        """Play a single beep using MacroPad's speaker."""
        if not self.sfx_enabled:
            return
        try:
            # Preferred: built-in MacroPad helper
            if hasattr(self.mac, "play_tone"):
                self.mac.play_tone(freq, dur)
                return
            # Fallback: direct speaker control
            spk = getattr(self.mac, "speaker", None)
            if spk:
                spk.enable = True
                spk.play_tone(freq, dur)
        except Exception:
            pass  # Ignore sound errors

    def _beep_seq(self, notes, gap=0.02):
        """Play a sequence of (frequency, duration) beeps."""
        if not self.sfx_enabled:
            return
        for freq, dur in notes:
            self._beep(freq, dur)
            try:
                time.sleep(gap)
            except Exception:
                pass
            
    def _ensure_personality_items(self):
        _load_profiles()
        keys = tuple(ppl.PROFILES.keys())
        # Always populate the choices
        self._settings_items[2] = ("Personality", keys)
        # Coerce profile_id to a valid one
        if not keys:
            # Nothing to choose from (shouldn’t happen), keep as-is
            return
        if self.profile_id not in ppl.PROFILES:
            try:
                self.profile_id = ppl.DEFAULT_PROFILE_ID
            except Exception:
                self.profile_id = keys[0]
    
    def tick(self):
        now = time.monotonic()

        # Lazy init tick timers/flags the first time we're called
        if not hasattr(self, "_tick_inited"):
            self._tick_inited = True
            # Cursor blink
            self._cursor_visible = True
            self._blink_period = 0.40  # seconds
            self._next_cursor_toggle = now + self._blink_period
            # Ghost validity refresh (PLACE only)
            self._ghost_refresh_period = 0.20
            self._next_ghost_refresh = now + self._ghost_refresh_period

        # Nothing to do for non-game screens
        if self.state in (TITLE, SETTINGS):
            return
        
        elif self.state == RESULTS:
            # Wait until timer expires, then go back to title
            if time.monotonic() >= self._post_win_until:
                self._enter_title()

        # --- Gameplay screens ---
        if self.state in (PLACE, BATTLE):
            # Blink the cursor overlay (TileGrid show/hide only; no redraw)
            try:
                if getattr(self.ui, "_cursor_tg", None) and now >= self._next_cursor_toggle:
                    self._cursor_visible = not self._cursor_visible
                    self.ui._cursor_tg.hidden = not self._cursor_visible
                    self._next_cursor_toggle = now + self._blink_period
            except Exception:
                pass
                    
            # In tick(), PLACE refresh:
            if self.state == PLACE:
                if now >= self._next_ghost_refresh:
                    try:
                        if self.placed_index < len(self.to_place):
                            _, length = self.to_place[self.placed_index]
                        else:
                            length = 1
                        horiz = self.ghost.get("horiz", True)
                        board = self.boards[self.current_player]
                        cx, cy = self.cursor
                        ok = board.can_place(cx, cy, length, horiz)

                        ghost_state = (cx, cy, horiz, ok)
                        if ghost_state != self._last_ghost_state:
                            self.ui.redraw_ghost(self, ok=ok)
                            self._last_ghost_state = ghost_state
                    except Exception:
                        pass
                    finally:
                        self._next_ghost_refresh = now + self._ghost_refresh_period
                    
            # in Battleship.tick (after computing `now`)
            if self.state == BATTLE:
                try:
                    if getattr(self, "_led_flash_until", 0) and now >= self._led_flash_until:
                        self._led_flash_until = 0
                        self.ui.leds_battle()
                except Exception:
                    pass

    # Encoder rotation while in-game (launcher forwards this)
    def encoderChange(self, pos, last_pos):
        if self.state != SETTINGS:
            return
        delta = pos - (last_pos if last_pos is not None else pos)
        if delta == 0:
            return

        name, values = self._settings_items[self._settings_index]
        if not values:
            return

        current_value = self._get_setting_value(name)
        try:
            idx = values.index(current_value)
        except ValueError:
            idx = 0
            self._apply_setting(name, values[idx])

        idx = (idx + (1 if delta > 0 else -1)) % len(values)
        self._apply_setting(name, values[idx])

        # subtle encoder tick
        self._beep(520, 0.05)

        if hasattr(self.ui, "update_setting_value"):
            self.ui.update_setting_value(self._settings_items, self._settings_index, self)
        else:
            self.ui.draw_settings(self._settings_items, self._settings_index, self)

    # Key handling (launcher sends presses only)
    def button(self, key):
        if self.state == TITLE:
            if key == 9:       # K9: toggle 1P/2P
                self.mode_2p = not self.mode_2p
                self.ui.set_title_mode(self.mode_2p)
                self.ui.leds_title(self.mode_2p)
                self._beep(520, 0.05)  # confirm chirp
            elif key == 10:    # K10: open Settings
                self._beep(520, 0.05)  # menu tick
                self._goto_settings()
            elif key == 11:    # K11: start
                self._beep(520, 0.05)  # menu tick
                self._start_new_game()

        elif self.state == SETTINGS:
            if key == 10:  # back to title
                self._beep(260, 0.05)  # exit cue
                self._enter_title()
            elif key == 11:  # next setting field
                self._beep(520, 0.03)  # next-field tick
                self._next_item()
                if self._settings_items[self._settings_index][0] == "Mode":
                    self.ui.clear()
                self.ui.draw_settings(self._settings_items, self._settings_index, self)
                self.ui.leds_settings()

        elif self.state == PLACE:
            if key in (1, 3, 5, 7):  # move ghost
                dx = 1 if key == 5 else -1 if key == 3 else 0
                dy = 1 if key == 7 else -1 if key == 1 else 0
                self._beep(520, 0.02)  # movement tick
                self.ui.move_cursor(self, dx, dy)
                
                length = self.to_place[self.placed_index][1] if self.placed_index < len(self.to_place) else 1
                horiz = self.ghost.get("horiz", True)
                board = self.boards[self.current_player]
                ok = board.can_place(self.cursor[0], self.cursor[1], length, horiz)
                self.ui.redraw_ghost(self, ok=ok)

            elif key in (0, 2):  # rotate ghost
                self._beep(440, 0.03)  # rotate tick
                self.ui.rotate_ghost(self)
                length = self.to_place[self.placed_index][1] if self.placed_index < len(self.to_place) else 1
                board = self.boards[self.current_player]
                ok = board.can_place(self.cursor[0], self.cursor[1], length, self.ghost.get("horiz", True))
                self.ui.redraw_ghost(self, ok=ok)

            elif key == 4:  # place ship
                _, length = self.to_place[self.placed_index] if self.placed_index < len(self.to_place) else ("", 1)
                x0, y0 = self.cursor
                horiz = self.ghost.get("horiz", True)
                board = self.boards[self.current_player]
                if board.can_place(x0, y0, length, horiz):
                    self._beep(1200, 0.05)  # placement chirp
                    board.place(x0, y0, length, horiz)
                    self.ui.repaint_ship_segment_range(self, self.current_player, x0, y0, length, horiz, show_ships=True)
                    try:
                        self.ui.leds_place()
                    except Exception:
                        pass

                    self.placed_index += 1
                    if self.placed_index < len(self.to_place):
                        self.ghost["length"] = self.to_place[self.placed_index][1]
                        self.ui.redraw_ghost(self, ok=True)
                    else:
                        if self.mode_2p:
                            if self.current_player == 0:
                                self.current_player = 1
                                self.placed_index = 0
                                self.cursor = [0, 0]
                                self.ghost = {"length": self.to_place[0][1], "horiz": True}
                                self._last_ghost_state = None
                                self.ui._set_game_layers_visible(grid=False, board=False, cursor=False)
                                _vis(self.ui)
                                self.ui.next_player_screen(2)
                                self.ui.leds_title()
                                self._beep(880, 0.06)  # handoff cue
                                self._handoff_next = "PLACE"
                                self.state = HANDOFF
                                return
                            else:
                                self._beep_seq([(660,0.05),(880,0.05),(1100,0.1)], gap=0.02)
                                self._begin_battle()
                        else:
                            self._beep_seq([(660,0.05),(880,0.05),(1100,0.1)], gap=0.02)
                            self._begin_battle()
                else:
                    self._beep(220, 0.08)  # invalid placement
                    self.ui.redraw_ghost(self, ok=False)

            if key == 9:
                self._enter_title()
                return

        elif self.state == BATTLE:
            if key in (1, 3, 5, 7):  # move targeting cursor
                dx = 1 if key == 5 else -1 if key == 3 else 0
                dy = 1 if key == 7 else -1 if key == 1 else 0
                self._beep(520, 0.02)  # targeting tick
                self.ui.move_cursor(self, dx, dy)
               

            elif key == 4:  # fire
                shooter = self.current_player
                target  = 1 - shooter
                x, y    = self.cursor

                # Your shot hits the model first
                result = self.boards[target].fire(x, y)
                debug_print("enemy_cell_after_fire:", self.boards[target].grid[y*GRID_W + x])
                debug_print(result, x, y)

                # Make sure layers exist/are visible (cheap, idempotent)
                self.ui._ensure_game_layers()
                self.ui._set_game_layers_visible(grid=True, board=True, cursor=True)
                _vis(self.ui)

                # Paint just the changed cell and push to display immediately
                self.ui.overlay_update_cells(self, [(x, y)])
                debug_print("self.ui.overlay_update_cells board_visible:", not self.ui._board_tg.hidden)
                debug_print("self.ui.overlay_update_cells bmp_center_idx:", self.ui._peek_center_index(x, y))
                debug_print("PAL:", int(self.ui._board_pal[0]), int(self.ui._board_pal[1]),
                            int(self.ui._board_pal[2]), int(self.ui._board_pal[3]))
                debug_print("transparent0?", getattr(self.ui._board_pal, "transparent_index", None))

                # Debug: draw a big white square and flush, then read center
                if DEBUG==True:
                    self.ui._fill_cell(self.ui._board_bmp, 0, 0, 2, filled=True)
                    self.ui._flush()
                    debug_print("center_after_flush:", self.ui._peek_center_index(x, y))  # <-- added here

                # Redraw full overlay (repaints the whole board)
                self.ui.draw_battle_overlay(self)
                if DEBUG==True:
                    debug_print("self.ui.draw_battle_overlay board_visible:", not self.ui._board_tg.hidden)
                    debug_print("self.ui.draw_battle_overlay bmp_center_idx:", self.ui._peek_center_index(x, y))
                    self.ui.debug_visible_ships(self, 0, tag="[BATTLE after AI shot on player]")
                    self.ui.debug_visible_ships(self, 1, tag="[BATTLE after AI shot (enemy check)]")
                
                # Sounds, text prompt, and temporary LED color (may sleep ~0.25s)
                self.ui.on_shot(result, tag=("P1" if shooter == 0 else ("P2" if self.mode_2p else "CPU")))

                # Keep D-pad LEDs hot briefly; tick() will restore after expiry
                self._led_flash_until = max(getattr(self, "_led_flash_until", 0.0),
                                            time.monotonic() + 0.5)

                # Victory after your shot?
                if self.boards[target].all_sunk():
                    self._beep_seq([(660,0.06),(880,0.06),(1175,0.12)], gap=0.03)
                    self.ui.draw_results(winner=(shooter == 0))
                    self.ui.leds_results()
                    self._post_win_until = time.monotonic() + 2.0
                    self.state = RESULTS
                    return

                if self.mode_2p:
                    # Hand off to the other human
                    self.current_player = 1 - self.current_player
                    self.ui.next_player_screen(self.current_player + 1)
                    self._beep(880, 0.06)  # handoff cue
                    self._handoff_next = "BATTLE"
                    self.state = HANDOFF
                    return
                else:
                    # --- 1P: AI replies immediately ---
                    ax, ay = self.ai.pick_shot(self.difficulty)
                    ar     = self.boards[0].fire(ax, ay)
                    debug_print("ally_cell_after_ai:", self.boards[0].grid[ay*GRID_W + ax])
                    debug_print(ar, ax, ay)
                    
                    # Ensure layers (no-op if already set) and paint AI’s cell
                    self.ui._ensure_game_layers()
                    self.ui._set_game_layers_visible(grid=True, board=True, cursor=True)
                    _vis(self.ui)
                    self.ui.overlay_update_cells(self, [(ax, ay)])
                    debug_print("ai self.ui.overlay_update_cells board_visible:", not self.ui._board_tg.hidden)
                    debug_print("ai self.ui.overlay_update_cells bmp_center_idx:", self.ui._peek_center_index(ax, ay))
                    debug_print("PAL:", int(self.ui._board_pal[0]), int(self.ui._board_pal[1]),
                                int(self.ui._board_pal[2]), int(self.ui._board_pal[3]))
                    debug_print("transparent0?", getattr(self.ui._board_pal, "transparent_index", None))

                    # Debug: draw a big white square and flush, then read center
                    if DEBUG==True:
                        self.ui._fill_cell(self.ui._board_bmp, 0, 0, 2, filled=True)
                        self.ui._flush()
                        debug_print("center_after_flush(AI):", self.ui._peek_center_index(ax, ay))

                    # Redraw full overlay
                    self.ui.draw_battle_overlay(self)
                    debug_print("ai self.ui.draw_battle_overlay board_visible:", not self.ui._board_tg.hidden)
                    debug_print("ai self.ui.draw_battle_overlay bmp_center_idx:", self.ui._peek_center_index(ax, ay))

                    # Sounds + message for AI shot
                    if   ar == "hit":    self._beep(750, 0.09)
                    elif ar == "sunk":   self._beep_seq([(600,0.06),(820,0.06),(1050,0.12)], gap=0.02)
                    elif ar == "miss":   self._beep(320, 0.06)
                    elif ar == "repeat": self._beep(240, 0.05)

                    self.ui.on_shot(ar, tag="CPU")

                    # Extend LED flash for AI’s turn
                    self._led_flash_until = max(getattr(self, "_led_flash_until", 0.0),
                                                time.monotonic() + 0.5)

                    # Feed hunt stack
                    if hasattr(self.ai, "feed_result"):
                        try:
                            self.ai.feed_result(ax, ay, ar)
                        except Exception:
                            pass

                    # Did the AI win?
                    if self.boards[0].all_sunk():
                        self._beep_seq([(880,0.06),(660,0.06),(494,0.12)], gap=0.03)
                        self.ui.draw_results(winner=False)
                        self.ui.leds_results()
                        self._post_win_until = time.monotonic() + 2.0
                        self.state = RESULTS
                        return
                    else:
                        self.ui.draw_battle_overlay(self)

            if key == 9:
                self._enter_title()
                return

        elif self.state == HANDOFF:
            if key == 11:
                self.ui.clear()
                if self._handoff_next == "PLACE":
                    self.ui.draw_place(self)
                    self.ui.leds_place()
                    self.state = PLACE
                else:
                    self.ui.draw_battle_overlay(self)
                    self.ui.leds_battle()
                    self.state = BATTLE
            elif key == 9:
                self._enter_title()

        elif self.state == RESULTS:
            if key in (9, 11, 4):
                self._enter_title()

    # ---------------- internal helpers ----------------
    def _enter_title(self):
        gc.collect()
        self.state = TITLE
        self.ui.profile = self.profile  # ensure binding
        self.ui._set_game_layers_visible(grid=False, board=False, cursor=False)
        _vis(self.ui)
        #self.ui.clear()
        self.ui.draw_title()
        self.ui.set_title_mode(self.mode_2p)
        self.ui.leds_title(self.mode_2p)

    def _display_name_for_profile(self, pid):
        _load_profiles()
        try:
            return ppl.get_profile_display(pid)  # if your module provides this
        except AttributeError:
            return getattr(ppl, "PROFILE_DISPLAY", {}).get(pid, pid)

    def _goto_settings(self):
        gc.collect()
        self._settings_index = 0
        self._ensure_personality_items()
        # (Optional) enforce valid profile again, then sync UI profile
        if self.profile_id not in ppl.PROFILES and self._settings_items[2][1]:
            self.profile_id = self._settings_items[2][1][0]

        if self.ui is None:
            from battleship_ui import UI
            self.ui = UI(self.mac, self.profile)
            self.group = self.ui.group
        else:
            self.ui.profile = self.profile

        self.ui.ensure_attached() 

        self.ui._set_game_layers_visible(grid=False, board=False, cursor=False)
        _vis(self.ui)
        self.ui.clear()
        self.ui.draw_settings(self._settings_items, self._settings_index, self)
        self.ui.leds_settings()
        self.state = SETTINGS
        
    def _start_new_game(self):
        gc.collect()
        _load_profiles()

        # Lock in personality for this round
        self.profile = ppl.PROFILES.get(self.profile_id, ppl.PROFILES[ppl.DEFAULT_PROFILE_ID])
        
        # Seed RNG using monotonic time (works on CircuitPython)
        try:
            seed = int(time.monotonic() * 1000000)
        except Exception:
            seed = 123456789
        self.rng = RNG(seed)

        # Fresh AI built only when needed
        self.ai = AI(self.rng)
        self.ai.reset()

        # Lazy-create UI (first run) or just retint existing UI
        if self.ui is None:
            from battleship_ui import UI
            self.ui = UI(self.mac, self.profile)
            self.group = self.ui.group
        else:
            self.ui.profile = self.profile
            self.ui.refresh_palette()  # recolor without reallocating bitmaps
            
        self.ui.ensure_attached() 

        # Fresh boards and placement
        self.boards = [Board(), Board()]
        self.to_place = self.profile["ships"][:]
        self.placed_index = 0
        self.current_player = 0
        self.cursor = [0, 0]
        self.ghost = {"length": (self.to_place[0][1] if self.to_place else 2), "horiz": True}

        # Reset AI & auto-place enemy if 1P
        if not self.mode_2p:
            self.ai.random_place(self.boards[1], self.profile["ships"])
            enemy_ships = sum(1 for v in self.boards[1].grid if v == SHIP)
            debug_print("enemy_ship_cells:", enemy_ships)

        # Draw placement screen
        self.ui.clear()
        self.ui.draw_place(self)
        self.ui.debug_visible_ships(self, self.current_player, tag="[PLACE after draw_place]")
        self.ui.leds_place()
        self.state = PLACE

    def _begin_battle(self):
        p_ships = sum(1 for v in self.boards[0].grid if v == SHIP)
        e_ships = sum(1 for v in self.boards[1].grid if v == SHIP)
        debug_print("ship_cells  player:", p_ships, " enemy:", e_ships)
    
        gc.collect() 
        self.current_player = 0
        self.cursor = [0,0]
        self.ui.clear(); 
        self.ui.draw_battle_overlay(self) 
        self.ui.debug_visible_ships(self, 1, tag="[BATTLE after initial overlay]")
        #self.ui.draw_battle(self)
        self.ui.leds_battle()
        
        # TEMP: force-place a 2-long enemy ship at (0,0)
        if DEBUG==True:
            self.boards[1].place(0, 0, 2, horizontal=True)
            debug_print("forced_ship_at:", (0,0), "and", (1,0))
        
        self.state = BATTLE

    def _next_item(self):
        self._settings_index = (self._settings_index + 1) % len(self._settings_items)

    def _get_setting_value(self, name):
        if name == "Mode": return "2P" if self.mode_2p else "1P"
        if name == "Difficulty": return self.difficulty
        if name == "Personality": return self.profile_id
        if name == "SFX": return "on" if self.sfx_enabled else "off"
        return ""
         
    def _apply_setting(self, name, value):
        if name == "Mode":
            self.mode_2p = (value == "2P")

        elif name == "Difficulty":
            self.difficulty = value

        elif name == "Personality":
            # update IDs and palette
            _load_profiles()
            self.profile_id = value
            self.profile = ppl.PROFILES.get(self.profile_id, ppl.PROFILES[ppl.DEFAULT_PROFILE_ID])
            self.ui.profile = self.profile

            # Rebuild UI layers for the new palette
            # self.ui.refresh_palette()

            # IMPORTANT: while not in gameplay, keep game layers hidden so the grid
            # doesn't flash during Settings/Title redraws.
            if self.state not in (PLACE, BATTLE):
                self.ui._set_game_layers_visible(grid=False, board=False, cursor=False)
                _vis(self.ui)

        elif name == "SFX":
            self.sfx_enabled = (value == "on")
