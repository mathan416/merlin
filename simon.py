# simon.py — Classic “repeat the sequence” game for Adafruit MacroPad
# Class: simon
# Originally by Keith Tanner, Updates by Iain Bennett
#
# Overview:
#   Simon generates an ever-growing sequence of keys (K0–K11). Watch and listen
#   as each step is flashed and beeped, then repeat the sequence exactly.
#   If you press a wrong key, the round ends and your score is shown on the
#   keypad; K11 lights to indicate you can start again.
#
# Controls:
#   • K11    : Start / Restart a new game.
#   • K0–K11 : During play, press to reproduce the sequence step-by-step.
#   • Encoder: Change tempo in 5 BPM steps.
#
# Display & Sound:
#   • Each step in the sequence lights its key with a themed color and plays a tone.
#   • On error, the keypad animates your score (length reached before the mistake),
#     and K11 turns green to prompt a restart.
#
# Notes:
#   • Uses all 12 keys as playable inputs (0–11).
#   • Designed for CircuitPython MacroPad (8.x / 9.x compatible).

import time
from random import randint

# init
# flash the square
# choose a random config
class simon():
    def __init__(self, macropad, tones):
        # shows how the keys affect others
        self.tones = tones
        self.colors = [
        0xf400fd,0xde04ee,0xc808de,
        0xb20ccf,0x9c10c0,0x8614b0,
        0x6f19a1,0x591d91,0x432182,
        0x2d2573,0x172963,0x012d54
        ]

        self.macropad = macropad
        self.gameMode =""
        self.puzzle=[]
        self.player=0
        self.tempo = 150 # bpm
        #self.new_game()

    def new_game(self):
        print("new Simon game")

        # (No need to force auto_write True here; the wipe handles its own state.)
        self.gameMode = "playing"
        self.puzzle.clear()

        # Clean slate, then begin the first sequence
        self.macropad.pixels.fill((0, 0, 0))
        self.play_sequence()
           
    def play_sequence(self):
        time.sleep(0.5)
        self.clear_board()
        #take a breath
        time.sleep(0.5)
        # add a new value to the puzzle
        self.puzzle.append(randint(0, 11))
        # reset the count
        self.player = 0
        #play it
        delay = 60/self.tempo
        for x in self.puzzle:
            self.macropad.pixels[x]=self.colors[x]
            self.macropad.play_tone(self.tones[x], delay)
            self.macropad.pixels[x]=0x000000
            time.sleep(delay/10)

    def error(self):
        # bzzzt
        time.sleep(0.5)
        self.clear_board()
        self.gameMode ="ended"
        light_count = 9 
        tens = 0
        #can really only show a max score of 49 unless I add some extra jazz
        for x in range (len(self.puzzle)-1):
        #for x in range (32):
            if x==light_count:
                self.clear_board()
                self.macropad.pixels[9]=0x000099
                time.sleep(0.2)
                tens = tens+1
            elif x==(light_count)*2+1:
                self.clear_board()
                self.macropad.pixels[9]=0x000099
                self.macropad.pixels[10]=0x000099
                time.sleep(0.2)
                tens = tens+1
            elif x==(light_count)*3+2:
                self.clear_board()
                self.macropad.pixels[9]=0x0a0014
                self.macropad.pixels[10]=0x000099
                time.sleep(0.2)
                tens = tens+1
            elif x==(light_count)*4+3:
                self.clear_board()
                self.macropad.pixels[9]=0x0a0014
                self.macropad.pixels[10]=0x0a0014
                time.sleep(0.2)
                tens = tens+1
            else:
                self.macropad.pixels[(x-tens)%light_count]=0x000099
                time.sleep(0.2)
                self.macropad.pixels[(x-tens)%light_count]=0x0a0014

        self.macropad.pixels[11]=0x00ff00
    
        
    
    def clear_board(self):
        # show the results
        self.macropad.pixels.fill((0,0,0))
        #for x in range (len(self.clear)):
        #    self.macropad.pixels[x] = self.clear[x]
        
        # make boop
        #self.macropad.play_tone(self.tones[7], 0.5)
        

    def button(self,key):
        #check to see if we're in selectionMode
        if self.gameMode=="playing":
            if key <12:
                #do the game thing
                
                self.clear_board()
                self.player = self.player+1
                
                if key == self.puzzle[self.player-1]:
                    #correct
                    self.macropad.pixels[key]=0x000099
                    self.macropad.play_tone(self.tones[key], 0.2)
                    if self.player == len(self.puzzle):
                        self.play_sequence()
                    
                else:
                    self.macropad.pixels[key]=0x990000
                    self.macropad.play_tone(100, 0.7)
                    self.error()
                    
        else:
            #game is over, ignore all but game control buttons
            if key ==11:
                self.new_game()
    
    def encoderChange(self,newPosition, oldPosition):
        self.tempo = self.tempo +(newPosition-oldPosition)*5
        print ("new tempo",self.tempo,"bpm")
       
# keypress
# take the key number, pull the modifier array, apply
# check for win
# show result
