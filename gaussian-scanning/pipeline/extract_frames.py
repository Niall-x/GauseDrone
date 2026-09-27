"""Stage 1: turn a capture (video file or folder of photos) into training frames.

Video: the timeline is split into 1/fps-second buckets and the sharpest frame
in each bucket is kept (variance of the Laplacian, on a fixed-size greyscale
copy so the score doesn't depend on resolution). Frames are decoded in order
rather than seeked, which is both faster and exact for the variable-frame-rate
video phones produce, and each frame's real presentation timestamp is recorded
so it can later be matched to drone sensor logs.

Photos: copied (resized if larger than --max-size), in name order.

Writes <run>/frames/*.jpg and <run>/frames.csv (file_name, source,
timestamp_sec, sharpness, width, height).
"""
import argparse
import csv
import shutil
from pathlib import Path

import cv2
import numpy as np

from pipeline.common import IMAGE_EXTS, VIDEO_EXTS, RunPaths, fresh_dir, progress, result

SHARPNESS_SIZE = 640  # long side of the copy the blur score is measured on
CANDIDATES_PER_BUCKET = 8  # frames scored per bucket; the rest are skipped undecoded


def sharpness(img: np.ndarray) -> float:
    h, w = img.shape[:2]
    s = SHARPNESS_SIZE / max(h, w)
    small = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def fit(img: np.ndarray, max_size: int) -> np.ndarray:
    h, w = img.shape[:2]
    s = max_size / max(h, w)
    if max_size <= 0 or s >= 1:
        return img
    return cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)


def from_video(video: Path, out: Path, fps: float, max_size: int) -> tuple[list, dict]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"could not open video {video}")
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    stride = max(1, round(video_fps / fps / CANDIDATES_PER_BUCKET))

    rows = []
    best = None  # (sharpness, timestamp, frame) for the current bucket
    bucket = 0
    size = None

    def flush():
        if best is None:
            return
        s, t, frame = best
        name = f"frame_{len(rows):05d}.jpg"
        img = fit(frame, max_size)
        cv2.imwrite(str(out / name), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        rows.append((name, video.name, f"{t:.4f}", f"{s:.1f}", img.shape[1], img.shape[0]))

    index = 0
    while True:
        if index % stride:
            if not cap.grab():
                break
            index += 1
            continue
        ok, frame = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        size = size or frame.shape[1::-1]
        b = int(t * fps)
        if b != bucket:
            flush()
            best, bucket = None, b
        s = sharpness(frame)
        if best is None or s > best[0]:
            best = (s, t, frame)
        index += 1
        if index % 50 == 0:
            progress(index / total, f"decoded {index}/{total} frames, kept {len(rows)}")
    flush()
    cap.release()
    return rows, {"source_kind": "video", "video_fps": round(video_fps, 3), "source_size": size}


def from_images(src: Path, out: Path, max_size: int) -> tuple[list, dict]:
    files = sorted(p for p in src.rglob("*") if p.suffix.lower() in IMAGE_EXTS)
    if not files:
        raise SystemExit(f"no images found in {src}")
    rows, size = [], None
    for i, f in enumerate(files):
        img = cv2.imread(str(f))  # applies EXIF orientation
        if img is None:
            print(f"skipping unreadable image {f}")
            continue
        size = size or img.shape[1::-1]
        name = f"{i:05d}_{f.stem}.jpg"
        resized = fit(img, max_size)
        if resized is img and f.suffix.lower() in {".jpg", ".jpeg"}:
            shutil.copyfile(f, out / name)
        else:
            cv2.imwrite(str(out / name), resized, [cv2.IMWRITE_JPEG_QUALITY, 95])
        rows.append((name, str(f.relative_to(src)), "", f"{sharpness(img):.1f}", resized.shape[1], resized.shape[0]))
        if i % 10 == 0:
            progress(i / len(files), f"{i}/{len(files)} images")
    return rows, {"source_kind": "images", "source_size": size}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--input", type=Path, required=True, help="video file, or folder of photos")
    p.add_argument("--fps", type=float, default=2.0, help="frames kept per second of video")
    p.add_argument("--max-size", type=int, default=1600, help="longest image side in pixels (0 = keep)")
    p.add_argument(
        "--blur-reject",
        type=float,
        default=0.0,
        help="drop frames whose sharpness is below this fraction of the median (0 = off). "
        "Low-texture views also score low, so leave off unless blur is a known problem",
    )
    args = p.parse_args()

    paths = RunPaths(args.run_dir)
    out = fresh_dir(paths.frames)

    src = args.input
    if src.is_file() and src.suffix.lower() in VIDEO_EXTS:
        rows, info = from_video(src, out, args.fps, args.max_size)
    elif src.is_dir():
        videos = [v for v in src.iterdir() if v.suffix.lower() in VIDEO_EXTS]
        images = [i for i in src.rglob("*") if i.suffix.lower() in IMAGE_EXTS]
        if len(videos) == 1 and not images:
            rows, info = from_video(videos[0], out, args.fps, args.max_size)
        else:
            rows, info = from_images(src, out, args.max_size)
    else:
        raise SystemExit(f"{src} is neither a video file nor a folder")

    if args.blur_reject > 0 and rows:
        median = float(np.median([float(r[3]) for r in rows]))
        keep = [r for r in rows if float(r[3]) >= args.blur_reject * median]
        for r in rows:
            if r not in keep:
                (out / r[0]).unlink()
        print(f"blur reject: dropped {len(rows) - len(keep)} of {len(rows)} frames (median sharpness {median:.1f})")
        rows = keep

    if len(rows) < 3:
        raise SystemExit(f"only {len(rows)} usable frames; need many more for reconstruction")

    with open(paths.frames_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file_name", "source", "timestamp_sec", "sharpness", "width", "height"])
        w.writerows(rows)

    sizes = sorted({(int(r[4]), int(r[5])) for r in rows})
    progress(1.0, f"kept {len(rows)} frames")
    result(num_frames=len(rows), frame_size=list(sizes[0]) if len(sizes) == 1 else [list(x) for x in sizes], **info)


if __name__ == "__main__":
    main()
