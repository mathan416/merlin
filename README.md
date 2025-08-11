# Merlin
Recreation of the **Merlin** electronic handheld game using the Adafruit **MacroPad**, now with additional games from *Merlin* and *Master Merlin*.

Firstly - thank you to Keith Tanner for the original starting point code plus the STL files to print a case for the Macropad.

---

## 📜 Project Overview

This project recreates and expands upon the classic *Merlin* electronic handheld game using an **Adafruit MacroPad** running CircuitPython.  
It includes a launcher system to select and start different game modes, each implemented as a separate Python class with LED, sound, and OLED display feedback.

You will need:
- [Adafruit MacroPad Libraries](https://learn.adafruit.com/adafruit-macropad-rp2040/macropad-circuitpython-library)  
- CircuitPython **9.1** or higher (developed using **9.1.4**)

Case for Macropad Merlin:
- [Merlin case for Adafruit Macropad](https://www.thingiverse.com/thing:5118991)

Merlin Guides:
- [Merlin Manual (Parker Bros.)](https://www.monroeworld.com/vmerlin/bin/merlinmanual.pdf)
- [Master Merlin Manual (Parker Bros.)](http://pdf.textfiles.com/manuals/HANDHELDS/ParkerBros-MasterMerlin.pdf)  

---

## 🚀 Quick Start / 📥 Installation & Setup

1. **Install CircuitPython 9.1 or higher**  
   Follow Adafruit’s guide for your MacroPad:  
   <https://learn.adafruit.com/adafruit-macropad-rp2040/circuitpython>

2. **Install Required Libraries**  
   Download the latest library bundle from Adafruit and copy the following to your `lib` folder on the MacroPad:  
   - `adafruit_display_text`  
   - `adafruit_macropad`  
   - `adafruit_ticks`
   - Any other dependencies from the MacroPad guide.

3. **Copy Game Files**  
   - Copy all `.py` files and `MerlinChrome.bmp` to the root of your MacroPad’s CIRCUITPY drive.

4. **Eject and reboot** the MacroPad.

5. **Play!**  
   - Rotate the encoder to select a game.  
   - Press the encoder to start.  
   - Press it again (or Key 9 in some games) to return to the menu.  

---

## 🎯 Games Overview

| Game Name       | Type / Inspiration          | Difficulty | Summary |
|-----------------|-----------------------------|------------|---------|
| **Blackjack 13** | Card game (Merlin)          | ★☆☆        | Get as close to 13 without going over; CPU opponent |
| **Echo**         | Memory / Sequence (Merlin)| ★★☆        | Repeat an increasing sequence of tones and lights |
| **Hi Lo**        | Guessing (Master Merlin)    | ★☆☆        | Guess the number; LEDs guide you higher or lower |
| **Hit or Miss**  | Reaction / Timing (Master Merlin)          | ★★☆        | Press keys quickly when LEDs light up — don’t miss |
| **Magic Square** | Puzzle (Merlin)             | ★★☆        | Arrange lights into a magic square pattern |
| **Match It**     | Memory (Master Merlin)      | ★★☆        | Flip keys to find matching pairs |
| **Mindbender**   | Logic puzzle (Merlin)       | ★★★        | Guess the hidden code with feedback each attempt |
| **Music Machine**| Free play (Merlin)          | ☆☆☆        | Play tones by pressing keys — like a mini piano |
| **Pair Off**     | Memory (Master Merlin)      | ★★☆        | Match pairs hidden on the board |
| **Simon**        | Memory / Sequence (Simon & Merlin)   | ★★☆        | Repeat LED/sound sequences — classic Simon game |
| **Snake**        | Arcade / Nokia-style        | ★★☆        | Eat food, grow the snake, avoid walls and self |
| **Snake II**     | Arcade / Nokia-style        | ★★★        | Snake with wrap-around and bonus items |
| **Three Shells** | Memory (Master Merlin)      | ★★☆        | Track the ball under shuffled shells |
| **Tic Tac Toe**  | Board game (Merlin)         | ★☆☆        | Play against CPU; animated endgame pulses |

\*Difficulty ratings are approximate and assume normal skill settings.

--- 

## 🎛 Controls

### General (Launcher)
- **Rotate Encoder** → Select game from menu
- **Press Encoder** → Start selected game
- **Key 9** → Return to launcher from a game (when supported)
- **Keys** → Game-specific controls

### Per-Game Controls Overview

| Game               | Keys Used                                  | Encoder Use | Notes |
|--------------------|--------------------------------------------|-------------|-------|
| **Blackjack 13**   | K9-K11 for hit/stand inputs, special key for stand | None        | Try to reach exactly 13 without going over; simplified blackjack variant. |
| **Echo**           | K0–K8 to repeat sequence                    | None        | Merlin’s “Echo” memory game; repeat the tone/light sequence. |
| **Hi Lo**          | K0–K8, K10 for number entry                      | None        | Guess the hidden number; skill determines range. |
| **Hit or Miss**    | K0–K9 for guessing                         | None        | Try to guess the hidden pattern; feedback after each guess. |
| **Magic Square**   | K0–K8 to place numbers                      | None        | Arrange numbers so each row, column, and diagonal add to the same total. |
| **Match It**       | K0–K8 for card selection                    | None        | Flip two cards to match pictures/numbers; memory challenge. |
| **Mindbender**     | K0–K8 for code guesses                      | None        | Mastermind-style pattern logic game. |
| **Music Machine**  | K0–K9 play notes                            | Encoder scrolls pitch | Play tones freely; use encoder to change pitch range. |
| **Pair Off**       | K0–K8 for card selection                    | None        | Flip cards to find matching pairs. |
| **Simon**          | K0–K9 to repeat sequence                    | None        | Classic Simon memory game; sequence grows each round. |
| **Snake / Snake II** | K4 = up, K6 = left, K8 = right, K10 = down | None | Classic snake; avoid walls and yourself; Snake II adds extra rules. |
| **Three Shells**   | K3, K4, K5 = shells                         | None        | K0–K8 sets skill level before play; follow the ball under the shells. |
| **Tic Tac Toe**    | K0–K8 board squares                         | None        | K9 New game, K10 Swap starter, K11 CPU Move. |


---

## 🎮 Launcher Details

### `code.py` — Game Launcher  
The main entry point (also called `launcher.py`).  
Handles:
- Initializing MacroPad hardware, display, and sound
- Loading available games dynamically
- Showing the Merlin-style chrome logo and menu
- Navigating between games with the rotary encoder
- Launching and returning from games without rebooting

---

## 🎮 Games Details

### `hi_lo.py` — High or Low  
A classic number guessing game. The MacroPad picks a random number; you guess higher or lower using the keys. LED colors and sounds indicate whether your guess is too high, too low, or correct. Difficulty can be adjusted by skill level.

### `mindbender.py` — Mindbender (based on Hi_LO)  
A logic puzzle variant inspired by the Master Merlin game *Mindbender*.  
Players attempt to guess a hidden pattern with feedback after each attempt.  
Built using `hi_lo.py` as a base, with expanded status display and new sound effects.

### `pair_off.py` — Pair Off  
A memory matching game based on Master Merlin's *Pair Off*.  
Players try to find matching pairs hidden under keys.  
Includes smooth LED reveal animations, sound cues, and skill levels that control the number of pairs.

### `snake.py` — Snake / Snake II  
A Nokia-style Snake game with tick-based movement.  
Eat food to grow your snake while avoiding collisions with walls and yourself.  
Snake II features include wrap-around and bonus items. Smooth LED movement and sound effects make it feel like the classic mobile game.

### `three_shells.py` — Three Shells  
A recreation of Master Merlin’s *Three Shells* game.  
Track the ball as it’s shuffled under three shells (K3, K4, K5).  
Skill selection (K0–K8) controls shuffle speed and number of swaps. Score is tracked across rounds.

### `tictactoe.py` — Tic Tac Toe  
A 3×3 human-vs-CPU Tic Tac Toe game.  
Human plays RED (blinking), CPU plays BLUE (steady).  
CPU can win, block, and follow basic strategies. Includes animated endgame pulses and on-screen status/legend.

---

## 🛠 Developer Notes

- All games are **self-contained classes** with `new_game()`, `button()`, and optional `tick()` methods.
- The launcher dynamically loads games and maintains a single MacroPad instance.
- LED animations use **non-blocking timing** (`time.monotonic()`), so game logic stays responsive.
- Sound playback is done with `macropad.play_tone()`, with fallbacks for missing tone lists.
- Games should avoid blocking loops — animations should progress incrementally in `tick()`.

## 📂 File Structure

- code.py             # Game launcher (menu system)
- blackjack13.py
- echo.py
- hit_or_miss.py
- hi_lo.py
- hot_potato.py
- magic_square.py
- match_it.py
- mindbender.py
- music_machine.py
- musical_ladder.py
- pair_off.py
- patterns.py
- simon.py
- snake.py             # Supports two variants - Snake and Snake II
- three_shells.py
- tictactoe.py
- my_game.py           # Sample starter template to add your own game
- MerlinChrome.bmp     # Merlin-style chrome frame for menu
- lib/                 # Required Adafruit CircuitPython libraries

## To Dos

- Add Level 2 to Match It 
- Reconfirm Sounds for all games
- Add Master Merlin games
   - Score - Will be based on Music Maker code

## Won't Dos

- 2 Player support for 
   - Match It
   - Pair Off