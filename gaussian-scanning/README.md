# gaussian-scanning

Capture → camera poses (COLMAP) → Gaussian splat (gsplat) → web viewer, plus
**Splat Lab**, the local app that runs and tracks it. Design notes are in
[`BRIEF.md`](BRIEF.md) (pipeline) and [`app/BRIEF.md`](app/BRIEF.md) (app).

## Requirements

- Nix with flakes enabled
- An NVIDIA GPU + driver (tested: RTX 4070 Ti Super, driver 595). The CUDA
  toolkit itself comes from the flake.

## Run it

```sh
cd gaussian-scanning
nix develop            # first time: fetches COLMAP/Node/CUDA compiler, installs Python deps (~5 GB)
splat-app              # builds the frontend if needed, serves http://127.0.0.1:8000
```

`bin/splat-app` also works from outside the dev shell; it enters it itself.
Other commands: `splat-app dev` (auto-reload API on :8000 + Vite on :5173),
`splat-app build`, `splat-app gen-api` (regenerate frontend API types after
changing backend models).

The first training run compiles gsplat's CUDA kernels (~2 min, once; cached
in `~/.cache/torch_extensions`).

Then: **Captures** → upload a video/photos or import a path on this machine →
**Run** → pick *Draft* (7k iterations, a few minutes) or *Standard* (30k) →
**Open viewer** when it finishes.

Using a GPU machine remotely: run `splat-app` there and tunnel,
`ssh -L 8000:127.0.0.1:8000 gpu-box`, then open http://127.0.0.1:8000
locally. There is no login, so don't bind it to a public interface.

## Test data

```sh
python scripts/fetch_test_data.py          # Mip-NeRF 360 "room", 311 photos (~78 MB of a 12.5 GB archive)
```

Import `data/test/mipnerf360_room/images` on the Captures page. A Draft run
with "Hold out every Nth frame" = 8 should give roughly 30–31 dB PSNR.

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
