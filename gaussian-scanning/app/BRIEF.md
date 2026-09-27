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

- **Backend** (`app/server/`): stage registry, run/capture store, job runner (cancel, resume after crash/restart, rerun from stage, reuse from another run), API, serves the built frontend.
- **Frontend** (`app/frontend/`): runs list, new run (capture, preset, advanced settings, reuse), run detail (live stage progress, logs, metrics, loss curve, frames, downloads, config + environment), captures (upload by drag-drop/folder, import by path), full-screen viewer.
- **Viewer**: orbit and fly controls, capture trajectory and camera frustums, step through the capture cameras with the source photo alongside (a quick visual check of where the splat is weak), double-click to focus, screenshot, PLY download.

## 5. Designed for, not built yet (in rough priority order)

1. **Drone rosbag import.** A new capture kind whose importer writes the same frames/timestamps plus the VIO poses. COLMAP 4's `pose_prior_mapper` can use those poses as priors directly (Tier 2 in `../BRIEF.md`), as an alternative SfM stage.
2. **Metric scale.** A stage after SfM (floor-plane fit + rangefinder height, or a known-size marker) that stores a scale/transform in the run and applies it to exports. Training doesn't need it; measurements and coverage do.
3. **Scenes and comparable evaluation (M8).** Today each run is scored on held-out frames from *its own* capture, which can't compare autonomous vs manual vs lawnmower scans fairly: each would be graded on a different test set. Needed: a *Scene* (one room) with one independent test capture and a reference frame; runs align to the scene and are all rendered from the same test views. Then a comparison screen and a coverage metric (both still to be defined).
4. Viewer overlays for the above (coverage heatmap, VIO-vs-SfM trajectory difference).

## 6. Test result

Mip-NeRF 360 "room" (311 photos at 779x519, fetched with `scripts/fetch_test_data.py`), Draft preset (7k iterations), every 8th frame held out, RTX 4070 Ti Super:

- COLMAP (CPU, exhaustive + global mapper): 311/311 frames posed, 0.52 px mean reprojection error, ~4.5 min
- Training: ~2.8 min, ~585k Gaussians, 1.1 GB peak GPU memory
- **Held-out PSNR 30.8 dB, SSIM 0.927** (published 3DGS on this scene is ~31-32 dB at 30k iterations)
- Export: 138 MB PLY, 9.9 MB SPZ

The video path was also checked with a video made from the same photos.
