# code.py — Merlin Fusion Game Launcher
# CircuitPython 9.x / Adafruit MacroPad RP2040 (128×64 mono OLED)
# Originally by Keith Tanner
# Updated and extended by Iain Bennett — 2025
#
# Purpose:
# - Provides the main menu and runtime environment for the Merlin Fusion collection
#   of Merlin-inspired and retro-style games.
# - Dynamically loads each game module on demand to conserve the MacroPad’s limited RAM.
#
# Features:
# - Menu-driven selection of games via the rotary encoder.
# - Lazy-loading and targeted unloading of modules for memory efficiency.
# - RAM usage diagnostics with per-stage and delta reporting.
# - Optional LED “wipe” animation when launching games.
# - Rich construction diagnostics to support multiple game class signatures.
# - Graceful cleanup and reset when returning to menu.
#
# Controls:
# - Encoder rotate → Scroll menu items
# - Encoder press:
#     • In menu: Start selected game
#     • In game: Return to menu (or double-press exit for games like Tempo)
# - Keys 0–11 are forwarded to the active game’s button handlers.
#
# Notes:
# - Uses MerlinChrome.bmp as menu/logo background.
# - Double garbage-collection and display detachment techniques maximize free heap
#   before loading large game modules.
# - Includes robust error handling for construction, imports, and cleanup steps.

print("Merlin Fusion\nLoading\n")
import time
import displayio
import terminalio
import gc, sys
from adafruit_display_text import label
from adafruit_macropad import MacroPad

# ---- Encoder handling ----
ENC_DBL_MS = 600  # encoder double-press window (milliseconds)
last_enc_down_ms = -1
last_menu_idx = 0
menu_anchor_pos = 0
menu_anchor_idx = 0
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
    b_free, b_alloc = before
    a_free, a_alloc = ram_snapshot()
    df = a_free - b_free
    da = a_alloc - b_alloc
    print(f"[RAM Δ] {label} — Δfree: {df} bytes, Δalloc: {da} bytes (now free {a_free}, alloc {a_alloc})")
    return (a_free, a_alloc)

def _aggressive_free_before_import():
    # Only detach/refresh if a group is attached; if already frozen (root_group=None),
    # don't refresh or you'll push a blank frame over the frozen logo.
    try:
        if macropad.display.root_group is not None:
            try:
                macropad.display.root_group = None
            except Exception:
                pass
            try:
                macropad.display.refresh(minimum_frames_per_second=0)
            except Exception:
                try:
                    macropad.display.refresh()
                except Exception:
                    pass
    except Exception:
        pass

    # LEDs off (free pixel buffers if any drivers allocate)
    try:
        macropad.pixels.fill((0, 0, 0))
        macropad.pixels.show()
    except Exception:
        pass

    # Double GC tends to help fragmentation on CP
    gc.collect(); gc.collect()
    
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

def _current_menu_index():
    return (menu_anchor_idx + (macropad.encoder - menu_anchor_pos)) % len(game_names)

# 12-tone palette
tones = (196, 220, 247, 262, 294, 330, 349, 392, 440, 494, 523, 587)

# ---------- Lazy-load registry instead of pre-import factories ----------
GAMES_REG = [
    ("Pac Man",        "pacman",            "pacman",        {}),
    ("Asteroids-Lite", "asteroids_lite",    "asteroids_lite",{}),
    ("Battleship",     "battleship",        "Battleship",    {}),
    ("Beat Trainer",   "beat_trainer",      "beat_trainer",  {}),
    ("Blackjack 13",   "blackjack13",       "blackjack13",   {}),
    ("Echo",           "echo",              "echo",          {}),
    ("Hit or Miss",    "hit_or_miss",       "hit_or_miss",   {}),
    ("Hi/Lo",          "hi_lo",             "hi_lo",         {}),
    ("Horseracing",    "horseracing",       "horseracing",   {}),
    ("Hot Potato",     "hot_potato",        "hot_potato",    {}),
    ("Knights Tour",   "knights_tour",      "knights_tour",  {}),
    ("LED Pinball",    "led_pinball",       "led_pinball",   {}),
    ("Lights Out",     "lights_out",        "lights_out",    {}),
    ("Macro Maze",     "macro_maze",        "maze3d",        {}),
    ("Magic Square",   "magic_square",      "magic_square",  {}),
    ("Match It",       "match_it",          "match_it",      {}),
    ("Merlin Adventure","adventure",        "adventure",     {}),
    ("Merlin Dice",    "merlin_dice",       "merlin_dice",   {}),
    ("Merlin Rogue",   "minirogue",         "minirogue",     {}),
    ("Mindbender",     "mindbender",        "mindbender",    {}),
    ("Mixed Game Bag", "mixed_game_bag",    "mix_bag",       {}),
    ("Music Machine",  "music_machine",     "music_machine", {}),
    ("Musical Ladder", "musical_ladder",    "musical_ladder",{}),
    ("Pair Off",       "pair_off",          "pair_off",      {}),
    ("Patterns",       "patterns",          "patterns",      {}),
    ("Simon",          "simon",             "simon",         {}),
    ("Snake",          "snake",             "snake",         {"snake2": False}),
    ("Slots",          "slot_reels",        "slot_reels",    {}),
    ("Snake II",       "snake",             "snake",         {"snake2": True}),
    ("Spin the Bottle","spin_the_bottle",   "spin_bottle",   {}),
    ("Tempo",          "tempo",             "tempo",         {"tones": tones}),
    ("Three Shells",   "three_shells",      "three_shells",  {}),
    ("Tic Tac Toe",    "tictactoe",         "tictactoe",     {}),
    ("Tower of Hanoi", "hanoi",             "hanoi",         {}),
    ("Whack-A-Mole",   "whack_a_mole",      "whack_a_mole",  {}),
    ("70s Demo Scene", "vector_dreams_bag", "vector_dreams_bag", {}),
    ("80s Demo Scene", "sinclair_demo_bag", "sinclair_demo_bag", {}),
    ("90s Demo Scene", "90s_demoscene",     "demoscene",     {}),
    ("00s Demo Scene", "demoscene_2000s",   "shader_bag",    {}),
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
menu_anchor_pos = macropad.encoder
menu_anchor_idx = 0

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

def _release_menu_assets(detach=False):
    global menu_group, title_lbl, choice_lbl
    if detach:
        try:
            macropad.display.root_group = None
        except Exception:
            pass
    menu_group = None
    title_lbl = None
    choice_lbl = None
    gc.collect()

def _return_to_menu(current_game_ref):
    snap_pre_unload = ram_snapshot()  # existing
    # 0) Failsafe: stop any tone the game left running
    try:
        if hasattr(macropad, "stop_tone"):
            macropad.stop_tone()
    except Exception:
        pass

    # 1) Ask the game to clean up (best effort)
    try:
        if current_game_ref and hasattr(current_game_ref, "cleanup"):
            current_game_ref.cleanup()
    except Exception as e:
        print("cleanup error:", e)
    current_game_ref = None

    # Ensure display resumes normal updates even if a game left it off
    try:
        macropad.display.auto_refresh = True
    except Exception:
        pass
    
    # 2) Launcher-level visual reset (in case game cleanup was incomplete)
    try:
        # LEDs: off + normalize auto_write so menu draws predictably
        try: macropad.pixels.auto_write = True
        except Exception: pass
        macropad.pixels.fill((0, 0, 0))
        try: macropad.pixels.show()
        except Exception: pass
    except Exception:
        pass

    # 3) Detach any leftover game group before we rebuild menu assets
    try:
        macropad.display.root_group = None
    except Exception:
        pass

    # 4) Purge game modules and GC (your existing targeted purge)
    _purge_game_modules()
    gc.collect()

    # 5) Recreate menu UI and show current selection immediately
    _rebuild_menu_assets()
    choice_lbl.text = game_names[last_menu_idx]
    global menu_anchor_pos, menu_anchor_idx 
    global last_encoder_position, enc_exit_armed 
    menu_anchor_pos = macropad.encoder
    menu_anchor_idx = last_menu_idx
    last_encoder_position = macropad.encoder  # <-- re-baseline encoder for the menu loop
    enc_exit_armed = False 
    enter_menu()

    ram_report_delta(snap_pre_unload, "After unloading game & purge")  # existing
    ram_report("Returned to menu")                                     # existing
    return current_game_ref

def _rebuild_menu_assets():
    global menu_group, title_lbl, choice_lbl
    global menu_anchor_pos, menu_anchor_idx
    menu_anchor_pos = macropad.encoder
    menu_anchor_idx = last_menu_idx
    menu_group, title_lbl, choice_lbl = build_menu_group()
    choice_lbl.text = game_names[last_menu_idx]

def _freeze_display_frame():
    try:
        macropad.display.auto_refresh = False
    except Exception:
        pass
    # Push the current frame once
    try:
        macropad.display.refresh(minimum_frames_per_second=0)
    except Exception:
        try:
            macropad.display.refresh()
        except Exception:
            pass
    # Detach the root group so its objects can be GC'd
    try:
        macropad.display.root_group = None
    except Exception:
        pass

# ---- Better diagnostics when constructing a game ----
# ---- Better diagnostics when constructing a game ----
def _construct_with_diagnostics(mod, class_name, macropad, tones, kwargs0):
    """
    Try several constructor signatures for the game's class and print detailed diagnostics
    if construction fails. Returns an instance on success, otherwise raises TypeError with
    the last error and useful module metadata.

    Tries, in order:
      cls(macropad, tones, **kwargs)
      cls(macropad, **kwargs)
      cls(macropad, tones)
      cls(macropad)
      cls()
    """
    # Fallback-friendly imports (CircuitPython may lack full traceback)
    try:
        import traceback as _tb
    except Exception:
        _tb = None
    try:
        import sys as _sys
    except Exception:
        _sys = None

    # Resolve class
    try:
        cls = getattr(mod, class_name)
    except Exception as e:
        mfile = getattr(mod, "__file__", "?")
        raise TypeError("Module '{}' ({}) has no attribute '{}': {}".format(
            getattr(mod, "__name__", "?"), mfile, class_name, e
        ))

    # Prepare attempts
    attempts = [
        ("cls(macropad, tones, **kwargs)",    lambda kw: cls(macropad, tones, **kw)),
        ("cls(macropad, **kwargs)",           lambda kw: cls(macropad, **kw)),
        ("cls(macropad, tones)",              lambda kw: cls(macropad, tones)),
        ("cls(macropad)",                     lambda kw: cls(macropad)),
        ("cls()",                             lambda kw: cls()),
    ]

    last_err = None
    last_desc = None
    kwargs = dict(kwargs0) if kwargs0 else {}

    # Try each signature
    for desc, attempt in attempts:
        try:
            inst = attempt(kwargs)
            print("[ctor] OK with:", desc)
            return inst
        except TypeError as e:
            last_err, last_desc = e, desc
            print("[ctor] TypeError during", desc, "->", e)
            # Print a traceback if available
            if _tb:
                try:
                    _tb.print_exception(e, e, e.__traceback__)
                except Exception:
                    pass
            elif _sys and hasattr(_sys, "print_exception"):
                try:
                    _sys.print_exception(e)
                except Exception:
                    pass
        except MemoryError as e:
            # Memory is special: emit hint and re-raise immediately (heap likely corrupted)
            print("[ctor] MemoryError during", desc, "->", e)
            print("[ctor] Hint: free display root_group, GC twice, and ensure large bitmaps aren't alive.")
            raise
        except Exception as e:
            last_err, last_desc = e, desc
            print("[ctor] Exception during", desc, "->", e)
            if _tb:
                try:
                    _tb.print_exception(e, e, e.__traceback__)
                except Exception:
                    pass
            elif _sys and hasattr(_sys, "print_exception"):
                try:
                    _sys.print_exception(e)
                except Exception:
                    pass

    # If all attempts failed, raise a rich error with module context
    mfile = getattr(mod, "__file__", "?")
    mname = getattr(mod, "__name__", "?")
    # Trim export list to keep message small
    try:
        exports = [n for n in dir(mod) if not n.startswith("_")]
    except Exception:
        exports = []
    exports_str = ", ".join(exports[:32]) + (" ..." if len(exports) > 32 else "")

    raise TypeError(
        "Couldn't construct game '{cn}' from module '{mn}' ({mf}).\n"
        "Last attempt: {desc}\n"
        "Last error: {et}: {em}\n"
        "Module exports: {ex}\n"
        "Tips:\n"
        "  • Check the class __init__ signature and any required parameters.\n"
        "  • Ensure __init__ doesn't touch hardware that isn't ready yet (display root_group, pixels, tones).\n"
        "  • If you rely on module-level constants (e.g., PROMPT_Y1/PROMPT_Y2), make sure they are defined.\n"
        "  • Try constructing the class with fewer arguments to isolate the failure."
        .format(
            cn=class_name,
            mn=mname,
            mf=mfile,
            desc=(last_desc or "?"),
            et=(type(last_err).__name__ if last_err else "?"),
            em=(str(last_err) if last_err else "?"),
            ex=exports_str
        )
    )

# ---------- Menu/Game switching ----------
def enter_menu():
    try: macropad.pixels.auto_write = True
    except AttributeError: pass
    macropad.pixels.brightness = 0.30
    macropad.pixels.fill((50, 0, 0))
    macropad.display.root_group = menu_group
    # nudge the screen once (safe on CP 8/9)
    try:
        macropad.display.refresh(minimum_frames_per_second=0)
    except Exception:
        try: macropad.display.refresh()
        except Exception: pass

def start_game_by_name(name):
    global last_menu_idx 
    snap_before = ram_report(f"Before loading {name}")

    # Update menu UI so it reads "Now Playing" and selected game
    macropad.pixels.fill((0, 0, 0))
    if name not in SKIP_WIPE:
        play_global_wipe(macropad)  # LEDs only — display still shows menu/logo

    # Make the title say "Now Playing:" and the chosen game (already done in your loop)
    # We want that frame visible during load, so freeze it:
    _freeze_display_frame()

    # Now that the pixels are frozen, we can drop the menu objects from RAM
    _release_menu_assets(detach=False)  # we already detached in _freeze_display_frame()

    # Maximize contiguous heap before import/construct/new_game
    _aggressive_free_before_import()
    _purge_game_modules()
    ram_report_delta(snap_before, f"After purge (pre-load {name})")

    # --- (unchanged) find registry / import module ---
    rec_iter = (r for r in GAMES_REG if r[0] == name)
    try:
        rec = next(rec_iter)
    except StopIteration:
        rec = None
    if not rec:
        raise ValueError("Unknown game: " + name)
    _, module_name, class_name, kwargs = rec
    kwargs = dict(kwargs)

    snap_import = ram_snapshot()
    gc.collect()
    try:
        mod = __import__(module_name)
    except MemoryError:
        _aggressive_free_before_import()
        mod = __import__(module_name)
    ram_report_delta(snap_import, f"Imported module {module_name}")
    if module_name == "70s_demoscene":
        print("DEBUG 70s name:", getattr(mod, "__name__", None))
        print("DEBUG 70s file:", getattr(mod, "__file__", None))
        print("DEBUG 70s exports:", [n for n in dir(mod) if not n.startswith("_")])
    if module_name == "vector_dreams_bag":
        print("DEBUG 70s name:", getattr(mod, "__name__", None))
        print("DEBUG 70s file:", getattr(mod, "__file__", None))
        print("DEBUG 70s exports:", [n for n in dir(mod) if not n.startswith("_")])

    # --- construct (with rich diagnostics) ---
    snap_construct = ram_snapshot()
    if module_name == "snake" and "snake2" in kwargs:
        kwargs = {"wraparound": bool(kwargs["snake2"])}
    gc.collect()
    game = _construct_with_diagnostics(mod, class_name, macropad, tones, kwargs)

    ram_report_delta(snap_construct, f"Constructed {class_name}")

    # One more GC right before the game allocates its UI in new_game()
    gc.collect()
    ram_report_delta(snap_before, f"Total delta after loading {name}")

    # Let the game build its UI (bitmaps/labels etc.)
    game.new_game()

    # Hand display back to live updates
    try:
        macropad.display.auto_refresh = True
    except Exception:
        pass
    
    # Attach either the game's group (preferred) or a tiny placeholder
    if hasattr(game, "group") and game.group is not None:
        macropad.display.root_group = game.group
    else:    
        # Fallback placeholder so screen isn’t blank
        ph = displayio.Group()
        
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile = displayio.TileGrid(
                bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            ph.append(tile)
        except Exception:
            pass
        
        title = label.Label(
            terminalio.FONT, text="Now Playing: ", color=0xFFFFFF,
            anchor_point=(0.5, 0.0),
            anchored_position=(macropad.display.width // 2, 31)
        )
        choice = label.Label(
            terminalio.FONT, text=name, color=0xFFFFFF,
            anchor_point=(0.5, 0.0),
            anchored_position=(macropad.display.width // 2, 45)
        )
        ph.append(title)
        ph.append(choice)
        macropad.display.root_group = ph

        
    # Hand off control: re-enable auto_refresh and show the game group
    try:
        macropad.display.auto_refresh = True
    except Exception:
        pass
    if hasattr(game, "group") and game.group is not None:
        macropad.display.root_group = game.group

    return game

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
            #idx = pos % len(game_names)
            #choice_lbl.text = game_names[idx]
            idx = _current_menu_index()
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
            idx = _current_menu_index()
            sel = game_names[idx]
            last_menu_idx = idx
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