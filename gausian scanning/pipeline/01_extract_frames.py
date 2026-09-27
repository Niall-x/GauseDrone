#!/usr/bin/env python3
"""Extract sharp, evenly-spaced frames from a video for splat capture.

Blurry frames are dropped using a Laplacian-variance sharpness check, since
motion blur is the main enemy of splat quality (see ../BRIEF.md). Rather
than blindly taking the frame at each sample time, this searches a small
window around it for the sharpest nearby frame.

Writes frame_timestamps.csv alongside the extracted frames, mapping each
kept file name to its source video timestamp -- needed later to match
frames against sensor readings (rangefinder log, etc).
"""
import argparse
import csv
from pathlib import Path

import cv2
import numpy as np


def sharpness(gray: np.ndarray) -> float:
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("video", type=Path, help="input video file")
    p.add_argument("out_dir", type=Path, help="output directory for frame images")
    p.add_argument("--fps", type=float, default=2.0, help="target sampling rate (frames/sec)")
    p.add_argument(
        "--blur-threshold",
        type=float,
        default=100.0,
        help="minimum Laplacian variance to keep a frame; raise if still getting blurry frames",
    )
    p.add_argument(
        "--search-window",
        type=float,
        default=0.3,
        help="seconds around each sample time to search for the sharpest nearby frame",
    )
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise SystemExit(f"could not open {args.video}")

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / video_fps
    step = 1.0 / args.fps
    window_frames = max(1, int(args.search_window * video_fps))

    kept = []
    t = 0.0
    idx_out = 0
    while t < duration:
        centre_frame = int(round(t * video_fps))
        best = None  # (sharpness, frame_idx, image)
        lo = max(0, centre_frame - window_frames)
        hi = min(frame_count, centre_frame + window_frames + 1)
        for f in range(lo, hi):
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            s = sharpness(gray)
            if best is None or s > best[0]:
                best = (s, f, frame)

        if best is not None and best[0] >= args.blur_threshold:
            s, f, frame = best
            name = f"frame_{idx_out:05d}.jpg"
            cv2.imwrite(str(args.out_dir / name), frame)
            kept.append((name, f"{f / video_fps:.3f}", f"{s:.1f}"))
            idx_out += 1
        else:
            best_s = f"{best[0]:.1f}" if best is not None else "n/a"
            print(f"skipped t={t:.2f}s: no sharp frame in window (best sharpness={best_s})")
        t += step

    cap.release()

    with open(args.out_dir / "frame_timestamps.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file_name", "timestamp_sec", "sharpness"])
        w.writerows(kept)

    print(f"kept {len(kept)} frames -> {args.out_dir}")


if __name__ == "__main__":
    main()
