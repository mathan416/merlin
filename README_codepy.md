# Merlin Launch Architecture
Recreation of the **Merlin** electronic handheld game using the Adafruit **MacroPad**, now with additional games and *Master Merlin*-inspired modes.

Firstly — thank you to Keith Tanner for the original starting point code plus the STL files to print a case for the Macropad.

---

## 📑 Table of Contents
1. [Introduction](#merlin)
2. [📜 Code.py Architecture](#-codepy-architecture)
    - [Internal Architecture](#internal-architecture)
    - [GAMES_REG](#games_reg)
    - [start_game_by_name()](#start_game_by_name)
    - [_purge_game_modules()](#_purge_game_modules)
    - [Menu vs Game State](#menu-vs-game-state)
3. [⚠️ Known Limitations & RAM Constraints](#️-known-limitations--ram-constraints)
4. [State Diagram (Menu ↔ Game)](#state-diagram-menu--game)
5. [Event → Action Summary](#event--action-summary)
6. [🧠 RAM Handling](#-ram-handling)
    - [🧠 Why We Log RAM](#-why-we-log-ram)
    - [RAM Logging Flow](#ram-logging-flow)
    - [RAM-handling Sequence Flow](#ram-handling-sequence-flow)
7. [🚀 Porting a Game](#-porting-a-game-checklist)
    - [TL;DR Checklist](#tldr--porting-a-game)
    - [Detailed Guidance](#detail--porting-a-game)
    - [Minimal Skeleton Template](#minimal-skeleton-template)
8. [Appendix: Notes](#appendix-notes)

---

## 📜 Code.py Architecture

### Internal Architecture
- **GAMES_REG** — Registry of available games.  
  Each tuple contains:  
  `(Display Name, Module Name, Class Name, Constructor kwargs)`  
  This is the single source of truth for all loadable games.

```python
GAMES_REG = [
    ("Blackjack 13",  "blackjack13",   "blackjack13",   {}),
    ("Echo",          "echo",          "echo",          {}),
    ("Hit or Miss",   "hit_or_miss",   "hit_or_miss",   {}),
    ("Hi/Lo",         "hi_lo",         "hi_lo",         {}),
    ("Hot Potato",    "hot_potato",    "hot_potato",    {}),
    ("Magic Square",  "magic_square",  "magic_square",  {}),
    ("Match it",      "match_it",      "match_it",      {}),
    ("Mindbender",    "mindbender",    "mindbender",    {}),
    ("Music Machine", "music_machine", "music_machine", {}),
    ("Pair Off",      "pair_off",      "pair_off",      {}),
    ("Simon",         "simon",         "simon",         {}),
    ("Snake",         "snake",         "snake",         {"snake2": False}),
    ("Snake II",      "snake",         "snake",         {"snake2": True}),
    ("Three Shells",  "three_shells",  "three_shells",  {}),
    ("Tic Tac Toe",   "tictactoe",     "tictactoe",     {}),
]
game_names = [n for (n, _, _, _) in GAMES_REG]
```

### start_game_by_name()
Loads and starts a game:
1. Optionally plays the LED “wipe” animation.
2. Purges only the game modules listed in `GAMES_REG` from `sys.modules`.
3. Imports the game module and retrieves the target class.
4. Attempts to construct the game object with several possible signatures.
5. Calls the game’s `new_game()` method and sets its display group.

### _purge_game_modules()
Frees RAM by removing all known game modules from `sys.modules`, then calls `gc.collect()`.

### Menu vs Game State
Controlled by `mode_menu` flag.  
- When `mode_menu` is `True`: rotary encoder scrolls menu, press starts game.  
- When `False`: encoder and keys are passed to the active game’s handlers.

---

## ⚠️ Known Limitations & RAM Constraints

### CircuitPython 9.x RAM Environment
The Adafruit MacroPad M4 has **192 KB SRAM** total, with **CircuitPython 9.x** consuming a larger portion at boot than earlier versions.

**Safe practice:**  
- Keep total free RAM above **20 KB** during gameplay to avoid random crashes.  
- Expect large `.bmp` or `.wav` assets to consume memory *very quickly*.  
- Use **OnDiskBitmap** for images instead of loading into RAM.  
- Always `gc.collect()` after freeing large assets.

### Strategies to Stay RAM-Safe
- Lazy-load only what’s needed for the active game.
- Purge modules (`_purge_game_modules`) aggressively when switching games.
- Avoid long-lived global references to large objects.
- Prefer integer math over large float arrays.
- For sound: keep `.wav` short; loop in software rather than storing multiple long clips.

---

## State Diagram (Menu ↔ Game)
```
  ┌─────────────────────────────────────────────────────────┐
  │                         MENU                            │
  │  - Encoder rotates: highlight selection                 │
  │  - Encoder press: start_game_by_name(sel)               │
  └───────────────┬─────────────────────────────────────────┘
                  │ (encoder press)
                  ▼
  ┌─────────────────────────────────────────────────────────┐
  │                         GAME                            │
  │  - tick() called every loop                             │
  │  - key events routed to game.button()/button_up()       │
  │  - optional encoder routed to game.encoderChange()      │
  │                                                         │
  │  (encoder press)                                        │
  │    → game.cleanup() if present                          │
  │    → _purge_game_modules() + gc.collect()               │
  │    → return to MENU                                     │
  └───────────────┬─────────────────────────────────────────┘
                  │ (encoder press)
                  ▼
  ┌─────────────────────────────────────────────────────────┐
  │                         MENU                            │
  └─────────────────────────────────────────────────────────┘
```

---

## Event → Action Summary
| Event                    | Action                                                                |
|--------------------------|------------------------------------------------------------------------|
| **Boot**                 | Build menu group; show first game name                                |
| Encoder rotate (MENU)    | Update selection label                                                 |
| Encoder press  (MENU)    | `start_game_by_name(sel)`: RAM snapshot + optional wipe → purge modules → import module/class → construct game → `new_game()` + set display group |
| Encoder rotate (GAME)    | If game has `encoderChange()`, call it                                 |
| Keys (GAME)              | Route to `game.button()` / `button_up()`                              |
| Encoder press  (GAME)    | Exit game: snapshot → `cleanup()` → purge modules → GC → RAM delta → return to menu |

---

## 🧠 RAM Handling
### 🧠 Why We Log RAM
CircuitPython has **no virtual memory**—if you run out of RAM, the interpreter stops with `MemoryError`.  
Logging RAM lets us:
- Track asset-heavy games that push limits.
- Spot memory leaks from games not cleaning up.
- Compare pre-load and post-cleanup RAM usage.


---

### RAM Logging Flow
| Log line (prefix)                              | When it happens                                 |
|-----------------------------------------------|--------------------------------------------------|
| `[RAM] Boot start`                             | Immediately after import/setup begins            |
| `[RAM] After setup complete`                   | Right before entering the main loop              |
| `[RAM] After purge`                            | After targeted module purge + `gc.collect()`     |
| `[RAM Δ] Global wipe`                          | After the LED wipe animation finishes            |
| `[RAM] Before loading {name}`                  | At the start of `start_game_by_name()`           |
| `[RAM Δ] After purge (pre-load {name})`        | After purging old game modules (pre-import)      |
| `[RAM Δ] Imported module {module}`             | After `__import__(module)` + class lookup        |
| `[RAM Δ] Constructed {ClassName}`              | After successfully constructing the game object  |
| `[RAM Δ] Total delta after loading {name}`     | After GC, comparing to the pre-load snapshot     |
| `[RAM Δ] After unloading game & purge`         | When exiting a game back to menu                 |
| `[RAM] Returned to menu`                       | After returning to the menu UI                   |

---

### 📊 Example RAM Usage Log

This is an example of healthy RAM usage when loading and unloading a game.  
Use it as a benchmark — if your game shows significantly higher deltas, you may need to optimize.

```
[RAM] Boot start:  Free=58240  Alloc=108000
[RAM] After setup complete:  Free=55408  Alloc=110832
[RAM] Before loading Snake:  Free=55296  Alloc=110944
[RAM Δ] Global wipe:  ΔFree=-64  ΔAlloc=+64
[RAM] After purge:  Free=56736  Alloc=109504
[RAM Δ] After purge (pre-load Snake):  ΔFree=+1440  ΔAlloc=-1440
[RAM Δ] Imported module snake:  ΔFree=-3200  ΔAlloc=+3200
[RAM Δ] Constructed snake:  ΔFree=-4096  ΔAlloc=+4096
[RAM Δ] Total delta after loading Snake:  ΔFree=-5376  ΔAlloc=+5376
[RAM Δ] After unloading game & purge:  ΔFree=+5312  ΔAlloc=-5312
[RAM] Returned to menu:  Free=56704  Alloc=109536
```

**Interpretation tips:**
- **ΔFree** should be near zero after unloading & purge.
- Large negative deltas after load indicate big memory spikes — check image/audio sizes.
- If **Free** RAM drops below ~20 KB during gameplay, you risk `MemoryError` crashes.
- If **ΔFree** after unload stays negative, there may be lingering references (memory leak).

---

### RAM-handling Sequence Flow
```mermaid
sequenceDiagram
  autonumber
  participant U as Encoder Press (User)
  participant L as Main Loop
  participant R as RAM Logs
  participant W as play_global_wipe()
  participant P as _purge_game_modules()
  participant I as Import + getattr
  participant C as Game Constructor
  participant G as Game Instance
  participant D as Display Root

  %% Boot & setup
  Note over L,R: [RAM] Boot start
  L->>R: ram_report("Boot start")
  L->>D: build_menu_group()
  L->>D: set root_group
  Note over L,R: [RAM] After setup complete
  L->>R: ram_report("After setup complete")

  %% Start game from menu
  U->>L: Press encoder (in menu)
  L->>R: ram_report("Before loading {name}")

  alt name NOT in SKIP_WIPE
    L->>W: play_global_wipe(macropad)
    W->>R: ram_report_delta(snap_wipe, "Global wipe")
    Note over W,R: [RAM Δ] Global wipe
  else name in SKIP_WIPE
    Note over L: Skip wipe (Echo)
  end

  %% Purge old game modules
  L->>P: _purge_game_modules()
  P->>P: del sys.modules[...]
  P->>P: gc.collect()
  P->>R: ram_report("After purge")
  Note over P,R: [RAM] After purge
  L->>R: ram_report_delta(snap_before, "After purge (pre-load {name})")
  Note over L,R: [RAM Δ] After purge (pre-load {name})

  %% Import module + class
  L->>R: snap_import = ram_snapshot()
  L->>I: __import__(module_name)
  L->>I: getattr(class_name)
  I->>R: ram_report_delta(snap_import, "Imported module {module_name}")
  Note over I,R: [RAM Δ] Imported module {module_name}

  %% Construct game
  L->>R: snap_construct = ram_snapshot()
  L->>C: Try constructors with fallbacks
  C->>R: ram_report_delta(snap_construct, "Constructed {ClassName}")
  Note over C,R: [RAM Δ] Constructed {ClassName}

  %% Post-load + start
  L->>L: gc.collect()
  L->>R: ram_report_delta(snap_before, "Total delta after loading {name}")
  Note over L,R: [RAM Δ] Total delta after loading {name}
  L->>G: game.new_game()
  alt game has group
    L->>D: set display.root_group to game.group
  end

  %% Gameplay loop (simplified)
  loop While playing
    L->>G: tick()
    U->>G: button()/button_up()
    U->>L: encoder press to exit
  end

  %% Exit game → back to menu
  U->>L: Press encoder (exit)
  L->>R: snap_pre_unload = ram_snapshot()
  opt game has cleanup()
    L->>G: cleanup()
  end
  L->>L: current_game = None
  L->>P: _purge_game_modules()
  P->>L: gc.collect()
  L->>R: ram_report_delta(snap_pre_unload, "After unloading game & purge")
  Note over L,R: [RAM Δ] After unloading game & purge
  L->>R: ram_report("Returned to menu")
  Note over L,R: [RAM] Returned to menu
  L->>D: enter_menu()

  %% ---- COLOR STYLES ----
  %% Normal RAM reports = green
  style 2 stroke:#22aa22,stroke-width:2px
  style 6 stroke:#22aa22,stroke-width:2px
  style 18 stroke:#22aa22,stroke-width:2px
  style 40 stroke:#22aa22,stroke-width:2px

  %% RAM delta reports = orange
  style 13 stroke:#ff8800,stroke-width:2px
  style 22 stroke:#ff8800,stroke-width:2px
  style 31 stroke:#ff8800,stroke-width:2px
  style 36 stroke:#ff8800,stroke-width:2px
  style 43 stroke:#ff8800,stroke-width:2px
  style 53 stroke:#ff8800,stroke-width:2px
```

---

## 🚀 Porting a Game (Checklist)

### TL;DR – Porting a Game
1. **Constructor** – support at least one of:  
   ```python
   def __init__(self, macropad, tones, **kwargs)  # preferred
   def __init__(self, macropad, **kwargs)
   def __init__(self, macropad, tones)
   def __init__(self, macropad)
   ```
2. **Must-have methods** – `new_game()`, `button(key)`, `tick()`, `cleanup()`.
3. **Display** – set `self.group = displayio.Group()`; launcher will show it.
4. **LED etiquette** – batch pixel updates, restore state in `cleanup()`.
5. **Non-blocking** – no long sleeps; use `time.monotonic()` for timing.
6. **Optional** – `button_up(key)`, `encoderChange(pos, last_pos)`.
7. **RAM-safe** – lazy-load assets, store state on `self`, no global refs to other games.

---

### Detail – Porting a Game

#### 1) Constructor Signatures
Preferred:
```python
def __init__(self, macropad, tones, **kwargs)
```
Fallbacks:
- `__init__(self, macropad, **kwargs)`
- `__init__(self, macropad, tones)`
- `__init__(self, macropad)`

#### 2) Required Methods
- `new_game()` – initialize state/graphics/audio.
- `button(key)` – handle key down for 0–11.
- `tick()` – non-blocking per-frame work (animations, timers).
- `cleanup()` – restore LEDs/auto_write/brightness; stop sounds.

_Optional_:  
- `button_up(key)` – if you need key-up.  
- `encoderChange(position, last_position)` – if you use the knob.

#### 3) Display Group
- Create `self.group = displayio.Group()` and populate it.
- After `new_game()`, the launcher will set `macropad.display.root_group = game.group` if present.
- Don’t call `show()` from outside your class; inside, prefer:
  - CP 8.x: `mac.display.show(self.group)`
  - CP 9.x: `mac.display.root_group = self.group`

#### 4) LED Etiquette
- Batch updates:
```python
try: self.mac.pixels.auto_write = False
except AttributeError: pass
self.mac.pixels.brightness = 0.30
```
- Minimize `.show()` calls.
- On `cleanup()`:
```python
for i in range(12): self.mac.pixels[i] = 0
try: self.mac.pixels.show()
except AttributeError: pass
try: self.mac.pixels.auto_write = True
except AttributeError: pass
```

#### 5) Timing Model
- Use `time.monotonic()` and step logic at intervals.
- Avoid busy-waiting.

#### 6) Input Handling
- Expect key indices 0–11.
- Ignore unknown keys gracefully.

#### 7) Sound
```python
def _play(self, f, d):
    try: self.mac.play_tone(f, d)
    except Exception: pass
```

#### 8) Assets & RAM
- Lazy-load.
- Avoid globals holding other games' state.

#### 9) Files / High Scores
- Keep small and unique per-game.

#### 10) Pause / Menu Return
- Ensure `cleanup()` leaves hardware in safe state.

---

### Minimal Skeleton Template
```python
import time, displayio, terminalio
from adafruit_display_text import label

class my_game:
    def __init__(self, macropad, tones=None, **kwargs):
        self.mac = macropad
        self.tones = tones or ()
        try: self.mac.pixels.auto_write = False
        except AttributeError: pass
        self.mac.pixels.brightness = 0.30
        self.group = displayio.Group()
        self.title = label.Label(terminalio.FONT, text="My Game", color=0xFFFFFF,
                                 anchor_point=(0.5, 0.0),
                                 anchored_position=(self.mac.display.width//2, 0))
        self.group.append(self.title)
        self._interval = 0.15
        self._next_step = time.monotonic()

    def new_game(self):
        self._next_step = time.monotonic() + self._interval
        for i in range(12): self.mac.pixels[i] = 0
        try: self.mac.pixels.show()
        except AttributeError: pass

    def button(self, key):
        pass

    def tick(self):
        now = time.monotonic()
        if now >= self._next_step:
            self._step()
            self._next_step = now + self._interval

    def _step(self):
        pass

    def encoderChange(self, pos, last_pos):
        pass

    def cleanup(self):
        for i in range(12): self.mac.pixels[i] = 0
        try: self.mac.pixels.show()
        except AttributeError: pass
        try: self.mac.pixels.auto_write = True
        except AttributeError: pass
```

---

## Appendix: Notes
- `SKIP_WIPE` controls which titles bypass the startup LED wipe.
- Snake kwarg adapter: `{"snake2": bool}` → `{"wraparound": bool}` before construct.