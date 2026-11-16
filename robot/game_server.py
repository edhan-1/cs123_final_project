"""The robot server for red light, green light: Gemini Pupper's server, with the
game's tools, the game's prompt, and the fast ear.

    python3 robot/game_server.py                     (robot/start.sh runs it, after the robot stack)
    PORT=8001 python3 robot/game_server.py --fake    the same server on a fake robot: nothing moves

Nothing in gemini_pupper is changed. Its server.py builds the whole app (GET
/tools, POST /tools/<name>, the camera, the web app at /); this file loads it,
adds game/red_light_green_light.py to the tools, points it at game/prompt.md,
and adds two addresses of its own:

    GET  /play         web/play.html: the web app in a frame, with the fast ear above it
    POST /game/heard   what the ear heard: {"what": "voice"}, "red light", "green light" or "listening"

--fake is for trying the page and tuning the ear at a desk. It needs no robot
stack and can run next to the real server, on another port.
"""

import os
import sys

import bootstrap

bootstrap.add_paths()
FAKE = "--fake" in sys.argv[1:]
if FAKE:
    import test_tools  # gemini_pupper/robot/test_tools.py: a fake ROS, before anything imports the real one

import uvicorn  # noqa: E402
from fastapi import Body  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

import server  # noqa: E402  gemini_pupper/robot/server.py: loads lab/, makes the FastAPI app

game = bootstrap.load_game()  # the game's tools, and only the lab tools it keeps
server.PROMPT_FILE = bootstrap.PROMPT_FILE  # GET /tools now sends game/prompt.md


@server.app.get("/play")
def play_page():
    return FileResponse(bootstrap.PLAY_PAGE, headers={"Cache-Control": "no-store"})  # an edited page shows on reload


@server.app.post("/game/heard")
async def game_heard(body: dict = Body(default={})):
    """The fast ear in web/play.html heard something. Not one of Gemini's tools."""
    what = str(body.get("what", ""))
    res = await game.heard(server.T(), what)
    if res.ok and what != "listening":  # refusals and "listening" arrive all the time: not logged
        server.log.info("ear heard %s -> %s", what, res.message)
    return res.as_dict()


# server.py ends by mounting the web app at "/", which answers every address after
# it in the list. Move the two routes above in front of it.
routes = server.app.router.routes
for _ in range(2):
    routes.insert(0, routes.pop())


def fake_robot():
    """--fake: the fake robot the tests use, with real time, standing in locomotion mode."""
    import logging

    import tricks

    rig = test_tools.Rig(tricks=tricks.load_tricks)
    bootstrap.real_time(rig)
    for name in ("robot_api", "tools", "behaviors"):  # the rig keeps these logs to itself: print them again
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    return rig.ts


if FAKE:
    server.Robot = fake_robot  # what server.py creates when it starts

if __name__ == "__main__":
    if FAKE:
        print("FAKE ROBOT: nothing moves. Tool calls and the ear are logged below.", flush=True)
    uvicorn.run(server.app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
