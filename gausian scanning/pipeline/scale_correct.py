#!/usr/bin/env python3
"""Tier 1 scale correction: resolve COLMAP/nerfstudio's arbitrary scale
using one or more known real-world camera-to-camera distances.

Monocular SfM reconstructs shape correctly but at an unknown, arbitrary
scale. Given a handful of frames where the REAL 3D distance between camera
positions is known (e.g. two shots at tape-measured heights, or later,
drone rangefinder readings synced to frames), this fits a single scale
factor by least squares and applies it to every camera pose.

Only pairwise camera-to-camera distances are used -- never a single "height"
read straight off one of COLMAP's own axes, because COLMAP's reconstruction
has no known up-axis or origin, only internally-consistent (if unscaled)
relative distances. Two or more reference heights are enough even though
they aren't along a COLMAP-recognised vertical axis.

Sync between video time and rangefinder time is NOT handled here -- this
assumes reference_points.csv already lines up file names with a real-world
reading. See ../BRIEF.md section 4 for the sync discussion and the planned
Tier 2 (full trajectory alignment) upgrade.
"""
import argparse
import csv
import json
from itertools import combinations
from pathlib import Path

import numpy as np


def load_transforms(path: Path) -> dict:
    with open(path) as fh:
        return json.load(fh)


def camera_center(transform_matrix) -> np.ndarray:
    return np.array(transform_matrix)[:3, 3]


def load_reference_heights(path: Path) -> dict:
    heights = {}
    with open(path) as fh:
        for row in csv.DictReader(fh):
            heights[row["file_name"]] = float(row["height_m"])
    return heights


def fit_scale(frames: list, heights: dict) -> float:
    """Least-squares scale fit: minimises sum((real_i - scale*colmap_i)^2)."""
    by_name = {Path(f["file_path"]).name: camera_center(f["transform_matrix"]) for f in frames}

    real_dists, colmap_dists, pairs = [], [], []
    for name_a, name_b in combinations(heights, 2):
        if name_a not in by_name or name_b not in by_name:
            print(f"warning: {name_a} or {name_b} not found in transforms.json, skipping")
            continue
        colmap_d = float(np.linalg.norm(by_name[name_a] - by_name[name_b]))
        real_d = abs(heights[name_a] - heights[name_b])
        if colmap_d < 1e-9:
            continue
        real_dists.append(real_d)
        colmap_dists.append(colmap_d)
        pairs.append((name_a, name_b, real_d, colmap_d))

    if not pairs:
        raise SystemExit("no usable reference pairs found -- check file names match transforms.json")

    real = np.array(real_dists)
    colmap = np.array(colmap_dists)
    scale = float(np.dot(real, colmap) / np.dot(colmap, colmap))

    print(f"fitted scale factor: {scale:.6f}  (from {len(pairs)} pairs)")
    print(f"{'pair':40s} {'real_m':>8s} {'colmap':>8s} {'pred_m':>8s} {'err_m':>8s}")
    for a, b, real_d, colmap_d in pairs:
        pred = colmap_d * scale
        label = f"{a[:18]}~{b[:18]}"
        print(f"{label:40s} {real_d:8.3f} {colmap_d:8.3f} {pred:8.3f} {abs(real_d - pred):8.3f}")

    return scale


def apply_scale(data: dict, scale: float) -> dict:
    for frame in data["frames"]:
        m = np.array(frame["transform_matrix"])
        m[:3, 3] *= scale
        frame["transform_matrix"] = m.tolist()
    return data


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("transforms", type=Path, help="input transforms.json from ns-process-data")
    p.add_argument(
        "reference_points",
        type=Path,
        help="CSV with columns file_name,height_m for a few known-height frames",
    )
    p.add_argument("output", type=Path, help="output path for scaled transforms.json")
    args = p.parse_args()

    data = load_transforms(args.transforms)
    heights = load_reference_heights(args.reference_points)
    scale = fit_scale(data["frames"], heights)
    scaled = apply_scale(data, scale)

    with open(args.output, "w") as fh:
        json.dump(scaled, fh, indent=2)
    print(f"wrote scaled transforms -> {args.output}")


if __name__ == "__main__":
    main()
