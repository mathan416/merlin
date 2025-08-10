# merlin
Recreation of the **Merlin** electronic handheld game using the Adafruit **MacroPad**, now with additional games and *Master Merlin*-inspired modes.

You will need:
- [Adafruit MacroPad Libraries](https://learn.adafruit.com/adafruit-macropad-rp2040/macropad-circuitpython-library)  
- CircuitPython **9.1** or higher (developed using **9.1.4**)

Merlin Guides:
- [Master Merlin Manual (Parker Bros.)](http://pdf.textfiles.com/manuals/HANDHELDS/ParkerBros-MasterMerlin.pdf)  
- [Original Merlin Manual](https://www.monroeworld.com/vmerlin/bin/merlinmanual.pdf)

---

## 📜 Project Overview

This project recreates and expands upon the classic *Merlin* electronic handheld game using an **Adafruit MacroPad** running CircuitPython.  
It includes a launcher system to select and start different game modes, each implemented as a separate Python class with LED, sound, and OLED display feedback.

---

## 🎮 Games

### `code.py` — Game Launcher  
The main entry point (also called `launcher.py`).  
Handles:
- Initializing MacroPad hardware, display, and sound
- Loading available games dynamically
- Showing the Merlin-style chrome logo and menu
- Navigating between games with the rotary encoder
- Launching and returning from games without rebooting

---

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

## 📥 Installation & Setup

1. **Install CircuitPython 9.1 or higher**  
   Follow Adafruit’s guide for your MacroPad:  
   <https://learn.adafruit.com/adafruit-macropad-rp2040/circuitpython>

2. **Install the required MacroPad libraries**  
   Download the latest library bundle from Adafruit and copy the following to your `lib` folder on the MacroPad:  
   - `adafruit_display_text`  
   - `adafruit_macropad`  
   - `adafruit_ticks` (if needed for non-blocking timers)  
   - Any other dependencies from the MacroPad guide.

3. **Copy this project to your MacroPad**  
   - Place all `.py` game files and `code.py` in the root of the MacroPad’s CIRCUITPY drive.  
   - Include `MerlinChrome.bmp` in the root for the launcher and games that display it.  
   - Ensure the folder structure matches what’s in this repo.

4. **Eject and reboot** the MacroPad.

---

## 🎛 Controls

### General (Launcher)
- **Rotate Encoder** → Select game from menu
- **Press Encoder** → Start selected game
- **Key 9** → Return to launcher from a game (when supported)
- **Keys** → Game-specific controls

### Game Controls Overview
| Game           | Keys Used | Encoder Use | Notes |
|----------------|-----------|-------------|-------|
| Hi Lo          | K0–K9 for number entry | None | Skill determines range |
| Mindbender     | K0–K9 for code guesses | None | Pattern logic game |
| Pair Off       | K0–K8 for card selection | None | Match hidden pairs |
| Snake / Snake II | K0–K2, K3–K5, K6–K8, K9–K11 for direction | None | Avoid collisions |
| Three Shells   | K3, K4, K5 for shells | None | K0–K8 to set skill |
| Tic Tac Toe    | K0–K8 board squares | None | K9 New, K10 Swap, K11 CPU Move |

---


