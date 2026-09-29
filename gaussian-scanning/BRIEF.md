# Gaussian Splat Pipeline: Sub-Brief (v0.6)

Status: M1 ("splat pipeline, no drone") from the main project brief is **built**: a pipeline plus a local app (Splat Lab) that runs it and views the result. See [`README.md`](README.md) to access/install it and [`app/BRIEF.md`](app/BRIEF.md) for the app's design. No drone sensor data is used yet.

## 1. What this covers

Turning photos or a walked/orbited video into a viewable Gaussian splat — from a handheld camera now, the drone's camera later — before any other drone sensor data is brought in.

## 2. Pipeline

1. **Capture**: overlapping photos or video of the room. No stereo/depth sensor needed.
2. **Frames**: from video, the sharpest frame per 1/fps-second window is kept, with its real timestamp (for matching to drone logs later).
3. **Structure-from-Motion (SfM)**: COLMAP 4 works out camera poses plus a sparse point cloud from feature matching alone. GPU feature extraction/matching; exhaustive matching and the incremental mapper up to 800 frames (global/GLOMAP beyond); undistortion to a pinhole camera. Poses are then checked — bad frames are left out of training, and untrustworthy runs pause before training (3b).
4. **Training**: gsplat fits Gaussians (position, scale/orientation, opacity, colour) against the photos — standard 3DGS recipe (densification, L1+SSIM loss, spherical harmonics degree 3). 7k iterations for a draft, 30k for full quality.
5. **Export + viewer**: PLY (full precision) and SPZ (~10x smaller) plus the camera path, opened in the app's own viewer.

Tooling: **COLMAP 4 + gsplat**, not nerfstudio (it pins old PyTorch and was the hardest part to install; gsplat is what it uses underneath). Environment: Nix flake + `uv.lock`.

## 3. Capture requirements and findings

Needs: high overlap (roughly 60–80%), enough surface texture (blank walls/mirrors/glass break SfM), sharp images (motion blur is the main enemy), a static scene, coverage from varied heights/angles.

### 3a. Findings from the first handheld scans (2026-09-29)

Two phone videos of one room (a 39 s turn-on-the-spot, a 77 s walk with close-ups) both came out garbled at first; numbers are in [`app/BRIEF.md`](app/BRIEF.md) section 6.

- **The global mapper (GLOMAP) was the main cause of garbled splats.** It reported sub-pixel reprojection error on poses that were actually wrong (frames stacked on one spot, multi-unit jumps, 168° flips) — it places cameras from pairwise translation directions, which are noise at a short baseline (turning on the spot) or with features at infinity (a window). The incremental mapper on the same matches: +5.3 dB held-out PSNR. **Now the default up to 800 frames.**
- **2 fps was too sparse for handheld video**; 4 fps + incremental scored 22.9 dB vs 19.6 dB for the old defaults. **Now 4 fps.**
- Blurry or unplaceable stretches can only be left out and reported — a sharpness-threshold filter didn't reliably tell blur from a plain surface (it dropped many fine frames), so it's off; a warning points at the stretch to refilm instead.
- Turning on the spot is a weak capture even with correct poses (little parallax) — walk the room.
- Auto-exposure swings near a bright window cause floaters; not addressed yet (candidates: per-image appearance embeddings in training, or exposure lock on the phone).

Capture guidance (also in the how-to-access/install guide): walk slowly rather than turning on the spot; move gradually between room-scale and close-up views; avoid quick sweeps over blank walls/doors/floor; don't film out of windows; keep zoom fixed.

### 3b. Handling captures that aren't ideal (decided 2026-09-29)

Bad captures will keep happening, including from the drone. Principles: leave untrustworthy data out rather than let it corrupt the rest; detect, then fix or tell; say where (seconds + thumbnail, so the user or later the planner knows what to refly); only raise what's actionable; stop early rather than spend training time on poses already known to be wrong.

| Problem | Detected by | Automatic response | Shown to the user |
|---|---|---|---|
| Wrong camera positions (jumps, stacked frames, impossible turns) | Neighbouring-frame motion (video) | One retry (below); flagged frames left out of training | Warning with times; red cameras in the viewer |
| Unplaceable stretches | ≥1 s of video (3+ frames for photos) missing from the model | Retry with extra frames around them | Warning: "refilm these moments" |
| Scene split into pieces | More than one COLMAP model | Same retry; largest piece used | Warning, or error if under 70% of frames |
| Most frames unplaced | Under half placed | Same retry | Error |
| Blur or plain surfaces | Sharpness under 35% of the median for ≥1.5 s | None (rejection was tested and hurts) | Info, named as the likely cause when it overlaps a failure |

**Verdict**: *Good* (nothing found) / *Usable with gaps* (some stretches missing or left out, rest trustworthy) / *Unreliable* (wrong positions in 3+ places or >5% of frames, largest piece under 70%, or under half placed) — pauses before training as **Needs attention**, offering *Train anyway*, *Re-run camera poses*, *Stop here*. Thresholds were calibrated on six reconstructions of the two test videos.

**Retry**: runs once, only if the first attempt isn't Good — incremental mapper (if global was used) plus extra frames at 3x the capture rate within 2 s of each failed stretch, reusing the first attempt's features/matches. Keeps the better of the two attempts (verdict first, then share of frames placed).

Also built: training's Gaussian count is now capped from free GPU memory, so a noisy capture can't run it out of memory (a worst-case walk previously reached 6.45M Gaussians and crashed a 30k run on a 16 GB card).

**Not built yet**: exposure compensation in training; detecting moving objects from badly-reproduced frames; a "turned on the spot" detector; a "moving too fast" detector; warnings before a run starts (e.g. capture too short). Each needs testing against a set of known-fault clips plus one clean walk before it ships.

## 4. Decision: camera-only now, staged sensor fusion later

The pipeline trains on camera footage alone; sensor fusion is staged into tiers of increasing effort/risk. None is needed for *training* — nerf/splat training is scale-agnostic. Scale and alignment matter for measurements, the coverage metric, and comparing runs, so they're applied to the reconstruction/exports as a transform, not baked into training.

| Tier | What it is | Status |
|---|---|---|
| **1. Metric scale** | Solve SfM's unknown scale factor from a known real distance (a tape-measured edge, or a printed ArUco/ChArUco marker) or camera height above the floor (rangefinder + a floor plane fitted to the sparse points). Least-squares fit over several measurements; `colmap model_aligner`/`model_transformer` apply it. | Planned. (An earlier `scale_correct.py` compared full 3D camera distance to *height* difference alone — wrong unless the camera moved purely vertically — withdrawn.) |
| **2. Trajectory alignment / pose priors** | Align the whole VIO trajectory to the SfM trajectory with a similarity transform (Umeyama, as `evo` does), or feed VIO poses into SfM directly as priors via COLMAP 4's `pose_prior_mapper`. | Planned once a real VIO trajectory exists (M4/M5); lands as a rosbag importer plus an alternative SfM stage. |
| **3. Tight VIO/IMU fusion** | VIO/IMU as residuals inside bundle adjustment, or full visual-inertial Gaussian-splatting SLAM (MonoGS, Photo-SLAM). Research-grade code; the gain over Tier 2 matters mainly for fast motion / weak texture / large scale. | Stretch goal only. |

Ruled out: **depth data** (denser point cloud, fewer floaters — real benefit, but adds hardware/calibration cost, not needed for Tiers 1–2); **stereo** (a moving single camera already gives a longer effective baseline than a small stereo rig); **optical flow** (an M4 candidate for indoor hold, but gives no usable 3D pose for this pipeline — orthogonal to this decision).

## 4a. Evaluation: what the numbers mean

Held-out PSNR/SSIM checks one reconstruction, but can't compare capture strategies (autonomous vs manual vs lawnmower, M8) fairly — each would be graded on held-out frames from its own flight, so a planner that hovers and takes easy views scores well. M8 needs a shared **test capture per room** that every run is aligned to and rendered from (designed in `app/BRIEF.md` section 5; not built).

## 5. Status and next step

Built and tested (Mip-NeRF 360 "room": all 311 frames posed, 30.6–30.8 dB held-out PSNR at 7k iterations, about 3 min end to end; details in `app/BRIEF.md` section 6). Next, in order: more real handheld room scans to learn capture technique (M1's "notes on capture quality"); the rosbag importer once the capture node writes bags (M5); metric scale (Tier 1); scenes + shared evaluation for M8.
