# cs123_final_project
Final Project for CS123 Fall 2026

Pupper plays **red light, green light**. Pupper is the runner and a person is
the caller: say "green light" and Pupper walks toward the finish line, say "red
light" and it freezes. It wins when it has walked the whole course.

**Step 1 (this version): the lights are called by voice.** Gemini Live is
Pupper's voice, as in lab 6, and starts and ends the games. The lights
themselves are heard by a fast ear in the browser page, because Gemini takes a
second or two to act and that is too long for a red light.

- [How Pupper works, and how to build on it](docs/architecture.md): the layers
  of the robot, which lab taught which, who does what in the game, and how to
  use each part from our code.

## What's where

```
game/
  red_light_green_light.py   the game: its rules, the tools Gemini calls, what the ear may do
  prompt.md                  who Pupper is and how it plays (Gemini's system prompt)
  test.py                    python3 game/test.py   checks on a fake robot
  chat.py                    python3 game/chat.py   play in text with Gemini; nothing moves
web/
  play.html                  the page to play on: the web app in a frame, plus the fast ear
  test_play.js               node web/test_play.js   checks of the ear's logic
robot/
  start.sh, stop.sh          start and stop everything on the Pupper
  game_server.py             Gemini Pupper's robot server, with the game added (--fake: a fake robot)
  bootstrap.py               finds gemini_pupper and loads the game on top of it
docs/architecture.md
```

This repo needs **gemini_pupper next to it** (`~/labs/gemini_pupper`, set up
with its `robot/setup.sh`). We borrow its robot server, web app, robot API and
our lab 6 tools, and change nothing in it. If yours is somewhere else, set
`GEMINI_PUPPER_DIR`.

## Playing

Put Pupper on the ground at the start line, facing the finish line, with clear
floor ahead (the course is 3 m unless you say otherwise) and the gamepad in
reach: **pressing its right stick is the e-stop.**

On the Pupper:

```bash
robot/start.sh            # the robot stack and the game server (about a minute)
robot/stop.sh             # relax the motors and stop everything
```

On a laptop, in **Google Chrome**:

1. `ssh -N -L 8000:localhost:8000 pi@<pupper>`
2. Open **http://localhost:8000/play** and allow the microphone.
3. Paste the Gemini key in **Settings** and press **WAKE PUPPER**.
4. Check the bar at the top: it should say `voice ear: on · word ear: on`.

The laptop is Pupper's ears and voice: our Pupper has a speaker but no
microphone, so `robot/start.sh --kiosk` (the app on Pupper's own screen) shows
the face but cannot hear you.

Then talk to it:

| You say | Pupper |
| --- | --- |
| "Let's play red light, green light. The finish line is two meters away." | stands up at the start line and waits on red |
| "Green light!" | walks straight ahead |
| "Red light!" | freezes at the first sound of your voice, then says about how far is left |
| "Did you make it?" / "How's the game going?" | checks the game and tells you |
| "Stop." | stops (in a game, that is a red light) |
| "We're done playing." | ends the game; it can move, turn and do tricks again |

You can also play with Gemini asleep: **New game** in the bar starts a game, and
the ear does the rest. Pupper just won't talk.

## The fast ear: who works the lights

Gemini needs a second or two to turn the words "green light" or "red light" into
a tool call: it waits for the end of the sentence, thinks, and the call crosses
the internet twice. On the real robot, the browser had recognised "red light"
1.0 to 1.7 s before Gemini's call arrived, every time. So **Gemini does not work
the lights.** The page at `/play` listens to the microphone itself, in the
browser, and tells the robot directly.

The ear has two parts:

- **The word ear** is the browser's own speech recognition (it needs Google
  Chrome). It listens for "green light" and "red light" and tells the robot at
  once. While it is listening, the green lights are its job: Gemini's own
  `green_light` call changes nothing, because it arrives so late that the light
  may have turned red again by then. Gemini's `red_light` still stops Pupper
  (stopping is always allowed).
- **The voice ear** freezes Pupper the moment somebody starts to speak during a
  green light, before "red light" is even finished. If "red light" doesn't
  follow (you said "green beans", or it was a noise), Pupper walks on after 3 s:
  it flinched.

**Freeze on**, in the bar, picks what stops Pupper:

| Freeze on | What happens | When to use it |
| --- | --- | --- |
| **any voice** (default) | Both ears. Pupper stops at the first sound; the words decide whether it stays stopped. | A quiet room. Tune it with the **Sensitivity** slider: the bar next to it shows how loud the microphone is, and the white line is the level that counts as a voice. |
| **the words "red light"** | The word ear only. Pupper stops when the words are recognised, a little later than a voice. | A loud room, where voices and noise would make it flinch all the time. |
| **nothing** | No ear. Gemini works both lights, as slowly as before. | To compare. |

"Green light" always comes from the words, never from a noise.

To try the page and tune the slider without Pupper moving, run a second server
on a fake robot (it can run next to the real one) and open it through its own
tunnel:

```bash
PORT=8001 python3 robot/game_server.py --fake      # on the Pupper
ssh -N -L 8001:localhost:8001 pi@<pupper>          # on the laptop, then http://localhost:8001/play
```

## The rules, as the robot enforces them

They are in `game/red_light_green_light.py`, not in the prompt or the page, so
they hold whatever Gemini calls and whatever the ear hears.

- Only a green light moves Pupper during a game. `move`, `turn` and
  `play_trick` are refused until the game ends.
- A green light walks at 0.4 m/s (0.2 to 0.5 allowed: walking only) until a red
  light, the finish line, or 6 seconds, whichever comes first. The 6 seconds are
  there so that Pupper stops by itself if it stops hearing us.
- Anything that stops Pupper turns the light red: a red light from the ear or
  from Gemini, the `stop` tool, the gamepad e-stop, a fall.
- The ear can only change a light the right way round: a green light on red, a
  red light or a voice on green. With no game on, it does nothing.
- A voice holds Pupper still for 3 s; without a red light it then walks on. A
  voice in the first half second of a green light is ignored (it is the end of
  "green light!").
- While the word ear is listening, only the ear gives green lights. If the page
  is closed, the robot notices within 5 s and Gemini's `green_light` works again.
- "Green light" in Pupper's own voice does not count: the page ignores it while
  Pupper is talking and for a second after.
- The course is 1 to 7 m.

## Testing without the robot

```bash
python3 game/test.py     # 71 checks of the rules, on a fake robot with fake time
node web/test_play.js    # 17 checks of the ear's logic in web/play.html (node is in ~/.local/node/bin)
python3 game/chat.py     # play against Gemini in text, on a fake robot in real time
```

In the chat, type `green light`, wait two seconds, type `red light`: the reply
shows how far the fake Pupper got. It prints every tool call and what Gemini
hears back. There is no ear in the chat, so there Gemini works the lights. It
needs the Gemini key (`~/.config/gemini-pupper/api_key`).

## Limits of step 1

- **Pupper does not know where it is.** "Distance walked" is the commanded
  speed times the time walked. The real robot slips and takes a moment to get
  going, so the finish line is only about where Pupper thinks it is.
- **The ear lives in the browser, because the microphone does.** It only works
  on the `/play` page, and the word ear only in Chrome. On plain `/`, the lights
  are as slow as Gemini.
- **A stale red light can interrupt a quick green.** Say "red light" and then
  "green light" within about two seconds, and Gemini's late `red_light` for the
  first one may stop Pupper again. Say "green light" once more.
- **The voice ear cannot tell words apart.** In a loud room, switch to the words.
- **Pupper only speaks when spoken to.** The robot cannot tell Gemini that it
  crossed the finish line; Gemini finds out at its next tool call.
- **Not tried on the robot yet:** green lights from the ear, and the page
  ignoring Pupper's own voice. Both pass their checks at a desk.
