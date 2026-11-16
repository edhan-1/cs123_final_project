#!/usr/bin/env python3
"""Where a person's nose, eyes and shoulders are: YOLOv8s-pose on the Hailo.

The eye (robot/eye.py) uses this to tell whether the caller's back is turned.
It is the same kind of file as follow_me_pupper/robot/yolo_seg.py from lab 5:
the model comes from the Hailo model zoo, the chip hands back raw tensors, and
this file turns them into people. Nothing here knows about the game.

For every person the model gives a box and 17 keypoints (the COCO set, see
KEYPOINTS), each with x, y and a score from 0 to 1: how sure the model is that
it can see that point. A nose seen from behind gets a low score.

The model's outputs, for each of three grid sizes (80x80, 40x40, 20x20 cells):

    64 channels   the box: 4 sides x 16 bins (a histogram of distances, as in lab 5)
     1 channel    the score: is a person centred in this cell? (already 0 to 1)
    51 channels   17 keypoints x (x, y, score)

Quick check on a still picture from Pupper's camera (nothing moves):

    python3 robot/eye.py --image some_frame.jpg --out seen.jpg
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

MODEL = os.environ.get("POSE_MODEL", "/usr/share/hailo-models/yolov8s_pose_h8l_pi.hef")  # comes with the Pi's Hailo software
INPUT_SIZE = 640  # the model looks at a 640 x 640 picture
BINS = 16
KEYPOINTS = ["nose", "left eye", "right eye", "left ear", "right ear", "left shoulder", "right shoulder",
             "left elbow", "right elbow", "left wrist", "right wrist", "left hip", "right hip",
             "left knee", "right knee", "left ankle", "right ankle"]
NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR, LEFT_SHOULDER, RIGHT_SHOULDER = range(7)


@dataclass
class Person:
    """One person in the picture. The left shoulder is the person's own left."""

    score: float  # 0 to 1: how sure the model is that this is a person
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels of the picture given to infer()
    points: np.ndarray  # 17 rows of (x, y, score), in the order of KEYPOINTS

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]

    @property
    def middle(self) -> float:
        return (self.box[0] + self.box[2]) / 2


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def softmax(x):
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def overlap(box, others):
    """How much `box` overlaps each of `others` (intersection over union, 0 to 1)."""
    x1, y1 = np.maximum(box[0], others[:, 0]), np.maximum(box[1], others[:, 1])
    x2, y2 = np.minimum(box[2], others[:, 2]), np.minimum(box[3], others[:, 3])
    both = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    area = lambda b: (b[..., 2] - b[..., 0]) * (b[..., 3] - b[..., 1])  # noqa: E731
    return both / np.maximum(area(box) + area(others) - both, 1e-9)


def decode(outputs: dict[str, np.ndarray], min_score: float = 0.5) -> list[Person]:
    """The model's raw outputs -> people, best first. `outputs` maps a layer's name to its array."""
    # Sort the nine layers by grid size and by what they are (their number of channels).
    grids: dict[int, dict[int, np.ndarray]] = {}
    for out in outputs.values():
        grids.setdefault(out.shape[0], {})[out.shape[2]] = out
    found = []  # (score, box, points) of every cell that says "a person is centred here"
    for cells, layers in grids.items():
        stride = INPUT_SIZE / cells  # pixels per cell
        scores = layers[1].reshape(-1)
        hits = np.nonzero(scores >= min_score)[0]
        if hits.size == 0:
            continue
        cx, cy = hits % cells, hits // cells  # which cell, as column and row
        # The box: each side is a histogram over 16 distances (in cells) from the
        # cell's centre; the distance is the histogram's mean.
        sides = (softmax(layers[4 * BINS].reshape(-1, 4, BINS)[hits]) * np.arange(BINS)).sum(axis=-1)
        left, top, right, bottom = sides.T
        boxes = np.stack([cx + 0.5 - left, cy + 0.5 - top, cx + 0.5 + right, cy + 0.5 + bottom], axis=1) * stride
        # The keypoints: x and y are counted from the cell, in half cells.
        points = layers[51].reshape(-1, 17, 3)[hits].astype(np.float32)
        points[..., 0] = (points[..., 0] * 2 + cx[:, None]) * stride
        points[..., 1] = (points[..., 1] * 2 + cy[:, None]) * stride
        points[..., 2] = sigmoid(points[..., 2])
        found += list(zip(scores[hits], boxes, points))
    # Neighbouring cells report the same person: keep the best, drop those that overlap it.
    found.sort(key=lambda f: -f[0])
    people: list[Person] = []
    for score, box, points in found:
        if people and overlap(box, np.array([p.box for p in people])).max() > 0.6:
            continue
        people.append(Person(float(score), tuple(float(v) for v in box), points))
    return people


class HailoPose:
    """Runs the pose model on the Hailo. One at a time: call infer() from one thread."""

    def __init__(self, model_path: str = MODEL):
        from hailo_platform import FormatType, HailoSchedulingAlgorithm, VDevice

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"{model_path} not found (sudo apt install hailo-all, or set POSE_MODEL)")
        params = VDevice.create_params()
        params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
        self.device = VDevice(params)  # fails if another program holds the Hailo
        model = self.device.create_infer_model(model_path)
        model.set_batch_size(1)
        self.shapes = {}
        for name in model.output_names:
            model.output(name).set_format_type(FormatType.FLOAT32)  # real numbers, not the chip's 8-bit codes
            self.shapes[name] = tuple(model.output(name).shape)
        self.configured = model.configure()
        self.bindings = self.configured.create_bindings(
            output_buffers={name: np.empty(shape, np.float32) for name, shape in self.shapes.items()})

    def infer(self, picture: np.ndarray, min_score: float = 0.5) -> list[Person]:
        """People in a 640 x 640 RGB picture, best first."""
        self.bindings.input().set_buffer(np.ascontiguousarray(picture))
        self.configured.run([self.bindings], 10000)
        return decode({name: self.bindings.output(name).get_buffer() for name in self.shapes}, min_score)

    def close(self) -> None:
        """Let go of the Hailo, so that another program can use it."""
        configured, self.configured = self.configured, None
        if configured is not None:
            configured.__exit__(None, None, None)
        self.device.release()
