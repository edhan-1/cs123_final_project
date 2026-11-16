"""Red light, green light: the lights are called by voice, or by turning around.

The person is the caller and Pupper is the runner. On a green light Pupper walks
straight ahead; on a red light it freezes. Pupper wins when it has walked the
whole course, from the start line to the finish line.

A game is played in one of two ways, chosen when it starts (start_game's `lights`):

  by voice    the caller says "green light" and "red light".
  by camera   the caller turns their back (green) or faces Pupper (red), as in
              the playground game. Pupper watches with its own camera.

Three things can ask for a light. Gemini, by calling a tool: it is Pupper's voice
and starts and ends the games, but it needs a second or two to act. The fast ear
in the browser page (web/play.html), which hears the words long before Gemini
does. And the eye (robot/eye.py), which looks at the caller ten times a second.
This file is where all three arrive, and where it is decided what counts.
docs/architecture.md has the whole picture.

This file has the same two halves as the files in gemini_pupper/lab/ (read
lab/basics.py there first):

  WHAT THE ROBOT DOES   the Game (the score sheet), and one behavior per tool:
                        start_game, green_light, red_light, game_status, end_game
  WHAT GEMINI READS     the @tool for each of them

and three extra parts: the fast ear (heard: what the browser page tells the
robot), the eye (saw: what robot/eye.py tells the robot), and at the end which
of the lab's tools Gemini keeps, and which of those are refused while a game is
on.

Four things to know before reading on:

  1. The rules live here, not in the prompt or the page. game/prompt.md tells
     Gemini how to play and web/play.html reports what it hears; this file makes
     sure Pupper can't walk on red, whoever asks.
  2. Pupper has no idea where it is. `walked` is an estimate: the speed it was
     told to walk at, times the time it walked (dead reckoning). The real robot
     slips and needs a moment to get going, so treat it as "about".
  3. Gemini only hears from the robot when it calls a tool. If Pupper crosses
     the finish line or times out by itself, Gemini finds out at its next call
     (red_light and game_status both say so). The same goes for a light the
     ear changed.
  4. Stopping is always allowed; walking has to be earned. A stop is taken from
     anyone at any time. A green light is taken only on red. By voice, only
     from the words "green light", and only from one of the two: the ear while
     it is listening, else Gemini. By camera, only from the eye, and only for a
     turn: it must have seen the caller facing Pupper, and then their back.

After changing this file:  python3 game/test.py   then   python3 game/chat.py
"""

from __future__ import annotations

from dataclasses import dataclass

from basics import stand_up
from part2_walk import check_move
from part3_follow import prepare_to_move
from robot_api import FELL_MESSAGE, LIMITS, LLM_CMD_RATE, LOCOMOTION, LOCOMOTION_CONTROLLER, WALK_READY_S, Result, Robot, with_note
from tool_registry import TOOLS, Param, tool

# ------------------------------------------------------------ the numbers of the game
COURSE_DEFAULT_M = 3.0  # start line to finish line, when the person gives no distance
COURSE_MIN_M = 1.0
COURSE_MAX_M = LIMITS.distance_max  # 7.0 m: the lab's limit for one move, kept for a whole game

GREEN_SPEED = 0.4  # m/s: the lab's walking speed
GREEN_SPEED_MIN = LIMITS.vx_min  # 0.2 m/s: slower than this barely moves
GREEN_SPEED_MAX = 0.5  # m/s: above this the locomotion policy runs, and a run takes longer to stop
# One green light walks at most this long. Nobody is holding the robot back while
# the light is green: if the microphone or the Gemini session drops, this is what
# stops it.
GREEN_MAX_S = 6.0

# The fast ear (see heard, below). Gemini needs a second or two to turn a light
# into a tool call; the ear in the browser page (web/play.html) is much faster.
HOLD_S = 3.0  # a voice freezes Pupper for this long; "red light" (the ear's, or Gemini's) should arrive within it
DEAF_S = 0.5  # at the very start of a green light a voice is ignored (the end of "green light!")
EAR_ALIVE_S = 5.0  # the page says "listening" every 2 s; this long without it and the ear counts as gone

# The eye (see saw, below). In a game by camera, robot/eye.py reports what it sees
# of the caller about ten times a second: "back", "facing" or "unsure".
BACK_STEADY_S = 0.5  # the eye must see the caller's back for this long, without a break, before a green light
EYE_FRESH_S = 0.5  # Pupper walks only while "back" keeps arriving: this long without one and it stands still
EYE_ALIVE_S = 3.0  # this long without any report and the eye counts as not running

# Who calls the lights: chosen when the game starts.
VOICE = "voice"  # the caller says "green light" and "red light"
CAMERA = "camera"  # the caller turns their back (green) or faces Pupper (red)

# The phases of a game.
NO_GAME = "no game"
RED = "red light"  # a game is on, and Pupper stands still
GREEN = "green light"  # a game is on, and Pupper walks (or is about to)
FINISHED = "finished"  # Pupper crossed the finish line


# ============================================================ what the robot does
@dataclass
class Game:
    """The score sheet of one game. start_game makes a new one."""

    phase: str = NO_GAME
    lights: str = VOICE  # who calls the lights: VOICE or CAMERA
    course: float = COURSE_DEFAULT_M  # m from the start line to the finish line
    walked: float = 0.0  # m walked so far (an estimate: speed x time)
    greens: int = 0  # green lights given so far
    first_green: float | None = None  # robot.now() when Pupper first started walking
    time: float | None = None  # s from the first step to the finish line
    note: str = ""  # how the last green light ended, when it ended by itself
    green_stops: int = 0  # robot.stops when the last green light was given: see game_of
    walking_since: float | None = None  # robot.now() when this green light started walking
    hold_until: float = 0.0  # the ear heard a voice: stand still until this time (robot.now())
    # A game by camera only (see saw):
    faced: bool = False  # the eye has seen the caller facing Pupper since the last green light
    back_since: float | None = None  # on red: robot.now() when the eye began to see the caller's back
    back_until: float = 0.0  # on green: the eye sees the caller's back, so Pupper may walk until this time

    @property
    def to_go(self) -> float:
        return max(0.0, self.course - self.walked)

    def progress(self) -> str:
        return f"about {min(self.walked, self.course):.1f} m walked, {self.to_go:.1f} m to the finish line"

    def result(self) -> str:
        return f"Pupper crossed the finish line ({self.course:g} m) in {self.time:.1f} s, with {self.greens} green light(s)"


def game_of(robot: Robot) -> Game:
    """The game this robot is playing, brought up to date.

    A green light can end without red_light: the stop tool, the gamepad e-stop
    and a fall all stop Pupper too. Each of them counts as a stop (robot.stops),
    so if that number has changed since the green light was given, the light is
    red, whoever stopped the robot.
    """
    game = getattr(robot, "game", None)
    if game is None:
        game = robot.game = Game()
    if game.phase == GREEN and robot.stops != game.green_stops:
        game.phase = RED
    return game


async def start_game(robot: Robot, distance: float = COURSE_DEFAULT_M, lights: str = VOICE) -> Result:
    """A new game: forget whatever was going on, stand up at the start line, wait on red."""
    # NOW: check the course, and who calls the lights.
    if not COURSE_MIN_M <= distance <= COURSE_MAX_M:
        return Result(False, f"the finish line must be {COURSE_MIN_M:g} to {COURSE_MAX_M:g} m away, not {distance:g} m")
    if lights not in (VOICE, CAMERA):
        return Result(False, f"the lights are called by '{VOICE}' or by '{CAMERA}', not {lights!r}")
    if lights == CAMERA and not eye_watching(robot):
        return Result(False, "Pupper's eye is not running, so it cannot play by camera. Play by voice (lights='voice'),"
                             " or ask a person to start the eye on the robot: robot/start.sh starts it")
    if robot.fallen:
        return Result(False, FELL_MESSAGE)
    # Drop what was queued and what is running (an old green light, a move), the way
    # robot.set_following does before it takes over, and stand still.
    await robot.clear_queue()
    if robot.current and not robot.current.done():
        robot.current.cancel()
    robot.send_speed(0, 0, 0)
    # LATER (queued): stand up, with the lab's own stand_up (it also ends follow mode).
    res = await stand_up(robot)
    if not res.ok:
        return res
    robot.game = Game(phase=RED, course=distance, lights=lights)
    how = ("only green_light makes it walk" if lights == VOICE else
           "the lights are called by camera. It walks while its eye sees the caller's back and freezes when the"
           " caller faces it. The caller should face Pupper first, then turn around")
    return with_note(f"New game: the finish line is {distance:g} m straight ahead. The light is red: Pupper"
                     f" waits at the start line and {how}.", res)


async def green_light(robot: Robot, speed: float | None = None) -> Result:
    """Walk straight ahead until red_light, the finish line, or GREEN_MAX_S.

    The same shape as walk in gemini_pupper/lab/part2_walk.py: check now, queue a
    job, and the job checks again, walks and reports. Two differences: the job
    adds up how far Pupper has walked, and it has no fixed end. It ends when it
    is cancelled (red_light, or any other stop), at the finish line, or after
    GREEN_MAX_S.
    """
    game = game_of(robot)
    # NOW: is a green light allowed?
    if game.phase == NO_GAME:
        return Result(False, "no game is on: call start_game first")
    if game.phase == FINISHED:
        return Result(False, f"the game is over: {game.result()}. Call start_game to play again")
    if game.phase == GREEN:
        return Result(True, f"the light is already green and Pupper is walking; {game.progress()}")
    speed = GREEN_SPEED if speed is None else speed
    if not GREEN_SPEED_MIN <= speed <= GREEN_SPEED_MAX:
        return Result(False, f"a green light walks at {GREEN_SPEED_MIN:g} to {GREEN_SPEED_MAX:g} m/s, not {speed:g} m/s")
    seconds = min(game.to_go / speed, GREEN_MAX_S)  # the longest this green light can last
    refused = check_move(speed, 0.0, 0.0, seconds)  # the lab's limits apply to the game too
    if refused:
        return Result(False, refused)
    if robot.fallen:
        return Result(False, FELL_MESSAGE)
    note = await prepare_to_move(robot)  # ends follow mode, if it was on
    standing = robot.state_after_queue == LOCOMOTION  # else the job stands up first

    async def job() -> Result:  # LATER, when the queue gets to it
        def red(why: str) -> Result:  # the green light ended by itself: back to red
            robot.send_speed(0, 0, 0)
            game.phase, game.note, game.walking_since = RED, why, None
            return Result(False, why)

        if robot.fallen:
            return red(FELL_MESSAGE)
        res = await robot.switch_to(LOCOMOTION_CONTROLLER)  # stands up first if it has to
        if not res.ok:
            return red(res.message)
        began = last = game.walking_since = robot.now()
        if game.first_green is None:
            game.first_green = began
        while game.to_go > 1e-6 and robot.now() - began < GREEN_MAX_S - 1e-6:
            if robot.fallen:
                return red(FELL_MESSAGE)
            holding = robot.now() < game.hold_until  # the ear heard a voice: stand still for now
            if game.lights == CAMERA:
                holding = robot.now() >= game.back_until  # the eye does not see the caller's back right now
            robot.send_speed(0.0 if holding else speed, 0.0, 0.0)  # again and again: cmd_vel_mux forgets it after 0.5 s
            await robot.sleep(1.0 / LLM_CMD_RATE)  # red_light cancels the job here
            now = robot.now()
            if not holding:
                game.walked += speed * (now - last)
            last = now
        robot.send_speed(0, 0, 0)  # stand still
        game.walking_since = None
        if game.to_go <= 1e-6:
            game.phase, game.time = FINISHED, robot.now() - game.first_green
            return Result(True, f"finished: {game.result()}")
        if game.lights == CAMERA:
            return red(f"the caller did not turn around for {GREEN_MAX_S:g} s, so Pupper stopped by itself: it walks"
                       f" again when the caller has faced it and turned away again; {game.progress()}")
        return red(f"nobody called red light for {GREEN_MAX_S:g} s, so Pupper stopped by itself; {game.progress()}")

    # What Gemini hears NOW: the green light was accepted.
    res = await robot.queue("green light", job, seconds + (0 if standing else WALK_READY_S), then=LOCOMOTION)
    if not res.ok:
        return res
    game.phase, game.note = GREEN, ""
    game.walking_since, game.hold_until = None, 0.0
    game.faced, game.back_since = False, None  # by camera: the next green light needs a new turn
    game.green_stops = robot.stops
    game.greens += 1
    said = (f"Green light: {'walking' if standing else 'standing up, then walking'} straight ahead at {speed:g} m/s"
            f" until red_light, the finish line ({game.to_go:.1f} m to go) or {GREEN_MAX_S:g} s.")
    return with_note(f"{note} {said}", res)


async def red_light(robot: Robot) -> Result:
    """Freeze. Not queued: it stops whatever is running, right now."""
    game = game_of(robot)
    was_green = game.phase == GREEN
    held = was_green and robot.now() < game.hold_until  # the ear had already frozen it
    # Stop FIRST, then work out what to say: every moment in between is Pupper
    # walking on red. immediate_stop clears the queue, cancels the green light's
    # job and sends a zero speed. It is always safe, game or no game.
    await robot.immediate_stop()
    game = game_of(robot)  # the stop was counted, so a green light has turned red
    if game.phase == NO_GAME:
        return Result(True, "stopped. No game is on: call start_game to play")
    if game.phase == FINISHED:
        return Result(True, f"stopped. The game is already over: {game.result()}")
    how = ("Pupper had already frozen at the sound of a voice" if held else "Pupper froze" if was_green
           else "Pupper was already standing still")
    return Result(True, f"Red light: {how}; {game.progress()}. {game.note}".strip())


def ear_listening(robot: Robot) -> bool:
    """Is the page's word ear listening right now? (It says so every 2 s: see heard.)"""
    return robot.now() < getattr(robot, "ear_until", 0.0)


async def heard(robot: Robot, what: str) -> Result:
    """The fast ear: what the browser page heard, sent straight to the robot.

    Not a tool: Gemini never calls it. The page web/play.html listens to the same
    microphone as Gemini and posts here (POST /game/heard, robot/game_server.py)
    long before Gemini has worked out what was said. It can say four things:

      "voice"        somebody started speaking. During a green light the next
                     thing the caller says is almost always "red light", so
                     Pupper holds still at once, for HOLD_S. If "red light"
                     follows (from the ear's words, or from Gemini), the light is
                     red. If not (it was "green beans", or a noise), Pupper walks
                     on by itself: it flinched.
      "red light"    the page recognised the words: a red light, full stop.
      "green light"  the page recognised the words: a green light, the same one
                     Gemini's tool gives, a second or two sooner.
      "listening"    nothing was heard; the word ear is on. While it is, the
                     green lights are the ear's job and Gemini's green_light
                     changes nothing (see green_light_tool): its call arrives so
                     late that the light may have turned red again by then.

    A voice and "red light" only count while the light is green, and "green
    light" only while it is red: the ear also hears Pupper's own voice from the
    speaker, and that must not stop a stand-up or start a walk.
    """
    if what not in ("voice", "red light", "green light", "listening"):
        return Result(False, f"the ear says 'voice', 'red light', 'green light' or 'listening', not {what!r}")
    if what != "voice":  # only the word ear says the other three
        robot.ear_until = robot.now() + EAR_ALIVE_S
    if what == "listening":
        return Result(True, "the word ear is listening")
    game = game_of(robot)
    if game.lights == CAMERA and game.phase in (RED, GREEN) and what != "red light":
        # Stopping is always allowed, so the words "red light" still count. The rest is the eye's job.
        return Result(False, f"heard {what}, but in this game the lights are called by camera: nothing to do")
    if what == "green light":
        if game.phase != RED:
            return Result(False, f"heard green light, but the light is not red ({game.phase}): nothing to do")
        return await green_light(robot)
    if game.phase != GREEN:
        return Result(False, f"heard {what}, but the light is not green: nothing to do")
    if what == "red light":
        res = await red_light(robot)
        game.note = "Pupper's own ear heard the words and stopped it before Gemini called red_light."
        return res
    now = robot.now()
    if game.walking_since is None or now - game.walking_since < DEAF_S:
        return Result(False, "heard a voice, but this green light has only just begun: ignored")
    game.hold_until = now + HOLD_S
    robot.send_speed(0, 0, 0)  # now, not at the job's next step
    return Result(True, f"heard a voice: holding still for {HOLD_S:g} s, or until red_light")


def eye_watching(robot: Robot) -> bool:
    """Is the eye (robot/eye.py) running? It reports what it sees at least once a second: see saw."""
    return robot.now() - getattr(robot, "eye_at", -1e9) < EYE_ALIVE_S


async def saw(robot: Robot, what: str) -> Result:
    """The eye: what Pupper's camera sees of the caller, sent straight to the robot.

    Not a tool: Gemini never calls it. The program robot/eye.py finds the caller
    in the camera picture and posts here (POST /game/saw, robot/game_server.py)
    for every picture it looks at. It can say three things:

      "back"     it sees the caller's back: no face, and the shoulders the way
                 round they are from behind.
      "facing"   it sees the caller's face, or their shoulders from the front.
      "unsure"   anything else: nobody there, somebody side-on, a blurry picture.

    They only count in a game by camera (start_game's lights). What they do:

      on red     A green light needs a turn. The eye must first see the caller
                 FACING Pupper, and then their back for BACK_STEADY_S without a
                 break. So a coat on a chair that looks like a back, or a caller
                 who never looked, cannot start Pupper. And after any stop (the
                 stop tool, the e-stop, 6 s of walking) the caller has to turn
                 around once more.
      on green   Pupper walks only while "back" keeps arriving. "unsure", or
                 no report for EYE_FRESH_S (the eye crashed, the camera froze),
                 and it stands still but the light stays green: it walks on at
                 the next "back". "facing" is a red light.
    """
    if what not in ("back", "facing", "unsure"):
        return Result(False, f"the eye says 'back', 'facing' or 'unsure', not {what!r}")
    now = robot.now()
    quiet = now - getattr(robot, "eye_at", -1e9)  # s since the eye's last report
    robot.eye_at, robot.eye_sees = now, what
    game = game_of(robot)
    if game.lights != CAMERA or game.phase not in (RED, GREEN):
        return Result(False, f"the eye sees {what}, but no game by camera is on: nothing to do")
    if game.phase == GREEN:
        if what == "back":
            game.back_until = now + EYE_FRESH_S
            return Result(False, "the eye still sees the caller's back: nothing to change")
        if what == "facing":
            res = await red_light(robot)
            game.faced, game.note = True, "The caller turned around, and Pupper's eye stopped it."
            return res
        game.back_until = now  # unsure: stand still now, not EYE_FRESH_S from now
        if game.walking_since is not None:
            robot.send_speed(0, 0, 0)
        return Result(False, "the eye is unsure: Pupper holds still until it sees the caller's back again")
    # The light is red.
    if what == "facing":
        game.faced, game.back_since = True, None
        return Result(False, "the eye sees the caller facing Pupper: the light stays red")
    if what == "unsure" or not game.faced:
        game.back_since = None
        return Result(False, "the eye has to see the caller facing Pupper, and then their back")
    if game.back_since is None or quiet > EYE_FRESH_S:
        game.back_since = now  # the first "back", or the first after a gap
    if now - game.back_since < BACK_STEADY_S:
        return Result(False, f"the eye sees the caller's back, but not yet for {BACK_STEADY_S:g} s")
    res = await green_light(robot)
    if res.ok:
        game.back_until = now + EYE_FRESH_S
    return res


async def game_status(robot: Robot) -> Result:
    """How the game stands, in words. A question: it changes nothing."""
    game = game_of(robot)
    if game.phase == NO_GAME:
        return Result(True, "no game is on. Call start_game to play")
    if game.phase == FINISHED:
        return Result(True, f"game over: {game.result()}. Call start_game to play again")
    if game.lights == CAMERA:
        return Result(True, _camera_status(robot, game))
    doing = ("Pupper is standing still" if game.phase == RED
             else "Pupper is holding still because it heard a voice" if robot.now() < game.hold_until
             else "Pupper is walking")
    return Result(True, f"game on, {game.phase}: {doing}; {game.progress()}; {game.greens} green light(s) so far. {game.note}".strip())


def _camera_status(robot: Robot, game: Game) -> str:
    """game_status for a game by camera: the same, plus what the eye is waiting for."""
    if not eye_watching(robot):
        doing = "Pupper is standing still because its eye is not running (a person has to start it: robot/start.sh)"
    elif game.phase == GREEN:
        doing = ("Pupper is walking" if robot.now() < game.back_until
                 else "Pupper is holding still until its eye sees the caller's back again")
    elif game.faced:
        doing = "Pupper is standing still, and walks when the caller turns their back"
    else:
        doing = "Pupper is standing still, and waits for the caller to face it and then turn their back"
    return (f"game on, lights by camera, {game.phase}: {doing}; {game.progress()};"
            f" {game.greens} green light(s) so far. {game.note}").strip()


async def end_game(robot: Robot) -> Result:
    """Stop, and leave the game. Pupper stays standing; the lab's motion tools work again."""
    game = game_of(robot)
    await robot.immediate_stop()
    if game.phase == NO_GAME:
        return Result(True, "stopped. No game was on")
    summary = game.result() if game.phase == FINISHED else f"ended before the finish line; {game.progress()}"
    robot.game = Game()
    return Result(True, f"game ended: {summary}. Pupper is standing still")


# ============================================================ what Gemini reads
@tool(
    "start_game",
    "Start a new game of red light, green light. Pupper is the runner; the person calls the lights. Pupper"
    " stands up where it is (that is the start line), facing the finish line, and waits on red. The finish"
    f" line is `distance` metres straight ahead. Calling it during a game starts over from 0 m.",
    distance=Param("number", f"How far away the finish line is, in metres: {COURSE_MIN_M:g} to {COURSE_MAX_M:g}."
                   f" Default {COURSE_DEFAULT_M:g}. Use the person's number if they give one.", required=False),
    lights=Param("string", f"Who calls the lights. '{VOICE}' (the default): the person says green light and red light."
                 f" '{CAMERA}': the person turns their back for green and faces Pupper for red, and Pupper's own eye"
                 " works the lights. Use it when they want to play by turning around, or without calling out.",
                 enum=[VOICE, CAMERA], required=False),
)
async def start_game_tool(robot: Robot, distance: float = COURSE_DEFAULT_M, lights: str = VOICE) -> Result:
    return await start_game(robot, distance, lights)


@tool(
    "green_light",
    "Green light: Pupper walks straight ahead. Call it the moment the person calls green light, before you say"
    " anything. It only works during a game. Pupper keeps walking until red_light, the finish line, or"
    f" {GREEN_MAX_S:g} s without a red light, whichever comes first. When Pupper's own ear is listening, the"
    " ear has already given the green light and the reply says so. Refused in a game by camera.",
    speed=Param("number", f"Walking speed in m/s, {GREEN_SPEED_MIN:g} to {GREEN_SPEED_MAX:g}. Default {GREEN_SPEED:g}."
                " Leave it out unless the person asks for faster or slower.", required=False),
)
async def green_light_tool(robot: Robot, speed: float | None = None) -> Result:
    if game_of(robot).lights == CAMERA and game_of(robot).phase in (RED, GREEN):
        # By camera, a green light is a turn that the eye saw. Nobody can say it.
        status = await game_status(robot)
        return Result(False, "in this game the lights are called by camera: Pupper walks when its own eye sees the"
                             f" caller's back, so this call changed nothing. Now: {status.message}")
    if ear_listening(robot):
        # The ear heard "green light" long before this call got here. If the light is
        # red by now, that is because a red light came after it: walking again would
        # be walking on red. So the call changes nothing, and says how things stand.
        status = await game_status(robot)
        return Result(True, "Pupper's own ear is listening for the lights and gives the green lights itself,"
                            f" so this call changed nothing. Now: {status.message}")
    return await green_light(robot, speed)


@tool(
    "red_light",
    "Red light: Pupper stops walking at once and stands still. Call it the moment the person calls red light,"
    " before you say anything: until you do, Pupper is walking on red. It is always safe to call. The reply"
    " says about how far Pupper has walked and how far is left.",
)
async def red_light_tool(robot: Robot) -> Result:
    return await red_light(robot)


@tool(
    "game_status",
    "How the game stands: whether one is on, whether the light is red or green, about how far Pupper has"
    " walked, how far is left, and whether it has crossed the finish line (with its time). Call it when someone"
    " asks about the game or the score, and before you say that Pupper won.",
)
async def game_status_tool(robot: Robot) -> Result:
    return await game_status(robot)


@tool(
    "end_game",
    "End the game: Pupper stops and stands still, and move, turn and play_trick work again. Use it when the"
    " person is done playing, or wants Pupper to do something else.",
)
async def end_game_tool(robot: Robot) -> Result:
    return await end_game(robot)


# ============================================================ the lab's tools, during a game
# Every tool written in gemini_pupper/lab/ is loaded too. Gemini keeps these, next
# to the five above. Fewer tools means fewer wrong calls: nothing in a game needs
# arc, follow or interactive_action.
LAB_TOOLS = ["stand_up", "lie_down", "stop", "robot_status", "move", "turn", "play_trick"]
# ... and these would move Pupper around the rules (a move on red), so while a game
# is on they are refused. The stop tool is not here: stopping is always allowed,
# and game_of turns the light red when it happens.
ONLY_BETWEEN_GAMES = ["move", "turn", "play_trick"]


def setup_lab_tools() -> None:
    """Take the lab's other tools away from Gemini, and guard ONLY_BETWEEN_GAMES.

    Run once, after every lab/ file and this one are loaded (robot/bootstrap.py).
    """
    for name in list(TOOLS):
        if TOOLS[name].module != __name__ and name not in LAB_TOOLS:
            del TOOLS[name]
    for name in ONLY_BETWEEN_GAMES:
        if name in TOOLS and not getattr(TOOLS[name].run, "only_between_games", False):
            TOOLS[name].run = _only_between_games(name, TOOLS[name].run)
            TOOLS[name].description += " Refused during a game of red light, green light: call end_game first."


def _only_between_games(name: str, run):
    async def guarded(robot: Robot, **args) -> Result:
        if game_of(robot).phase in (RED, GREEN):
            return Result(False, f"{name} is not allowed during a game: only green_light moves Pupper."
                                 " To do it anyway, call end_game first")
        return await run(robot, **args)

    guarded.only_between_games = True
    return guarded
