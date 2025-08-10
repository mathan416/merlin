# magic_square.py — Merlin-style Magic Square for Adafruit MacroPad
# Class: magic_square
# Originally by Keith Tanner, Updates by Iain Bennett
#
# Magic Square is a 3×3 light-toggle puzzle. Each of the 9 grid keys (K0–K8)
# flips a specific pattern of lights. The goal is to reach the target shape:
# a lit square with the center dark.
#
# Controls:
#   • K0–K8: Toggle lights according to the Merlin pattern for that position.
#   • K9 (Same Game): Restore and replay the starting configuration.
#   • K11 (New Game): Start a new random configuration.
#   • Encoder: (unused)
#
# Notes:
#   • Lights turn green and a victory jingle plays when you win.
#   • Runs on CircuitPython 8.x / 9.x with Adafruit MacroPad.

from random import randint

# init
# flash the square
# choose a random config
class magic_square():
    def __init__(self, macropad, tones):
        # shows how the kets affect others
        self.keys = [
            0b110110000,
            0b111000000,
            0b011011000,
            0b100100100,
            0b010111010,
            0b001001001,
            0b000110110,
            0b000000111,
            0b000011011]
        self.state=0b0
        self.start = 0b0
        self.tones = tones
        self.color = 0xff0000
        self.macropad = macropad
        #self.new_game()        
        
    def new_game(self):
        print("new Magic Square game")
        try:
            self.macropad.pixels.auto_write = True
        except AttributeError:
            pass
        self.macropad.pixels.brightness = 0.30
        self.macropad.pixels.fill((0, 0, 0))

        # Proceed into the normal game setup
        self.color = 0x0009ff
        self.state = 0b111101111
        self.show_leds()
        self.color = 0xff0000

        # Generate a new matrix (keep this an INT, not a '0b...' string)
        self.state=bin(randint(0, 511))
        if self.state == 0b111101111:
            self.state += 1

        print("starting", self.state)
        self.start = self.state
        self.show_leds()

        # Labels / controls
        self.macropad.pixels[9]  = 0xff9900  # Same Game
        self.macropad.pixels[11] = 0x00ff00  # New Game
        
    
    def same_game(self):
        # show a square for fun
        self.color = 0xff9900
        self.state = 0b111101111
        self.show_leds()
        self.macropad.play_tone(self.tones[4], 0.5)
        self.macropad.play_tone(self.tones[2], 0.5)
        self.color = 0xff0000
        self.state = self.start
        self.show_leds()

    
    def winner(self):
        # do a winning thing
        self.color = 0x00ff00
        self.show_leds()
        self.macropad.play_tone(self.tones[0], 0.2)
        self.macropad.play_tone(self.tones[2], 0.2)
        self.macropad.play_tone(self.tones[4], 0.2)
        self.macropad.play_tone(self.tones[6], 0.2)
        self.macropad.play_tone(self.tones[4], 0.2)
        self.macropad.play_tone(self.tones[6], 0.5)
        print ("you are a winner")
        
    def bits(self,n):
        arr = [int(x) for x in bin(int(n))[2:]]
        for x in range (0,(9-len(arr))):
           arr.insert(0,0)
        return arr

    def show_leds(self):
        # show the results
        matrix = self.bits(self.state)
        #print (matrix)
        for x in range (len(matrix)):
            if matrix[x]:
                self.macropad.pixels[x] = self.color
            else:
                self.macropad.pixels[x] = 0x000000

        # make boop
        #self.macropad.play_tone(self.tones[7], 0.5)
        

    def button(self,key):
        if key==9:
            self.same_game()
        elif key ==11:
            self.new_game()
        elif key <9:
            #print ("is",bin(self.state),", affects",bin(self.keys[key]))
            self.macropad.play_tone(self.tones[key], 0.2)
            self.state = int(self.state)^int(self.keys[key])
            if (self.state == 0b111101111):
                self.winner()
            else:
                self.show_leds()
        else: # it's another button, weirdo
            pass

    def encoderChange(self,newPosition, oldPosition):
        pass

    
# keypress
# take the key number, pull the modifier array, apply
# check for win
# show result
