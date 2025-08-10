# Merlin emulator launcher (CircuitPython 9.x)
# Menu -> press encoder to start a game; press again to return to menu.
print("Loading Merlin")
import time
import displayio
import terminalio
from adafruit_display_text import label
from adafruit_macropad import MacroPad



# ---- Import game classes (no instances yet!) ----
from mindbender import mindbender
from magic_square import magic_square
from echo import echo
from simon import simon
from music_machine import music_machine
from tictactoe import tictactoe
from blackjack13 import blackjack13
from snake import snake
from hit_or_miss import hit_or_miss
from three_shells import three_shells

# ---------- Setup hardware ----------
macropad = MacroPad()
macropad.pixels.fill((50, 0, 0))  # clear pads

# 12-tone palette
tones = [196, 220, 247, 262, 294, 330, 349, 392, 440, 494, 523, 587]

# ---------- Lazy game factories (no drawing until chosen) ----------
games_factories = {
    "Magic Square":  lambda: magic_square(macropad, tones),
    "Mindbender":    lambda: mindbender(macropad, tones),
    "Echo":          lambda: echo(macropad, tones),
    "Simon":         lambda: simon(macropad, tones),
    "Music Machine": lambda: music_machine(macropad, tones),
    "Tic Tac Toe":   lambda: tictactoe(macropad, tones),
    "Blackjack 13":  lambda: blackjack13(macropad, tones),
    "Snake":         lambda: snake(macropad, tones, False),
    "Snake II":      lambda: snake(macropad, tones, True),
    "Hit or Miss":   lambda: hit_or_miss(macropad, tones),
    "Three Shells":  lambda: three_shells(macropad, tones),
}
game_names = list(games_factories.keys())
game_instances = {}  # name -> instance (created on first play)

# ---------- Menu UI ----------
def build_menu_group():
    group = displayio.Group()
    # Optional splash image
    try:
        bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
        tile = displayio.TileGrid(bmp, pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter()))
        group.append(tile)
    except Exception:
        pass  # fine if missing

    title = label.Label(
        terminalio.FONT, text="choose your game:", color=0xFFFFFF,
        anchor_point=(0.5, 0.0), anchored_position=(macropad.display.width // 2, 31)
    )
    choice = label.Label(
        terminalio.FONT, text=" " * 20, color=0xFFFFFF,
        anchor_point=(0.5, 0.0), anchored_position=(macropad.display.width // 2, 45)
    )
    group.append(title)   # index 1
    group.append(choice)  # index 2
    return group

menu_group = build_menu_group()
macropad.display.root_group = menu_group
# show initial selection
menu_group[2].text = game_names[0]

# ---------- Helpers ----------
def enter_menu():
    # normalize pixel behavior for menu
    try:
        macropad.pixels.auto_write = True
    except AttributeError:
        pass
    macropad.pixels.brightness = 0.30
    macropad.pixels.fill((50, 0, 0))  # menu hint
    macropad.display.root_group = menu_group

def start_game_by_name(name):
    # Let each game manage auto_write itself; just clear first
    macropad.pixels.fill((0, 0, 0))

    game = game_instances.get(name)
    if game is None:
        game = games_factories[name]()  # create on demand
        game_instances[name] = game

    # Start it
    game.new_game()

    # Hand display to the game UI if provided
    if hasattr(game, "group") and game.group is not None:
        macropad.display.root_group = game.group

    # Clear any lingering menu LEDs
    #macropad.pixels.fill((0, 0, 0))
    return game

# ---------- Main loop state ----------
mode_menu = True
last_encoder_position = macropad.encoder
last_encoder_switch = False
current_game = None

# ---------- Main loop ----------
while True:
    # --- encoder turn ---
    pos = macropad.encoder
    if pos != last_encoder_position:
        if mode_menu:
            idx = pos % len(game_names)
            menu_group[2].text = game_names[idx]
        else:
            if current_game and hasattr(current_game, "encoderChange"):
                try:
                    current_game.encoderChange(pos, last_encoder_position)
                except Exception as e:
                    print("encoderChange error:", e)
        last_encoder_position = pos

    # --- encoder press (toggle menu/game) ---
    macropad.encoder_switch_debounced.update()
    enc_pressed = macropad.encoder_switch_debounced.pressed
    if enc_pressed != last_encoder_switch:
        last_encoder_switch = enc_pressed
        if enc_pressed:
            if mode_menu:
                # Enter game
                mode_menu = False
                menu_group[1].text = "Now Playing:"
                sel = game_names[macropad.encoder % len(game_names)]
                current_game = start_game_by_name(sel)
            else:
                # Return to menu
                # Give the active game a chance to clean up LEDs/auto_write
                try:
                    if current_game and hasattr(current_game, "cleanup"):
                        current_game.cleanup()
                except Exception as e:
                    print("cleanup error:", e)
                mode_menu = True
                menu_group[1].text = "choose your game:"
                enter_menu()

    if mode_menu:
        time.sleep(0.01)
        continue

    # --- game tick/update ---
    if current_game and hasattr(current_game, "tick"):
        try:
            current_game.tick()
        except Exception as e:
            print("tick error:", e)

    # --- key events to active game ---
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