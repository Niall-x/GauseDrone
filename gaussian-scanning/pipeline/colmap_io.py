"""Read COLMAP text models (cameras.txt, images.txt, points3D.txt).

Only what the pipeline needs, and only undistorted pinhole cameras: the SfM
stage always runs `colmap image_undistorter` first, so training never has to
deal with lens distortion.
"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Camera:
    width: int
    height: int
    K: np.ndarray  # 3x3


@dataclass
class Image:
    name: str
    camera_id: int
    world_to_cam: np.ndarray  # 4x4, OpenCV convention (x right, y down, z forward)

    @property
    def cam_to_world(self) -> np.ndarray:
        return np.linalg.inv(self.world_to_cam)


def _lines(path: Path):
    with open(path) as fh:
        return [ln.rstrip("\n") for ln in fh if not ln.startswith("#")]


def qvec_to_rotmat(q) -> np.ndarray:
    w, x, y, z = q
    return np.array([
        [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y],
        [2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x],
        [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y],
    ])


def read_cameras(path: Path) -> dict[int, Camera]:
    cams = {}
    for ln in _lines(path):
        if not ln.strip():
            continue
        parts = ln.split()
        cid, model, w, h = int(parts[0]), parts[1], int(parts[2]), int(parts[3])
        p = [float(v) for v in parts[4:]]
        if model == "PINHOLE":
            fx, fy, cx, cy = p
        elif model == "SIMPLE_PINHOLE":
            fx, cx, cy = p
            fy = fx
        else:
            raise ValueError(f"camera {cid} is {model}; expected an undistorted PINHOLE model")
        cams[cid] = Camera(w, h, np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64))
    return cams


def read_images(path: Path) -> list[Image]:
    lines = _lines(path)
    images = []
    # Each image is two lines: pose line, then its 2D points (which may be empty).
    for i in range(0, len(lines) - 1, 2):
        parts = lines[i].split()
        if not parts:
            continue
        q = [float(v) for v in parts[1:5]]
        t = np.array([float(v) for v in parts[5:8]])
        w2c = np.eye(4)
        w2c[:3, :3] = qvec_to_rotmat(q)
        w2c[:3, 3] = t
        images.append(Image(name=" ".join(parts[9:]), camera_id=int(parts[8]), world_to_cam=w2c))
    return sorted(images, key=lambda im: im.name)


def read_points(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (xyz Nx3 float, rgb Nx3 uint8, reprojection error N)."""
    xyz, rgb, err = [], [], []
    for ln in _lines(path):
        parts = ln.split()
        if len(parts) < 8:
            continue
        xyz.append([float(v) for v in parts[1:4]])
        rgb.append([int(v) for v in parts[4:7]])
        err.append(float(parts[7]))
    return (
        np.array(xyz, dtype=np.float32).reshape(-1, 3),
        np.array(rgb, dtype=np.uint8).reshape(-1, 3),
        np.array(err, dtype=np.float32),
    )


def read_model(model_dir: Path):
    return (
        read_cameras(model_dir / "cameras.txt"),
        read_images(model_dir / "images.txt"),
        read_points(model_dir / "points3D.txt"),
    )
