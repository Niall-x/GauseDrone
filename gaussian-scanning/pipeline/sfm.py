"""Stage 2: camera poses and a sparse point cloud with COLMAP (Structure-from-Motion).

feature extraction -> matching -> mapping -> undistortion -> text export.

Matching: "auto" uses exhaustive matching up to --exhaustive-limit frames
(catches loop closures when a room scan returns to its start), and sequential
matching beyond that. Mapping: "auto" uses the incremental mapper up to
--incremental-limit frames and COLMAP 4's global mapper (GLOMAP) beyond.
Global mapping is faster on big captures, but on handheld video with little
parallax (turning on the spot, views through a window, blurry or blank
transitions) it confidently returns wrong poses: frames stacked on one spot,
jumps, flips. Incremental mapping registers each frame against triangulated
points instead, and splits the scene into pieces rather than forcing
unconnected parts together.

After mapping the poses are sanity-checked (check_poses) and any problems are
reported as `warnings` in the stage result, so a bad reconstruction doesn't
look like a clean "done".

Outputs <run>/sfm/undistorted/{images,sparse} (pinhole images for training)
and <run>/sfm/sparse_txt (the same model as text).
"""
import argparse
import csv
import re
import struct
import subprocess
import time
from pathlib import Path

import numpy as np

from pipeline.colmap_io import read_model
from pipeline.common import RunPaths, fresh_dir, progress, result

PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)(?:, (\d+)/(\d+))?\]")
REGISTER_RE = re.compile(r"Registering image #\d+ \((?:num_reg_frames=)?(\d+)\)")  # COLMAP 4.1 prints "(num_reg_frames=N)"
# The global mapper prints no counters; map its phases onto rough fractions
# (measured on a ~300-frame room: positioning and bundle adjustment dominate).
GLOBAL_MAPPER_PHASES = [
    (re.compile(r"Decomposing relative poses"), lambda m: 0.05),
    (re.compile(r"Rotation averaging done"), lambda m: 0.15),
    (re.compile(r"Track establishment done"), lambda m: 0.2),
    (re.compile(r"Global positioning done"), lambda m: 0.4),
    (re.compile(r"Global bundle adjustment iteration (\d+) / (\d+) finished"), lambda m: 0.4 + 0.45 * int(m[1]) / int(m[2])),
    (re.compile(r"[Rr]etriangulat"), lambda m: 0.9),
]


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
        else:
            for pattern, to_frac in GLOBAL_MAPPER_PHASES:
                if m := pattern.search(line):
                    frac = to_frac(m)
                    break
        if frac is not None and frac != last_frac and time.monotonic() - last > 1.0:
            progress(lo + (hi - lo) * min(frac, 1.0), label)
            last, last_frac = time.monotonic(), frac
    if proc.wait() != 0:
        raise SystemExit(f"colmap {args[0]} failed with exit code {proc.returncode}")


def num_registered(model_dir: Path) -> int:
    with open(model_dir / "images.bin", "rb") as fh:
        return struct.unpack("<Q", fh.read(8))[0]


# Pose sanity checks, calibrated on handheld room videos where the splat was
# visibly garbled (global mapper) or clean (incremental): the bad models had
# 3-13 neighbouring-frame steps over 8x the median step and frames stacked on
# one spot while turning; the good ones had neither (largest step 5x median).
JUMP_FACTOR = 8.0  # a step this many times the median step between neighbouring frames
STACK_FACTOR = 0.05  # ...or this small, while the view turns by more than STACK_MIN_TURN_DEG
STACK_MIN_TURN_DEG = 2.0
FLIP_MIN_DEG = 45.0  # a turn this large between neighbouring frames, faster than FLIP_DEG_PER_SEC
FLIP_DEG_PER_SEC = 180.0
MIN_GAP_FRAMES = 3  # report runs of this many consecutive unregistered frames


def where(labels: list[str], limit: int = 4) -> str:
    """'at 1.5 s, 3.0-4.5 s and 2 more' style list of places."""
    shown = ", ".join(labels[:limit])
    return f"{shown} and {len(labels) - limit} more" if len(labels) > limit else shown


def frame_list(frames_csv: Path, images: Path) -> list[tuple[str, float | None]]:
    """Every frame in capture order with its video timestamp (None for photos)."""
    if not frames_csv.exists():
        return [(p.name, None) for p in sorted(images.glob("*.jpg"))]
    with open(frames_csv) as fh:
        return [(r["file_name"], float(r["timestamp_sec"]) if r.get("timestamp_sec") else None) for r in csv.DictReader(fh)]


def check_poses(
    frames: list[tuple[str, float | None]],
    c2w: dict[str, np.ndarray],
    model_sizes: list[int],
    mapper: str,
) -> list[str]:
    """Human-readable warnings about a reconstruction that is likely wrong.

    frames: every extracted frame in capture order, with its video timestamp
    (None for photos). c2w: camera-to-world 4x4 of each registered frame.
    model_sizes: registered frames in each model COLMAP produced, largest first
    (c2w holds the largest).
    The neighbouring-frame checks only run for video, where consecutive frames
    really are close together in time and space.
    """
    warnings = []
    fix = "try the incremental mapper" if mapper == "global" else "try more frames per second, or refilm that part more slowly"

    # Incremental mapping sometimes leaves a small duplicate model of frames the
    # main one also has; that only matters if the model used is missing frames.
    if len(model_sizes) > 1 and len(c2w) < len(frames):
        warnings.append(
            f"COLMAP could not connect the capture into one scene: it split into {len(model_sizes)} pieces "
            f"({', '.join(map(str, model_sizes))} frames) and only the largest is used. "
            "The pieces usually meet at blurry or blank stretches of the capture."
        )

    def label(i: int, j: int | None = None) -> str:
        """Frame i (or frames i..j) as a time or name."""
        a, b = frames[i], frames[j if j is not None else i]
        if a[1] is not None and b[1] is not None:
            return f"{a[1]:.1f} s" if a is b else f"{a[1]:.1f}-{b[1]:.1f} s"
        return a[0] if a is b else f"{a[0]}-{b[0]}"

    def runs(indices: list[int]) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for i in indices:
            if out and i == out[-1][1] + 1:
                out[-1] = (out[-1][0], i)
            else:
                out.append((i, i))
        return out

    missing = [i for i, (name, _) in enumerate(frames) if name not in c2w]
    gaps = [(a, b) for a, b in runs(missing) if b - a + 1 >= MIN_GAP_FRAMES]
    if gaps:
        n = sum(b - a + 1 for a, b in gaps)
        warnings.append(
            f"{n} frames could not be placed, in stretches at {where([label(a, b) for a, b in gaps])}; "
            "the splat will be missing or thin there."
        )

    video = all(t is not None for _, t in frames)
    pairs = [(k, k + 1) for k in range(len(frames) - 1) if frames[k][0] in c2w and frames[k + 1][0] in c2w]
    if not video or len(pairs) < 10:
        return warnings

    steps, turns, dts = [], [], []
    for a, b in pairs:
        A, B = c2w[frames[a][0]], c2w[frames[b][0]]
        steps.append(np.linalg.norm(B[:3, 3] - A[:3, 3]))
        cos = (np.trace(A[:3, :3].T @ B[:3, :3]) - 1) / 2
        turns.append(np.degrees(np.arccos(np.clip(cos, -1, 1))))
        dts.append(max(frames[b][1] - frames[a][1], 1e-3))
    steps, turns, dts = map(np.array, (steps, turns, dts))
    median = float(np.median(steps))
    if median <= 0:
        return warnings

    def flagged(mask: np.ndarray) -> list[str]:
        return [label(pairs[s][0], pairs[e][1]) for s, e in runs(list(np.flatnonzero(mask)))]

    jumps = steps > JUMP_FACTOR * median
    if jumps.any():
        warnings.append(
            f"The camera path jumps {int(jumps.sum())} times (a step over {JUMP_FACTOR:g}x the usual distance between "
            f"neighbouring frames) at {where(flagged(jumps))}. These poses are probably wrong and will garble the splat; {fix}."
        )
    stacked = (steps < STACK_FACTOR * median) & (turns > STACK_MIN_TURN_DEG)
    if stacked.any():
        warnings.append(
            f"{int(stacked.sum())} frames were placed on the same spot as the previous one while the view turned, "
            f"at {where(flagged(stacked))}. This usually means SfM could not judge distance there "
            f"(turning on the spot, or looking out of a window); {fix}."
        )
    flips = (turns > FLIP_MIN_DEG) & (turns / dts > FLIP_DEG_PER_SEC)
    if flips.any():
        warnings.append(
            f"The camera flips round faster than a hand can turn it ({int(flips.sum())} times) at {where(flagged(flips))}. "
            f"Those poses are wrong; {fix}."
        )
    return warnings


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--matcher", choices=["auto", "exhaustive", "sequential"], default="auto")
    # 800 frames is ~3 min of video at 4 fps; exhaustive matching took 53 s for 310 frames and grows with n^2 (~6 min at 800).
    p.add_argument("--exhaustive-limit", type=int, default=800)
    p.add_argument("--mapper", choices=["auto", "incremental", "global"], default="auto")
    p.add_argument("--incremental-limit", type=int, default=800, help="auto mapper: incremental up to this many frames, global beyond")
    p.add_argument("--camera-model", choices=["OPENCV", "SIMPLE_RADIAL", "PINHOLE", "OPENCV_FISHEYE"], default="OPENCV")
    p.add_argument(
        "--single-camera",
        type=int,
        choices=[0, 1],
        default=1,
        help="1 = every frame shares one set of intrinsics (one physical camera, fixed zoom)",
    )
    p.add_argument("--use-gpu", type=int, choices=[0, 1], default=1, help="GPU SIFT extraction + matching (needs a CUDA build of COLMAP)")
    args = p.parse_args()

    paths = RunPaths(args.run_dir)
    images = paths.frames
    n_frames = len(list(images.glob("*.jpg")))
    if n_frames == 0:
        raise SystemExit(f"no frames in {images}; run the frames stage first")

    single_camera = args.single_camera
    if single_camera and paths.frames_csv.exists():
        with open(paths.frames_csv) as fh:
            sizes = {(r.get("width"), r.get("height")) for r in csv.DictReader(fh)}
        if len(sizes) > 1:
            # e.g. a photo set mixing portrait and landscape shots: one shared
            # camera can't have two image sizes.
            print(f"frames have {len(sizes)} different sizes; using one camera per image instead of a shared one")
            single_camera = 0

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
            "--ImageReader.single_camera", str(single_camera),
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

    mapper = args.mapper
    if mapper == "auto":
        mapper = "incremental" if n_frames <= args.incremental_limit else "global"
    # Bundle adjustment stays on the CPU: GPU BA needs Ceres built with CUDA +
    # cuDSS, which nixpkgs' Ceres isn't (COLMAP would just warn and fall back).
    if mapper == "global":
        map_args = ["global_mapper", "--GlobalMapper.gp_use_gpu", "0", "--GlobalMapper.ba_ceres_use_gpu", "0"]
    else:
        map_args = ["mapper", "--Mapper.ba_use_gpu", "0"]
    map_args += ["--database_path", str(db), "--image_path", str(images), "--output_path", str(sparse)]
    colmap(map_args, (0.55, 0.9), f"{mapper} mapping", n_frames)

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
    warnings = check_poses(
        frame_list(paths.frames_csv, images),
        {im.name: im.cam_to_world for im in imgs},
        sorted(counts.values(), reverse=True),
        mapper,
    )
    if registered < 0.5 * n_frames:
        warnings.insert(0, f"Only {registered} of {n_frames} frames could be placed.")
    for w in warnings:
        print(f"WARNING: {w}")
    result(
        matcher=matcher,
        mapper=mapper,
        registered_frames=registered,
        total_frames=n_frames,
        num_models=len(models),
        sparse_points=int(len(xyz)),
        mean_reprojection_error_px=round(float(np.mean(err)), 3) if len(err) else None,
        sfm_seconds=round(time.monotonic() - t0, 1),
        warnings=warnings,
    )


if __name__ == "__main__":
    main()
