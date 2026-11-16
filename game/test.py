#!/usr/bin/env python3
"""Desk tests for red light, green light: no robot, no ROS, no Gemini needed.

    python3 game/test.py

They use the fake robot from gemini_pupper/robot/test_tools.py: it records every
speed command and controller switch, and its time is fake, so a 6 s green light
takes no real time. Each test calls the tools the way Gemini does, or heard()
the way the fast ear's page does (POST /game/heard), or saw() the way the eye
does (POST /game/saw), and checks what the robot was told and what the caller
hears. The page's own logic is checked by node web/test_play.js. The eye's
judgement (is this a back?) is checked here too, on made-up people: no camera
and no Hailo needed.

Passing these does not mean the robot is ready: that is what the real Pupper,
clear floor and a hand near the e-stop are for.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "robot"))
import bootstrap  # noqa: E402

bootstrap.add_paths()
import test_tools as tt  # noqa: E402  installs the fake ROS and loads the lab's tools

game = bootstrap.load_game()  # after test_tools: the game imports robot_api
import numpy as np  # noqa: E402

import eye  # noqa: E402  robot/eye.py: only its judgement is used here
import pose  # noqa: E402  robot/pose.py
from test_tools import Rig, check, tools  # noqa: E402

GAME_TOOLS = ["start_game", "green_light", "red_light", "game_status", "end_game"]


async def run_for(rig: Rig, seconds: float) -> None:
    """Let the fake robot run for this many fake seconds, without emptying the queue."""
    end = rig.clock.now + seconds
    for _ in range(100_000):
        if rig.clock.now >= end - 1e-9:
            return
        if rig.ts.commands.empty() and rig.ts.current is None:
            break  # nothing is running: only the clock moves
        await asyncio.sleep(0)
    rig.clock.now = max(rig.clock.now, end)


async def call(rig: Rig, name: str, **args):
    """Call a tool the way Gemini does, and DON'T wait for its job (rig.call does)."""
    res = await tools.call(rig.ts, name, args)
    await asyncio.sleep(0)
    return res


def moving(rig: Rig, since: int = 0):
    """The speed commands that move the robot, as (vx, vy, wz), from published[since:]."""
    out = []
    for _, topic, m in rig.robot.published[since:]:
        if topic == "/llm_cmd_vel" and abs(m.linear.x) + abs(m.linear.y) + abs(m.angular.z) > 1e-9:
            out.append((round(m.linear.x, 3), round(m.linear.y, 3), round(m.angular.z, 3)))
    return out


def standing_still(rig: Rig) -> bool:
    """Is the last speed command a zero?"""
    twists = rig.robot.twists()
    return bool(twists) and not any((twists[-1][1].linear.x, twists[-1][1].linear.y, twists[-1][1].angular.z))


def phase(rig: Rig) -> str:
    return game.game_of(rig.ts).phase


# ----------------------------------------------------------------------------- the tests
async def test_tools_offered() -> None:
    print("What Gemini is offered")
    rig = Rig()
    try:
        names = [d["name"] for d in tools.declarations(rig.ts)]
        check("the five game tools and the lab tools the game keeps, nothing else",
              sorted(names) == sorted(GAME_TOOLS + game.LAB_TOOLS), f"offered: {names}")
        decls = {d["name"]: d for d in tools.declarations(rig.ts)}
        check("every game tool has a real description",
              all(len(decls[n]["description"]) >= 20 for n in GAME_TOOLS))
        check("green_light's words give the time limit",
              f"{game.GREEN_MAX_S:g} s" in decls["green_light"]["description"])
        check("move's words say it is refused during a game", "end_game" in decls["move"]["description"])
        lights = decls["start_game"]["parameters"]["properties"].get("lights", {})
        check("start_game offers the lights by voice or by camera", lights.get("enum") == [game.VOICE, game.CAMERA], f"got {lights}")
        prompt = bootstrap.PROMPT_FILE.read_text()
        check("game/prompt.md names every game tool", all(n in prompt for n in GAME_TOOLS),
              f"missing: {[n for n in GAME_TOOLS if n not in prompt]}")
    finally:
        rig.close()


async def test_no_game() -> None:
    print("Before a game")
    rig = Rig()
    try:
        res = await rig.call("green_light")
        check("green_light is refused, and says to start a game", not res.ok and "start_game" in res.message, f"got {res}")
        check("... and the robot is sent no speed", not moving(rig))
        res = await rig.call("red_light")
        check("red_light still stops (always safe), and says no game is on", res.ok and "No game" in res.message, f"got {res}")
        res = await rig.call("move", direction="forward")
        check("move works: the lab's tools are free between games", res.ok and moving(rig), f"got {res}")
    finally:
        rig.close()


async def test_start() -> None:
    print("start_game")
    rig = Rig()
    try:
        res = await rig.call("start_game", distance=50)
        check("a 50 m course is refused, with the limit", not res.ok and f"{game.COURSE_MAX_M:g}" in res.message, f"got {res}")
        check("... and no game starts", phase(rig) == game.NO_GAME)
        res = await rig.call("start_game")
        check("start_game is accepted", res.ok and "New game" in res.message, f"got {res}")
        check("the light is red", phase(rig) == game.RED)
        check("Pupper stands (locomotion holds the legs) and has not walked",
              tt.LOCOMOTION_CONTROLLER in rig.robot.active() and not moving(rig))
        res = await rig.call("game_status")
        check("game_status says red, and the whole course is left",
              "red light" in res.message and f"{game.COURSE_DEFAULT_M:.1f} m to the finish" in res.message, f"got {res}")
    finally:
        rig.close()


async def test_green_then_red() -> None:
    print("Green light, then red light")
    rig = Rig()
    try:
        await rig.call("start_game")
        res = await call(rig, "green_light")
        check("green_light is accepted", res.ok and "Green light" in res.message, f"got {res}")
        await run_for(rig, 2.0)
        check("Pupper walks straight ahead at the walking speed",
              set(moving(rig)) == {(game.GREEN_SPEED, 0.0, 0.0)}, f"speeds sent: {set(moving(rig))}")
        check("the light is green", phase(rig) == game.GREEN)
        res = await call(rig, "green_light")
        check("a second green_light says it is already green", res.ok and "already" in res.message, f"got {res}")
        res = await call(rig, "red_light")
        check("red_light stops Pupper: the last speed sent is zero", res.ok and standing_still(rig), f"got {res}")
        sent = len(rig.robot.published)
        await run_for(rig, 2.0)
        check("... and it stays stopped", not moving(rig, sent), f"sent after red: {moving(rig, sent)}")
        walked = game.game_of(rig.ts).walked
        check("about 0.8 m walked (2 s at 0.4 m/s)", 0.7 <= walked <= 0.9, f"walked {walked:.2f} m")
        check("the reply gives the distance walked and left", "0.8 m walked" in res.message and "to the finish" in res.message, f"got {res}")
        check("the light is red", phase(rig) == game.RED)
        res = await rig.call("move", direction="forward")
        check("move is refused on red, and says how to get out", not res.ok and "end_game" in res.message, f"got {res}")
        res = await tools.call(rig.ts, "play_trick", {"name": "bow"})  # (rig.call's own first argument is called name)
        await rig.settle()
        check("play_trick is refused during a game", not res.ok and "end_game" in res.message, f"got {res}")
        check("... and neither moved the robot", not moving(rig, sent))
    finally:
        rig.close()


async def test_finish() -> None:
    print("Reaching the finish line")
    rig = Rig()
    try:
        await rig.call("start_game", distance=2)
        await call(rig, "green_light")
        await run_for(rig, 2.0)
        await call(rig, "red_light")
        res = await rig.call("green_light")  # rig.call waits: this one walks to the finish line (1.2 m, 3 s)
        check("the second green light is accepted", res.ok, f"got {res}")
        g = game.game_of(rig.ts)
        check("Pupper stops by itself at the finish line", g.phase == game.FINISHED and standing_still(rig), f"phase {g.phase}")
        check("it walked the course, no further", abs(g.walked - 2.0) < 0.05, f"walked {g.walked:.2f} m")
        check("the time counts the red light too (2 s + 3 s walking)", g.time is not None and 4.9 <= g.time <= 5.2, f"time {g.time}")
        res = await rig.call("game_status")
        check("game_status says the game is over, with the time", "game over" in res.message and "5." in res.message, f"got {res}")
        sent = len(rig.robot.published)
        res = await rig.call("green_light")
        check("a green light after the finish is refused", not res.ok and "over" in res.message and not moving(rig, sent), f"got {res}")
        res = await tools.call(rig.ts, "play_trick", {"name": "bow"})  # (rig.call's own first argument is called name)
        await rig.settle()
        check("a victory trick is allowed once the game is over", res.ok, f"got {res}")
    finally:
        rig.close()


async def test_nobody_calls_red() -> None:
    print("Nobody calls red light")
    rig = Rig()
    try:
        await rig.call("start_game", distance=7)
        await rig.call("green_light")  # waits until the job ends by itself
        g = game.game_of(rig.ts)
        check(f"Pupper stops by itself after {game.GREEN_MAX_S:g} s", g.phase == game.RED and standing_still(rig), f"phase {g.phase}")
        check("... having walked 2.4 m", abs(g.walked - game.GREEN_SPEED * game.GREEN_MAX_S) < 0.05, f"walked {g.walked:.2f} m")
        res = await rig.call("game_status")
        check("game_status tells Gemini why it stopped", "nobody called red light" in res.message, f"got {res}")
    finally:
        rig.close()


async def test_speed() -> None:
    print("The speed of a green light")
    rig = Rig()
    try:
        await rig.call("start_game")
        res = await rig.call("green_light", speed=1.2)
        check("running is refused, with the limit", not res.ok and f"{game.GREEN_SPEED_MAX:g}" in res.message, f"got {res}")
        check("... and nothing moves", not moving(rig) and phase(rig) == game.RED)
        await call(rig, "green_light", speed=game.GREEN_SPEED_MAX)
        await run_for(rig, 1.0)
        check("the fastest walk is allowed", set(moving(rig)) == {(game.GREEN_SPEED_MAX, 0.0, 0.0)}, f"sent {set(moving(rig))}")
        await call(rig, "red_light")
    finally:
        rig.close()


async def test_other_stops() -> None:
    print("Other things that stop Pupper")
    rig = Rig()
    try:
        await rig.call("start_game")
        await call(rig, "green_light")
        await run_for(rig, 1.0)
        res = await call(rig, "stop")
        check("the stop tool turns the light red", res.ok and phase(rig) == game.RED and standing_still(rig), f"got {res}")

        await call(rig, "green_light")
        await run_for(rig, 1.0)
        await rig.ts.emergency_stop()  # the gamepad e-stop: motors relaxed
        check("the gamepad e-stop turns the light red", phase(rig) == game.RED)
        sent = len(rig.robot.published)
        res = await call(rig, "green_light")
        check("the next green light says it stands up first", res.ok and "standing up" in res.message, f"got {res}")
        await run_for(rig, tt.WALK_READY_S - 0.5)
        check("... and does not walk while standing up", not moving(rig, sent))
        await run_for(rig, 1.5)
        check("... then walks", bool(moving(rig, sent)))

        rig.ts.fallen = tt.LOCOMOTION_CONTROLLER  # a fall while walking
        await run_for(rig, 0.5)
        check("a fall ends the green light and stops the speed commands", phase(rig) == game.RED and standing_still(rig))
        res = await rig.call("green_light")
        check("green_light after a fall is refused, and says the robot fell", not res.ok and "fell" in res.message, f"got {res}")
    finally:
        rig.close()


async def test_end_and_restart() -> None:
    print("Ending and restarting")
    rig = Rig()
    try:
        await rig.call("start_game")
        await call(rig, "green_light")
        await run_for(rig, 1.0)
        res = await call(rig, "start_game", distance=4)
        await rig.settle()
        g = game.game_of(rig.ts)
        check("start_game during a game starts over: red, 0 m walked, the new course",
              res.ok and g.phase == game.RED and g.walked == 0 and g.course == 4 and standing_still(rig), f"got {res}; {g}")
        await call(rig, "green_light")
        await run_for(rig, 1.0)
        res = await call(rig, "end_game")
        check("end_game stops Pupper and says how far it got", res.ok and "0.4 m walked" in res.message and standing_still(rig), f"got {res}")
        check("no game is on afterwards", phase(rig) == game.NO_GAME)
        sent = len(rig.robot.published)
        res = await rig.call("turn", direction="left")
        check("turn works again", res.ok and bool(moving(rig, sent)), f"got {res}")
    finally:
        rig.close()


async def test_fast_ear() -> None:
    print("The fast ear (what the browser page tells the robot directly)")
    rig = Rig()
    try:
        heard = lambda what: game.heard(rig.ts, what)  # noqa: E731  what POST /game/heard runs
        res = await heard("green light")
        check("with no game on, 'green light' from the ear moves nothing", not res.ok and not moving(rig), f"got {res}")
        await call(rig, "start_game")  # the stand-up is queued, not done
        res = await heard("red light")
        await rig.settle()
        check("on red a 'red light' is ignored, and does not cancel the stand-up",
              not res.ok and not any("cancelled" in o for o in rig.outcomes()), f"got {res}; {rig.outcomes()}")
        res = await heard("a dog barking")
        check("the ear only says what the robot knows", not res.ok and "voice" in res.message, f"got {res}")

        res = await heard("green light")
        check("'green light' from the ear is a green light", res.ok and phase(rig) == game.GREEN, f"got {res}")
        await run_for(rig, 0.2)
        res = await heard("voice")
        check(f"a voice in the first {game.DEAF_S:g} s of a green light is ignored", not res.ok, f"got {res}")
        await run_for(rig, 0.8)
        check("... and Pupper is walking", set(moving(rig)) == {(game.GREEN_SPEED, 0.0, 0.0)}, f"sent {set(moving(rig))}")
        res = await heard("green light")
        check("a second 'green light' changes nothing", not res.ok, f"got {res}")
        res = await heard("voice")
        check("a voice during a green light freezes Pupper at once", res.ok and standing_still(rig), f"got {res}")
        sent, walked = len(rig.robot.published), game.game_of(rig.ts).walked
        await run_for(rig, game.HOLD_S - 0.5)
        g = game.game_of(rig.ts)
        check("... it holds still, the light stays green, and the distance does not grow",
              not moving(rig, sent) and g.phase == game.GREEN and g.walked - walked < 0.03,  # 0.03: at most the step it was in
              f"sent {moving(rig, sent)[:3]}; {g}")
        res = await call(rig, "game_status")
        check("game_status says it is holding for a voice", "voice" in res.message, f"got {res}")
        await run_for(rig, 1.5)
        check("with no red light, Pupper walks on by itself", bool(moving(rig, sent)) and phase(rig) == game.GREEN)

        await heard("voice")
        res = await call(rig, "red_light")
        check("Gemini's red_light during the hold makes it a red light, and Gemini is told the voice came first",
              res.ok and phase(rig) == game.RED and "voice" in res.message, f"got {res}")
        sent = len(rig.robot.published)
        await run_for(rig, game.HOLD_S + 1.0)
        check("... and Pupper does not walk on when the hold runs out", not moving(rig, sent))
        check("about 0.8 m walked (two 1 s walks): the hold was not counted", abs(game.game_of(rig.ts).walked - 0.8) < 0.1,
              f"walked {game.game_of(rig.ts).walked:.2f} m")

        await heard("green light")
        await run_for(rig, 1.0)
        res = await heard("red light")
        check("the words 'red light' from the ear are a red light", res.ok and phase(rig) == game.RED and standing_still(rig), f"got {res}")
        res = await call(rig, "red_light")
        check("Gemini's own red_light then says Pupper was already still, and why",
              res.ok and "already standing still" in res.message and "ear" in res.message, f"got {res}")
    finally:
        rig.close()


async def test_who_gives_the_green_light() -> None:
    print("Who gives the green light: the ear while it listens, else Gemini")
    rig = Rig()
    try:
        heard = lambda what: game.heard(rig.ts, what)  # noqa: E731
        await rig.call("start_game")
        await heard("listening")
        # "green light!" ... "red light!": the ear did both; Gemini's green_light arrives only now.
        await heard("green light")
        await run_for(rig, 1.0)
        await heard("red light")
        sent = len(rig.robot.published)
        res = await call(rig, "green_light")
        await run_for(rig, 1.0)
        check("Gemini's late green_light does not start Pupper again on red",
              res.ok and not moving(rig, sent) and phase(rig) == game.RED, f"got {res}; sent {moving(rig, sent)[:3]}")
        check("... and the reply says the ear gives the green lights, and that the light is red",
              "ear" in res.message and "red light" in res.message, f"got {res}")
        await heard("green light")
        await run_for(rig, 1.0)
        res = await call(rig, "red_light")
        check("Gemini's red_light still stops Pupper: stopping is always allowed", res.ok and phase(rig) == game.RED and standing_still(rig), f"got {res}")
        await run_for(rig, game.EAR_ALIVE_S + 1.0)  # the page is closed: no more "listening"
        sent = len(rig.robot.published)
        res = await call(rig, "green_light")
        await run_for(rig, 1.0)
        check("once the ear is gone, Gemini's green_light works as before", res.ok and bool(moving(rig, sent)), f"got {res}")
        await call(rig, "red_light")
    finally:
        rig.close()


async def look(rig: Rig, what: str, seconds: float):
    """The eye reports `what` ten times a second for this long, as robot/eye.py does. Returns the last reply."""
    res = None
    for _ in range(round(seconds * 10)):
        res = await game.saw(rig.ts, what)
        await run_for(rig, 0.1)
    return res


async def test_camera_start() -> None:
    print("Lights by camera: starting a game")
    rig = Rig()
    try:
        res = await rig.call("start_game", lights="telepathy")
        check("lights by telepathy are refused, with the real choices",
              not res.ok and game.VOICE in res.message and game.CAMERA in res.message, f"got {res}")
        res = await rig.call("start_game", lights="camera")
        check("with no eye running, a game by camera is refused, and the reply says what would work",
              not res.ok and "voice" in res.message and "start.sh" in res.message and phase(rig) == game.NO_GAME, f"got {res}")
        await game.saw(rig.ts, "unsure")  # the eye is running
        res = await rig.call("start_game", lights="camera")
        check("with the eye running it is accepted, and the reply says how the lights work",
              res.ok and "camera" in res.message and "back" in res.message and phase(rig) == game.RED, f"got {res}")
        res = await rig.call("game_status")
        check("game_status says the lights are by camera, and what Pupper waits for",
              "by camera" in res.message and "face" in res.message, f"got {res}")
        await run_for(rig, game.EYE_ALIVE_S + 1.0)  # the eye stopped reporting
        res = await rig.call("game_status")
        check("... and when the eye stops reporting, that the eye is not running", "not running" in res.message, f"got {res}")

        await rig.call("start_game")  # a game by voice
        await look(rig, "facing", 0.3)
        await look(rig, "back", 2.0)
        check("in a game by voice the eye changes nothing", phase(rig) == game.RED and not moving(rig))
    finally:
        rig.close()


async def test_camera_lights() -> None:
    print("Lights by camera: a green light is a turn, a red light is a face")
    rig = Rig()
    try:
        await game.saw(rig.ts, "unsure")
        await rig.call("start_game", lights="camera")
        await look(rig, "back", 2.0)
        check("a back alone is no green light: the eye must see the caller facing Pupper first",
              phase(rig) == game.RED and not moving(rig))
        await look(rig, "facing", 0.3)
        await look(rig, "back", 0.3)
        check(f"a back for less than {game.BACK_STEADY_S:g} s is not enough", phase(rig) == game.RED and not moving(rig))
        await look(rig, "unsure", 0.1)
        await look(rig, "back", 0.3)
        check("... and a break starts the count again", phase(rig) == game.RED and not moving(rig))
        await run_for(rig, 1.0)  # the eye says nothing for a second
        await look(rig, "back", 0.3)
        check("... and so does a gap in the eye's reports", phase(rig) == game.RED and not moving(rig))
        await look(rig, "back", 1.0)
        check("facing, then a steady back: a green light, and Pupper walks straight ahead",
              phase(rig) == game.GREEN and set(moving(rig)) == {(game.GREEN_SPEED, 0.0, 0.0)}, f"sent {set(moving(rig))}")

        sent, walked = len(rig.robot.published), game.game_of(rig.ts).walked
        res = await game.saw(rig.ts, "unsure")
        check("'unsure' stops Pupper at once", standing_still(rig), f"got {res}")
        await run_for(rig, 1.0)
        g = game.game_of(rig.ts)
        check("... it holds still, the light stays green, and the distance does not grow",
              not moving(rig, len(rig.robot.published) - 5) and g.phase == game.GREEN and g.walked - walked < 0.03, f"{g}")
        res = await call(rig, "game_status")
        check("game_status says it is holding until the eye sees the back again", "holding" in res.message, f"got {res}")
        sent = len(rig.robot.published)
        await look(rig, "back", 0.5)
        check("the next 'back' and it walks on", bool(moving(rig, sent)) and phase(rig) == game.GREEN)

        await run_for(rig, game.EYE_FRESH_S + 0.2)  # the eye crashed: no more reports
        sent = len(rig.robot.published)
        await run_for(rig, 1.0)
        check(f"when the eye goes quiet, Pupper stands still within {game.EYE_FRESH_S:g} s", not moving(rig, sent),
              f"sent {moving(rig, sent)[:3]}")

        await look(rig, "back", 0.5)
        res = await game.saw(rig.ts, "facing")
        check("'facing' is a red light, at once", res.ok and phase(rig) == game.RED and standing_still(rig), f"got {res}")
        sent = len(rig.robot.published)
        await look(rig, "facing", 1.0)
        check("... and Pupper stays still while the caller looks", not moving(rig, sent) and phase(rig) == game.RED)
        res = await call(rig, "red_light")
        check("Gemini's red_light then says Pupper was already still, and that the eye did it",
              res.ok and "already standing still" in res.message and "eye" in res.message, f"got {res}")
        await look(rig, "back", 1.0)
        check("the caller turns away again: the next green light", phase(rig) == game.GREEN and bool(moving(rig, sent)))
        await call(rig, "red_light")  # (a test must not end with Pupper walking)
    finally:
        rig.close()


async def test_camera_rules() -> None:
    print("Lights by camera: who else may change the light")
    rig = Rig()
    try:
        await game.saw(rig.ts, "unsure")
        await rig.call("start_game", distance=7, lights="camera")
        await look(rig, "facing", 0.3)
        res = await call(rig, "green_light")
        await run_for(rig, 1.0)
        check("Gemini's green_light is refused: by camera only the eye gives the green light",
              not res.ok and "camera" in res.message and not moving(rig) and phase(rig) == game.RED, f"got {res}")
        res = await game.heard(rig.ts, "green light")
        check("... and so are the ear's words 'green light'", not res.ok and not moving(rig) and phase(rig) == game.RED, f"got {res}")

        await look(rig, "facing", 0.2)
        await look(rig, "back", 1.5)
        sent = len(rig.robot.published)
        res = await game.heard(rig.ts, "voice")
        await look(rig, "back", 0.5)
        check("a voice does not freeze Pupper in a game by camera", not res.ok and bool(moving(rig, sent)), f"got {res}")
        res = await call(rig, "stop")
        check("the stop tool still stops it: stopping is always allowed", res.ok and phase(rig) == game.RED and standing_still(rig), f"got {res}")
        sent = len(rig.robot.published)
        await look(rig, "back", 2.0)
        check("... and the back that is still turned does not start it again: a new turn is needed",
              phase(rig) == game.RED and not moving(rig, sent), f"sent {moving(rig, sent)[:3]}")
        await look(rig, "facing", 0.2)
        await look(rig, "back", 1.0)
        check("after the caller has faced Pupper and turned away, it walks again", phase(rig) == game.GREEN and bool(moving(rig, sent)))
        res = await game.heard(rig.ts, "red light")
        check("the ear's words 'red light' still stop it", res.ok and phase(rig) == game.RED and standing_still(rig), f"got {res}")

        await look(rig, "facing", 0.2)
        await look(rig, "back", game.GREEN_MAX_S + 1.5)  # the caller never turns around
        g = game.game_of(rig.ts)
        check(f"one green light still walks at most {game.GREEN_MAX_S:g} s", g.phase == game.RED and standing_still(rig), f"phase {g.phase}")
        sent = len(rig.robot.published)
        await look(rig, "back", 2.0)
        check("... and the next one needs a new turn", phase(rig) == game.RED and not moving(rig, sent))
        res = await rig.call("game_status")
        check("game_status tells Gemini why it stopped, and what the caller has to do",
              "did not turn around" in res.message and "face" in res.message, f"got {res}")

        await rig.call("start_game", distance=1, lights="camera")
        await look(rig, "facing", 0.2)
        await look(rig, "back", 4.0)
        g = game.game_of(rig.ts)
        check("Pupper stops by itself at the finish line", g.phase == game.FINISHED and standing_still(rig) and abs(g.walked - 1.0) < 0.05,
              f"phase {g.phase}, walked {g.walked:.2f} m")
    finally:
        rig.close()


def person(face=(0.0, 0.0, 0.0), shoulders=(280.0, 360.0), sure=0.9, score=0.9, middle=320.0, height=300.0) -> pose.Person:
    """A made-up person in the eye's 640 x 640 picture.

    face: the scores of the nose, the left eye and the right eye. shoulders: where
    the person's left and right shoulders are in the picture (x, in pixels).
    """
    points = np.zeros((17, 3), np.float32)
    points[[pose.NOSE, pose.LEFT_EYE, pose.RIGHT_EYE], 2] = face
    points[pose.LEFT_SHOULDER] = (shoulders[0], 100.0, sure)
    points[pose.RIGHT_SHOULDER] = (shoulders[1], 100.0, sure)
    return pose.Person(score, (middle - 60.0, 20.0, middle + 60.0, 20.0 + height), points)


async def test_eye_judgement() -> None:
    print("The eye's judgement (robot/eye.py): which way is a person turned?")
    check("a face, and the left shoulder on the right of the picture: facing",
          eye.looks(person(face=(0.9, 0.9, 0.9), shoulders=(360, 280))) == "facing")
    check("no face, and the left shoulder on the left: back", eye.looks(person(shoulders=(280, 360))) == "back")
    check("no face, shoulders on top of each other (side-on): unsure", eye.looks(person(shoulders=(315, 325))) == "unsure")
    check("a back, but the nose and an eye peek over the shoulder: facing",
          eye.looks(person(face=(0.8, 0.7, 0.1), shoulders=(280, 360))) == "facing")
    check("a back, and only the nose is seen: unsure (not enough for a face, too much for a back)",
          eye.looks(person(face=(0.8, 0.1, 0.1), shoulders=(280, 360))) == "unsure")
    check("no face (too far to see), but the shoulders are the front way round: facing",
          eye.looks(person(shoulders=(360, 280))) == "facing")
    check("shoulders the model is not sure of: unsure", eye.looks(person(shoulders=(280, 360), sure=0.3)) == "unsure")

    tall, short = person(height=400), person(height=200, middle=250)
    check("the caller is the tallest person in the middle of the picture", eye.pick_caller([short, tall]) is tall)
    check("a taller person at the edge is a bystander", eye.pick_caller([short, person(height=600, middle=600)]) is short)
    check("a sofa that scores below PERSON_SURE is nobody", eye.pick_caller([person(score=0.4)]) is None)
    check("nobody in the picture: unsure", eye.see([]) == ("unsure", None))
    check("the word is the caller's, not a bystander's",
          eye.see([person(height=400), person(face=(0.9, 0.9, 0.9), middle=600)])[0] == "back")

    # pose.decode on a made-up output of the model: the cell in row 10, column 12 of the
    # 20 x 20 grid says "a person", and so does its neighbour, a little less sure.
    outputs = {f"{cells}/{channels}": np.zeros((cells, cells, channels), np.float32)
               for cells in (80, 40, 20) for channels in (64, 1, 51)}
    outputs["20/1"][10, 12], outputs["20/1"][10, 13] = 0.9, 0.8
    outputs["20/51"][10, 12, 0:3] = (1.0, 0.5, 4.0)  # the nose: 2 cells right of the cell's corner, 1 down, very sure
    people = pose.decode(outputs)
    check("pose.decode: two neighbouring cells are one person, the surer one", len(people) == 1 and abs(people[0].score - 0.9) < 1e-6,
          f"got {people}")
    nose = people[0].points[pose.NOSE] if people else None
    check("... with the nose where the cell says (32 pixels per cell), and seen",
          nose is not None and abs(nose[0] - 448) < 1e-3 and abs(nose[1] - 352) < 1e-3 and nose[2] > 0.9, f"got {nose}")
    check("... and a box around the cell's centre (all 16 bins equal: 7.5 cells each way)",
          bool(people) and np.allclose(people[0].box, (160, 96, 640, 576)), f"got {people[0].box if people else None}")


TESTS = [test_tools_offered, test_no_game, test_start, test_green_then_red, test_finish, test_nobody_calls_red,
         test_speed, test_other_stops, test_end_and_restart, test_fast_ear,
         test_who_gives_the_green_light, test_camera_start, test_camera_lights, test_camera_rules,
         test_eye_judgement]


def main() -> None:
    for test in TESTS:
        asyncio.run(test())
        print()
    if tt.FAIL:
        print(f"{tt.FAIL} check(s) failed, {tt.PASS} passed.")
        raise SystemExit(1)
    print(f"All {tt.PASS} checks passed. Next: python3 game/chat.py, then the robot.")


if __name__ == "__main__":
    main()
