# battleship_ui.py — UI helper for Battleship (Adafruit MacroPad) - 2025-08-15
# Light on RAM: lazy Label import, minimal title/settings canvas,
# one-time allocation for 60×60 board layer when needed.

import time
import gc
import displayio, terminalio
import bitmaptools

# Grid constants (must match battleship.py)
GRID_W = 10
GRID_H = 10
CELL   = 6
GRID_PX = CELL * GRID_W
ORIGIN_X = 128 - GRID_PX - 1   # right aligned
ORIGIN_Y = 0

# Cell values (must match battleship.py)
EMPTY = 0
SHIP  = 1
HIT   = 2
MISS  = 3

# UI message pause (used in on_shot)
MSG_PAUSE = 0.1


class UI:
    def __init__(self, mac, profile):
        self.mac = mac
        self.profile = profile
        self.group = displayio.Group()

        # Prompt/label caching
        self._prompt_left_margin = 2
        self._prompt_max_chars = 0
        self._prompt_last_text = None

        # Board/cursor/ghost layers (allocated on demand)
        self._bg_grid = None
        self._board_bmp = None
        self._board_pal = None
        self._board_tg = None
        self._board_index_shown = None

        self._cursor_tg = None
        self._ghost_prev_cells = None

        # Settings/title labels (created by draw_*)
        self._settings_name_lbl = None
        self._settings_val_lbl = None
        self._settings_hint_lbl = None
        self._title_mode_label = None
        self._results_lbl = None
        self._prompt_lbl = None

        # Lazy cache for Label class
        self._Label = None

        # LED cache
        self._init_leds()

    # ---------- LED helpers ----------
    def _init_leds(self):
        self._led_last = [None] * 12
        self._next_led_time = 0.0

    def _set_leds(self, mapping, default=None, throttle_ms=50):
        now = time.monotonic()
        if now < self._next_led_time:
            return
        self._next_led_time = now + (throttle_ms / 1000.0)

        base = self.profile["key_leds"]["idle"] if default is None else default
        px = self.mac.pixels
        changed = False
        for i in range(12):
            want = mapping.get(i, base)
            if self._led_last[i] != want:
                px[i] = want
                self._led_last[i] = want
                changed = True
        if changed:
            try:
                px.show()
            except AttributeError:
                pass

    def leds_title(self, mode_2p=False):
        p = self.profile["palette"]; k = self.profile["key_leds"]
        self._set_leds({9:p["accent"], 10:p["miss"], 11:k["confirm"]}, default=k["idle"])

    def leds_settings(self):
        p = self.profile["palette"]; k = self.profile["key_leds"]
        self._set_leds({10:p["miss"], 11:k["confirm"]}, default=k["idle"])

    def leds_place(self):
        p = self.profile["palette"]; k = self.profile["key_leds"]
        self._set_leds({1:p["cursor"],3:p["cursor"],5:p["cursor"],7:p["cursor"],
                        0:p["accent"],2:p["accent"],4:k["confirm"],9:k["warn"]},
                       default=k["idle"])

    def leds_battle(self):
        p = self.profile["palette"]; k = self.profile["key_leds"]
        self._set_leds({1:p["cursor"],3:p["cursor"],5:p["cursor"],7:p["cursor"],
                        4:k["confirm"],9:k["warn"]},
                       default=k["idle"])

    def leds_results(self):
        k = self.profile["key_leds"]
        self._set_leds({}, default=k["idle"])

    # ---------- Lightweight canvases ----------
    def _get_Label(self):
        if self._Label is None:
            from adafruit_display_text import label as _label
            self._Label = _label.Label
        return self._Label

    def _build_title_layers(self):
        # No 60×60 bitmaps here—only text labels.
        while len(self.group):
            self.group.pop()
        gc.collect()

        Label = self._get_Label()
        p = self.profile["palette"]

        # Shared prompt label we reuse everywhere
        self._prompt_lbl = Label(terminalio.FONT, text="", color=p["text"], scale=1)
        self._prompt_lbl.anchor_point = (0.0, 0.0)
        self._prompt_lbl.anchored_position = (self._prompt_left_margin, 2)
        self.group.append(self._prompt_lbl)

        # Full-width column when the grid is hidden
        try:
            glyph_w = terminalio.FONT.get_bounding_box()[0] or 6
        except Exception:
            glyph_w = 6
        self._prompt_max_chars = max(1, (128 - self._prompt_left_margin) // glyph_w)

        self._prompt_last_text = None

    # ---------- Game layers (allocated once) ----------
    def _build_layers(self):
        # Bail if already built and valid
        # (Callers may rely on rebuild to clear content, so we always rebuild group)
        while len(self.group):
            self.group.pop()
        gc.collect()

        Label = self._get_Label()
        p = self.profile["palette"]

        # Static BG + grid
        static_pal = displayio.Palette(2)
        static_pal[0] = p["bg"]
        static_pal[1] = p["grid"]
        bg = displayio.Bitmap(GRID_PX, GRID_PX, 2)
        # Fill bg
        for y in range(GRID_PX):
            for x in range(GRID_PX):
                bg[x, y] = 0
        # Grid lines
        for i in range(GRID_W + 1):
            x = i * CELL
            for yy in range(GRID_PX):
                if 0 <= x < GRID_PX:
                    bg[x, yy] = 1
        for j in range(GRID_H + 1):
            y = j * CELL
            for xx in range(GRID_PX):
                if 0 <= y < GRID_PX:
                    bg[xx, y] = 1

        self._bg_grid = displayio.TileGrid(bg, pixel_shader=static_pal, x=ORIGIN_X, y=ORIGIN_Y)
        self._bg_grid.hidden = True
        self.group.append(self._bg_grid)

        # Board layer (transparent idx 0)
        self._board_pal = displayio.Palette(4)
        self._board_pal.make_transparent(0)
        self._board_pal[1] = 0xFFFFFF
        self._board_pal[2] = 0xFFFFFF
        self._board_pal[3] = 0xFFFFFF

        self._board_bmp = displayio.Bitmap(GRID_PX, GRID_PX, 4)
        self._clear_bitmap(self._board_bmp, 0)
        self._board_tg = displayio.TileGrid(self._board_bmp, pixel_shader=self._board_pal,
                                            x=ORIGIN_X, y=ORIGIN_Y)
        self._board_tg.hidden = True
        self.group.append(self._board_tg)

        # Cursor outline (transparent bg)
        cur_pal = displayio.Palette(2)
        cur_pal.make_transparent(0)
        cur_pal[1] = p["cursor"]
        cur_bmp = displayio.Bitmap(CELL, CELL, 2)
        for xx in range(CELL):
            cur_bmp[xx, 0] = 1
            cur_bmp[xx, CELL-1] = 1
        for yy in range(CELL):
            cur_bmp[0, yy] = 1
            cur_bmp[CELL-1, yy] = 1
        self._cursor_tg = displayio.TileGrid(cur_bmp, pixel_shader=cur_pal, x=ORIGIN_X, y=ORIGIN_Y)
        self._cursor_tg.hidden = True
        self.group.append(self._cursor_tg)

        # Prompt label (left column)
        self._prompt_lbl = Label(terminalio.FONT, text="", color=p["text"], scale=1)
        self._prompt_lbl.anchor_point = (0.0, 0.0)
        self._prompt_lbl.anchored_position = (self._prompt_left_margin, 2)
        self.group.append(self._prompt_lbl)

        # Compute left column width beside grid
        try:
            glyph_w = terminalio.FONT.get_bounding_box()[0] or 6
        except Exception:
            glyph_w = 6
        col_px = max(0, ORIGIN_X - self._prompt_left_margin)
        self._prompt_max_chars = max(1, col_px // glyph_w)

        gc.collect()

    # Public: used by the game code before drawing gameplay screens
    def clear(self):
        # Rebuild full gameplay layers (grid/board/cursor + prompt)
        self._build_layers()

    # Palette retint without reallocating bitmaps
    def refresh_palette(self):
        p = self.profile["palette"]
        # Build once if never built
        if self._bg_grid is None or self._board_tg is None or self._cursor_tg is None:
            self._build_layers()

        try:
            static_pal = getattr(self._bg_grid, "pixel_shader", None)
            if static_pal:
                static_pal[0] = p["bg"]
                static_pal[1] = p["grid"]
        except Exception:
            pass

        try:
            if self._board_pal is not None:
                self._board_pal[1] = 0xFFFFFF
                self._board_pal[2] = 0xFFFFFF
                self._board_pal[3] = 0xFFFFFF
        except Exception:
            pass

        try:
            cur_pal = getattr(self._cursor_tg, "pixel_shader", None)
            if cur_pal:
                cur_pal[1] = p["cursor"]
        except Exception:
            pass

        # Hide heavy layers; caller will decide what to show
        try:
            if self._bg_grid:   self._bg_grid.hidden   = True
            if self._board_tg:  self._board_tg.hidden  = True
            if self._cursor_tg: self._cursor_tg.hidden = True
        except Exception:
            pass

        gc.collect()

    # ---------- Layer visibility ----------
    def _set_game_layers_visible(self, *, grid, board, cursor):
        if not board and getattr(self, "_ghost_prev_cells", None):
            self._ghost_prev_cells = None
        if self._bg_grid:
            self._bg_grid.hidden = not grid
        if self._board_tg:
            self._board_tg.hidden = not board
        if self._cursor_tg:
            self._cursor_tg.hidden = not cursor

    # ---------- Drawing helpers ----------
    def _clear_bitmap(self, bmp, idx):
        bitmaptools.fill_region(bmp, 0, 0, bmp.width, bmp.height, idx)

    def _fill_cell(self, bmp, gx, gy, color_idx, filled=True):
        px = gx * CELL + 1
        py = gy * CELL + 1
        w = CELL - 2
        h = CELL - 2
        if filled:
            # Fast C-level fill instead of nested loops
            bitmaptools.fill_region(bmp, px, py, px + w, py + h, color_idx)
        else:
            # Borders still need manual draw
            for xx in range(w):
                bmp[px + xx, py] = color_idx
                bmp[px + xx, py + h - 1] = color_idx
            for yy in range(h):
                bmp[px, py + yy] = color_idx
                bmp[px + w - 1, py + yy] = color_idx

    def _draw_x_in_cell(self, bmp, gx, gy, color_idx):
        px = gx * CELL + 1
        py = gy * CELL + 1
        w = CELL - 2
        h = CELL - 2
        d = min(w, h)
        for i in range(d):
            bmp[px + i,     py + i]     = color_idx
            bmp[px + w-1-i, py + i]     = color_idx
        # ensure the exact center is marked (important when w,h are even)
        cx = px + w // 2
        cy = py + h // 2
        bmp[cx, cy] = color_idx

    def _draw_plus_in_cell(self, bmp, gx, gy, color_idx):
        px = gx * CELL + 1
        py = gy * CELL + 1
        w = CELL - 2
        h = CELL - 2
        cx = px + w // 2
        cy = py + h // 2
        for yy in range(py, py + h):
            bmp[cx, yy] = color_idx
        for xx in range(px, px + w):
            bmp[xx, cy] = color_idx

    # ---------- Title / Settings / Results ----------
    def draw_title(self):
        self._build_title_layers()
        Label = self._get_Label()
        p = self.profile["palette"]

        title = Label(terminalio.FONT,
                      text=self.profile.get("title", "Battleship"),
                      color=p["text"], scale=1)
        title.anchor_point = (0.5, 0.0)
        title.anchored_position = (64, 0)
        self.group.append(title)

        sub = Label(terminalio.FONT,
                    text=self.profile.get("subtitle", ""),
                    color=p["accent"], scale=1)
        sub.anchor_point = (0.5, 0.0)
        sub.anchored_position = (64, 18)
        self.group.append(sub)

        h = Label(terminalio.FONT, text="Mode  Set  Start", color=p["text"], scale=1)
        h.anchor_point = (0.5, 1.0)
        h.anchored_position = (64, 63)
        self.group.append(h)

    def set_title_mode(self, mode_2p):
        Label = self._get_Label()
        p = self.profile["palette"]
        if self._title_mode_label and self._title_mode_label in self.group:
            self.group.remove(self._title_mode_label)
        txt = self.profile["strings"]["title_2p"] if mode_2p else self.profile["strings"]["title_1p"]
        self._title_mode_label = Label(terminalio.FONT, text=txt, color=p["text"], scale=1)
        self._title_mode_label.anchor_point = (0.5, 0.0)
        self._title_mode_label.anchored_position = (64, 36)
        self.group.append(self._title_mode_label)

    def draw_settings(self, items, index, session):
        # Keep gameplay layers hidden on settings
        self._set_game_layers_visible(grid=False, board=False, cursor=False)

        # Clear any previous settings labels
        for i in range(len(self.group) - 1, -1, -1):
            node = self.group[i]
            if node in (self._settings_name_lbl, self._settings_val_lbl,
                        self._settings_hint_lbl, self._title_mode_label):
                self.group.pop(i)

        self.set_title_mode(session.mode_2p)

        Label = self._get_Label()
        p = self.profile["palette"]
        name, _vals = items[index]

        self._settings_name_lbl = Label(terminalio.FONT, text=name, color=p["text"], scale=1)
        self._settings_name_lbl.anchor_point = (0.5, 0.0)
        self._settings_name_lbl.anchored_position = (64, 4)
        self.group.append(self._settings_name_lbl)

        val = self._get_val(name, session)
        self._settings_val_lbl = Label(terminalio.FONT, text=str(val), color=p["accent"], scale=1)
        self._settings_val_lbl.anchor_point = (0.5, 0.0)
        self._settings_val_lbl.anchored_position = (64, 21)
        self.group.append(self._settings_val_lbl)

        if self._settings_hint_lbl is None:
            self._settings_hint_lbl = Label(terminalio.FONT, text="Enc  Back  Next", color=p["text"], scale=1)
            self._settings_hint_lbl.anchor_point = (0.5, 1.0)
            self._settings_hint_lbl.anchored_position = (64, 63)
        self.group.append(self._settings_hint_lbl)

    def update_setting_value(self, items, index, session):
        if not self._settings_val_lbl:
            self.draw_settings(items, index, session)
            return
        name, _ = items[index]
        self._settings_val_lbl.text = str(self._get_val(name, session))

    def _get_val(self, name, session):
        if name == "Mode": return "2P" if session.mode_2p else "1P"
        if name == "Difficulty": return session.difficulty
        if name == "Personality":
            if hasattr(session, "_display_name_for_profile"):
                return session._display_name_for_profile(session.profile_id)
            return session.profile_id
        if name == "SFX": return "on" if session.sfx_enabled else "off"
        return ""

    def _flush(self):
        # Mark the bitmap dirty (if supported)
        try:
            if hasattr(self._board_bmp, "dirty"):
                self._board_bmp.dirty()
        except Exception:
            pass

        # Force an immediate refresh
        try:
            disp = getattr(self.mac, "display", None)
            if disp and hasattr(disp, "refresh"):
                try:
                    disp.refresh(minimum_frames_per_second=0)  # <- IMPORTANT
                except TypeError:
                    disp.refresh()
        except Exception:
            pass
        
    def draw_results(self, winner):
        self._set_game_layers_visible(grid=False, board=False, cursor=False)

        if hasattr(self, "_results_lbl") and self._results_lbl in self.group:
            self.group.remove(self._results_lbl)

        Label = self._get_Label()
        p = self.profile.get("palette", {})
        strings = self.profile.get("strings", {})
        msg = strings.get("win" if winner else "lose",
                          "You Win!" if winner else "You Lose!")

        self._results_lbl = Label(terminalio.FONT, text=msg, color=p.get("accent", 0xFFFFFF), scale=1)
        self._results_lbl.anchor_point = (0.5, 0.5)
        self._results_lbl.anchored_position = (64, 28)
        self.group.append(self._results_lbl)

        hint = strings.get("results_hint", "")
        self.draw_prompt(hint)

    def next_player_screen(self, player_num):
        self._set_game_layers_visible(grid=False, board=False, cursor=False)

        while len(self.group):
            self.group.pop()
        gc.collect()

        Label = self._get_Label()
        p = self.profile["palette"]

        lbl = Label(terminalio.FONT, text=f"Player {player_num}, get ready", color=p["text"], scale=1)
        lbl.anchor_point = (0.5, 0.5)
        lbl.anchored_position = (64, 28)
        self.group.append(lbl)

        hint = Label(terminalio.FONT, text="Press Start", color=p["accent"], scale=1)
        hint.anchor_point = (0.5, 1.0)
        hint.anchored_position = (64, 63)
        self.group.append(hint)

    # ---------- Prompt text ----------
    def _wrap_text_local(self, text, width):
        if width <= 1:
            return [text or ""]
        words = (text or "").split(" ")
        lines, line = [], ""
        for w in words:
            if not line:
                while len(w) > width:
                    lines.append(w[:width]); w = w[width:]
                line = w
            else:
                if len(line) + 1 + len(w) <= width:
                    line = line + " " + w
                else:
                    lines.append(line)
                    while len(w) > width:
                        lines.append(w[:width]); w = w[width:]
                    line = w
        lines.append(line)
        return lines

    def draw_prompt(self, text, tag=None):
        # If a tag is provided, render as:
        # P1/P2/CPU:
        # Message
        if tag:
            text = f"{tag}:\n{text}"

        if text == self._prompt_last_text:
            return
        self._prompt_last_text = text

        if self._prompt_max_chars <= 3:
            if self._prompt_lbl:
                self._prompt_lbl.text = text or ""
            return

        if self._prompt_lbl:
            lines = self._wrap_text_local(text or "", self._prompt_max_chars)
            self._prompt_lbl.text = "\n".join(lines)

    def _actor_tag(self, session, who=None, is_cpu=False):
            if is_cpu:
                return "CPU"
            if who is None:
                who = getattr(session, "current_player", 0)
            # In 1P mode, player index 1 is the CPU; only index 0 is human (P1)
            if who == 0:
                return "P1"
            return "P2" if getattr(session, "mode_2p", False) else "CPU"
    
    def on_shot(self, result, tag=None):
        strings = self.profile.get("strings", {})
        key = (str(result).lower() if result is not None else "")
        msg = strings.get(key, {"hit": "Hit!", "miss": "Miss!", "sunk": "Sunk!"}.get(key, str(result)))
        self.draw_prompt(msg, tag=tag)

        p = self.profile.get("palette", {})
        color = p.get(key, None)
        if color is not None:
            self._set_leds({}, default=color)

        time.sleep(MSG_PAUSE)

    # ---------- Placement & Battle drawing ----------
    def _ensure_game_layers(self):
        if self._bg_grid is None or self._board_bmp is None or self._cursor_tg is None:
            self._build_layers()
            
    def ensure_attached(self):
        try:
            disp = getattr(self.mac, "display", None)
            root = getattr(disp, "root_group", None)
            if root is not None and (self.group not in root):
                root.append(self.group)
        except Exception:
            pass

    def draw_place(self, session):
        self._board_index_shown = session.current_player
        self._ensure_game_layers()
        self._set_game_layers_visible(grid=True, board=True, cursor=True)

        for y in range(GRID_H):
            for x in range(GRID_W):
                self.paint_board_cell_from_model(session, session.current_player, x, y, show_ships=True)
        self.redraw_ghost(session, ok=True)
        self.draw_prompt(self.profile["strings"]["place_prompt"],
                 tag=self._actor_tag(session, who=session.current_player))

    def debug_visible_ships(self, session, board_index, tag=""):
        b = session.boards[board_index]
        total = 0
        seen_as_1 = 0  # center pixel shows palette index 1 (ship fill)
        seen_as_2 = 0  # center shows a hit "X" color
        seen_as_3 = 0  # center shows a miss dot
        leak_centers = []  # list of ship cells whose centers are 1 (leak)

        for y in range(GRID_H):
            for x in range(GRID_W):
                v = b.grid[y*GRID_W + x]
                if v == SHIP:
                    total += 1
                    idx = self._peek_center_index(x, y)
                    if idx == 1:
                        seen_as_1 += 1
                        leak_centers.append((x, y))
                    elif idx == 2:
                        seen_as_2 += 1
                    elif idx == 3:
                        seen_as_3 += 1

    def draw_battle_overlay(self, session):
        # Ensure layers exist and are visible
        self._ensure_game_layers()
        self._set_game_layers_visible(grid=True, board=True, cursor=True)

        # Clear the board layer once
        bmp = self._board_bmp
        self._clear_bitmap(bmp, 0)

        # Paint all cells from the model exactly once
        for y in range(GRID_H):
            for x in range(GRID_W):
                self._overlay_paint_cell(session, x, y)

        # Position the cursor sprite (cheap — just moving a TileGrid)
        cx, cy = session.cursor
        self._cursor_tg.x = ORIGIN_X + cx * CELL
        self._cursor_tg.y = ORIGIN_Y + cy * CELL

        # Prompt (avoid churn if unchanged; draw_prompt already caches)
        strings = self.profile.get("strings", {})
        prompt = strings.get("fire_prompt", "")
        if prompt:
            self.draw_prompt(prompt, tag=self._actor_tag(session))  # current player
            time.sleep(MSG_PAUSE)

        # NOTE:
        # - No display.refresh() here; let auto_refresh handle it, or
        #   batch at a higher level if you’ve disabled auto_refresh.
        # - For per-move updates, use overlay_update_cells(session, cells)
        #   with a small list of (x, y) that actually changed.

    def paint_board_cell_from_model(self, session, target_board_index, gx, gy, show_ships, hit_style="enemy"):
        if getattr(self, "_board_index_shown", None) != target_board_index:
            return
        b = session.boards[target_board_index]
        v = b.grid[gy*GRID_W + gx]
        if v == HIT:
            self._fill_cell(self._board_bmp, gx, gy, 0, filled=True)
            if hit_style == "ally":
                self._draw_plus_in_cell(self._board_bmp, gx, gy, 2)
            else:
                self._draw_x_in_cell(self._board_bmp, gx, gy, 2)
        # elif v == MISS:
        #    self._fill_cell(self._board_bmp, gx, gy, 0, filled=True)
        #    self._fill_cell(self._board_bmp, gx, gy, 3, filled=False)
        #    cx = gx * CELL + 1 + (CELL - 2) // 2
        #    cy = gy * CELL + 1 + (CELL - 2) // 2
        #    self._board_bmp[cx, cy] = 3
        elif v == SHIP and show_ships:
            self._fill_cell(self._board_bmp, gx, gy, 1, filled=True)
        else:
            self._fill_cell(self._board_bmp, gx, gy, 0, filled=True)

    def repaint_ship_segment_range(self, session, board_index, gx, gy, length, horiz, show_ships):
        for i in range(length):
            x = gx + (i if horiz else 0)
            y = gy + (0 if horiz else i)
            if 0 <= x < GRID_W and 0 <= y < GRID_H:
                self.paint_board_cell_from_model(session, board_index, x, y, show_ships)
        #self._flush()

    def move_cursor(self, session, dx, dy):
        x, y = session.cursor
        session.cursor = [max(0, min(GRID_W - 1, x + dx)), max(0, min(GRID_H - 1, y + dy))]
        cx, cy = session.cursor
        self._cursor_tg.x = ORIGIN_X + cx * CELL
        self._cursor_tg.y = ORIGIN_Y + cy * CELL

    # ----- Ghost helpers -----
    def _ghost_cells(self, session, length, horiz, gx, gy):
        cells = []
        for i in range(length):
            x = gx + (i if horiz else 0)
            y = gy + (0 if horiz else i)
            if 0 <= x < GRID_W and 0 <= y < GRID_H:
                cells.append((x, y))
        return cells

    def _restore_prev_ghost_cells(self, session):
        if not self._ghost_prev_cells:
            return
        for (x, y) in self._ghost_prev_cells:
            self.paint_board_cell_from_model(session, session.current_player, x, y, show_ships=True)
        self._ghost_prev_cells = None

    def redraw_ghost(self, session, ok=True):
        if session.placed_index >= len(session.to_place):
            self._restore_prev_ghost_cells(session)
            return
        length = session.ghost.get("length", session.to_place[session.placed_index][1])
        horiz = session.ghost.get("horiz", True)
        gx, gy = session.cursor

        self._restore_prev_ghost_cells(session)

        cells = self._ghost_cells(session, length, horiz, gx, gy)
        idx = 1 if ok else 3
        for (x, y) in cells:
            self._fill_cell(self._board_bmp, x, y, idx, filled=False)

        self._ghost_prev_cells = cells
        #self._flush()

    def rotate_ghost(self, session):
        try:
            if session.placed_index >= len(session.to_place):
                return
        except Exception:
            return
        session.ghost['horiz'] = not session.ghost.get('horiz', True)
        self.redraw_ghost(session)

    # ----- Battle overlay cell painter -----
    def _overlay_paint_cell(self, session, x, y):
        bmp = self._board_bmp
        self._fill_cell(bmp, x, y, 0, filled=True)

        cell_enemy  = session.boards[1].grid[y*GRID_W + x]
        cell_player = session.boards[0].grid[y*GRID_W + x]

        if cell_enemy == HIT:
            self._draw_x_in_cell(bmp, x, y, 2)
        #elif cell_enemy == MISS:
        #    self._fill_cell(bmp, x, y, 3, filled=False)
        #    cx = x * CELL + 1 + (CELL - 2) // 2
        #    cy = y * CELL + 1 + (CELL - 2) // 2
        #    bmp[cx, cy] = 3

        if cell_player == HIT:
            self._draw_plus_in_cell(bmp, x, y, 2)
        #elif cell_player == MISS:
        #    self._fill_cell(bmp, x, y, 3, filled=False)

    def overlay_update_cells(self, session, cells):
        for (x, y) in cells:
            if 0 <= x < GRID_W and 0 <= y < GRID_H:
                self._overlay_paint_cell(session, x, y)
        #self._flush()
        
    def _peek_center_index(self, gx, gy):
        px = gx * CELL + 1 + (CELL - 2) // 2
        py = gy * CELL + 1 + (CELL - 2) // 2
        return int(self._board_bmp[px, py])