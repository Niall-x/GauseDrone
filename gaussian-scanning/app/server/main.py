"""FastAPI app: captures, runs, stage definitions, run files, and the built frontend.

    uvicorn app.server.main:app            (see bin/splat-app)

The data directory defaults to <project>/data and can be moved with
SPLAT_DATA_DIR. There is no authentication: bind to localhost (the default)
and use an SSH tunnel to reach a remote machine.
"""
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from app.server import stages
from app.server.models import (
    Capture,
    CreateRunRequest,
    CreateUploadRequest,
    ImportCaptureRequest,
    RerunRequest,
    Run,
    StageState,
    UpdateRequest,
    Upload,
    UploadItem,
)
from app.server.runner import PROJECT_ROOT, Runner
from app.server.store import OffsetMismatch, Store, check_source

DATA_DIR = Path(os.environ.get("SPLAT_DATA_DIR", PROJECT_ROOT / "data"))
# Folders "import by path" may read from (os.pathsep-separated). Anyone who can
# reach the app can import from these, so narrow it when sharing the app.
IMPORT_ROOTS = [Path(p).expanduser().resolve() for p in os.environ.get("SPLAT_IMPORT_ROOTS", "~").split(os.pathsep) if p]
FRONTEND_DIST = PROJECT_ROOT / "app" / "frontend" / "dist"

store: Store
runner: Runner
ENV: dict = {}


def environment_info() -> dict:
    """Tool versions recorded into every run, so results can be traced to the software that made them."""
    def cmd(*args: str) -> str:
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=10, cwd=PROJECT_ROOT).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""

    from importlib.metadata import PackageNotFoundError, version

    def pkg(name: str) -> str:
        try:
            return version(name)
        except PackageNotFoundError:
            return ""

    first_line = lambda s: s.splitlines()[0] if s else ""  # noqa: E731
    commit = cmd("git", "rev-parse", "--short", "HEAD")
    dirty = bool(cmd("git", "status", "--porcelain", "--", "pipeline", "app/server"))
    return {
        "git_commit": commit + ("-dirty" if dirty else ""),
        "colmap": first_line(cmd("colmap", "version")),
        "torch": pkg("torch"),
        "gsplat": pkg("gsplat"),
        "gpu": first_line(cmd("nvidia-smi", "--query-gpu=name", "--format=csv,noheader")),
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    global store, runner, ENV
    store = Store(DATA_DIR)
    runner = Runner(store)
    ENV = environment_info()
    yield
    runner.shutdown()


app = FastAPI(title="GauseDrone Splat App", version="0.1.0", lifespan=lifespan)


def revalidated_file(request: Request, path: Path) -> Response:
    """A file served with `Cache-Control: no-cache` that answers a matching If-None-Match
    with 304, so the browser keeps its copy until the file changes (FileResponse alone
    always resends the whole body, e.g. a 35 MB splat on every viewer visit)."""
    response = FileResponse(path, headers={"Cache-Control": "no-cache"}, stat_result=path.stat())
    etag = response.headers["etag"]
    if etag in [t.strip().removeprefix("W/") for t in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    return response


def get_run_or_404(run_id: str) -> Run:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"no run {run_id}")
    return run


def get_capture_or_404(capture_id: str) -> Capture:
    capture = store.get_capture(capture_id)
    if capture is None:
        raise HTTPException(404, f"no capture {capture_id}")
    return capture


# --- system ---

@app.get("/api/system")
def system() -> dict:
    usage = shutil.disk_usage(DATA_DIR)
    gpu_mem = ""
    try:
        gpu_mem = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        pass
    used, total = (int(x) for x in gpu_mem.split(", ")) if gpu_mem else (None, None)
    return {
        **ENV,
        "data_dir": str(DATA_DIR),
        "disk_free_gb": round(usage.free / 1e9, 1),
        "gpu_mem_used_mb": used,
        "gpu_mem_total_mb": total,
        "active_run": runner.current,
        "queued_runs": list(runner.queue),
    }


@app.get("/api/stages")
def get_stages() -> dict:
    return stages.describe()


# --- captures ---

@app.get("/api/captures")
def list_captures() -> list[Capture]:
    return store.list_captures()


@app.get("/api/captures/{capture_id}")
def get_capture(capture_id: str) -> Capture:
    return get_capture_or_404(capture_id)


# --- uploads: create, send each file in chunks (resumable), finish into a capture ---

MAX_CHUNK_BYTES = 64 << 20


def get_upload_or_404(upload_id: str) -> Upload:
    upload = store.get_upload(upload_id)
    if upload is None:
        raise HTTPException(404, f"no upload {upload_id}")
    return upload


@app.get("/api/uploads")
def list_uploads() -> list[Upload]:
    """Unfinished uploads; the browser resumes one when the same files are picked again."""
    return store.list_uploads()


@app.post("/api/uploads")
def create_upload(req: CreateUploadRequest) -> Upload:
    total = sum(f.size for f in req.files)
    free = shutil.disk_usage(DATA_DIR).free
    if total > free - (1 << 30):
        raise HTTPException(507, f"not enough disk space: {total / 1e9:.1f} GB to upload, {free / 1e9:.1f} GB free")
    try:
        return store.create_upload(req.name, req.files)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/uploads/{upload_id}")
def get_upload(upload_id: str) -> Upload:
    return get_upload_or_404(upload_id)


@app.put("/api/uploads/{upload_id}/files/{index}")
async def upload_chunk(upload_id: str, index: int, offset: int, request: Request) -> UploadItem:
    """Raw bytes of one file starting at `offset`. 409 (with the server's byte
    count) if that isn't where the file currently ends, so a client can resync."""
    data = bytearray()
    async for part in request.stream():
        data += part
        if len(data) > MAX_CHUNK_BYTES:
            raise HTTPException(413, f"chunks are limited to {MAX_CHUNK_BYTES >> 20} MB")
    try:
        return await run_in_threadpool(store.write_chunk, upload_id, index, offset, data)
    except KeyError:
        raise HTTPException(404, f"no upload {upload_id} file {index}")
    except OffsetMismatch as e:
        raise HTTPException(409, {"message": str(e), "received": e.received})
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/uploads/{upload_id}/finish")
def finish_upload(upload_id: str) -> Capture:
    get_upload_or_404(upload_id)
    try:
        return store.finish_upload(upload_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/uploads/{upload_id}")
def delete_upload(upload_id: str) -> dict:
    get_upload_or_404(upload_id)
    store.delete_upload(upload_id)
    return {"deleted": upload_id}


@app.post("/api/captures/import")
def import_capture(req: ImportCaptureRequest) -> Capture:
    source = Path(req.path).expanduser().resolve()  # resolved first, so symlinks can't lead outside the roots
    root = next((r for r in IMPORT_ROOTS if source == r or r in source.parents), None)
    if root is None:
        roots = ", ".join(map(str, IMPORT_ROOTS))
        raise HTTPException(403, f"{req.path} is outside the folders captures can be imported from ({roots}); see SPLAT_IMPORT_ROOTS")
    if any(part.startswith(".") for part in source.relative_to(root).parts):
        raise HTTPException(403, "hidden folders can't be imported")
    if not source.exists():
        raise HTTPException(400, f"{source} does not exist on the server")
    try:
        check_source(source)
    except ValueError as e:
        raise HTTPException(400, str(e))
    name = req.name or Path(req.path).expanduser().stem
    capture_id = store.new_id(name, store.captures_dir)
    d = store.capture_dir(capture_id)
    d.mkdir(parents=True)
    src = d / "source"
    try:
        if req.link:
            if source.is_dir():
                src.symlink_to(source.resolve(), target_is_directory=True)
            else:
                src.mkdir()
                (src / source.name).symlink_to(source.resolve())
        elif source.is_dir():
            shutil.copytree(source, src)
        else:
            src.mkdir()
            shutil.copy2(source, src / source.name)
        return store.finalize_capture(capture_id, name, origin=str(source.resolve()), linked=req.link)
    except (ValueError, OSError) as e:
        store.delete_capture(capture_id)
        raise HTTPException(400, str(e))


@app.patch("/api/captures/{capture_id}")
def update_capture(capture_id: str, req: UpdateRequest) -> Capture:
    capture = get_capture_or_404(capture_id)
    if req.name is not None:
        capture.name = req.name
    if req.notes is not None:
        capture.notes = req.notes
    store.save_capture(capture)
    return capture


@app.delete("/api/captures/{capture_id}")
def delete_capture(capture_id: str) -> dict:
    get_capture_or_404(capture_id)
    runs = store.runs_for_capture(capture_id)
    if runs:
        raise HTTPException(409, f"capture is used by {len(runs)} run(s); delete those first")
    store.delete_capture(capture_id)
    return {"deleted": capture_id}


@app.get("/api/captures/{capture_id}/thumb")
def capture_thumb(capture_id: str):
    path = store.capture_dir(capture_id) / "thumb.jpg"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


# --- runs ---

@app.get("/api/runs")
def list_runs() -> list[Run]:
    return store.list_runs()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> Run:
    return get_run_or_404(run_id)


@app.post("/api/runs")
def create_run(req: CreateRunRequest) -> Run:
    capture = get_capture_or_404(req.capture_id)
    overrides: dict = {}
    if req.preset:
        if req.preset not in stages.PRESETS:
            raise HTTPException(400, f"unknown preset {req.preset}")
        for stage_name, values in stages.PRESETS[req.preset]["config"].items():
            overrides.setdefault(stage_name, {}).update(values)
    for stage_name, values in (req.config or {}).items():
        overrides.setdefault(stage_name, {}).update(values)
    try:
        config = stages.resolve_config(overrides)
    except ValueError as e:
        raise HTTPException(400, str(e))

    name = req.name or capture.name
    run = Run(
        id=store.new_id(name, store.runs_dir),
        name=name,
        capture_id=capture.id,
        config=config,
        stages=[StageState(name=s.name) for s in stages.STAGES],
        env=environment_info(),
        base_run_id=req.base_run_id,
    )

    if req.base_run_id:
        base = get_run_or_404(req.base_run_id)
        if base.capture_id != capture.id:
            raise HTTPException(400, "base run is for a different capture")
        names = [s.name for s in stages.STAGES]
        until = req.reuse_until or names[0]
        if until not in names:
            raise HTTPException(400, f"unknown stage {until}")
        reuse = names[: names.index(until) + 1]
        if any(base.stage(n).status != "done" for n in reuse):
            raise HTTPException(400, f"base run has not completed stages up to {until}")
        run_dir = store.run_dir(run.id)
        run_dir.mkdir(parents=True)
        for n in reuse:
            # Hard links: reuse costs no extra disk, and stages always write
            # fresh output directories, so the base run is never modified.
            for rel in stages.STAGE_BY_NAME[n].outputs:
                src = store.run_dir(base.id) / rel
                if src.is_dir():
                    shutil.copytree(src, run_dir / rel, copy_function=os.link)
                elif src.exists():
                    os.link(src, run_dir / rel)
            run.config[n] = base.config[n]
            state = base.stage(n).model_copy(deep=True)
            state.reused_from = base.stage(n).reused_from or base.id
            run.stages[names.index(n)] = state

    store.save_run(run)
    runner.enqueue(run.id)
    return store.get_run(run.id)


@app.patch("/api/runs/{run_id}")
def update_run(run_id: str, req: UpdateRequest) -> Run:
    get_run_or_404(run_id)

    def apply(r: Run):
        if req.name is not None:
            r.name = req.name
        if req.notes is not None:
            r.notes = req.notes
    return store.update_run(run_id, apply)


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> Run:
    run = get_run_or_404(run_id)
    if run.status == "paused":  # nothing is running: just close it
        return store.update_run(run_id, lambda r: setattr(r, "status", "cancelled"))
    if not runner.cancel(run_id):
        raise HTTPException(409, "run is not queued, running or paused")
    return get_run_or_404(run_id)


@app.post("/api/runs/{run_id}/rerun")
def rerun(run_id: str, req: RerunRequest) -> Run:
    """Re-run a finished/failed run in place from the given stage (e.g. retrain with new settings)."""
    run = get_run_or_404(run_id)
    if runner.is_active(run_id):
        raise HTTPException(409, "run is already queued or running")
    names = [s.name for s in stages.STAGES]
    if req.from_stage not in names:
        raise HTTPException(400, f"unknown stage {req.from_stage}")
    start = names.index(req.from_stage)
    if any(run.stages[i].status != "done" for i in range(start)):
        raise HTTPException(400, "earlier stages must be complete; rerun from the first incomplete stage")
    try:
        merged = {k: dict(v) for k, v in run.config.items()}
        for stage_name, values in (req.config or {}).items():
            if names.index(stage_name) < start:
                raise ValueError(f"cannot change {stage_name} settings without rerunning it")
            merged.setdefault(stage_name, {}).update(values)
        config = stages.resolve_config(merged)
    except ValueError as e:
        raise HTTPException(400, str(e))

    env = environment_info()

    def reset(r: Run):
        r.config = config
        r.status = "queued"
        r.env = env
        for i in range(start, len(r.stages)):
            r.stages[i] = StageState(name=r.stages[i].name)
    store.update_run(run_id, reset)
    runner.enqueue(run_id)
    return get_run_or_404(run_id)


@app.post("/api/runs/{run_id}/resume")
def resume(run_id: str) -> Run:
    run = get_run_or_404(run_id)
    first = next((s.name for s in run.stages if s.status != "done"), None)
    if first is None:
        raise HTTPException(400, "run is already complete")
    return rerun(run_id, RerunRequest(from_stage=first))


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str) -> dict:
    get_run_or_404(run_id)
    if runner.is_active(run_id):
        raise HTTPException(409, "cancel the run before deleting it")
    store.delete_run(run_id)
    return {"deleted": run_id}


@app.get("/api/runs/{run_id}/log/{stage_name}", response_class=PlainTextResponse)
def run_log(run_id: str, stage_name: str, tail: int = 200) -> str:
    get_run_or_404(run_id)
    path = store.run_dir(run_id) / "logs" / f"{stage_name}.log"
    if not path.exists():
        return ""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - 256 * 1024))  # never read more than the last 256 KB
        lines = fh.read().decode(errors="replace").splitlines()
    return "\n".join(lines[-tail:])


@app.get("/api/runs/{run_id}/frames")
def run_frames(run_id: str) -> list[str]:
    get_run_or_404(run_id)
    frames = store.run_dir(run_id) / "frames"
    return sorted(p.name for p in frames.glob("*.jpg")) if frames.exists() else []


@app.get("/api/runs/{run_id}/files/{path:path}")
def run_file(run_id: str, path: str, request: Request):
    get_run_or_404(run_id)
    root = store.run_dir(run_id).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404)
    # Re-running a stage in place rewrites files at the same URL (splat.spz, stats.json, frames),
    # so browsers must revalidate rather than guess a cache lifetime.
    return revalidated_file(request, target)


# --- frontend (production build) ---

class HashedAssets(StaticFiles):
    """Vite puts a content hash in every asset name, so a cached copy can never be stale."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


if FRONTEND_DIST.exists():
    app.mount("/assets", HashedAssets(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str, request: Request):
        if full_path.startswith("api/"):
            raise HTTPException(404, "no such API endpoint")
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and FRONTEND_DIST.resolve() in candidate.parents and candidate.is_file():
            return revalidated_file(request, candidate)
        # index.html names the current hashed bundles; a stale copy would load the old app after a rebuild.
        return revalidated_file(request, FRONTEND_DIST / "index.html")
