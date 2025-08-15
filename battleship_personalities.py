# battleship_personalities.py — Battleship “personality packs” for Adafruit MacroPad
# -----------------------------------------------------------------------------------
# Defines color palettes, UI themes, and sound/personality profiles for the Battleship game.
# A "personality" describes only the presentation layer (colors, labels, sound cues) and 
# does not affect game rules or mechanics.
#
# Contents:
# - Shared RGB color constants (CircuitPython NeoPixel GRB order).
# - Multiple theme dictionaries with unique IDs, titles, subtitles, and palette mappings.
# - Palette entries define background, grid, cursor, ally ships, enemy waters, and hit/miss colors.
#
# Creating Your Own Personality:
# 1. Choose a unique ID:
#      Example: "retro_terminal"
#      This will be used internally to reference your personality.
#
# 2. Pick a title and subtitle:
#      These appear on the title screen.
#      Example:
#        "title": "RETRO TERMINAL",
#        "subtitle": "Classic green phosphor"
#
# 3. Define a color palette dictionary:
#      Required keys (all colors are RGB hex values):
#        "bg"     — Background color for the board area
#        "grid"   — Grid line color
#        "cursor" — Cursor highlight
#        "ally"   — Your ships
#        "enemy"  — Fog of war / unknown cells
#        "hit"    — Successful hit
#        "miss"   — Missed shot
#        (optional keys: "accent", "sunk", "text" for extra effects)
#
# 4. Add it as a dictionary in this file:
#      Example:
#        RETRO_TERMINAL = {
#            "id": "retro_terminal",
#            "title": "RETRO TERMINAL",
#            "subtitle": "Classic green phosphor",
#            "palette": {
#                "bg": 0x000000,
#                "grid": 0x00FF00,
#                "cursor": 0xFFFFFF,
#                "ally": 0x00FF00,
#                "enemy": 0x003300,
#                "hit": 0xFF0000,
#                "miss": 0x999999
#            }
#        }
#
# 5. Register it in the PROFILES dictionary:
#      PROFILES["retro_terminal"] = RETRO_TERMINAL
#
# 6. Test in-game:
#      Launch the game, go to Settings, and select your new personality.
#
# Date: 2025-08-15
# Author: Iain Bennett (adapted for MacroPad Battleship)

# Shared color helpers (RGB hex)
WHITE=0xFFFFFF; 
BLACK=0x000000
RED=0xDD3344; 
GREEN=0x3CCB5A; 
BLUE=0x3399FF; 
GOLD=0xD4AF37; 
TEAL=0x1BB6A9; 
GRAY=0x404040
ORANGE = 0xFF8800
YELLOW = 0xFFD300
PURPLE = 0x8A2BE2
PINK   = 0xFF69B4
BROWN  = 0x8B4513
CYAN   = 0x00FFFF
LIME   = 0xBFFF00
MAGENTA = 0xFF00FF
DEEP_BLUE = 0x0000FF
DEEP_RED = 0xFF0000
DEEP_GREEN = 0x00FF00


# A personality describes the *presentation*, not the rules.
BRIT_PIRATE = {
    "id": "brit_pirate",
    "title": "BROADSIDE BRIGANDS",
    "subtitle": "A bit o’ piracy",
    # UI palette
    "palette": {
        "bg": 0x0A0D14,
        "grid": TEAL,
        "cursor": GREEN,
        "ally": BLUE,          # your ships
        "enemy": GRAY,         # unknown waters
        "hit": RED,
        "miss": DEEP_BLUE,
        "sunk": DEEP_RED,
        "text": WHITE,
        "accent": GOLD,
    },
    # Ship set (name, length)
    "ships": [
        ("Flagship ‘Sovereign’", 5),
        ("Man‑o’‑War", 4),
        ("Frigate", 3),
        ("Brig", 3),
        ("Sloop", 2),
    ],
    # Flavor text
    "strings": {
        "place_prompt": "Lay yer fleet, Captain.",
        "fire_prompt":  "Call yer shot!",
        "hit":          "BULLSEYE Their timbers be shiverin’!",
        "miss":         "Water and wind. Try again.",
        "sunk":         "Down she goes! Send em to Davy Jones!",
        "you_win":      "Victory! Raise the colours!",
        "you_lose":     "Cursed luck! Strike the colours…",
        "p1_turn":      "Captain One, make yer mark.",
        "p2_turn":      "Captain Two, have at em.",
        "title_1p":     "1 Player vs. Navy",
        "title_2p":     "2 Players: Hotseat",
        "repeat":       "Stop wasting cannon balls!"
    },
    # Taunts shown randomly on hits/misses
    "taunts_hit": [
        "A tidy broadside!", "Powder well spent!", "Mind the splinters!"
    ],
    "taunts_miss": [
        "Ye wet the waves.", "Sea gull laughs at ye.", "Blame the swell."
    ],
    # Sound design tokens the sfx module interprets
    "sfx": {
        "hit":   {"type":"cannon", "boom": 220, "crackle": True},
        "miss":  {"type":"splash", "depth": 0.6},
        "sunk":  {"type":"bell",   "notes":[523,659,784]},
        "place": {"type":"rope",   "creak": True},
        "start": {"type":"fife",   "notes":[784,880,988]},
    },
    # LED key glow scheme (optional)
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
        "bg": 0x00060A, "grid": 0x5DA6F0, "cursor": DEEP_GREEN,
        "ally": 0x3F78C5, "enemy": 0x243347, "hit": 0xF25C54,
        "miss": 0x0D2030, "sunk": 0xB22222, "text": WHITE, "accent": 0xE0E0E0, "rotate": PINK
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
        "you_win":"Mission accomplished.",
        "you_lose":"Mission failed.",
        "p1_turn":"Player 1 turn.",
        "p2_turn":"Player 2 turn.",
        "title_1p":"1P vs. AI",
        "title_2p":"2P Hotseat",
        "repeat":"Stop wasting cannon balls!"
    },
    "taunts_hit":["Direct hit!","Confirm secondary fires.","Well spotted."],
    "taunts_miss":["Adjust fire.","Negative impact.","Recalibrate."],
    "sfx":{"hit":{"type":"shell"}, "miss":{"type":"splash"}, "sunk":{"type":"klaxon"}, "place":{"type":"clack"}, "start":{"type":"trill"} },
    "key_leds":{"idle":0x04090F,"confirm":DEEP_RED,"warn":0xB22222}
}

PROFILES = {
    BRIT_PIRATE["id"]: BRIT_PIRATE,
    WW2_NAVAL["id"]: WW2_NAVAL,
}

# Friendly names for UI
PROFILE_DISPLAY = {
    "brit_pirate": "British Pirate",
    "ww2_naval": "WW2 Naval",
}

DEFAULT_PROFILE_ID = "brit_pirate"

def get_profile(profile_id=None):
    return PROFILES.get(profile_id or DEFAULT_PROFILE_ID, BRIT_PIRATE)

def get_profile_display(profile_id):
    return PROFILE_DISPLAY.get(profile_id, profile_id)