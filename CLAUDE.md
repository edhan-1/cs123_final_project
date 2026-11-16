# Notes for coding agents (CS 123 final project)

Pupper, a real robot dog, plays red light, green light. Read
[docs/architecture.md](docs/architecture.md) first: it explains the robot's
layers, who does what in the game (Gemini is the voice; the fast ear in the
browser page works the lights in a game by voice, the eye on the robot in a
game by camera; the robot enforces the rules), and how to use each part. [README.md](README.md) has the layout and how to run the game.

This is a student project. Explain what you change and why, keep changes small
enough to review, and write code the students can explain line by line, in the
style of `gemini_pupper/lab/` (behaviors first, then the `@tool`s).

## Safety rules (these override everything else)

1. **Never move the robot without the student's explicit OK, right then.** That
   includes `robot/start.sh`, `robot/stop.sh` while a session is running,
   `python3 game/chat.py --robot`, `curl` to any POST endpoint of the robot
   server on port 8000 (`/tools/...`, `/game/heard` and `/game/saw` all move
   it), `python3 robot/eye.py` pointed at port 8000 (its reports are what makes
   Pupper walk in a game by camera),
   `ros2 topic pub`, and anything that activates a controller. Say what will
   happen and wait. The student must be at the robot, with a hand near the
   e-stop (the gamepad's right stick).
2. **Check whether the robot is live before testing anything.**
   `pgrep -f ros2_control_node` and `ss -ltn "sport = :8000"`. If it is, leave
   port 8000 alone and test on a fake robot on another port (below).
3. **Respect the limits.** Don't raise `MoveLimits`, `GREEN_SPEED_MAX`,
   `GREEN_MAX_S`, tilt limits or gains to make something work. Anything that
   stops Pupper may be trigger-happy; anything that moves it must not be.
4. **Heat.** If the student says the robot is hot or a motor faults, stop
   testing and let it cool.
5. **No secrets in files.** The Gemini key lives in
   `~/.config/gemini-pupper/api_key`. Never write it into the repo or a log.

## Working here

- `gemini_pupper/` (next to this repo) is borrowed, not edited: its `robot/`
  folder is provided infrastructure and its `lab/` folder is the students'
  lab 6 work. Changes for the game go in `game/`, `web/` and `robot/` here.
- After a change in `game/`: `python3 game/test.py` (fake robot, fake time),
  then `python3 game/chat.py` (Gemini in text, fake robot; uses the Gemini key).
  After a change in `web/play.html`: `~/.local/node/bin/node web/test_play.js`.
  After a change in `robot/eye.py` or `robot/pose.py`: `python3 game/test.py`,
  then `python3 robot/eye.py --image <a saved camera picture>` (it needs the
  Hailo: only when the eye is not running). None of these moves anything.
- To run the real page without the robot:
  `PORT=8011 python3 robot/game_server.py --fake` (a fake robot; safe next to
  the live server). Stop it with `pkill -f "[g]ame_server.py --fake"`; the live
  server's command line has no `--fake`. For a game by camera on it:
  `python3 robot/eye.py --pretend --server http://localhost:8011` (type b, f, u).
- One program holds the Hailo. `robot/start.sh` starts the stack with the lab 5
  follower (`FOLLOW_ME_DIR`) so that the eye can have it. Saved pictures from a
  Pupper camera, for `eye.py --image`:
  `~/pupperv3-monorepo/ros2_ws/src/hailo/config/camera_image_raw_compressed-*.png`.
- The Pi has no microphone, and its headless Chromium has no speech service and
  loads pages unreliably while the robot stack is running. The word ear can
  only be tried in the student's Chrome; `web/test_play.js` covers its logic.
- Tool replies are all Gemini learns: say what happened, or what was wrong and
  what would work. Rules are enforced in the behavior, not only in the prompt
  or the page: the page reports what it heard, `heard()` decides if it counts;
  the eye reports what it sees, `saw()` decides.
- Motion goes through `robot.queue`; wait with `await robot.sleep(...)`, never
  `time.sleep`. Units: metres, seconds, degrees; +y and positive turns are left.
