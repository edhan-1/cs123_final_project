"""Find gemini_pupper, and load the game on top of it.

This project does not copy Gemini Pupper. It borrows the whole stack from the
gemini_pupper repo next to it (the robot API, the tool registry, the robot
server, the web app, your lab/ tools) and adds the game on top:
game/red_light_green_light.py (the rules and the tools), game/prompt.md and
web/play.html (the page with the fast ear). Everything that starts the game goes
through here:

    import bootstrap
    bootstrap.add_paths()       # 1. make gemini_pupper importable
    import server               # 2. load the lab: server.py (the real robot),
                                #    or test_tools (the fake one), both from gemini_pupper/robot
    bootstrap.load_game()       # 3. add the game's tools, trim the lab's

The order matters: step 2 decides whether ROS is real or fake, so the game
(which imports robot_api) can only be imported after it.

gemini_pupper is looked for next to this repo (~/labs/gemini_pupper); set
GEMINI_PUPPER_DIR if yours is somewhere else.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GAME_DIR = REPO / "game"
PROMPT_FILE = GAME_DIR / "prompt.md"
PLAY_PAGE = REPO / "web" / "play.html"
GEMINI_PUPPER = Path(os.environ.get("GEMINI_PUPPER_DIR", REPO.parent / "gemini_pupper")).expanduser().resolve()


def add_paths() -> None:
    """Put gemini_pupper/robot, gemini_pupper/lab and game/ on Python's path."""
    if not (GEMINI_PUPPER / "robot" / "robot_api.py").exists():
        sys.exit(f"Can't find gemini_pupper at {GEMINI_PUPPER}. Clone it next to this repo, or set GEMINI_PUPPER_DIR.")
    robot = str(GEMINI_PUPPER / "robot")
    if robot not in sys.path:
        sys.path.insert(0, robot)  # first: server, robot_api, tool_registry, test_tools come from here
    for folder in (GEMINI_PUPPER / "lab", GAME_DIR):
        if str(folder) not in sys.path:
            sys.path.append(str(folder))


def load_game():
    """Import the game (which registers its tools), then keep only the tools it wants
    Gemini to have. Returns the game module."""
    import red_light_green_light as game

    game.setup_lab_tools()
    return game


class _RealClock:
    """What the fake robot stamps its records with, when its time is real."""

    @property
    def now(self) -> float:
        import time

        return time.monotonic()


def real_time(rig) -> None:
    """Give a test rig (the fake robot in gemini_pupper/robot/test_tools.py) real time.

    The rig is built for tests: its clock is fake, so a queued job finishes at
    once. In this game, how long the light stays green is the whole point, so
    game/chat.py and game_server.py --fake let the fake robot take real seconds.
    """
    import asyncio
    import time

    import robot_api

    robot_api.time, robot_api.asyncio = time, asyncio
    rig.clock = rig.robot.clock = _RealClock()
