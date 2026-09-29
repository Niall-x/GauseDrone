# Splat Lab (pipeline app): Sub-Brief (v0.5, built)

Status: **v1 built and tested end to end** (see section 6). Sits under [`../BRIEF.md`](../BRIEF.md) (the splat pipeline stream), which sits under [`../../README.md`](../../README.md) (the main project). v0.1 was a scoping draft; v0.2 recorded what was built and why the draft's decisions changed; v0.3 (2026-09-28) adds a speed, robustness and usability pass: GPU feature matching, ~2.5x faster training, resumable uploads, import-path limits, one viewer control scheme, and a bug sweep (section 6). v0.4 (2026-09-29) follows the first real handheld phone scans: new defaults (4 fps, incremental mapper, exhaustive matching up to 800 frames, Draft holds out every 8th frame), capture and pose warnings, and adjustable viewer mouse sensitivity (decision 16, section 6). v0.5 (2026-09-29) adds the handling of non-ideal captures: a verdict per run, frames with wrong camera positions left out of training, one automatic retry, a pause before training when the result can't be trusted, and a capture report (decision 17; design in `../BRIEF.md` section 3b).

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
| 9 | Each person runs their own backend, or uses the other's: it binds to localhost (no login) and is shared over **Tailscale Serve** (HTTPS to tailnet members, including a friend's shared machine) or an SSH tunnel. Never Funnel. Sharing a machine exposes all its ports, so restrict the sharee to 443 in the tailnet policy. Captures can be imported by server-side path (optionally symlinked) as well as uploaded. Because anyone who reaches the app can import, path import is confined to `SPLAT_IMPORT_ROOTS` (default: the home folder; hidden folders and symlinks leading out are refused) | Refined: path import added because multi-GB uploads through a browser are impractical; confined to allowed roots in v0.3 |
| 10 | No synced database between users; share runs by copying folders | Same |
| 11 | ~~Hand-managed native installs~~ → **Nix flake** pins COLMAP (built with CUDA for GPU feature extraction/matching), Node, Python, the CUDA compiler; `uv.lock` pins the Python packages (torch, gsplat). Each run records git commit + tool versions | **Changed.** See `../README.md`. The CUDA COLMAP isn't in the Nix binary cache, so it compiles locally (a few minutes) once per nixpkgs bump, for sm_89 (RTX 40xx) only |
| 12 | Training uses **gsplat directly** (a compact trainer in `pipeline/train.py`), not nerfstudio | **New.** nerfstudio pins old torch and is the hardest part to install; gsplat is what it uses underneath anyway |
| 13 | Stages reuse work: "New run from this" hard-links an earlier run's frames/poses into a new run (zero extra disk), and a run can be re-run in place from any stage with new settings | **New.** COLMAP is the slow part; most experiments only change training |
| 14 | Turned on/off as a **systemd user service** (`splat-app install-service`, then `systemctl --user start/stop splat-app`), not a Docker image | **New.** The service just runs the launcher, which enters the pinned Nix shell, so there is no second environment to maintain. Docker would need the NVIDIA container toolkit (a system-level change) and a ~10 GB image duplicating the flake. Revisit Docker only if someone needs to run it without Nix (e.g. Windows) |
| 15 | Browser uploads are **resumable**: the file list is declared first, then each file arrives in chunks appended at an explicit offset; the bytes on disk (`data/uploads/<id>/`) are the only record of progress. A dropped connection or server restart costs at most one chunk; picking the same files again resumes | **New (v0.3).** Replaces the single multipart request, which lost everything on any failure. No resumable-upload library (tus etc.): ~150 lines on both sides, and the offset check makes retries safe |
| 16 | Defaults are chosen on **real handheld captures**, not only benchmark photo sets: 4 fps, the **incremental mapper** up to 800 frames (global beyond), exhaustive matching up to 800 frames. Stages report problems as a `warnings` list in their result (blurry/blank stretches from Frames; jumps, stacked frames, flips, unplaced stretches and split models from Camera poses), shown on the run and in the runs list | **New (v0.4).** The global mapper and 2 fps worked on Mip-NeRF 360 but garbled both of our first phone videos while reporting every frame posed at sub-pixel error, so a finished run looked healthy. Warnings make a bad reconstruction visible without opening the viewer. Findings: `../BRIEF.md` section 3a |
| 17 | Capture problems are **structured issues with a verdict**, not log lines. Stages return `issues` (kind, severity, time ranges, frames, evidence, fix) and the camera-pose stage a `verdict` (good / gaps / unreliable) plus frames to leave out (`sfm/quality.json`). A stage result with `verdict: unreliable` makes the runner **pause** the run (status `paused`, shown as *Needs attention*); resuming carries on without re-checking, which is *Train anyway* | **New (v0.5).** Warnings alone left bad data in training and a bad run looking done. Pausing is generic (any stage can return a verdict), so later checks, e.g. on the drone's VIO poses, reuse it. The structured record is also what a re-capture planner will need |

## 3. Pipeline stages (v1)

| Stage | CLI | Output in run folder |
|---|---|---|
| Frames | `pipeline.extract_frames` | `frames/*.jpg`, `frames.csv` (file, source, **real video timestamp**, sharpness) |
| Camera poses | `pipeline.sfm` | `sfm/` (COLMAP 4 database, sparse model, undistorted images, text model) |
| Train splat | `pipeline.train` | `train/splats.pt`, `train/stats.json` (loss curve, PSNR/SSIM) |
| Export | `pipeline.export` | `export/splat.ply` (full), `export/splat.spz` (~10x smaller, viewer), `export/view.json` (camera path, up vector) |

Stage protocol: `python -m pipeline.<stage> --run-dir DIR [--param value...]`, printing `@@progress <0-1> <msg>` and `@@result <json>` lines. Anything else is log.

## 4. What exists

- **Service**: `bin/splat-app install-service` writes a systemd user unit; `systemctl --user start|stop splat-app` turns the app on and off, logs go to the journal; `enable` + `loginctl enable-linger` starts it at boot. Stopping mid-run marks the run interrupted and resumable (tested: stop during camera poses → restart → resume).
- **Backend** (`app/server/`): stage registry, run/capture store, job runner, API, serves the built frontend. Runs can be cancelled, resumed, re-run from any stage, or started from another run's frames/poses. Stopping the server stops the running stage and marks it interrupted (resumable); queued runs survive restarts; after a hard crash, a leftover stage process is killed only if its command line still names that run; a malformed progress line from a stage is logged, never fatal. Resumable uploads (decision 15) and confined path import (decision 9). Run files are served with `Cache-Control: no-cache` + ETag, so a re-run's new splat is never shown stale and an unchanged one isn't re-downloaded (304); hashed frontend bundles are cached permanently.
- **Frontend** (`app/frontend/`): runs list, new run (capture, preset, advanced settings, reuse), run detail (live stage progress, logs, metrics, loss curve, frames, downloads, config + environment), captures (resumable upload by drag-drop/folder, import by path), full-screen viewer. Polling pauses in hidden tabs and slows to 10 s when nothing is running. The sidebar says what each section is for (Runs: generate and view splats; Captures: source videos and photos).
- **Viewer**: one game-style control scheme (WASD/arrows move while mouse-drag looks; right-drag orbits, middle-drag pans, scroll dollies); step through the capture cameras with the source photo alongside (a quick visual check of where the splat is weak); an overview from above with the capture path, camera frustums and a ceiling cutaway (a first, visual version of "coverage"); double-click to focus; adjustable mouse sensitivity (look/orbit and scroll, stored per browser); screenshot; PLY download. "Up" is estimated from the capture cameras' horizontal axes, which stays correct for a drone camera pitched down.
- **Capture quality** (`pipeline/quality.py`): the frames stage reports long blurry or blank stretches (info); the camera-pose stage checks for unplaced stretches, split scenes, and neighbouring-frame jumps, stacked frames and flips (video only), gives a verdict, leaves wrongly placed frames out of training, and retries once (incremental mapper + frames at 3x the rate around the failures, reusing the first attempt's matches) keeping the better attempt. The run page has a **capture report**: the verdict, a timeline of the video with the problem stretches, each issue with thumbnails, what to do and the retry's outcome. Unreliable runs pause before training with *Train anyway* / *Re-run camera poses* / *Stop here*. The runs list shows the verdict; the viewer draws left-out cameras in red, and its photo comparison uses the undistorted frames (same lens model as the render).
- **Tests** (`tests/`, 41, ~6 s): API + runner behaviour with a fake stage (cancel, resume, rerun, reuse, shutdown/restart recovery, malformed stage output, upload resume across restarts and failed finishes, import confinement, file access confined to the run folder, cache revalidation) and pipeline units (SPZ/PLY writers, COLMAP reader, up estimation, EXIF orientation, reuse never rewriting a shared `frames.csv`, tiny point clouds, pose checks and verdicts, blur issues, sampling a video window) and the pause on an unreliable verdict. No GPU needed.
- **Handled capture quirks**: variable-frame-rate phone video (real timestamps), photo sets mixing portrait and landscape (SfM falls back to per-image cameras), phone photos with an EXIF rotation tag (COLMAP ignores the tag, so frames are always stored upright), long captures (pinned-memory budget in the trainer; memory-bounded neighbour search for large sparse clouds).

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

**Update 2026-09-28** (same data and settings, CUDA COLMAP + a training fix): the SSIM loss was being fed a non-contiguous (permuted) tensor, which made its convolutions ~10x slower and cost ~70% of every training step; COLMAP now extracts and matches features on the GPU (bundle adjustment stays on the CPU: nixpkgs' Ceres has no CUDA).

| Run | SfM | Train (7k) | Held-out PSNR / SSIM |
|---|---|---|---|
| Room photos, Draft | 272 s → **109 s** | 166 s → **66 s** | 30.66 → 30.63 dB / 0.926 → 0.924 (run-to-run noise) |
| Room video, Draft | 72 s → **39 s** | 162 s → **64 s** | 28.84 → 29.18 dB / 0.893 → 0.897 |

Export of the 1.65M-Gaussian Standard result now peaks at 2.4 GB of RAM instead of 3.9 GB (float32 in place instead of float64 temporaries), with byte-identical PLY/SPZ output.

Bugs found and fixed in the same pass (v0.3): re-running frames in a run that shared `frames.csv` with another (via "New run from this") rewrote the other run's copy through the hard link; EXIF-rotated photos reached COLMAP sideways; a malformed `@@progress` line abandoned the stage process; "New run from this" defaulted to reusing camera poses even when they hadn't finished; stale splats/charts after an in-place re-run; a failed upload finish could lose the uploaded bytes; `holdout-every 1` and point clouds of ≤4 points crashed training.

Known limits: bundle adjustment (most of the remaining SfM time) runs on the CPU (nixpkgs' Ceres has no CUDA); a Standard run at full 1600 px trains more slowly than these 779 px test images.

**Update 2026-09-29: first handheld phone scans** (4K portrait phone video of one room, Draft 7k, every 8th frame held out). Each row is a fresh run, so the held-out frames differ between rows: compare loosely. Runs made with the pipeline CLIs; rows with the same video and frame rate share the extracted frames and COLMAP matches, so only the mapper differs.

| Capture | Frames | Mapper | Frames posed | Held-out PSNR / SSIM |
|---|---|---|---|---|
| 39 s, turning on the spot | 2 fps (77) | global | 77/77, 0.77 px, but stacked and jumping | 18.9 dB / 0.784 |
| | 2 fps (77) | incremental | 77/77, 0.59 px | **24.2 dB / 0.892** |
| 77 s, walking + close-ups + window | 2 fps (155) | global | 147/155, flips of 168° and 178° | 19.6 dB / 0.801 |
| | 2 fps (155) | incremental | split: 108 + 34 | 19.2 dB / 0.816 (largest piece) |
| | 4 fps (310) | global | 304/310, 13 jumps | 20.7 dB / 0.840 |
| | 4 fps (310) | incremental | 281/310 (60–68 s blurry pan unplaced) | **22.9 dB / 0.875** |

Timings at 310 frames: exhaustive GPU matching 53 s, incremental mapping ~3.5 min, whole camera-pose stage ~5 min, about the same as global mapping (matching and extraction dominate either way). Incremental mapping above ~300 frames is untimed; if an 800-frame capture turns out too slow, lower `--incremental-limit` rather than going back to global. The pose-warning thresholds were calibrated on these six reconstructions: every bad one is flagged, the good ones get no jump/stack/flip warning.

Also in v0.4: the incremental mapper's progress bar was stuck (COLMAP 4.1 logs `Registering image #N (num_reg_frames=K)`); fixed. Viewer: mouse look/orbit and scroll sensitivity (0.25–4x, per browser); the right-hand panels now stack instead of overlapping.

**Update 2026-09-29: handling non-ideal captures, tested on the worst-case handheld video** (the 77 s walk: fast swings to close-ups, a blurry pan over the chair and floor, a window view; unlikely ever to give a good splat, which is what makes it a good test). Draft (7k), every 8th frame held out, through the app.

| Run | Camera poses | Verdict | Held-out PSNR / SSIM |
|---|---|---|---|
| Defaults (incremental, retry on) | First attempt 281/310 placed, 7 s unplaced at 60.7–67.5 s. Retry added 64 frames around it (12 fps): 371/374 placed. 9.7 min in total, 4.6 of it the retry | Good (the retry filled the gap; a 0.1 s sliver is left) | **23.4 dB / 0.877** |
| Global mapper, retry off (to force bad poses) | 304/310 placed, but 24 jumps, 4 stacked, 3 flips in 19 places; 49 frames flagged | Unreliable: **paused before training** as designed | after *Train anyway*, 49 frames left out: 21.6 dB / 0.854 |

For comparison, the same video scored 19.6 dB with the old defaults (2 fps, global) and 22.9 dB with 4 fps + incremental before the retry existed; held-out frames differ between runs, so compare loosely.

Bugs found and fixed in the same pass: a 30k training run on this video ran the 16 GB GPU out of memory (6.45M Gaussians; now capped from free memory, with a plain-language error if it still happens. Verified: the same run resumed completes, capped at step 5,701, 3.6M Gaussians, 5.7 GB peak, 23 min); the frames stage crashed reporting its result (a numpy integer in the issue JSON); a stray 2-frame COLMAP piece was reported as the scene "splitting"; a 3-frame, 0.1 s unplaced sliver after the retry downgraded the verdict; the pause banner claimed a retry had happened when it was switched off; status pills wrapped. Known slow spot, not fixed: extracting frames from 4K video takes about 2 min per minute of footage (2 min 38 s for this 77 s video), mostly converting every decoded frame to a full-size colour image to score its sharpness; decoding a pre-scaled greyscale copy with ffmpeg would be several times faster.

