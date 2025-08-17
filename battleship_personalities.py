# battleship_personalities.py — Battleship “personality packs” for Adafruit MacroPad
# -----------------------------------------------------------------------------------
# Defines color palettes, UI themes, and sound/personality profiles for the Battleship game.
# A "personality" describes only the presentation layer (colors, labels, sound cues) and 
# does not affect game rules or mechanics.
#
# License:
#   Released under the CC0 1.0 Universal (Public Domain Dedication).
#   You can copy, modify, distribute, and perform the work, even for commercial purposes,
#   all without asking permission. Attribution is appreciated but not required.
#
# Contents:
# - Shared RGB color constants.
# - Multiple theme dictionaries with unique IDs, titles, subtitles, and palette mappings.
# - Palette entries define background, grid, cursor, ally ships, enemy waters, and hit/miss colors.
#
# -----------------------------------------------------------------------------
# Creating Your Own Personality
# -----------------------------------------------------------------------------
# A personality defines the look, feel, and theming of the game — including
# colors, ship names, prompts, and key lighting. Follow these steps to create
# your own.
#
# 1. Choose a unique ID:
#      This is used internally to reference your personality.
#      Example:
#        "id": "retro_terminal"
#
# 2. Pick a title and subtitle:
#      These appear on the title screen when the personality is selected.
#      Example:
#        "title": "RETRO TERMINAL",
#        "subtitle": "Classic green phosphor"
#
# 3. Define a color palette dictionary:
#      All colors are RGB hex values (0xRRGGBB).
#      Required keys:
#        "bg"     — Background color for the board area
#        "grid"   — Grid line color - Recommed WHITE/0xFFFFFF
#        "cursor" — Cursor highlight color
#        "ally"   — Color of your ships
#        "enemy"  — Fog of war / unknown cells
#        "hit"    — Successful hit indicator
#        "miss"   — Missed shot indicator
#        "text"   — Text color (always use WHITE for readability) - Recommed WHITE/0xFFFFFF
#        "accent" — Accent color for emphasis or hints
#        "sunk"   — Sunk ship indicators
#
# 4. Define your ships:
#      Provide exactly 5 tuples: (Ship Name, Length in cells)
#      You can theme these to your liking. Example using Canadian naval vessels:
#        ("HMCS Bonaventure", 5),  # Aircraft carrier (Majestic-class; 1957–1970)
#        ("HMCS Ontario",     4),  # Light cruiser (Minotaur-class; WWII era)
#        ("HMCS Halifax",     3),  # Halifax-class frigate (modern)
#        ("HMCS Victoria",    3),  # Victoria-class submarine (modern)
#        ("HMCS Algonquin",   2)   # Iroquois-class destroyer (modern)
#
# 5. Define the strings dictionary:
#      These are prompts and messages used in-game. Keep them short so they fit
#      on screen. Example:
#        "place_prompt": "DEPLOY FLEET",
#        "fire_prompt":  "TARGET LOCK",
#        "hit":          "TARGET DESTROYED",
#        "miss":         "NO CONTACT",
#        "sunk":         "VESSEL SUNK",
#        "you_win":      "MISSION COMPLETE",
#        "you_lose":     "MISSION FAILED",
#        "p1_turn":      "P1 READY",
#        "p2_turn":      "P2 READY",
#        "title_1p":     "SOLO VS. AI",
#        "title_2p":     "2 PLAYERS: HOTSEAT",
#        "repeat":       "DUPLICATE COORDINATES"
#
# 6. Define key_leds:
#      Controls the MacroPad key backlight colors for different states:
#        "idle"    — Default idle glow
#        "confirm" — Placement or confirmation action
#        "warn"    — Warnings or invalid actions
#        "rotate"  — Ship rotation mode (optional)
#      Example:
#        "key_leds": {
#            "idle":    0x003300,  # deep green
#            "confirm": 0x00FF00,  # bright green
#            "warn":    0xFF0000,  # red
#            "rotate":  0x00FF55   # lighter green
#        }
#
# 7. Add your personality as a dictionary in this file:
#      Example:
#        RETRO_TERMINAL = { ... }
#
# 8. Register it in the PROFILES dictionary:
#      PROFILES["retro_terminal"] = RETRO_TERMINAL
#
# 9. Test in-game:
#      Launch the game, go to Settings, and select your new personality.
#
# -----------------------------------------------------------------------------
#
# Date: 2025-08-15
# Author: Iain Bennett (adapted for MacroPad Battleship)

# Shared color helpers (RGB hex)
WHITE       = 0xFFFFFF; 
BLACK       = 0x000000
RED         = 0xDD3344; 
GREEN       = 0x3CCB5A; 
BLUE        = 0x3399FF; 
GOLD        = 0xD4AF37; 
TEAL        = 0x1BB6A9; 
GRAY        = 0x404040
ORANGE      = 0xFF8800
YELLOW      = 0xFFD300
PURPLE      = 0x8A2BE2
PINK        = 0xFF69B4
BROWN       = 0x8B4513
CYAN        = 0x00FFFF
LIME        = 0xBFFF00
MAGENTA     = 0xFF00FF
DEEP_BLUE   = 0x0000FF
DEEP_RED    = 0xFF0000
DEEP_GREEN  = 0x00FF00


# A personality describes the *presentation*, not the rules.
BRIT_PIRATE = {
    "id": "brit_pirate",
    "title": "BROADSIDE BRIGANDS",
    "subtitle": "A bit o' piracy",
    "palette": {
        "bg": 0x0A0D14,
        "grid": WHITE,
        "cursor": GREEN,
        "ally": BLUE,
        "enemy": GRAY,
        "hit": RED,
        "miss": DEEP_BLUE,
        "sunk": DEEP_RED,
        "text": WHITE,
        "accent": GOLD,
    },
    "ships": [
        ("Flagship 'Sovereign'", 5),
        ("Man-o'-War", 4),
        ("Frigate", 3),
        ("Brig", 3),
        ("Sloop", 2),
    ],
    "strings": {
        "place_prompt": "Lay yer fleet, Captain.",
        "fire_prompt":  "Call yer shot!",
        "hit":          "BULLSEYE! Shiver 'em!",
        "miss":         "All water. Again.",
        "sunk":         "Down she goes!",
        "you_win":      "Victory! Raise\nthe colors!",
        "you_lose":     "Cursed luck!\nStrike 'em...",
        "p1_turn":      "Captain,\nyour mark.",
        "p2_turn":      "Captain,\nhave at 'em.",
        "title_1p":     "1 Player vs. Navy",
        "title_2p":     "2 Players: Hotseat",
        "repeat":       "Duplicate shot!"
    },
    "key_leds": {
        "idle": 0x061018,
        "confirm": DEEP_RED,
        "warn": RED,
        "rotate": DEEP_BLUE
    }
}

WW2_NAVAL = {
    "id": "ww2_naval",
    "title": "BATTLELINE",
    "subtitle": "Naval Operations",
    "palette": {
        "bg": 0x00060A, "grid": WHITE, "cursor": DEEP_GREEN,
        "ally": 0x3F78C5, "enemy": 0x243347, "hit": 0xF25C54,
        "miss": 0x0D2030, "sunk": 0xB22222, "text": WHITE, "accent": 0xE0E0E0
    },
    "ships": [
        ("Carrier",5),("Battleship",4),("Cruiser",3),("Submarine",3),("Destroyer",2)
    ],
    "strings": {
        "place_prompt":"Deploy your task force.",
        "fire_prompt":"Select target grid.",
        "hit":"Target damaged!",
        "miss":"Shot wide.",
        "sunk":"Enemy vessel sunk!",
        "you_win":"Mission\naccomplished.",
        "you_lose":"Mission\nfailed.",
        "p1_turn":"Player 1 turn.",
        "p2_turn":"Player 2 turn.",
        "title_1p":"1P vs. AI",
        "title_2p":"2P Hotseat",
        "repeat":"Duplicate coordinates"
    },
    "key_leds":{"idle":0x04090F,"confirm":DEEP_RED,"warn":0xB22222, "rotate":0x6FA8DC}
}

RETRO_TERMINAL = {
    "id": "retro_terminal",
    "title": "RETRO TERMINAL",
    "subtitle": "Green phosphor",
    "palette": {
        "bg": 0x000000, "grid": WHITE, "cursor": WHITE,
        "ally": 0x00FF00, "enemy": 0x003300, "hit": 0xFF0000,
        "miss": 0x999999, "text": WHITE, "accent": 0x00FF00, "sunk": 0xFF0000
    },
    "ships": [
        ("HMCS Algonquin",   5),
        ("HMCS Restigouche", 4),
        ("HMCS Halifax",     3),
        ("HMCS Saskatchewan",3),
        ("HMCS Objibwa",     2),
    ],
    "strings": {
        "place_prompt": "DEPLOY FLEET",
        "fire_prompt":  "TARGET LOCK",
        "hit":          "TARGET DESTROYED",
        "miss":         "NO CONTACT",
        "sunk":         "VESSEL SUNK",
        "you_win":      "MISSION COMPLETE",
        "you_lose":     "MISSION FAILED",
        "win":          "MISSION COMPLETE",
        "lose":         "MISSION FAILED",
        "p1_turn":      "P1 READY",
        "p2_turn":      "P2 READY",
        "title_1p":     "SOLO VS. AI",
        "title_2p":     "2 PLAYERS: HOTSEAT",
        "repeat":       "DUPLICATE COORDINATES"
    },
    "key_leds": {
        "idle": 0x003300, "confirm": 0x00FF00, "warn": 0xFF0000, "rotate": 0x00FF55
    }
}

PROFILES = {
    "brit_pirate": BRIT_PIRATE,
    "ww2_naval": WW2_NAVAL,
    "retro_terminal": RETRO_TERMINAL,
}

# Friendly names for UI
PROFILE_DISPLAY = {
    "brit_pirate": "British Pirate",
    "ww2_naval": "WW2 Naval",
    "retro_terminal": "Retro Terminal"
}

DEFAULT_PROFILE_ID = "brit_pirate"

def get_profile(profile_id=None):
    return PROFILES.get(profile_id or DEFAULT_PROFILE_ID, BRIT_PIRATE)

def get_profile_display(profile_id):
    return PROFILE_DISPLAY.get(profile_id, profile_id)