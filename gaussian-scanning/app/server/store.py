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

from app.server.models import Capture, Run, Upload, UploadFileSpec, UploadItem
from pipeline.common import IMAGE_EXTS, VIDEO_EXTS


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "untitled"


def capture_kind(num_videos: int, num_images: int) -> str:
    if num_videos == 1 and not num_images:
        return "video"
    if num_images and not num_videos:
        return "images"
    raise ValueError(f"a capture must be one video or a set of photos (found {num_videos} videos, {num_images} images)")


def check_source(src: Path, max_files: int = 100_000) -> str:
    """Capture kind of a file/folder before anything is copied; bails out early on
    a folder that can't be a capture (e.g. a mistyped `~`) instead of walking it all."""
    images = videos = seen = 0
    for p in [src] if src.is_file() else src.rglob("*"):
        seen += 1
        if seen > max_files:
            raise ValueError(f"{src} holds over {max_files:,} files; point at the capture's own folder")
        ext = p.suffix.lower()
        images += ext in IMAGE_EXTS
        videos += ext in VIDEO_EXTS
        if videos > 1 or (videos and images):
            break
    return capture_kind(videos, images)


def write_json_atomic(path: Path, data: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(data)
    os.replace(tmp, path)


class Store:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.captures_dir = self.root / "captures"
        self.runs_dir = self.root / "runs"
        self.uploads_dir = self.root / "uploads"
        for d in (self.captures_dir, self.runs_dir, self.uploads_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        # Uploads have their own locks (one per upload) so writing a large chunk
        # never stalls run progress updates or other requests behind self.lock.
        self._uploads_lock = threading.Lock()
        self._upload_locks: dict[str, threading.Lock] = {}
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
        kind = capture_kind(len(videos), len(images))

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

    # --- uploads (resumable; each file's size on disk is how much has arrived) ---

    def upload_dir(self, upload_id: str) -> Path:
        return self.uploads_dir / upload_id

    def _upload_lock(self, upload_id: str) -> threading.Lock:
        with self._uploads_lock:
            return self._upload_locks.setdefault(upload_id, threading.Lock())

    def create_upload(self, name: str, specs: list[UploadFileSpec]) -> Upload:
        items, taken = [], set()
        for spec in specs:
            # Folder uploads are flattened; camera dumps often repeat names across
            # subfolders (DCIM/100/IMG_0001, DCIM/101/IMG_0001), so never clash.
            p = Path(spec.source.replace("\\", "/"))
            if not p.name or p.name.startswith(".") or "\0" in p.name or len(p.name.encode()) > 200:
                raise ValueError(f"unusable file name {spec.source!r}")
            target, i = p.name, 2
            while target in taken:
                target, i = f"{p.stem}_{i}{p.suffix}", i + 1
            taken.add(target)
            items.append(UploadItem(source=spec.source, name=target, size=spec.size))
        capture_kind(
            sum(Path(f.name).suffix.lower() in VIDEO_EXTS for f in items),
            sum(Path(f.name).suffix.lower() in IMAGE_EXTS for f in items),
        )
        with self._uploads_lock:  # new_id + mkdir must not race another create
            upload = Upload(id=self.new_id(name, self.uploads_dir), name=name, files=items)
            d = self.upload_dir(upload.id)
            (d / "files").mkdir(parents=True)
        try:
            for item in items:
                (d / "files" / item.name).touch()
            write_json_atomic(d / "upload.json", upload.model_dump_json(indent=2))
        except OSError:
            shutil.rmtree(d, ignore_errors=True)
            raise
        return upload

    def get_upload(self, upload_id: str) -> Upload | None:
        path = self.upload_dir(upload_id) / "upload.json"
        if not path.exists():
            return None
        upload = Upload.model_validate_json(path.read_text())
        for item in upload.files:
            f = self.upload_dir(upload_id) / "files" / item.name
            item.received = f.stat().st_size if f.exists() else 0
        return upload

    def list_uploads(self) -> list[Upload]:
        uploads = [self.get_upload(p.name) for p in self.uploads_dir.iterdir()]
        return sorted((u for u in uploads if u), key=lambda u: u.created, reverse=True)

    def write_chunk(self, upload_id: str, index: int, offset: int, data: bytes | bytearray) -> UploadItem:
        """Append data to one file at exactly `offset`. A mismatched offset (e.g. a
        retry of a chunk that did arrive) raises OffsetMismatch with the true size."""
        with self._upload_lock(upload_id):
            upload = self.get_upload(upload_id)
            if upload is None or not 0 <= index < len(upload.files):
                raise KeyError(upload_id)
            item = upload.files[index]
            if offset != item.received:
                raise OffsetMismatch(item.received)
            if offset + len(data) > item.size:
                raise ValueError(f"{item.name}: chunk runs past the declared size {item.size}")
            with open(self.upload_dir(upload_id) / "files" / item.name, "r+b") as fh:
                fh.seek(offset)
                fh.write(data)
            item.received += len(data)
            return item

    def finish_upload(self, upload_id: str) -> Capture:
        with self._upload_lock(upload_id):
            upload = self.get_upload(upload_id)
            if upload is None:
                raise KeyError(upload_id)
            incomplete = [f.name for f in upload.files if f.received != f.size]
            if incomplete:
                raise ValueError(f"{len(incomplete)} file(s) not fully uploaded yet, e.g. {incomplete[0]}")
            with self.lock:
                capture_id = self.new_id(upload.name, self.captures_dir)
                d = self.capture_dir(capture_id)
                d.mkdir(parents=True)
            files = self.upload_dir(upload_id) / "files"
            os.replace(files, d / "source")  # same filesystem: a rename, no second copy
            try:
                capture = self.finalize_capture(capture_id, upload.name, origin="upload", linked=False)
            except BaseException:
                # Whatever went wrong, put the bytes back so the upload can be finished (or discarded) later.
                os.replace(d / "source", files)
                shutil.rmtree(d, ignore_errors=True)
                raise
            self._forget_upload(upload_id)
            return capture

    def delete_upload(self, upload_id: str) -> None:
        with self._upload_lock(upload_id):
            self._forget_upload(upload_id)

    def _forget_upload(self, upload_id: str) -> None:
        shutil.rmtree(self.upload_dir(upload_id), ignore_errors=True)
        with self._uploads_lock:
            self._upload_locks.pop(upload_id, None)


class OffsetMismatch(Exception):
    def __init__(self, received: int):
        super().__init__(f"server has {received} bytes of this file")
        self.received = received


