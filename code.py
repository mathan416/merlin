# to learn display
# 
# 
# # Merlin emulator
# games:
# tic tac toe
# Music Machine
# Echo (Simon)
# Blackjack 13
# Magic square
# Mindbender

import os
import displayio
import terminalio
from adafruit_display_shapes.rect import Rect
from adafruit_display_text import label
from adafruit_macropad import MacroPad
from mindbender import mindbender
from magic_square import magic_square
from echo import echo
from simon import simon
from music_machine import music_machine
from tictactoe import tictactoe
from blackjack13 import blackjack13
from snake import snake
#from rainbowio import colorwheel


macropad = MacroPad()
# little bit of cleanuo
macropad.pixels.fill((0,0,0))
# configuration
# scale
tones = [196, 220, 247, 262, 294, 330, 349, 392, 440, 494, 523, 587]
#length = 0.5

# create the objects for each game
# put them in an array
# turning dial switches to a different item in the array
# need to have the same API
games = dict()

games['Magic Square'] = magic_square(macropad, tones)
games['Mindbender'] = mindbender(macropad, tones)
games['Echo'] = echo(macropad, tones)
games['Simon'] = simon(macropad, tones)
games['Music Machine'] = music_machine(macropad, tones)
games['Tic Tac Toe'] = tictactoe(macropad, tones)
games['Blackjack 13'] = blackjack13(macropad, tones)
games['Snake'] = snake(macropad, tones, False)
games['Snake II'] = snake(macropad, tones, True)

#do display setup 
#macropad.display.auto_refresh = False
#macropad.pixels.auto_write = False
bitmap = displayio.OnDiskBitmap("MerlinChrome.bmp")
tile_grid = displayio.TileGrid(
        bitmap,
        pixel_shader=getattr(bitmap, 'pixel_shader', displayio.ColorConverter()))
# Create a Group to hold the TileGrid
group = displayio.Group()
macropad.display.root_group = group
    # Add the TileGrid to the Group
group.append(tile_grid)

group.append(label.Label(terminalio.FONT, text='choose your game:', color=0xffffff,
                         anchored_position=(macropad.display.width//2, 31),
                         anchor_point=(0.5, 0.0)
                         ))
group.append(label.Label(terminalio.FONT, text=' '*20, color=0xffffff,
                         anchored_position=(macropad.display.width//2, 45),
                         anchor_point=(0.5, 0.0)
                         ))

# macropad.display.show(group)

last_position = None
last_encoder_switch = None
#force a game selection
modechange =1
print ("modechange on")
# MAIN LOOP ----------------------------

while True:
    position = macropad.encoder
    if position != last_position:
        if modechange:
            pass  # cycle through the games (menu mode)
        else:
            # In game mode, let the game handle encoder changes if it wants
            current_game.encoderChange(position, last_position)
        last_position = position

    # Encoder button toggles between menu <-> game
    macropad.encoder_switch_debounced.update()
    encoder_switch = macropad.encoder_switch_debounced.pressed
    if encoder_switch != last_encoder_switch:
        last_encoder_switch = encoder_switch
        if encoder_switch:
            if modechange:
                modechange = 0
                print("modechange off")
                group[1].text = "Now Playing:"
                # select and start the chosen game
                current_game = games[list(games.keys())[macropad.encoder % len(games)]]
                current_game.new_game()                
            else:
                modechange = 1
                group[1].text = "Choose your game:"
                macropad.pixels.fill((50, 0, 0))
                # CP 9+: root_group; CP 8.x fallback
                try:
                    macropad.display.root_group = group
                except AttributeError:
                    macropad.display.show(group)

    elif modechange:
        # Menu mode: update highlighted game name as the knob turns
        current_knob = macropad.encoder % len(games)
        group[2].text = list(games.keys())[current_knob]

    else:
        # -------- Game mode: run the game's frame update --------
        if hasattr(current_game, "tick"):
            current_game.tick()

        # Then handle button presses for the current game
        key_event = macropad.keys.events.get()
        if key_event:
            key_number = key_event.key_number
            if key_event.pressed and key_number < 12:
                current_game.button(key_number)
            else:
                    # is it possible to get here?
                    # pass for now
                    pass
    