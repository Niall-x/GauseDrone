"""Stage 2: camera poses and a sparse point cloud with COLMAP (Structure-from-Motion).

feature extraction -> matching -> mapping -> quality check [-> one retry]
-> undistortion -> text export.

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

Quality check (pipeline/quality.py): the poses are checked for jumps, stacked
frames, impossible turns, unplaced stretches and split scenes, giving
structured `issues`, a `verdict` (good / gaps / unreliable) and frames to
leave out of training. If anything is wrong, one retry: the incremental
mapper, plus frames sampled at 3x the rate around the stretches that failed
(video only; the first attempt's features and matches are reused, so only the
new frames cost time). The better of the two attempts is kept. An unreliable
verdict makes the app pause the run before training.

Outputs <run>/sfm/undistorted/{images,sparse} (pinhole images for training),
<run>/sfm/sparse_txt (the same model as text), <run>/sfm/quality.json
(verdict, issues, excluded frames, attempts) and sfm/attempt*/ (COLMAP
databases and raw models). Extra frames from a retry live in sfm/images/.
"""
import argparse
import csv
import json
import os
import re
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pipeline.colmap_io import read_images, read_model
from pipeline.common import VIDEO_EXTS, RunPaths, fresh_dir, progress, result
from pipeline.extract_frames import sample_video
from pipeline.quality import VERDICT_RANK, Frame, blur_ranges, check_poses

RETRY_FPS_FACTOR = 3  # extra frames around failed stretches, at this multiple of the capture's frame rate
RETRY_MARGIN_SEC = 2.0  # ...from this long before to this long after each stretch

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



def read_frames(frames_csv: Path, images: Path) -> tuple[list[Frame], list[float], list[tuple[int, int]]]:
    """Every frame in capture order with its video timestamp (None for photos),
    plus its sharpness and (width, height)."""
    if not frames_csv.exists():
        names = sorted(p.name for p in images.glob("*.jpg"))
        return [(n, None) for n in names], [0.0] * len(names), []
    with open(frames_csv) as fh:
        rows = list(csv.DictReader(fh))
    frames = [(r["file_name"], float(r["timestamp_sec"]) if r.get("timestamp_sec") else None) for r in rows]
    sharp = [float(r.get("sharpness") or 0) for r in rows]
    sizes = [(int(r["width"]), int(r["height"])) for r in rows if r.get("width")]
    return frames, sharp, sizes


def find_video(source: Path | None) -> Path | None:
    if source is None:
        return None
    if source.is_file():
        return source if source.suffix.lower() in VIDEO_EXTS else None
    videos = [v for v in source.iterdir() if v.suffix.lower() in VIDEO_EXTS] if source.is_dir() else []
    return videos[0] if len(videos) == 1 else None


@dataclass
class Attempt:
    name: str
    work: Path
    images: Path
    frames: list[Frame]
    matcher: str = ""
    mapper: str = ""
    model: Path | None = None
    model_sizes: list[int] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    verdict: str = "unreliable"
    excluded: list[str] = field(default_factory=list)
    placed: int = 0

    def rank(self) -> tuple:
        """Lower is better: verdict first, then the share of frames that are placed and kept."""
        return VERDICT_RANK[self.verdict], -(self.placed - len(self.excluded)) / max(len(self.frames), 1)

    def summary(self) -> dict:
        return {"name": self.name, "matcher": self.matcher, "mapper": self.mapper, "frames": len(self.frames),
                "placed": self.placed, "excluded": len(self.excluded), "verdict": self.verdict,
                "models": self.model_sizes}


def reconstruct(a: Attempt, args, single_camera: int, span: tuple[float, float], mapper: str, db_from: Path | None = None) -> None:
    """COLMAP extraction, matching and mapping into a.work. With db_from, start
    from that database: images already in it keep their features and matches."""
    work = fresh_dir(a.work)
    db = work / "database.db"
    if db_from:
        shutil.copyfile(db_from, db)
    sparse = work / "sparse"
    sparse.mkdir()
    n = len(a.frames)
    gpu = str(args.use_gpu)
    lo, hi = span
    at = lambda f: lo + (hi - lo) * f  # noqa: E731
    prefix = "retry: " if db_from else ""

    extract = [
        "feature_extractor",
        "--database_path", str(db),
        "--image_path", str(a.images),
        "--ImageReader.camera_model", args.camera_model,
        "--ImageReader.single_camera", str(single_camera),
        "--FeatureExtraction.use_gpu", gpu,
    ]
    if db_from and single_camera:
        extract += ["--ImageReader.existing_camera_id", "1"]  # new frames share the first attempt's camera
    colmap(extract, (at(0.0), at(0.25)), f"{prefix}extracting features", n)

    a.matcher = args.matcher
    if a.matcher == "auto":
        a.matcher = "exhaustive" if n <= args.exhaustive_limit else "sequential"
    match_args = [f"{a.matcher}_matcher", "--database_path", str(db), "--FeatureMatching.use_gpu", gpu]
    if a.matcher == "sequential":
        match_args += ["--SequentialMatching.overlap", "15"]
    colmap(match_args, (at(0.25), at(0.55)), f"{prefix}{a.matcher} matching", n)

    a.mapper = mapper
    # Bundle adjustment stays on the CPU: GPU BA needs Ceres built with CUDA +
    # cuDSS, which nixpkgs' Ceres isn't (COLMAP would just warn and fall back).
    if mapper == "global":
        map_args = ["global_mapper", "--GlobalMapper.gp_use_gpu", "0", "--GlobalMapper.ba_ceres_use_gpu", "0"]
    else:
        map_args = ["mapper", "--Mapper.ba_use_gpu", "0"]
    map_args += ["--database_path", str(db), "--image_path", str(a.images), "--output_path", str(sparse)]
    colmap(map_args, (at(0.55), at(1.0)), f"{prefix}{mapper} mapping", n)

    models = [m for m in sparse.iterdir() if (m / "images.bin").exists()]
    counts = {m: num_registered(m) for m in models}
    if counts:
        a.model = max(counts, key=counts.get)
        a.model_sizes = sorted(counts.values(), reverse=True)
        if len(models) > 1:
            print(f"COLMAP split the scene into {len(models)} models {a.model_sizes}; using the largest")


def evaluate(a: Attempt, blurry: list[dict]) -> None:
    if a.model is None:
        a.issues = [{"kind": "few_placed", "severity": "error", "title": "The capture couldn't be reconstructed",
                     "detail": "COLMAP could not place any frames.", "fix": "Refilm with more overlap and texture.",
                     "ranges": [], "frames": 0}]
        a.verdict, a.excluded, a.placed = "unreliable", [], 0
        return
    txt = a.work / "txt"
    txt.mkdir(exist_ok=True)
    subprocess.run(["colmap", "model_converter", "--input_path", str(a.model), "--output_path", str(txt),
                    "--output_type", "TXT", "--log_target", "stderr"], check=True, capture_output=True)
    c2w = {im.name: im.cam_to_world for im in read_images(txt / "images.txt")}
    shutil.rmtree(txt)  # tens of MB, only needed for this check; the binary model stays
    a.placed = sum(1 for name, _ in a.frames if name in c2w)
    a.issues, a.verdict, a.excluded = check_poses(a.frames, c2w, a.model_sizes, a.mapper, blurry)
    print(f"{a.name}: {a.mapper} mapper, {a.placed}/{len(a.frames)} frames placed, verdict {a.verdict}")
    for i in a.issues:
        print(f"  {i['severity'].upper()}: {i['title']}. {i['detail']}")


def densify(first: Attempt, video: Path, work: Path, sizes: list[tuple[int, int]]) -> Attempt | None:
    """A copy of the first attempt's frames plus extra ones sampled around the
    stretches that failed; None if there is nothing to add."""
    times = [t for _, t in first.frames]
    ranges = [r for i in first.issues if i["kind"] in ("unplaced", "bad_poses") for r in i["ranges"] if r["start"] is not None]
    if not ranges or any(t is None for t in times):
        return None
    spacing = float(np.median(np.diff(times))) if len(times) > 1 else 0.25
    fps = RETRY_FPS_FACTOR / max(spacing, 1e-3)
    max_size = max(max(s) for s in sizes) if sizes else 1600
    windows: list[list[float]] = []
    for r in sorted(ranges, key=lambda r: r["start"]):
        lo, hi = r["start"] - RETRY_MARGIN_SEC, r["end"] + RETRY_MARGIN_SEC
        if windows and lo <= windows[-1][1]:
            windows[-1][1] = max(windows[-1][1], hi)
        else:
            windows.append([max(lo, 0.0), hi])

    images = fresh_dir(work)
    for name, _ in first.frames:
        os.link(first.images / name, images / name)
    names = [n for n, _ in first.frames]
    added: list[Frame] = []
    for lo, hi in windows:
        progress(0.62, f"retry: sampling extra frames at {lo:.1f}-{hi:.1f} s")

        def name(i, t):
            # Sort between the existing neighbours: frame_00123.jpg < frame_00123_01.jpg < frame_00124.jpg
            k = max(int(np.searchsorted(times, t)) - 1, 0)
            return f"{Path(names[k]).stem}_{i:03d}.jpg"
        rows, _ = sample_video(video, images, fps, max_size, start=lo, end=hi, name=name, skip_near=times)
        added += [(r[0], float(r[2])) for r in rows]
    if not added:
        return None
    print(f"retry: {len(added)} extra frames around {', '.join(f'{lo:.1f}-{hi:.1f} s' for lo, hi in windows)}")
    frames = sorted(first.frames + added, key=lambda f: f[1])
    return Attempt("retry", first.work.parent / "attempt2", images, frames)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--input", type=Path, help="the capture's source (video file or folder), for the retry's extra frames")
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
    p.add_argument("--retry", type=int, choices=[0, 1], default=1, help="1 = one automatic retry when the check finds problems")
    args = p.parse_args()

    paths = RunPaths(args.run_dir)
    if not any(paths.frames.glob("*.jpg")):
        raise SystemExit(f"no frames in {paths.frames}; run the frames stage first")
    frames, sharp, sizes = read_frames(paths.frames_csv, paths.frames)

    single_camera = args.single_camera
    if single_camera and len(set(sizes)) > 1:
        # e.g. a photo set mixing portrait and landscape shots: one shared
        # camera can't have two image sizes.
        print(f"frames have {len(set(sizes))} different sizes; using one camera per image instead of a shared one")
        single_camera = 0

    sfm = fresh_dir(paths.sfm)
    t0 = time.monotonic()
    blurry = blur_ranges(frames, sharp)
    mapper = args.mapper
    if mapper == "auto":
        mapper = "incremental" if len(frames) <= args.incremental_limit else "global"

    first = Attempt("first attempt", sfm / "attempt1", paths.frames, frames)
    reconstruct(first, args, single_camera, (0.0, 0.6), mapper)
    evaluate(first, blurry)
    chosen, attempts, retry_note = first, [first], ""

    if args.retry and first.verdict != "good":
        video = find_video(args.input)
        second = densify(first, video, sfm / "images", sizes) if video else None
        if second is None and mapper == "global":
            second = Attempt("retry", sfm / "attempt2", paths.frames, frames)
        if second is None:
            retry_note = "No automatic retry: there were no video moments to add frames around, and the incremental mapper was already used."
        else:
            reconstruct(second, args, single_camera, (0.62, 0.9), "incremental", db_from=first.work / "database.db")
            evaluate(second, blurry)
            attempts.append(second)
            better = second.rank() < first.rank()
            chosen = second if better else first
            extra = len(second.frames) - len(first.frames)
            how = " and ".join(filter(None, [
                "the incremental mapper" if mapper == "global" else "",
                f"{extra} extra frames around the problem stretches" if extra else "",
            ]))
            retry_note = (f"Retried automatically with {how}: {second.placed} of {len(second.frames)} frames placed "
                          f"(first attempt: {first.placed} of {len(first.frames)}). "
                          f"Kept the {'retry' if better else 'first attempt, which was better'}.")
            print(retry_note)
            # Only the kept attempt's database is worth its disk space (hundreds of MB).
            (second if not better else first).work.joinpath("database.db").unlink(missing_ok=True)

    if chosen.model is None:
        raise SystemExit("COLMAP produced no reconstruction -- check capture overlap/texture")
    n = len(chosen.frames)
    colmap(
        ["image_undistorter", "--image_path", str(chosen.images), "--input_path", str(chosen.model),
         "--output_path", str(paths.undistorted), "--output_type", "COLMAP"],
        (0.9, 0.97), "undistorting", n,
    )
    paths.sparse_txt.mkdir()
    colmap(
        ["model_converter", "--input_path", str(paths.undistorted / "sparse"), "--output_path", str(paths.sparse_txt),
         "--output_type", "TXT"],
        (0.97, 1.0), "exporting model", n,
    )

    _, imgs, (xyz, _, err) = read_model(paths.sparse_txt)
    quality = {
        "verdict": chosen.verdict,
        "issues": chosen.issues,
        "excluded": chosen.excluded,
        "frames": [{"name": name, "t": t} for name, t in chosen.frames],
        "attempts": [a.summary() for a in attempts],
        "kept": chosen.name,
        "retry": retry_note,
    }
    (paths.sfm / "quality.json").write_text(json.dumps(quality, indent=1))
    progress(1.0, f"placed {len(imgs)}/{n} frames, {len(xyz)} points; {chosen.verdict}")
    result(
        matcher=chosen.matcher,
        mapper=chosen.mapper,
        registered_frames=len(imgs),
        total_frames=n,
        added_frames=n - len(frames),
        excluded_frames=len(chosen.excluded),
        num_models=len(chosen.model_sizes),
        sparse_points=int(len(xyz)),
        mean_reprojection_error_px=round(float(np.mean(err)), 3) if len(err) else None,
        sfm_seconds=round(time.monotonic() - t0, 1),
        verdict=chosen.verdict,
        issues=chosen.issues,
        retry=retry_note,
    )


if __name__ == "__main__":
    main()
