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
        