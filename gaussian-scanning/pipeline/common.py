"""Shared helpers for pipeline stages.

Every stage is a standalone CLI (`python -m pipeline.<stage> --run-dir DIR ...`)
that reads its inputs from, and writes its outputs to, conventional paths
inside one run directory. The app runs stages as subprocesses and reads two
kinds of machine-readable lines from their stdout; everything else is log:

    @@progress <0..1> <message>
    @@result <json object>        (merged into the run record's outputs)
"""
import json
import shutil
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


class RunPaths:
    """Where each stage keeps its outputs inside a run directory."""

    def __init__(self, run_dir: Path):
        self.root = Path(run_dir)
        self.frames = self.root / "frames"
        self.frames_csv = self.root / "frames.csv"
        self.sfm = self.root / "sfm"
        self.undistorted = self.sfm / "undistorted"
        self.sparse_txt = self.sfm / "sparse_txt"
        self.train = self.root / "train"
        self.checkpoint = self.train / "splats.pt"
        self.export = self.root / "export"


def progress(fraction: float, message: str = "") -> None:
    print(f"@@progress {max(0.0, min(1.0, fraction)):.4f} {message}", flush=True)


def result(**values) -> None:
    print("@@result " + json.dumps(values), flush=True)


def fresh_dir(path: Path) -> Path:
    """Empty (or create) a stage's output directory so reruns never mix outputs."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path
