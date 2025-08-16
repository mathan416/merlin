# -----------------------------------------------------------------------------
# Battleship Configuration Module
# -----------------------------------------------------------------------------
# This file centralizes all configurable options, constants, and debug toggles
# for the Battleship game. It is imported by battleship.py, battleship_ui.py,
# and other modules so that global settings can be maintained in one place.
#
# Purpose:
#   - Keep global values consistent across files
#   - Provide a single switch for debugging output
#   - Define reusable helpers (e.g., debug_print)
#
# Typical Contents:
#   DEBUG
#     Boolean flag (True/False) that controls whether debug_print()
#     statements in the game output diagnostic information.
#
#   debug_print(*args, **kwargs)
#     A wrapper around print() that only outputs text if DEBUG is True.
#     Useful for logging without cluttering normal gameplay.
#
#   Global constants (optional)
#     You can define any additional global values here that multiple
#     modules need to share (e.g., screen dimensions, color defaults,
#     or gameplay tweaks).
#
# Usage:
#   In other modules:
#       import battleship_config
#
#   Then reference values:
#       if battleship_config.DEBUG:
#           battleship_config.debug_print("Debugging enabled")
#
# Benefits:
#   - Avoids circular imports (everything reads from this one place)
#   - Easier to toggle debugging or tweak shared values
#   - Keeps battleship.py and battleship_ui.py focused on gameplay/UI
# -----------------------------------------------------------------------------

DEBUG = False
REQUIRED_PALETTE = {"bg","grid","cursor","ally","enemy","hit","miss","sunk","text","accent"}
REQUIRED_STRINGS = {"place_prompt","fire_prompt","hit","miss","sunk","you_win","you_lose",
                    "p1_turn","p2_turn","title_1p","title_2p","repeat"}
REQUIRED_KEYLEDS = {"idle","confirm","warn", "rotate"}

def debug_print(*args, **kwargs):
    """Print only if DEBUG is enabled."""
    if DEBUG == True:
        print(*args, **kwargs)
        
def _vis(ui):
    bg   = getattr(ui, "_bg_grid", None)
    brd  = getattr(ui, "_board_tg", None)
    cur  = getattr(ui, "_cursor_tg", None)
    debug_print("VIS grid:",   (bg  is not None and (not bg.hidden)),
        "board:",      (brd is not None and (not brd.hidden)),
        "cursor:",     (cur is not None and (not cur.hidden)))
        
def _is_ascii(s):
    try:
        s.encode("ascii")
        return True
    except Exception:
        return False

def validate_profiles(profiles=None):
    """
    Validate all loaded personality profiles for required keys, types, and formats.
    If profiles is None, loads battleship_personalities.PROFILES automatically.

    Reports issues via print() (only shown when DEBUG is True if called that way).
    Does not raise exceptions unless something is badly malformed.
    """
    if profiles is None:
        try:
            import battleship_personalities as _ppl
            profiles = _ppl.PROFILES
        except Exception as e:
            print("validate_profiles: could not import personalities:", e)
            return

    for pid, prof in profiles.items():
        print(f"Validating profile: {pid}")

        # --- Required high-level keys ---
        for key in ("id", "title", "subtitle", "palette", "ships", "strings", "key_leds"):
            if key not in prof:
                print(f"  [MISSING] {pid}: missing key '{key}'")

        # --- Palette checks ---
        pal = prof.get("palette", {})
        for req in REQUIRED_PALETTE:
            if req not in pal:
                print(f"  [MISSING] {pid}.palette['{req}']")
            elif not isinstance(pal[req], int):
                print(f"  [TYPE] {pid}.palette['{req}'] should be int (0xRRGGBB), got {type(pal[req])}")

        # --- Strings checks ---
        strs = prof.get("strings", {})
        for req in REQUIRED_STRINGS:
            if req not in strs:
                print(f"  [MISSING] {pid}.strings['{req}']")
            elif not isinstance(strs[req], str):
                print(f"  [TYPE] {pid}.strings['{req}'] should be str, got {type(strs[req])}")
            else:
                # Check for only ASCII (keeps OLED safe)
                if not _is_ascii(strs[req]):
                    print(f"  [WARN] {pid}.strings['{req}'] has non-ASCII chars")

        # --- Key LED checks ---
        leds = prof.get("key_leds", {})
        for req in REQUIRED_KEYLEDS:
            if req not in leds:
                print(f"  [MISSING] {pid}.key_leds['{req}']")
            elif not isinstance(leds[req], int):
                print(f"  [TYPE] {pid}.key_leds['{req}'] should be int (0xRRGGBB), got {type(leds[req])}")

        # --- Ship checks ---
        ships = prof.get("ships", [])
        if not isinstance(ships, list) or len(ships) != 5:
            print(f"  [ERROR] {pid}.ships must be a list of 5 tuples, got {ships}")
        else:
            for ship in ships:
                if not (isinstance(ship, tuple) and len(ship) == 2):
                    print(f"  [ERROR] {pid}.ships entry {ship} must be tuple (name, length)")
                elif not isinstance(ship[0], str) or not isinstance(ship[1], int):
                    print(f"  [TYPE] {pid}.ships entry {ship} has wrong types")

    print("validate_profiles: finished.")