"""Filesystem-backed store for captures and runs.

    <data>/captures/<id>/capture.json, source/, thumb.jpg
    <data>/runs/<id>/run.json, logs/, frames/, sfm/, train/, export/
"""
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2

from app.server.models import Capture, Run
from pipeline.common import IMAGE_EXTS, VIDEO_EXTS


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "untitled"


def write_json_atomic(path: Path, data: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(data)
    os.replace(tmp, path)


class Store:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.captures_dir = self.root / "captures"
        self.runs_dir = self.root / "runs"
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._runs: dict[str, Run] = {}
        self._captures: dict[str, Capture] = {}
        self.rescan()

    # --- loading ---

    def rescan(self) -> None:
        """Pick up folders added or removed outside the app (e.g. copied from another machine)."""
        with self.lock:
            for kind, directory, cache, model in (
                ("run", self.runs_dir, self._runs, Run),
                ("capture", self.captures_dir, self._captures, Capture),
            ):
                present = {p.name for p in directory.iterdir() if (p / f"{kind}.json").exists()}
                for gone in set(cache) - present:
                    del cache[gone]
                for new in present - set(cache):
                    try:
                        cache[new] = model.model_validate_json((directory / new / f"{kind}.json").read_text())
                    except ValueError as e:
                        print(f"skipping unreadable {kind} {new}: {e}")

    def new_id(self, name: str, directory: Path) -> str:
        base = f"{datetime.now():%Y%m%d-%H%M%S}-{slugify(name)}"
        candidate, i = base, 2
        while (directory / candidate).exists():
            candidate, i = f"{base}-{i}", i + 1
        return candidate

    # --- captures ---

    def capture_dir(self, capture_id: str) -> Path:
        return self.captures_dir / capture_id

    def list_captures(self) -> list[Capture]:
        self.rescan()
        with self.lock:
            return sorted(self._captures.values(), key=lambda c: c.created, reverse=True)

    def get_capture(self, capture_id: str) -> Capture | None:
        with self.lock:
            return self._captures.get(capture_id)

    def save_capture(self, capture: Capture) -> None:
        with self.lock:
            self._captures[capture.id] = capture
            write_json_atomic(self.capture_dir(capture.id) / "capture.json", capture.model_dump_json(indent=2))

    def delete_capture(self, capture_id: str) -> None:
        with self.lock:
            self._captures.pop(capture_id, None)
            d = self.capture_dir(capture_id)
            src = d / "source"
            if src.is_symlink():
                src.unlink()  # never delete the original files of a linked capture
            shutil.rmtree(d, ignore_errors=True)

    def finalize_capture(self, capture_id: str, name: str, origin: str, linked: bool) -> Capture:
        """Inspect a populated source/ folder and write its capture.json + thumbnail."""
        d = self.capture_dir(capture_id)
        src = d / "source"
        files = sorted(p for p in src.rglob("*") if p.is_file())
        images = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
        videos = [p for p in files if p.suffix.lower() in VIDEO_EXTS]
        if len(videos) == 1 and not images:
            kind = "video"
        elif images and not videos:
            kind = "images"
        else:
            raise ValueError(
                f"a capture must be one video or a set of photos (found {len(videos)} videos, {len(images)} images)"
            )

        capture = Capture(
            id=capture_id,
            name=name,
            kind=kind,
            files=[str(p.relative_to(src)) for p in (videos if kind == "video" else images)],
            num_images=len(images),
            size_bytes=sum(p.stat().st_size for p in files),
            origin=origin,
            linked=linked,
        )
        if kind == "video":
            cap = cv2.VideoCapture(str(videos[0]))
            fps = cap.get(cv2.CAP_PROP_FPS) or 0
            count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            capture.duration_sec = round(count / fps, 2) if fps else None
            ok, first = cap.read()
            cap.release()
        else:
            first = cv2.imread(str(images[0]))
            ok = first is not None
        if ok:
            h, w = first.shape[:2]
            capture.resolution = [w, h]
            s = 480 / max(w, h)
            cv2.imwrite(str(d / "thumb.jpg"), cv2.resize(first, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA))
        self.save_capture(capture)
        return capture

    # --- runs ---

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def list_runs(self) -> list[Run]:
        self.rescan()
        with self.lock:
            return sorted((r.model_copy(deep=True) for r in self._runs.values()), key=lambda r: r.created, reverse=True)

    def get_run(self, run_id: str) -> Run | None:
        with self.lock:
            run = self._runs.get(run_id)
            return run.model_copy(deep=True) if run else None

    def save_run(self, run: Run) -> None:
        with self.lock:
            self._runs[run.id] = run.model_copy(deep=True)
            d = self.run_dir(run.id)
            d.mkdir(parents=True, exist_ok=True)
            write_json_atomic(d / "run.json", run.model_dump_json(indent=2))

    def update_run(self, run_id: str, fn: Callable[[Run], None], persist: bool = True) -> Run:
        """Apply fn to the run under the lock. persist=False updates memory only
        (used for high-frequency progress ticks; the next persisted update writes them)."""
        with self.lock:
            run = self._runs[run_id]
            fn(run)
            if persist:
                write_json_atomic(self.run_dir(run_id) / "run.json", run.model_dump_json(indent=2))
            return run.model_copy(deep=True)

    def delete_run(self, run_id: str) -> None:
        with self.lock:
            self._runs.pop(run_id, None)
            shutil.rmtree(self.run_dir(run_id), ignore_errors=True)

    def runs_for_capture(self, capture_id: str) -> list[Run]:
        return [r for r in self.list_runs() if r.capture_id == capture_id]


