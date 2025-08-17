# mindbender.py — Merlin-style logic puzzle for Adafruit MacroPad
# Class: mindbender
# Originally by Keith Tanner, Updates by Iain Bennett
#
# Mindbender is a code-breaking game inspired by Mastermind.
# Merlin (the game master) secretly selects a sequence of colored keys
# (numbers 1–9). The player must guess the sequence within as few tries
# as possible. After each guess, the MacroPad LEDs provide feedback:
#   - Green = correct key in the correct position
#   - Yellow = correct key in the wrong position
#   - Red = incorrect key
#
# Controls:
#   - At start, press keys 1–9 to set puzzle length.
#   - During play, press numbered keys (1–9) to enter your guess.
#   - Key 10 repeats the last puzzle after evaluation.
#   - Key 11 starts a brand-new game.
#   - Key 9 restarts the same puzzle mid-game.
#   - Rotary encoder changes tempo (cosmetic).
#
# CircuitPython 8.x / 9.x compatible
# Requires: displayio, adafruit_display_text, terminalio

import time
import displayio, terminalio
from random import randint
from adafruit_display_text import label

# init
# flash the square
# choose a random config
class mindbender():
    def __init__(self, macropad, tones):
        # shows how the keys affect others
        self.tones = tones
        self.macropad = macropad
        self.gameMode ="select"
        self.puzzle=[]
        self.tries = 0
        self.clear = [
            0xf400fd,0xd516ed,0xb71edc,
        0x9a21cb,0x7f21b8,0x651fa5,
        0x4c1c91,0x34177d,0x1d1268,
        0xff9900,0x000,0x00ff00]
        self.tempo = 150 # bpm
        self.player = []
        self._build_display()

    def cleanup(self):
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True

        # 1) Stop any tone / disable speaker (best-effort)
        try:
            if hasattr(self.macropad, "stop_tone"):
                self.macropad.stop_tone()
        except Exception:
            pass
        try:
            spk = getattr(self.macropad, "speaker", None)
            if spk is not None:
                spk.enable = False
        except Exception:
            pass

        # 2) LEDs: blackout and restore auto_write (many launchers expect True)
        try:
            px = getattr(self.macropad, "pixels", None)
            if px:
                for i in range(12):
                    px[i] = 0x000000
                try: px.show()
                except Exception: pass
                try: px.auto_write = True
                except Exception: pass
        except Exception:
            pass

        # 3) Display: if our group is the root, clear it
        try:
            disp = getattr(self.macropad, "display", None)
            if disp:
                g = getattr(self, "group", None)
                root = getattr(disp, "root_group", None)
                if root is g:
                    try:
                        disp.root_group = None      # CP 9+
                    except Exception:
                        try:
                            disp.show(None)        # CP 8
                        except Exception:
                            pass
        except Exception:
            pass

        # 4) Drop big refs and GC (optional but helps memory fragmentation)
        try:
            self.group = None
            self.title = None
            self.status = None
            import gc
            gc.collect()
            gc.collect()
        except Exception:
            pass

    def new_game(self):
        print ("new Mindbender game")
        try:
            self.macropad.pixels.auto_write = True
        except AttributeError:
            pass
        self.macropad.pixels.brightness = 0.30
        self.puzzle.clear()
        self.player.clear()
        self.tries = 0
        self.gameMode ="select"
        self._set_status("Pick length (1 to 9)")
        self.macropad.pixels.fill((0,0,0))
        # run dots through every active button
        for x in range (9):
            self.macropad.pixels[x]=0x000099
            time.sleep(0.1)
            self.macropad.pixels[x]=self.clear[x]
         
        
    def start_game(self, length):
        print ("player has selected", length)
        self.gameMode ="playing"
        self._set_status(f"Enter {length} keys")
        #clear and light up new/same buttons
        self.macropad.pixels.fill((0,0,0))
        time.sleep(0.5)
        for x in range(length):
            rando = randint(0, 8)
            self.puzzle.append(rando)
        
        print ("Merlin has chosen",self.puzzle)
        self.clear_board()
         
    def evaluate(self):
        self.tries += 1
        self.macropad.pixels.fill((0,0,0))
        print ("evaluating", self.player, "against", self.puzzle)

        green = yellow = red = 0
        tracker = self.puzzle.copy()

        if self.puzzle == self.player:
            self.winner()
            return

        # exact matches
        for x in range(len(self.player)):
            if self.player[x] == tracker[x]:
                green += 1
                tracker[x] = -1
                self.player[x] = -1

        # present but wrong place
        for x in range(len(tracker)):
            if tracker[x] >= 0:
                try:
                    pos = self.player.index(tracker[x])
                    yellow += 1
                    tracker[x] = -1
                    self.player[pos] = -1
                except ValueError:
                    red += 1

        print ("score is", green, yellow, red)
        # LEDs for result
        for i in range(green):
            self.macropad.pixels[i] = 0x146401   # green
        for i in range(green, green+yellow):
            self.macropad.pixels[i] = 0x645501   # yellow
        for i in range(green+yellow, green+yellow+red):
            self.macropad.pixels[i] = 0x640101   # red

        self.gameMode = "evaluated"
        self.player.clear()
        self.macropad.pixels[10] = 0x7f21b8     # repeat button hint

        self._set_status(f"Try again")


    def same_game(self):
        print ("restart game")
        self.macropad.pixels.fill((0,0,0))
        self.macropad.play_tone(self.tones[4], 0.5)
        self.macropad.play_tone(self.tones[2], 0.5)
        self.player.clear()
        self.gameMode ="playing"
        self.clear_board()
        self._set_status(f"Enter {len(self.puzzle)} keys")
        

    
    def winner(self):
        self.macropad.pixels.fill((0,200,0))
        self.macropad.play_tone(self.tones[0], 0.2)
        self.macropad.play_tone(self.tones[2], 0.2)
        self.macropad.play_tone(self.tones[4], 0.2)
        self.macropad.play_tone(self.tones[6], 0.2)
        self.macropad.play_tone(self.tones[4], 0.2)
        self.macropad.play_tone(self.tones[6], 0.5)
        self._set_status(f"You win - {self.tries} tries!")
        time.sleep(0.5)
        self.macropad.pixels.fill((0,0,0))
        light_count = 9 
        tens = 0
        for x in range (self.tries):
        #for x in range (32):
            if x==light_count:
                self.clear_board()
                #print ("clear")
                self.macropad.pixels[9]=0x000099
                #print (x,"blue")
                time.sleep(0.2)
                tens = tens+1
                #self.macropad.pixels[10]=0x0a0014
            elif x==(light_count)*2+1:
                self.clear_board()
                #print ("clear")
                self.macropad.pixels[9]=0x000099
                self.macropad.pixels[10]=0x000099
                #print (x,"aka 10 blue")
                time.sleep(0.2)
                tens = tens+1
                #self.macropad.pixels[10]=0x0a0014
            elif x==(light_count)*3+2:
                self.clear_board()
                #print ("clear")
                self.macropad.pixels[9]=0x0a0014
                self.macropad.pixels[10]=0x000099
                #print (x,"aka 9 blurple")
                time.sleep(0.2)
                tens = tens+1
                #self.macropad.pixels[10]=0x0a0014
            elif x==(light_count)*4+3:
                self.clear_board()
                #print ("clear")
                self.macropad.pixels[9]=0x0a0014
                self.macropad.pixels[10]=0x0a0014
                #print (x,"aka 10 plurple")
                time.sleep(0.2)
                tens = tens+1
                #self.macropad.pixels[10]=0x0a0014
            else:
                self.macropad.pixels[(x-tens)%light_count]=0x000099
                #print ((x-tens)%light_count,"blue")
                time.sleep(0.2)
                self.macropad.pixels[(x-tens)%light_count]=0x0a0014
                #print ((x-tens)%light_count,"blurple")
        for x in range(9,12):
            self.macropad.pixels[x]=self.clear[x]      
        self.gameMode ="ended"
    
    def clear_board(self):
        # show the results
        for x in range (len(self.clear)):
            self.macropad.pixels[x] = self.clear[x]
        
        # make boop
        #self.macropad.play_tone(self.tones[7], 0.5)
        
        

    def button(self,key):
        #check mode
        if self.gameMode =="select":
            if (key < 9):
                self.macropad.play_tone(self.tones[key], 0.2)
                self.macropad.pixels[key]=0x009900
                self._set_status(f"Length: {key+1}")
                self.start_game(key+1)
            else: 
                #ignore
                pass
        elif self.gameMode =="evaluated":
            if key == 10:
                self.gameMode = "playing"
                self.clear_board()
                self._set_status(f"Enter {len(self.puzzle)} keys")
                return
            else:
                #ignore
                pass

        elif self.gameMode=="playing":
            if key==9:
                self.same_game()
            elif key ==11:
                self.new_game()
            elif key <9:
                #print ("is",bin(self.state),", affects",bin(self.keys[key]))
                #do the game thing
                self.clear_board()
                self.macropad.pixels[key]=0x000099
                self.macropad.play_tone(self.tones[key], 0.2) 

                self.player.append(key)
                self._set_status(f"Entered {len(self.player)}/{len(self.puzzle)}")
                print ("player",self.player)
                if len(self.player) == len(self.puzzle):
                    #game is done
                    #evaluate
                    self.evaluate()
                
            else: # it's another button, weirdo
                pass
        else:
            #game is over, ignore all but game control buttons
            if key==9:
                self.same_game()
            elif key ==11:
                self.new_game()

    def encoderChange(self,newPosition, oldPosition):
        self.tempo = self.tempo +(newPosition-oldPosition)*5
        print ("new tempo",self.tempo,"bpm")

    def _build_display(self):
        W, H = self.macropad.display.width, self.macropad.display.height
        g = displayio.Group()

        # background
        bg = displayio.Bitmap(W, H, 1)
        pal = displayio.Palette(1); pal[0] = 0x000000
        g.append(displayio.TileGrid(bg, pixel_shader=pal))

        y0 = 0
        # logo (kept on screen)
        try:
            bmp = displayio.OnDiskBitmap("MerlinChrome.bmp")
            tile = displayio.TileGrid(
                bmp,
                pixel_shader=getattr(bmp, "pixel_shader", displayio.ColorConverter())
            )
            g.append(tile)
            y0 = bmp.height + 2
        except Exception as e:
            print("Logo not loaded:", e)

        # title
        self.title = label.Label(
            terminalio.FONT, text="Mindbender",
            color=0xFFFFFF, anchor_point=(0.5, 0.0),
            anchored_position=(W//2, y0)
        )
        g.append(self.title)

        # status
        self.status = label.Label(
            terminalio.FONT, text="",
            color=0xA0A0A0, anchor_point=(0.5, 0.0),
            anchored_position=(W//2, y0 + 14)
        )
        g.append(self.status)

        self.group = g
        self._show()
        
    def _show(self):
        try:
            self.macropad.display.show(self.group)      # CP 8.x
        except AttributeError:
            self.macropad.display.root_group = self.group  # CP 9.x

    def _set_status(self, text):
        if hasattr(self, "status") and self.status:
            self.status.text = text
# keypress
# take the key number, pull the modifier array, apply
# check for win
# show result
