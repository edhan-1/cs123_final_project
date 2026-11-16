#!/usr/bin/env python3
"""The eye: is the caller's back turned? For red light, green light by camera.

    python3 robot/eye.py                      (robot/start.sh runs it, next to the game server)
    python3 robot/eye.py --image frame.jpg    look at one saved camera picture, and say what the eye sees
    python3 robot/eye.py --pretend --server http://localhost:8011
                                              no camera: type b (back), f (facing) or u (unsure)

In a game by camera the caller turns their back for a green light and faces
Pupper for a red light. This program looks at Pupper's camera about ten times a
second, finds the caller, and tells the robot one word (POST /game/saw):

    "back"     no face in sight, and the shoulders the way round they are from behind
    "facing"   a face, or the shoulders the way round they are from the front
    "unsure"   nobody there, somebody side-on, a picture too blurry to tell

The eye only reports. What a word does (walk, hold still, red light) is decided
by saw() in game/red_light_green_light.py, the same split as the fast ear: the
page reports what it heard, the robot decides what counts.

How it sees: robot/pose.py runs a pose model on the Hailo. For every person it
gives 17 keypoints (nose, eyes, shoulders, ...), each with a score from 0 to 1:
how sure the model is that it can see that point. looks() below turns the
keypoints of one person into one of the three words.

The eye never moves Pupper by itself, but its reports do, through the game: it
is part of the robot, started and stopped with it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

import bootstrap

bootstrap.add_paths()
from fisheye_converter import load_camera_model  # noqa: E402  gemini_pupper/robot: the camera's lens model

from pose import INPUT_SIZE, LEFT_EYE, LEFT_SHOULDER, NOSE, RIGHT_EYE, RIGHT_SHOULDER, HailoPose, Person  # noqa: E402

# ------------------------------------------------------------ the numbers of the eye
SURE = 0.5  # a keypoint with a score above this counts as seen
PERSON_SURE = 0.6  # a person with a score below this is not there (a sofa scored 0.4 once)
MIDDLE = (0.2, 0.8)  # the caller stands in this part of the picture's width: the finish line is straight ahead
SHOULDERS_APART = 0.1  # from behind, the shoulders are at least this far apart, as a part of the person's height

VIEW_DEG = 90.0  # the eye looks at a square this wide and this high, straight ahead ...
VIEW_UP_DEG = 25.0  # ... and tilted up by this much: Pupper is small and people are tall
LOOKS_PER_S = 10.0  # pictures looked at per second during a game by camera
IDLE_LOOKS_PER_S = 1.0  # ... and the rest of the time, to keep the Pi cool

SERVER = "http://localhost:8000"
CAMERA_PARAMS = bootstrap.GEMINI_PUPPER / "robot" / "camera_params.yaml"
PICTURE = bootstrap.EYE_PICTURE  # what the eye sees, for the page (GET /game/eye.jpg)


# ============================================================ what the eye decides
def pick_caller(people: list[Person]) -> Person | None:
    """The caller is the tallest person in the middle of the picture. None: nobody is there."""
    middle = [p for p in people
              if p.score >= PERSON_SURE and MIDDLE[0] * INPUT_SIZE <= p.middle <= MIDDLE[1] * INPUT_SIZE]
    return max(middle, key=lambda p: p.height, default=None)


def looks(person: Person) -> str:
    """Which way is this person turned? "facing", "back" or "unsure".

    Two clues. The face: from behind, the model cannot see a nose or eyes. And
    the shoulders: a person facing Pupper has their left shoulder on the RIGHT
    of the picture; from behind it is on the left.

    "facing" needs one clue: stopping may be trigger-happy. "back" needs both,
    and the shoulders well apart (side-on they are on top of each other): a
    back is what makes Pupper walk, so the eye has to be sure.
    """
    seen = person.points[:, 2] > SURE
    face = int(seen[NOSE]) + int(seen[LEFT_EYE]) + int(seen[RIGHT_EYE])  # how many of the three are seen
    shoulders = seen[LEFT_SHOULDER] and seen[RIGHT_SHOULDER]
    apart = person.points[RIGHT_SHOULDER, 0] - person.points[LEFT_SHOULDER, 0]  # pixels; above 0 from behind
    if face >= 2 or (shoulders and apart < 0):
        return "facing"
    if face == 0 and shoulders and apart > SHOULDERS_APART * person.height:
        return "back"
    return "unsure"


def see(people: list[Person]) -> tuple[str, Person | None]:
    """One picture's people -> the word for the robot, and who the caller is."""
    caller = pick_caller(people)
    return (looks(caller) if caller else "unsure"), caller


# ============================================================ the camera picture
class View:
    """The part of the camera picture the eye looks at.

    Pupper's camera is a fisheye: it sees more than half the world, bent, and a
    person 3 m away is only about 130 pixels tall. The model wants a flat 640 x
    640 picture. So we cut out the part where the caller is (VIEW_DEG wide,
    straight ahead and a little up) and stretch it flat: for every pixel of the
    view, which pixel of the camera picture shows that direction? Lab 5 did the
    same for the whole picture.
    """

    def __init__(self, width: int, height: int):
        lens = load_camera_model(CAMERA_PARAMS, width, height)
        left_right = np.deg2rad(np.linspace(-VIEW_DEG / 2, VIEW_DEG / 2, INPUT_SIZE))
        down_up = np.deg2rad(np.linspace(-VIEW_DEG / 2 - VIEW_UP_DEG, VIEW_DEG / 2 - VIEW_UP_DEG, INPUT_SIZE))  # up is negative
        lon, lat = np.meshgrid(left_right, down_up)
        x, y, _ = lens.project(np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon))
        self.size = (width, height)
        self.x, self.y = x.astype(np.float32), y.astype(np.float32)

    def of(self, frame: np.ndarray) -> np.ndarray:
        return cv2.remap(frame, self.x, self.y, cv2.INTER_LINEAR)


def draw(view: np.ndarray, people: list[Person], caller: Person | None, word: str) -> np.ndarray:
    """The view with what the eye made of it drawn in, for people to check (BGR colours)."""
    colour = {"back": (80, 200, 80), "facing": (60, 60, 255), "unsure": (0, 200, 255)}[word]
    for person in people:
        x1, y1, x2, y2 = (int(v) for v in person.box)
        cv2.rectangle(view, (x1, y1), (x2, y2), colour if person is caller else (140, 140, 140), 3 if person is caller else 1)
    if caller is not None:
        for k in (NOSE, LEFT_EYE, RIGHT_EYE, LEFT_SHOULDER, RIGHT_SHOULDER):
            x, y, score = caller.points[k]
            if score > SURE:  # the person's left side in yellow, the rest in white
                cv2.circle(view, (int(x), int(y)), 5, (0, 255, 255) if k in (LEFT_EYE, LEFT_SHOULDER) else (255, 255, 255), -1)
    for mark in MIDDLE:  # the caller has to stand between these two lines
        cv2.line(view, (int(mark * INPUT_SIZE), 0), (int(mark * INPUT_SIZE), INPUT_SIZE), (90, 90, 90), 1)
    text = word if caller is not None else "nobody"
    cv2.putText(view, text, (12, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 7, cv2.LINE_AA)
    cv2.putText(view, text, (12, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.4, colour, 3, cv2.LINE_AA)
    return view


def save(picture: np.ndarray, where: Path = PICTURE) -> None:
    """Write the picture where the game server finds it. Renamed into place, so nobody reads half a file."""
    where.parent.mkdir(parents=True, exist_ok=True)
    half = where.with_suffix(".tmp.jpg")
    cv2.imwrite(str(half), picture, [cv2.IMWRITE_JPEG_QUALITY, 70])
    os.replace(half, where)


# ============================================================ telling the robot
def tell(server: str, what: str) -> dict:
    """Tell the robot what the eye sees. The robot decides whether it counts."""
    request = urllib.request.Request(server + "/game/saw", json.dumps({"what": what}).encode(),
                                     {"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=1.0) as reply:
        return json.load(reply)


class Reporter:
    """tell(), plus: print when something changes, and know how often to look."""

    def __init__(self, server: str):
        self.server, self.last, self.reached = server, "", True
        self.game_on = False  # is a game by camera on? (the robot's reply says so)

    def report(self, what: str) -> None:
        try:
            reply = tell(self.server, what)
        except OSError as error:  # the game server is not running (yet)
            if self.reached:
                print(f"cannot reach the game server at {self.server}: {error}", flush=True)
            self.reached, self.game_on = False, False
            return
        self.reached, self.game_on = True, bool(reply.get("camera_game"))
        if reply.get("success"):  # it changed a light
            print(f"saw {what} -> {reply.get('message')}", flush=True)
        elif what != self.last and self.game_on:
            print(f"saw {what}", flush=True)
        self.last = what

    def nap(self, began: float) -> None:
        """Wait for the rest of this look's time."""
        time.sleep(max(0.0, 1.0 / (LOOKS_PER_S if self.game_on else IDLE_LOOKS_PER_S) - (time.monotonic() - began)))


# ============================================================ the three ways to run it
def watch(server: str) -> None:
    """The real eye: Pupper's camera, the Hailo, and reports until it is stopped."""
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import CompressedImage

    try:
        model = HailoPose()
    except Exception as error:
        sys.exit(f"The eye cannot use the Hailo: {error}\nAnother program may be holding it (a person detector?)."
                 " Stop everything with robot/stop.sh, then start it with robot/start.sh.")
    rclpy.init()
    node = Node("game_eye")
    newest = []  # the newest camera picture, or nothing

    def on_image(msg):
        newest[:] = [msg]

    node.create_subscription(CompressedImage, "/camera/image_raw/compressed", on_image, 1)
    reporter, view, saved = Reporter(server), None, 0.0
    print(f"the eye is watching, and reports to {server}", flush=True)
    try:
        while rclpy.ok():
            began = time.monotonic()
            rclpy.spin_once(node, timeout_sec=0.5)  # wait for a picture
            if not newest:
                continue  # no camera picture: say nothing, and the robot will notice the silence
            frame = cv2.imdecode(np.frombuffer(bytes(newest.pop().data), np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            if view is None or view.size != (frame.shape[1], frame.shape[0]):
                view = View(frame.shape[1], frame.shape[0])
            flat = view.of(frame)
            people = model.infer(cv2.cvtColor(flat, cv2.COLOR_BGR2RGB))
            word, caller = see(people)
            reporter.report(word)
            if began - saved >= 0.5:  # twice a second is plenty for people to look at
                save(draw(flat, people, caller, word))
                saved = began
            reporter.nap(began)
    except KeyboardInterrupt:
        pass
    finally:
        model.close()


def look_at(image: str, out: str) -> None:
    """--image: what does the eye make of one saved camera picture? Nothing is told to the robot."""
    frame = cv2.imread(image)
    if frame is None:
        sys.exit(f"cannot read {image}")
    model = HailoPose()
    try:
        flat = View(frame.shape[1], frame.shape[0]).of(frame)
        people = model.infer(cv2.cvtColor(flat, cv2.COLOR_BGR2RGB), min_score=0.3)
    finally:
        model.close()
    word, caller = see(people)
    for person in people:
        scores = ", ".join(f"{name} {person.points[k, 2]:.2f}" for k, name in
                           ((NOSE, "nose"), (LEFT_EYE, "left eye"), (RIGHT_EYE, "right eye"),
                            (LEFT_SHOULDER, "left shoulder"), (RIGHT_SHOULDER, "right shoulder")))
        apart = person.points[RIGHT_SHOULDER, 0] - person.points[LEFT_SHOULDER, 0]
        print(f"{'the caller' if person is caller else 'a person  '}: score {person.score:.2f}, {person.height:.0f} px tall,"
              f" at {person.middle / INPUT_SIZE:.2f} of the width; {scores}; shoulders {apart:+.0f} px apart"
              f" -> {looks(person)}")
    print(f"the eye says: {word}" + ("" if caller else " (nobody in the middle of the picture)"))
    save(draw(flat, people, caller, word), Path(out))
    print(f"wrote {out}")


def pretend(server: str) -> None:
    """--pretend: no camera and no Hailo. You are the eye: type what it sees."""
    import threading

    word = ["unsure"]

    def keys():
        for line in sys.stdin:
            word[0] = {"b": "back", "f": "facing"}.get(line.strip()[:1].lower(), "unsure")
            print(f"the eye now says: {word[0]}", flush=True)

    threading.Thread(target=keys, daemon=True).start()
    print(f"Pretend eye, reporting to {server}. Type b (back), f (facing) or u (unsure), then Enter.", flush=True)
    reporter = Reporter(server)
    while True:
        began = time.monotonic()
        reporter.report(word[0])
        reporter.nap(began)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default=os.environ.get("GAME_SERVER", SERVER), help=f"the game server (default {SERVER})")
    ap.add_argument("--image", help="look at this saved camera picture instead of the camera, and tell the robot nothing")
    ap.add_argument("--out", default="seen.jpg", help="with --image: where to write what the eye saw (default seen.jpg)")
    ap.add_argument("--pretend", action="store_true", help="no camera: type what the eye sees (for a fake robot)")
    args = ap.parse_args()
    if args.image:
        look_at(args.image, args.out)
    elif args.pretend:
        try:
            pretend(args.server)
        except KeyboardInterrupt:
            print()
    else:
        watch(args.server)


if __name__ == "__main__":
    main()
