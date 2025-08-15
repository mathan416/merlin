# personalities.py — Battleship “personality packs” for Adafruit MacroPad - 2025-08-15
# CircuitPython 8.x/9.x
from ulab import numpy as np  # optional if you synthesize tones

# Shared color helpers (RGB hex)
WHITE=0xFFFFFF; BLACK=0x000000
RED=0xDD3344; GREEN=0x3CCB5A; BLUE=0x3399FF; GOLD=0xD4AF37; TEAL=0x1BB6A9; GRAY=0x404040

ORANGE = 0xFF8800
YELLOW = 0xFFD300
PURPLE = 0x8A2BE2
PINK   = 0xFF69B4
BROWN  = 0x8B4513
CYAN   = 0x00FFFF
LIME   = 0xBFFF00
MAGENTA = 0xFF00FF
DEEP_BLUE = 0x0000FF


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
        "sunk": RED,
        "text": WHITE,
        "accent": GOLD,
        "rotate": PINK
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
        "confirm": RED,
        "warn": RED,
    }
}

WW2_NAVAL = {
    "id": "ww2_naval",
    "title": "BATTLELINE",
    "subtitle": "Naval Operations",
    "palette": {
        "bg": 0x00060A, "grid": 0x5DA6F0, "cursor": 0xE0E0E0,
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
    "key_leds":{"idle":0x04090F,"confirm":0xE0E0E0,"warn":0xB22222}
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