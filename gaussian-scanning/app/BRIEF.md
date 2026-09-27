# Splat Lab (pipeline app): Sub-Brief (v0.2, built)

Status: **v1 built and tested end to end** (see section 6). Sits under [`../BRIEF.md`](../BRIEF.md) (the splat pipeline stream), which sits under [`../../BRIEF.md`](../../BRIEF.md) (the main project). v0.1 was a scoping draft; this version records what was built and why the draft's decisions changed.

## 1. What this is

A local web app that turns a capture (a handheld/drone video or a set of photos) into a Gaussian splat and lets you view it, without running each stage by hand. Every run is a self-contained, reproducible record: what went in, the exact settings, the tool versions, what came out, and quality numbers. The embedded viewer is the app's own (built on Spark/three.js), so drone-specific overlays can be added to it.

Scope of v1 is deliberately small: **import, generate, view**. Drone rosbag import, metric scale, and comparison/evaluation across runs are designed for but not built (section 5).

## 2. Architecture decisions

| # | Decision | Changed from v0.1? |
|---|---|---|
| 1 | Each pipeline stage is a standalone CLI in `pipeline/`; the app runs them as subprocesses and never reimplements their logic | Same |
| 2 | The pipeline is an ordered list of stages declared once (`app/server/stages.py`: module, parameters, defaults, owned outputs). The runner, API and the UI's advanced settings all read that list | Same, made concrete |
| 3 | ~~One normalized sensor-reading format with adapters~~ → **one importer per capture kind** (video, photo folder; later rosbag2) that all produce the same stage inputs: frames, per-frame timestamps, and optionally poses | **Changed.** A rangefinder height (1 number) and a VIO trajectory (6-DoF poses) don't share a useful common format, and the drone's real output will be a rosbag |
| 4 | One background worker runs one run at a time (the GPU is the bottleneck); progress is polled. No task queue system | Same |
| 5 | ~~SQLite + filesystem~~ → **the run folder is the source of truth** (`run.json` + outputs). No database: listing scans folders | **Changed.** Copying a folder shares a run between machines (covers decision 10); nothing can drift out of sync. Add an SQLite index only if listing ever gets slow |
| 6 | ~~Embed SuperSplat~~ → **own viewer on Spark (three.js)**; PLY download for SuperSplat when editing is needed | **Changed.** SuperSplat is a full editor app, not an embeddable component; trajectory/coverage overlays need a renderer we control |
| 7 | Backend FastAPI; frontend React + Vite + Tailwind. TypeScript API types are generated from the backend's OpenAPI schema | Same (shadcn/ui dropped: a small in-house component set was enough) |
| 8 | Hand-built screens from a shared component library. The one generic piece is the per-stage "advanced settings" form, rendered from decision 2's stage list so a new parameter needs no UI change | Refined |
| 9 | Each person runs their own backend. It binds to localhost (no login); reach a remote GPU box via an SSH tunnel. Captures can be imported by server-side path (optionally symlinked) as well as uploaded | Refined: path import added because multi-GB uploads through a browser are impractical |
| 10 | No synced database between users; share runs by copying folders | Same |
| 11 | ~~Hand-managed native installs~~ → **Nix flake** pins COLMAP, Node, Python, the CUDA compiler; `uv.lock` pins the Python packages (torch, gsplat). Each run records git commit + tool versions | **Changed.** See `../README.md` |
| 12 | Training uses **gsplat directly** (a compact trainer in `pipeline/train.py`), not nerfstudio | **New.** nerfstudio pins old torch and is the hardest part to install; gsplat is what it uses underneath anyway |
| 13 | Stages reuse work: "New run from this" hard-links an earlier run's frames/poses into a new run (zero extra disk), and a run can be re-run in place from any stage with new settings | **New.** COLMAP is the slow part; most experiments only change training |

## 3. Pipeline stages (v1)

| Stage | CLI | Output in run folder |
|---|---|---|
| Frames | `pipeline.extract_frames` | `frames/*.jpg`, `frames.csv` (file, source, **real video timestamp**, sharpness) |
| Camera poses | `pipeline.sfm` | `sfm/` (COLMAP 4 database, sparse model, undistorted images, text model) |
| Train splat | `pipeline.train` | `train/splats.pt`, `train/stats.json` (loss curve, PSNR/SSIM) |
| Export | `pipeline.export` | `export/splat.ply` (full), `export/splat.spz` (~10x smaller, viewer), `export/view.json` (camera path, up vector) |

Stage protocol: `python -m pipeline.<stage> --run-dir DIR [--param value...]`, printing `@@progress <0-1> <msg>` and `@@result <json>` lines. Anything else is log.

## 4. What exists

- **Backend** (`app/server/`): stage registry, run/capture store, job runner, API, serves the built frontend. Runs can be cancelled, resumed, re-run from any stage, or started from another run's frames/poses. Stopping the server stops the running stage and marks it interrupted (resumable); queued runs survive restarts; after a hard crash, a leftover stage process is killed only if its command line still names that run.
- **Frontend** (`app/frontend/`): runs list, new run (capture, preset, advanced settings, reuse), run detail (live stage progress, logs, metrics, loss curve, frames, downloads, config + environment), captures (upload by drag-drop/folder, import by path), full-screen viewer.
- **Viewer**: orbit and fly controls; step through the capture cameras with the source photo alongside (a quick visual check of where the splat is weak); an overview from above with the capture path, camera frustums and a ceiling cutaway (a first, visual version of "coverage"); double-click to focus; screenshot; PLY download. "Up" is estimated from the capture cameras' horizontal axes, which stays correct for a drone camera pitched down.
- **Tests** (`tests/`): API + runner behaviour with a fake stage (cancel, resume, rerun, reuse, shutdown/restart recovery, upload/import validation, file access confined to the run folder) and pipeline units (SPZ/PLY writers, COLMAP reader, up estimation). No GPU needed.
- **Handled capture quirks**: variable-frame-rate phone video (real timestamps), photo sets mixing portrait and landscape (SfM falls back to per-image cameras), long captures (pinned-memory budget in the trainer).

## 5. Designed for, not built yet (in rough priority order)

1. **Drone rosbag import.** A new capture kind whose importer writes the same frames/timestamps plus the VIO poses. COLMAP 4's `pose_prior_mapper` can use those poses as priors directly (Tier 2 in `../BRIEF.md`), as an alternative SfM stage.
2. **Metric scale.** A stage after SfM (floor-plane fit + rangefinder height, or a known-size marker) that stores a scale/transform in the run and applies it to exports. Training doesn't need it; measurements and coverage do.
3. **Scenes and comparable evaluation (M8).** Today each run is scored on held-out frames from *its own* capture, which can't compare autonomous vs manual vs lawnmower scans fairly: each would be graded on a different test set. Needed: a *Scene* (one room) with one independent test capture and a reference frame; runs align to the scene and are all rendered from the same test views. Then a comparison screen and a coverage metric (both still to be defined).
4. Viewer overlays for the above (coverage heatmap, VIO-vs-SfM trajectory difference).

## 6. Test results

All run through the app (import → run → viewer), RTX 4070 Ti Super, every 8th frame held out for scoring. Test data: Mip-NeRF 360 "room" (311 photos at 779x519, via `scripts/fetch_test_data.py`).

| Run | Frames posed | SfM (CPU) | Train | Gaussians | Held-out PSNR / SSIM | SPZ / PLY |
|---|---|---|---|---|---|---|
| Room photos, Draft (7k) | 311/311, 0.55 px | 4.5 min | 2.8 min | 580k | **30.7 dB / 0.926** | 10 / 138 MB |
| Room photos, Standard (30k; frames + poses reused from the Draft run) | (reused) | 0 | 18 min | 1.95M | **32.1 dB / 0.945** | 34 / 409 MB |
| Room as a 31 s video, 4 fps, Draft | 125/125, 0.52 px | 1.2 min | 2.7 min | 517k | **28.8 dB / 0.893** | 9 / 122 MB |

For reference, published 3DGS results on this scene are ~31–32 dB. The viewer renders the 1.65M-splat export at 60 fps (display-capped). Also exercised on real runs: resume after cancel; server stopped mid-training → stage marked interrupted, no orphaned process → resumed to completion; export re-run in place.

Known limits: COLMAP runs on the CPU (the Nix binary cache has no CUDA build), ~4–5 min per 300 frames; training runs at ~30–50 it/s at this resolution, so a Standard run at full 1600 px will take longer.
