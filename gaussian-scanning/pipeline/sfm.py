"""Stage 2: camera poses and a sparse point cloud with COLMAP (Structure-from-Motion).

feature extraction -> matching -> mapping -> undistortion -> text export.

Matching: "auto" uses exhaustive matching up to --exhaustive-limit frames
(catches loop closures when a room scan returns to its start), and sequential
matching beyond that. Mapping uses COLMAP 4's global mapper (GLOMAP) by
default, which is much faster than incremental mapping and usually as
accurate; "incremental" is the classic fallback if global mapping fails.

Outputs <run>/sfm/undistorted/{images,sparse} (pinhole images for training)
and <run>/sfm/sparse_txt (the same model as text).
"""
import argparse
import re
import struct
import subprocess
import time
from pathlib import Path

import numpy as np

from pipeline.colmap_io import read_model
from pipeline.common import RunPaths, fresh_dir, progress, result

PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)(?:, (\d+)/(\d+))?\]")
REGISTER_RE = re.compile(r"Registering image #\d+ \((\d+)\)")


def colmap(args: list[str], span: tuple[float, float], label: str, total_images: int) -> None:
    """Run one COLMAP command, streaming its log and mapping its [i/N] counters onto `span`."""
    cmd = ["colmap", *args, "--log_color", "0", "--log_target", "stderr"]
    print("$ " + " ".join(cmd), flush=True)
    lo, hi = span
    progress(lo, label)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    last, last_frac = 0.0, None
    for line in proc.stdout:
        print(line, end="", flush=True)
        frac = None
        if m := PROGRESS_RE.search(line):
            i, n = int(m[1]), int(m[2])
            if m[3]:  # exhaustive matching reports 2D blocks: [row/rows, col/cols]
                i, n = (i - 1) * int(m[4]) + int(m[3]), n * int(m[4])
            frac = i / n if n else None
        elif m := REGISTER_RE.search(line):
            frac = int(m[1]) / total_images
        if frac is not None and frac != last_frac and time.monotonic() - last > 1.0:
            progress(lo + (hi - lo) * min(frac, 1.0), label)
            last, last_frac = time.monotonic(), frac
    if proc.wait() != 0:
        raise SystemExit(f"colmap {args[0]} failed with exit code {proc.returncode}")


def num_registered(model_dir: Path) -> int:
    with open(model_dir / "images.bin", "rb") as fh:
        return struct.unpack("<Q", fh.read(8))[0]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--matcher", choices=["auto", "exhaustive", "sequential"], default="auto")
    p.add_argument("--exhaustive-limit", type=int, default=400)
    p.add_argument("--mapper", choices=["global", "incremental"], default="global")
    p.add_argument("--camera-model", choices=["OPENCV", "SIMPLE_RADIAL", "PINHOLE", "OPENCV_FISHEYE"], default="OPENCV")
    p.add_argument(
        "--single-camera",
        type=int,
        choices=[0, 1],
        default=1,
        help="1 = every frame shares one set of intrinsics (one physical camera, fixed zoom)",
    )
    p.add_argument("--use-gpu", type=int, choices=[0, 1], default=0, help="needs a CUDA build of COLMAP")
    args = p.parse_args()

    paths = RunPaths(args.run_dir)
    images = paths.frames
    n_frames = len(list(images.glob("*.jpg")))
    if n_frames == 0:
        raise SystemExit(f"no frames in {images}; run the frames stage first")

    sfm = fresh_dir(paths.sfm)
    db = sfm / "database.db"
    sparse = sfm / "sparse"
    sparse.mkdir()
    gpu = str(args.use_gpu)
    t0 = time.monotonic()

    colmap(
        [
            "feature_extractor",
            "--database_path", str(db),
            "--image_path", str(images),
            "--ImageReader.camera_model", args.camera_model,
            "--ImageReader.single_camera", str(args.single_camera),
            "--FeatureExtraction.use_gpu", gpu,
        ],
        (0.0, 0.25), "extracting features", n_frames,
    )

    matcher = args.matcher
    if matcher == "auto":
        matcher = "exhaustive" if n_frames <= args.exhaustive_limit else "sequential"
    match_args = [f"{matcher}_matcher", "--database_path", str(db), "--FeatureMatching.use_gpu", gpu]
    if matcher == "sequential":
        match_args += ["--SequentialMatching.overlap", "15"]
    colmap(match_args, (0.25, 0.55), f"{matcher} matching", n_frames)

    if args.mapper == "global":
        map_args = [
            "global_mapper",
            "--GlobalMapper.gp_use_gpu", gpu,
            "--GlobalMapper.ba_ceres_use_gpu", gpu,
        ]
    else:
        map_args = ["mapper", "--Mapper.ba_use_gpu", gpu]
    map_args += ["--database_path", str(db), "--image_path", str(images), "--output_path", str(sparse)]
    colmap(map_args, (0.55, 0.9), f"{args.mapper} mapping", n_frames)

    models = [m for m in sparse.iterdir() if (m / "images.bin").exists()]
    if not models:
        raise SystemExit("COLMAP produced no reconstruction -- check capture overlap/texture")
    counts = {m: num_registered(m) for m in models}
    best = max(counts, key=counts.get)
    if len(models) > 1:
        print(f"COLMAP split the scene into {len(models)} models {sorted(counts.values(), reverse=True)}; using the largest")

    colmap(
        [
            "image_undistorter",
            "--image_path", str(images),
            "--input_path", str(best),
            "--output_path", str(paths.undistorted),
            "--output_type", "COLMAP",
        ],
        (0.9, 0.97), "undistorting", n_frames,
    )
    paths.sparse_txt.mkdir()
    colmap(
        [
            "model_converter",
            "--input_path", str(paths.undistorted / "sparse"),
            "--output_path", str(paths.sparse_txt),
            "--output_type", "TXT",
        ],
        (0.97, 1.0), "exporting model", n_frames,
    )

    _, imgs, (xyz, _, err) = read_model(paths.sparse_txt)
    registered = len(imgs)
    progress(1.0, f"registered {registered}/{n_frames} frames, {len(xyz)} points")
    if registered < 0.5 * n_frames:
        print(f"WARNING: only {registered} of {n_frames} frames were registered")
    result(
        matcher=matcher,
        mapper=args.mapper,
        registered_frames=registered,
        total_frames=n_frames,
        num_models=len(models),
        sparse_points=int(len(xyz)),
        mean_reprojection_error_px=round(float(np.mean(err)), 3) if len(err) else None,
        sfm_seconds=round(time.monotonic() - t0, 1),
    )


if __name__ == "__main__":
    main()
