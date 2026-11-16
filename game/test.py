#!/usr/bin/env python3
"""Desk tests for red light, green light: no robot, no ROS, no Gemini needed.

    python3 game/test.py

They use the fake robot from gemini_pupper/robot/test_tools.py: it records every
speed command and controller switch, and its time is fake, so a 6 s green light
takes no real time. Each test calls the tools the way Gemini does, or heard()
the way the fast ear's page does (POST /game/heard), and checks what the robot
was told and what the caller hears. The page's own logic is checked by
node web/test_play.js.

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


TESTS = [test_tools_offered, test_no_game, test_start, test_green_then_red, test_finish, test_nobody_calls_red,
         test_speed, test_other_stops, test_end_and_restart, test_fast_ear,
         test_who_gives_the_green_light]


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
