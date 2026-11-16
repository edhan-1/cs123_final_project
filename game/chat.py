#!/usr/bin/env python3
"""Play red light, green light with Gemini in text, and watch every tool call.

    python3 game/chat.py            # the game on a fake robot: nothing moves
    python3 game/chat.py --robot    # the game on the real Pupper (through the game server): it moves!

The same loop as gemini_pupper/lab/chat.py (the chat itself is
gemini_pupper/robot/gemini_chat.py), with game/prompt.md and the game's tools.

One difference: here the fake robot runs in REAL time. In the lab's chat a queued
job finishes at once; in this game, how long the light stays green is the whole
point. So type "green light", wait a couple of seconds, type "red light", and
the reply tells you how far the fake Pupper got in between.

There is no fast ear here (it lives in the browser page, web/play.html), so in
the chat Gemini works the lights itself, as it does on the plain web app.

The Gemini key comes from GEMINI_API_KEY, or ~/.config/gemini-pupper/api_key.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "robot"))
import bootstrap  # noqa: E402

bootstrap.add_paths()
import gemini_chat  # noqa: E402  gemini_pupper/robot/gemini_chat.py


class GameDesk(gemini_chat.DeskBackend):
    """The game's tools on the fake robot, in real time."""

    name = "the game on a fake robot, in real time (nothing moves)"

    def setup(self) -> tuple[str, list[dict]]:
        super().setup()  # the fake ROS, the lab's tools, a fake robot standing in locomotion mode
        bootstrap.load_game()
        bootstrap.real_time(self.rig)  # the test rig's time is fake: make it real again
        return gemini_chat.prompt_text(bootstrap.PROMPT_FILE), self.registry.declarations(self.rig.ts)

    async def call(self, name: str, args: dict) -> dict:
        res = await self.registry.call(self.rig.ts, name, args)
        await asyncio.sleep(0.1)  # let a job that ends at once (stand up) report; a green light keeps going
        return res.as_dict()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robot", nargs="?", const="http://localhost:8000", metavar="URL",
                    help="the game on the real robot's game server (default http://localhost:8000)")
    ap.add_argument("--show", action="store_true", help="print the whole prompt and every tool declaration first")
    ap.add_argument("--model", default=gemini_chat.MODEL, help=f"Gemini Live model (default {gemini_chat.MODEL})")
    args = ap.parse_args()
    backend = gemini_chat.RobotBackend(args.robot) if args.robot else GameDesk()
    try:
        asyncio.run(gemini_chat.chat(backend, args.model, args.show))
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
