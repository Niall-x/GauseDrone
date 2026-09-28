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

`--host` / `--port` work with `serve` and `dev`. `SPLAT_DATA_DIR` moves the
data directory (default `data/`).

gsplat compiles its CUDA kernels on first use (~2 min, once per machine;
cached in `~/.cache/torch_extensions`).

## Test data

```sh
python scripts/fetch_test_data.py          # Mip-NeRF 360 "room", 311 photos (~78 MB of a 12.5 GB archive)
```

Import `data/test/mipnerf360_room/images` on the Captures page. A Draft run
with "Hold out every Nth frame" = 8 should give roughly 30–31 dB PSNR.

## Tests

```sh
python -m pytest tests     # ~5 s; no GPU or COLMAP needed (the runner tests use a fake stage)
```

## Pipeline without the app

Each stage is a CLI working on one run directory:

```sh
R=data/dev/myscan
python -m pipeline.extract_frames --run-dir $R --input path/to/video.mp4 --fps 2
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
