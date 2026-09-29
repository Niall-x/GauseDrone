# gaussian-scanning

Capture → camera poses (COLMAP) → Gaussian splat (gsplat) → web viewer, plus
**Splat Lab**, the local app that runs and tracks it. Design notes are in
[`BRIEF.md`](BRIEF.md) (pipeline) and [`app/BRIEF.md`](app/BRIEF.md) (app).

**To install and use the app, follow the guide in the
[top-level README](../README.md).** This page is the developer reference.

## Launcher

`bin/splat-app` (on `PATH` inside `nix develop`; also works from outside the
dev shell, it enters it itself):

| Command | What it does |
|---|---|
| `splat-app` | Build the frontend if sources changed, serve everything on http://127.0.0.1:8000 |
| `splat-app dev` | API with auto-reload on :8000 + Vite dev server on :5173 (open :5173) |
| `splat-app build` | Rebuild the frontend |
| `splat-app gen-api` | Regenerate `app/frontend/src/api/schema.d.ts` after changing backend models |
| `splat-app install-service` / `uninstall-service` | Write/remove a systemd user unit (`~/.config/systemd/user/splat-app.service`) that runs `splat-app serve` |
| `splat-app start` / `stop` / `restart` / `status` / `logs` | Shortcuts for `systemctl --user … splat-app` / `journalctl` |

`--host` / `--port` work with `serve`, `dev` and `install-service`. The unit
file records the absolute project path and where `nix` lives, so rerun
`install-service` after moving the checkout. On `systemctl stop`, systemd
SIGTERMs the whole service; the runner records a stage killed that way as
interrupted (resumable) rather than as a pipeline failure. `SPLAT_DATA_DIR` moves the
data directory (default `data/`). `SPLAT_IMPORT_ROOTS` (`:`-separated, default `~`)
limits which server folders *Import from a path* may read; hidden folders are always refused.

gsplat compiles its CUDA kernels on first use (~2 min, once per machine;
cached in `~/.cache/torch_extensions`). The flake builds COLMAP with CUDA
(GPU feature extraction + matching). cache.nixos.org has no CUDA builds, so the
first `nix develop` after a nixpkgs bump compiles it locally (a few minutes);
its kernels target sm_89 (RTX 40xx), so add your GPU's capability in
`flake.nix` for other cards, or run the SfM stage with *GPU features + matching* = 0.

Uploads from the browser are resumable (`/api/uploads`): the file list is
declared first, each file then arrives in chunks appended at an explicit
offset, and the bytes on disk under `data/uploads/<id>/` are the record of
progress, so a dropped connection or server restart costs at most one chunk.

## Test data

```sh
python scripts/fetch_test_data.py          # Mip-NeRF 360 "room", 311 photos (~78 MB of a 12.5 GB archive)
```

Import `data/test/mipnerf360_room/images` on the Captures page. A Draft run
(which holds out every 8th frame) should give roughly 30–31 dB held-out PSNR.

## Tests

```sh
python -m pytest tests     # ~5 s; no GPU or COLMAP needed (the runner tests use a fake stage)
```

## Pipeline without the app

Each stage is a CLI working on one run directory:

```sh
R=data/dev/myscan
python -m pipeline.extract_frames --run-dir $R --input path/to/video.mp4 --fps 4
python -m pipeline.sfm            --run-dir $R
python -m pipeline.train          --run-dir $R --iterations 7000 --holdout-every 8
python -m pipeline.export         --run-dir $R
```

`--help` on each lists its options.

## Layout

```
flake.nix, pyproject.toml, uv.lock   pinned environment
pipeline/                            stage CLIs (frames, sfm, train, export) + COLMAP reader
app/server/                          FastAPI backend: stage registry, run store, job runner
app/frontend/                        React UI + Spark-based splat viewer
bin/splat-app                        launcher
scripts/                             test data fetcher, OpenAPI dump
data/                                captures and runs (git-ignored); SPLAT_DATA_DIR moves it
```

Each run lives in `data/runs/<id>/` with a `run.json` recording its inputs,
settings, tool versions, git commit and results. Copying that folder to
another machine's `data/runs/` makes it show up there.
