# cs123_final_project
Final Project for CS123 Fall 2026

Pupper plays **red light, green light**. Pupper is the runner and a person is
the caller. On a green light Pupper walks toward the finish line, on a red
light it freezes. It wins when it has walked the whole course.

A game is played in one of two ways, chosen when it starts:

- **By voice (step 1).** Say "green light" and "red light". Gemini Live is
  Pupper's voice, as in lab 6, and starts and ends the games. The lights
  themselves are heard by a fast ear in the browser page, because Gemini takes a
  second or two to act and that is too long for a red light.
- **By camera (step 2).** Turn your back to Pupper and it walks; turn around and
  face it and it freezes, as on the playground. Pupper watches with its own
  camera: an eye on the robot finds your nose, eyes and shoulders about ten
  times a second and tells the game which way you are turned.

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
  eye.py                     the eye: is the caller's back turned? (--image: try it on a saved picture)
  pose.py                    the pose model on the Hailo that the eye looks through
  bootstrap.py               finds gemini_pupper and loads the game on top of it
docs/architecture.md
```

This repo needs **gemini_pupper next to it** (`~/labs/gemini_pupper`, set up
with its `robot/setup.sh`). We borrow its robot server, web app, robot API and
our lab 6 tools, and change nothing in it. If yours is somewhere else, set
`GEMINI_PUPPER_DIR`. Games by camera also need **follow_me_pupper next to it**
(lab 5; see "The eye" below for why) and the pose model that comes with the
Pi's Hailo software (`/usr/share/hailo-models/yolov8s_pose_h8l_pi.hef`).

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

To play **by camera**, stand at the finish line, straight ahead of Pupper, and
say so, or set **Lights** in the bar to "by camera" and press **New game**:

| You | Pupper |
| --- | --- |
| "Let's play, but I'll turn my back instead of calling out." | stands up and waits on red |
| face Pupper, then turn your back | walks, about half a second after your back is turned |
| turn around and face it | freezes |
| step out of view, or stand side-on | holds still until it sees your back again |
| keep your back turned for 6 s | stops by itself; face it and turn away again |
| "Stop." / "Red light." | stops; face it and turn away again to go on |

The small picture in the bar is what the eye sees (point at it to enlarge it):
your box, the points it found, and its word, `facing`, `back` or `unsure`.

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

## The eye: who works the lights in a game by camera

`robot/eye.py` runs on the robot, next to the game server. About ten times a
second it takes the newest camera picture, cuts out the part straight ahead and
flattens it (the camera is a fisheye), and runs a pose model on the Hailo
(`robot/pose.py`). The model gives 17 points for every person, each with a
score for how sure it is that it can see that point. The eye picks the caller,
the tallest person in the middle of the picture, and says one word:

| The eye says | When |
| --- | --- |
| `facing` | it sees at least two of nose, left eye, right eye; or the shoulders are the front way round (your left shoulder on the right of the picture) |
| `back` | it sees none of the three, and the shoulders are the other way round and well apart |
| `unsure` | anything else: nobody in the middle, somebody side-on, a blurry picture |

`facing` needs one clue and `back` needs both, because a back is what makes
Pupper walk. The eye only reports (`POST /game/saw`). What the word does is
decided by `saw()` in `game/red_light_green_light.py`:

- **A green light is a turn.** The eye must have seen you facing Pupper, and
  then your back for half a second without a break. A coat on a chair that
  looks like a back cannot start Pupper, because it never looked at it.
- **Pupper walks only while `back` keeps arriving.** `unsure`, or half a second
  without a report (the eye crashed, the camera froze), and it stands still. The
  light stays green: it walks on at the next `back`.
- **`facing` is a red light**, at once.

The eye needs the Hailo, and only one program can hold it. The robot stack's
own person detector would hold it all day, so `robot/start.sh` starts the stack
with our lab 5 follower instead (`FOLLOW_ME_DIR`), which only takes the Hailo
while Pupper follows somebody. If the eye cannot start, games by camera are
refused and the reply says why; games by voice work as before.

To see what the eye makes of a picture, without the robot stack running:

```bash
python3 robot/eye.py --image some_camera_frame.jpg --out seen.jpg
```

And to try the page and the rules at a desk, be the eye yourself, on a fake
robot:

```bash
PORT=8001 python3 robot/game_server.py --fake                     # in one terminal
python3 robot/eye.py --pretend --server http://localhost:8001     # in another: type b, f or u
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

In a game by camera, the first three rules hold as they are, and:

- Only the eye gives green lights. Gemini's `green_light` and the ear's "green
  light" are refused, and a voice does not freeze Pupper.
- A green light needs a turn: the eye sees you facing Pupper, then your back
  for 0.5 s. After any stop, you have to face it and turn away again.
- Pupper walks only while the eye sees your back. If the eye is unsure, or
  quiet for 0.5 s, Pupper holds still until it sees your back again.
- A game by camera cannot start unless the eye is running.

## Testing without the robot

```bash
python3 game/test.py     # 118 checks of the rules and of the eye's judgement, on a fake robot with fake time
node web/test_play.js    # 24 checks of the page's logic in web/play.html (node is in ~/.local/node/bin)
python3 game/chat.py     # play against Gemini in text, on a fake robot in real time
```

In the chat, type `green light`, wait two seconds, type `red light`: the reply
shows how far the fake Pupper got. It prints every tool call and what Gemini
hears back. There is no ear in the chat, so there Gemini works the lights. There
is no eye either, so a game by camera is refused. It needs the Gemini key
(`~/.config/gemini-pupper/api_key`).

## Limits

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
- **Not tried on the robot yet: the whole game by camera.** At a desk the eye
  was right on five saved pictures from a Pupper camera (three facing, one
  back, one too close to tell), and ran against a fake robot. It has not seen a
  live camera, a walking Pupper's shaking picture, or a person turning. Expect
  to tune the numbers at the top of `robot/eye.py` with the picture in the bar.
- **The eye needs to see your head and shoulders.** Closer than about 1 m your
  head is above its view and it says `unsure`, so stand a step behind the
  finish line. Far away (5 m and more) a face is only a few pixels and the
  shoulders are the main clue.
- **Anyone in the middle of the picture can be the caller.** The eye takes the
  tallest person there. Bystanders should stand to the side.
- **`start.sh` now starts the stack with our lab 5 follower.** That was not
  tried on the robot before. The follower starts cleanly by itself; the `follow`
  tool is not part of the game.
