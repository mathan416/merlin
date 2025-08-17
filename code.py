# code.py — Merlin Emulator Game Launcher for Adafruit MacroPad (CircuitPython 9.x)
#
# This script runs on an Adafruit MacroPad to provide a menu and runtime
# environment for a collection of Merlin-inspired games. Games are stored as
# separate Python modules and are loaded dynamically to conserve RAM.
#
# Key Features:
#   • Menu-driven selection of games via the MacroPad rotary encoder.
#   • Lazy-loading of game modules with targeted unloading to free memory.
#   • RAM usage monitoring with per-stage and delta reporting for debugging.
#   • Optional LED “wipe” animation when starting most games.
#   • Robust import and construction logic to support varying game class signatures.
#   • Graceful cleanup when returning to the menu from a game.
#
# Controls:
#   • Rotate encoder to scroll through menu items.
#   • Press encoder to start the selected game.
#   • Press encoder during a game to return to the menu (most games).
#   • Tempo opts into a double-press to exit using the encoder.
#   • Keys 0–11 are passed to the active game’s button handlers.
#
# Originally by Keith Tanner
# Updated and extended by Iain Bennett

print("Loading Merlin")
import time
import displayio
import terminalio
import gc, sys
from adafruit_display_text import label
from adafruit_macropad import MacroPad

# ---- Encoder handling ----
ENC_DBL_MS = 600  # encoder double-press window (milliseconds)
last_enc_down_ms = -1
enc_exit_armed = False

# ---- RAM debug helpers ----
def ram_snapshot():
    gc.collect()
    return (gc.mem_free(), gc.mem_alloc())

def ram_report(label=""):
    free, alloc = ram_snapshot()
    print(f"[RAM] {label} — free: {free} bytes, allocated: {alloc} bytes, total: {free+alloc} bytes")
    return (free, alloc)

def ram_report_delta(before, label=""):
    """Print the delta vs a prior snapshot tuple returned by ram_snapshot()/ram_report()."""
    b_free, b_alloc = before
    a_free, a_alloc = ram_snapshot()
    df = a_free - b_free
    da = a_alloc - b_alloc
    print(f"[RAM Δ] {label} — Δfree: {df} bytes, Δalloc: {da} bytes (now free {a_free}, alloc {a_alloc})")
    return (a_free, a_alloc)

# ---- Input flush helper ----
ram_report("Boot start")

def flush_inputs():
    # Drain all pending key events
    while True:
        e = macropad.keys.events.get()
        if not e:
            break
    # Update encoder debouncer so its state is fresh
    try:
        macropad.encoder_switch_debounced.update()
    except Exception:
        pass

# ---------- Setup hardware ----------
macropad = MacroPad()
macropad.pixels.fill((50, 0, 0))  # clear pads

# 12-tone palette
tones = (196, 220, 247, 262, 294, 330, 349, 392, 440, 494, 523, 587)

# ---------- Lazy-load registry instead of pre-import factories ----------
GAMES_REG = [
    ("Battleship",     "battleship",    "Battleship",    {}),
    ("Blackjack 13",   "blackjack13",   "blackjack13",   {}),
    ("Echo",           "echo",          "echo",          {}),
    ("Hit or Miss",    "hit_or_miss",   "hit_or_miss",   {}),
    ("Hi/Lo",          "hi_lo",         "hi_lo",         {}),
    ("Hot Potato",     "hot_potato",    "hot_potato",    {}),
    ("Macro Maze",     "macro_maze",    "maze3d",        {}),
    ("Magic Square",   "magic_square",  "magic_square",  {}),
    ("Match it",       "match_it",      "match_it",      {}),
    ("Mindbender",     "mindbender",    "mindbender",    {}),
    ("Mixed Game Bag", "mixed_game_bag","mix_bag",       {}),
    ("Music Machine",  "music_machine", "music_machine", {}),
    ("Musical Ladder", "musical_ladder","musical_ladder",{}),
    ("Pair Off",       "pair_off",      "pair_off",      {}),
    ("Patterns",       "patterns",      "patterns",      {}),
    ("Simon",          "simon",         "simon",         {}),
    ("80s Demo Scene", "sinclair_demo_bag", "sinclair_demo_bag", {}),
    ("Snake",          "snake",         "snake",         {"snake2": False}),
    ("Snake II",       "snake",         "snake",         {"snake2": True}),
    ("Tempo",          "tempo",         "tempo",         {"tones": tones}),
    ("Three Shells",   "three_shells",  "three_shells",  {}),
    ("Tic Tac Toe",    "tictactoe",     "tictactoe",     {}),
    ("80s Demo Scene", "sinclair_demo_bag", "sinclair_demo_bag", {}),
    ("90s Demo Scene", "90s_demoscene",     "demoscene",     {}),
]
game_names = [n for (n, _, _, _) in GAMES_REG]

SKIP_WIPE = {"Echo"}

# ---------- Menu UI ----------
def build_menu_group():
    group = displayio.Group()
    try:
        bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
        tile = displayio.TileGrid(
            bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
        )
        group.append(tile)
    except Exception:
        pass

    title = label.Label(
        terminalio.FONT, text="Choose your game:", color=0xFFFFFF,
        anchor_point=(0.5, 0.0),
        anchored_position=(macropad.display.width // 2, 31)
    )
    choice = label.Label(
        terminalio.FONT, text=" " * 20, color=0xFFFFFF,
        anchor_point=(0.5, 0.0),
        anchored_position=(macropad.display.width // 2, 45)
    )
    group.append(title)
    group.append(choice)
    return group, title, choice

menu_group, title_lbl, choice_lbl = build_menu_group()
macropad.display.root_group = menu_group
choice_lbl.text = game_names[0]

# ---------- Memory helpers ----------
def _purge_game_modules():
    # New targeted purge: remove only our game modules
    game_modnames = {mod for (_, mod, _, _) in GAMES_REG}
    todel = [m for m in list(sys.modules) if m in game_modnames]

    for m in todel:
        try:
            del sys.modules[m]
        except Exception:
            pass
    gc.collect()
    ram_report("After purge")

def _release_menu_assets():
    global menu_group, title_lbl, choice_lbl
    try:
        macropad.display.root_group = None
    except Exception:
        pass
    # Drop strong refs so GC can reclaim label glyph bitmaps, etc.
    menu_group = None
    title_lbl = None
    choice_lbl = None
    gc.collect()

def _rebuild_menu_assets():
    global menu_group, title_lbl, choice_lbl
    menu_group, title_lbl, choice_lbl = build_menu_group()
    # NEW: reflect current selection immediately
    idx = macropad.encoder % len(game_names)
    choice_lbl.text = game_names[idx]

# ---------- Menu/Game switching ----------
def enter_menu():
    try: macropad.pixels.auto_write = True
    except AttributeError: pass
    macropad.pixels.brightness = 0.30
    macropad.pixels.fill((50, 0, 0))
    macropad.display.root_group = menu_group

def start_game_by_name(name):
    # BEFORE LOADING snapshot
    snap_before = ram_report(f"Before loading {name}")  # NEW

    macropad.pixels.fill((0, 0, 0))
    if name not in SKIP_WIPE:
        play_global_wipe(macropad)

    # Purge previously loaded game modules
    _purge_game_modules()
    ram_report_delta(snap_before, f"After purge (pre-load {name})")  # NEW

    # Lazy import + instantiate
    rec_iter = (r for r in GAMES_REG if r[0] == name)
    try:
        rec = next(rec_iter)
    except StopIteration:
        rec = None

    if not rec:
        raise ValueError("Unknown game: " + name)
    _, module_name, class_name, kwargs = rec
    kwargs = dict(kwargs)

    snap_import = ram_snapshot()  # NEW

    _release_menu_assets()
    _purge_game_modules()
    gc.collect()

    try:
        mod = __import__(module_name)
    except Exception as e:
        raise ImportError("Failed to import module '{}': {}".format(module_name, e))
    try:
        cls = getattr(mod, class_name)
    except AttributeError as e:
        raise ImportError(f"Module '{module_name}' has no class '{class_name}'") from e
    ram_report_delta(snap_import, f"Imported module {module_name}")  # NEW

    snap_construct = ram_snapshot()  # NEW

    # --- BEGIN: KWARG ADAPTERS FOR SPECIAL CASES ---
    # Snake expects 'wraparound', but our registry uses 'snake2'
    if module_name == "snake" and "snake2" in kwargs:
        kwargs = {"wraparound": bool(kwargs["snake2"])}
    # --- END: KWARG ADAPTERS ---

    # Robust constructor: try common signatures in order.
    game = None
    ctor_err = None
    for attempt in (
        lambda: cls(macropad, tones, **kwargs),  # preferred (most games)
        lambda: cls(macropad, **kwargs),         # some games only take macropad + kwargs
        lambda: cls(macropad, tones),            # legacy two-arg
        lambda: cls(macropad),                   # oldest style: only macropad
    ):
        try:
            game = attempt()
            ctor_err = None
            break
        except TypeError as e:
            ctor_err = e
        except Exception as e:
            ctor_err = e

    if game is None:
        raise TypeError(
            "Couldn't construct game "
            + class_name
            + " with any known signature. Last error: "
            + str(ctor_err)
        )

    ram_report_delta(snap_construct, f"Constructed {class_name}")  # NEW

    gc.collect()
    ram_report_delta(snap_before, f"Total delta after loading {name}")  # NEW

    game.new_game()

    if hasattr(game, "group") and game.group is not None:
        macropad.display.root_group = game.group

    return game

def _return_to_menu(current_game_ref):
    """Shared path to cleanly unload the current game and return to the menu."""
    snap_pre_unload = ram_snapshot()  # NEW

    try:
        if current_game_ref and hasattr(current_game_ref, "cleanup"):
            current_game_ref.cleanup()
    except Exception as e:
        print("cleanup error:", e)
    current_game_ref = None

    _purge_game_modules()

    gc.collect()
    _rebuild_menu_assets()
    # Ensure last selection is visible right away
    idx = macropad.encoder % len(game_names)
    choice_lbl.text = game_names[idx]
    enter_menu()
    ram_report_delta(snap_pre_unload, "After unloading game & purge")  # NEW
    ram_report("Returned to menu")

    return current_game_ref

# ---------- Wipe ----------
def play_global_wipe(mac):
    snap_wipe = ram_snapshot()
    try: old_auto = mac.pixels.auto_write
    except AttributeError: old_auto = True
    try: mac.pixels.auto_write = False
    except AttributeError: pass
    mac.pixels.brightness = 0.30
    wipe_colors = [
        0xF400FD, 0xDE04EE, 0xC808DE, 0xB20CCF, 0x9C10C0, 0x8614B0,
        0x6F19A1, 0x591D91, 0x432182, 0x2D2573, 0x172963, 0x012D54
    ]
    for x in range(12):
        mac.pixels[x] = 0x000099
        try: mac.pixels.show()
        except AttributeError: pass
        time.sleep(0.06)
        mac.pixels[x] = wipe_colors[x]
        try: mac.pixels.show()
        except AttributeError: pass
    for s in (0.4, 0.2, 0.1, 0.0):
        for i in range(12):
            c = wipe_colors[i]
            r = int(((c >> 16) & 0xFF) * s)
            g = int(((c >> 8)  & 0xFF) * s)
            b = int((c & 0xFF) * s)
            mac.pixels[i] = (r << 16) | (g << 8) | b
        try: mac.pixels.show()
        except AttributeError: pass
        time.sleep(0.02)
    mac.pixels.fill((0, 0, 0))
    try: mac.pixels.show()
    except AttributeError: pass
    try: mac.pixels.auto_write = old_auto
    except AttributeError: pass
    ram_report_delta(snap_wipe, "Global wipe")

# ---------- Main loop ----------
mode_menu = True
last_encoder_position = macropad.encoder
last_encoder_switch = False
current_game = None

ram_report("After setup complete")

while True:
    pos = macropad.encoder
    if pos != last_encoder_position:
        if mode_menu:
            idx = pos % len(game_names)
            choice_lbl.text = game_names[idx]
        else:
            if current_game and hasattr(current_game, "encoderChange"):
                try:
                    current_game.encoderChange(pos, last_encoder_position)
                except Exception as e:
                    print("encoderChange error:", e)
        last_encoder_position = pos

    macropad.encoder_switch_debounced.update()
    enc_pressed = macropad.encoder_switch_debounced.pressed
    now_ms = int(time.monotonic() * 1000)  # milliseconds to match ENC_DBL_MS
    if enc_pressed != last_encoder_switch:
        last_encoder_switch = enc_pressed

        if mode_menu and enc_pressed:
            mode_menu = False
            title_lbl.text = "Now Playing:"
            sel = game_names[macropad.encoder % len(game_names)]
            current_game = start_game_by_name(sel)
            flush_inputs()
        elif not mode_menu:
            # Forward encoder button state to the current game if it wants it
            if current_game and hasattr(current_game, "encoder_button"):
                try:
                    current_game.encoder_button(enc_pressed)
                except Exception as e:
                    print("encoder_button error:", e)

            # Tempo (or any game that opts in) can use double-press to exit
            if enc_pressed:
                if getattr(current_game, "supports_double_encoder_exit", False):
                    if enc_exit_armed and (now_ms - last_enc_down_ms) <= ENC_DBL_MS:
                        # Second press within window -> exit to menu
                        current_game = _return_to_menu(current_game)
                        mode_menu = True
                        #title_lbl.text = "Choose your game:"
                        #enter_menu()
                        flush_inputs()
                        enc_exit_armed = False
                    else:
                        enc_exit_armed = True
                        last_enc_down_ms = now_ms
                        if hasattr(current_game, "on_exit_hint"):
                            try:
                                current_game.on_exit_hint()
                            except Exception as e:
                                print("on_exit_hint error:", e)
                else:
                    # Default behavior for games that don't opt-in: single press exits
                    current_game = _return_to_menu(current_game)
                    mode_menu = True
                    title_lbl.text = "Choose your game:"
                    enter_menu()
                    flush_inputs()

    # Disarm the armed single press after timeout (Tempo only)
    if (not mode_menu
        and current_game
        and getattr(current_game, "supports_double_encoder_exit", False)
        and enc_exit_armed
        and (now_ms - last_enc_down_ms) > ENC_DBL_MS):
        enc_exit_armed = False
        if hasattr(current_game, "on_exit_hint_clear"):
            try:
                current_game.on_exit_hint_clear()
            except Exception as e:
                print("on_exit_hint_clear error:", e)

    if mode_menu:
        time.sleep(0.01)
        continue

    if current_game and hasattr(current_game, "tick"):
        try:
            current_game.tick()
        except Exception as e:
            print("tick error:", e)

    evt = macropad.keys.events.get()
    if evt:
        key = evt.key_number
        if key < 12 and current_game:
            try:
                if evt.pressed:
                    current_game.button(key)
                else:
                    if hasattr(current_game, "button_up"):
                        current_game.button_up(key)
            except Exception as e:
                print("button error:", e)
                