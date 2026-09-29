# Gaussian Splat Pipeline: Sub-Brief (v0.6)

Status: M1 ("splat pipeline, no drone") from the main project brief is **built**: a pipeline plus a local app (Splat Lab) that runs it and views the result. See [`README.md`](README.md) to run it and [`app/BRIEF.md`](app/BRIEF.md) for the app's design. No drone sensor data is used yet.

## 1. What this covers

Turning a set of photos or a walked/orbited video into a viewable Gaussian splat, from a handheld camera now and from the drone's camera later, before any other drone sensor data is brought in.

## 2. Basic pipeline

1. **Capture**: sequential, overlapping photos, or video, of the object/room. No stereo or depth sensor needed.
2. **Frames**: from video, the sharpest frame in each 1/fps-second window is kept, with its real timestamp (needed later to match frames to drone logs).
3. **Structure-from-Motion (SfM)**: COLMAP 4 works out where each image was shot from (camera poses) plus a sparse 3D point cloud, purely by matching visual features. Feature extraction and matching run on the GPU; exhaustive matching for up to 800 frames (catches loop closures when a room scan returns to its start; ~3 min of video at the default 4 fps), then the incremental mapper up to 800 frames and the global mapper (GLOMAP, now built into COLMAP) beyond (bundle adjustment runs on the CPU), then undistortion to a pinhole camera. Global mapping was the default until it proved unreliable on handheld phone video (section 3a). The poses are then checked for errors; frames with wrong positions are left out of training, and a run whose positions can't be trusted pauses before training (section 3b).
4. **Gaussian splat training**: gsplat fits hundreds of thousands of 3D Gaussians (position, size/orientation, opacity, colour) so that rendering them from each camera pose matches the photo. Standard 3DGS recipe: densification, L1 + SSIM loss, spherical harmonics up to degree 3. 7k iterations for a draft, 30k for full quality.
5. **Export + viewer**: PLY (full precision) and SPZ (about 10x smaller) plus the camera path, opened in the app's own viewer.

Tooling decided: **COLMAP 4 + gsplat**, not nerfstudio (it pins old PyTorch and was the hardest part to install; gsplat is what it uses underneath). Environment: Nix flake + `uv.lock`.

## 3. What capture needs to succeed

- High overlap between consecutive shots (roughly 60–80%)
- Enough surface texture (blank walls, mirrors, glass all break step 3)
- Sharp images: motion blur is the main enemy
- A static scene: nothing moving between frames
- Coverage from varied heights/angles, not one flat orbit

### 3a. Findings from the first handheld scans (2026-09-29)

Two phone videos (4K portrait, 30 fps) of one room: a 39 s turn on the spot, and a 77 s walk around the room with close-ups of the desk and chair and a view out of the patio doors. Both first came out garbled or noisy; the numbers are in [`app/BRIEF.md`](app/BRIEF.md) section 6.

- **The global mapper (GLOMAP) was the main cause of garbled splats.** It reported every frame posed with sub-pixel reprojection error, but the poses were wrong: 11 frames stacked on one spot, 5–8-unit jumps between frames half a second apart, 168° flips. It places cameras from pairwise translation directions, which are noise when the baseline is a few centimetres (turning on the spot) or the features are at infinity (the garden through the window). The incremental mapper on the same matches: +5.3 dB held-out PSNR on the turn-on-the-spot video. It also fails honestly, splitting a capture into pieces instead of forcing unconnected parts together. **Now the default up to 800 frames.**
- **2 fps is too sparse for handheld video.** On the walk, 2 fps left transitions (room view → close-up, fast turns) without enough overlap; 4 fps + incremental held together as one model (281/310 frames) and scored 22.9 dB against 19.6 dB for the old defaults. **Now 4 fps.**
- **Unrecoverable stretches are blurry or blank.** The 60–68 s stretch (a quick pan over the chair, drawers and floor, at 13–35% of the median sharpness) could not be placed at 2 or 4 fps with either mapper. The software can only leave it out and say so; the fix is filming it more slowly.
- **Blur rejection does not help.** A median-relative sharpness threshold cannot tell blur from a plain surface: at every threshold tried (0.2–0.5), over half the frames it dropped had been posed fine, including every view of a blank wall. Left off; the blur *warning* points at the stretches to refilm instead.
- **Turning on the spot is a weak capture even with correct poses** (24 dB): little parallax means little depth information. Walk the room.
- **Auto-exposure swings** when the camera faces a bright window, which training can't reconcile (floaters). Not addressed yet; per-image appearance compensation in training (gsplat supports it) is the likely fix, or exposure lock on the phone.

Capture guidance that follows (also in the top-level README): walk slowly rather than turning on the spot; move gradually between room-scale views and close-ups; avoid quick sweeps over blank walls, doors and floor; don't film out of windows; keep the zoom fixed (a lens switch breaks the single-camera assumption).

### 3b. Handling captures that aren't ideal (decided 2026-09-29)

Good captures give good splats. Bad ones will keep happening, including from the drone: its movement will be more structured than a handheld phone, but blur, blank walls, windows and SfM failures don't go away. The pipeline can measure a lot about a capture, so the approach is to use those measurements rather than train blindly on whatever COLMAP returns.

**Principles**
1. **A missing area is better than a garbled room.** Data we can't trust is left out, and the user is told, instead of letting it corrupt everything else.
2. **Detect, then fix or tell.** Each problem is either fixed automatically (and logged) or reported with where it is and what to do.
3. **Say where.** For video that means seconds into the capture, with thumbnails, so the user knows which moment to refilm (and, later, the planner knows where to fly again).
4. **Only raise what's actionable.** Anything that doesn't change what the user does, or explain a flaw they'll see, is hidden or shown as info.
5. **Stop early when it's hopeless.** Don't spend training time on camera positions already known to be wrong.

**What happens** (code: `pipeline/quality.py`, `pipeline/sfm.py`)

| Problem | Detected by | Automatic response | Shown to the user |
|---|---|---|---|
| Wrong camera positions: jumps, frames stacked on one spot, impossible turns | Neighbouring-frame motion (video) | One retry (below). Flagged frames are left out of training | Warning with times; red cameras in the viewer |
| Stretches that couldn't be placed | Frames missing from the model, leaving 1 s or more of video uncovered (3+ frames for photos) | One retry with extra frames around them | Warning with times: "refilm these moments" |
| The scene split into pieces | More than one COLMAP model | Same retry; the largest piece is used | Warning, or error if the piece holds under 70% of the frames |
| Most frames unplaced | Under half placed | Same retry | Error |
| Blur or plain surfaces | Sharpness under 35% of the median for 1.5 s or more | None (blur rejection was tested and hurts) | Info, and named as the likely cause when it overlaps a failure |

**Verdict** for every run, from the camera-pose check:
- **Good:** nothing found.
- **Usable, with gaps:** some stretches missing or left out; the rest can be trusted.
- **Unreliable:** wrong positions in 3 or more separate places or on more than 5% of frames (spread-out errors mean the in-between positions can't be trusted either), the piece used holds under 70% of the frames, or under half the frames are placed. The run **pauses before training** ("Needs attention"), offering *Train anyway*, *Re-run camera poses* and *Stop here*.

The thresholds were set on six reconstructions of our two handheld videos: every garbled one comes out Unreliable and the good ones don't.

**The retry** runs once, only when the first attempt isn't Good: the incremental mapper (if the global one was used) plus frames at 3x the capture rate within 2 s of each failed stretch. It reuses the first attempt's features and matches, so only the new frames cost time. The better of the two attempts is kept, judged by verdict first and then the share of frames placed and kept.

**Deliberately not raised:** isolated blurry frames (frame selection already skips them), low sharpness where poses came out fine, the small duplicate models COLMAP sometimes leaves, reprojection error (garbled runs scored 0.5–0.8 px, which looks healthy), and absolute PSNR thresholds (they depend on the scene).

**Structured, not just text.** Each issue has a kind, severity, time ranges, frame names, the evidence and the fix, saved with the run (`sfm/quality.json` and the stage result). The UI draws the capture-report timeline from it. The same record is what the drone's planner will need to go back and re-fly weak areas (M7 and the stretch goal), so this is groundwork for autonomy as well as a UI feature.

**Training can't be run out of memory by a bad capture.** Noisy footage grows floaters without limit: the worst-case walk reached 6.45M Gaussians and crashed a 30k run on the 16 GB card. Densification now stops at a cap sized from the free GPU memory (about 4.2M on this machine), reported as an info note when reached.

**Next** (not built yet): exposure compensation in training (gsplat's appearance embeddings) for brightness swings; spotting moving objects from frames the finished splat reproduces badly; a "turned on the spot" detector from the camera path; a "moving too fast" detector from matches between neighbouring frames; warnings before a run starts (e.g. a capture too short). Each needs checking against a set of short test clips with known faults (fast pan, window, blank wall, turning on the spot, a person walking through, a zoom change) plus one clean walk before it ships.

## 4. Decision: camera-only now, staged sensor fusion later

**Decided:** the splat pipeline runs on camera footage alone first. Sensor fusion is staged into tiers of increasing effort/risk. None of them is needed for *training*: nerf/splat training is scale-agnostic. Metric scale and alignment matter for measurements, the coverage metric, and comparing runs in one room frame, so they are applied to the reconstruction/exports as a transform, not baked into training.

| Tier | What it is | Status |
|---|---|---|
| **1. Metric scale** | Solve the single unknown scale factor monocular SfM leaves. Correct inputs are either (a) a **known real distance between two things visible in the images** (a tape-measured edge, or a printed ArUco/ChArUco marker of known size), or (b) **camera height above the floor** from the rangefinder, with the floor plane fitted to the sparse points. Fit by least squares over several measurements; `colmap model_aligner` / `model_transformer` apply the result. | Planned stage. The earlier `scale_correct.py` was **withdrawn**: it compared the full 3D distance between two cameras against only their *height* difference, which is wrong unless the camera moved purely vertically (a sideways walk gave a scale ~4x off). |
| **2. Trajectory alignment / pose priors** | Align the whole VIO trajectory to the SfM camera trajectory with a similarity transform (Umeyama, as `evo` does), giving scale plus a whole-trajectory sanity check. COLMAP 4 also has `pose_prior_mapper`, which uses the VIO poses as priors *inside* SfM, which is a direct route from drone rosbag to a metric, gravity-aligned reconstruction. | Planned, once a real VIO trajectory exists (M4/M5); lands as a rosbag importer + alternative SfM stage |
| **3. Tight VIO/IMU fusion** | VIO/IMU as residuals inside bundle adjustment, or a full visual-inertial Gaussian-splatting SLAM (e.g. MonoGS, Photo-SLAM). Research-grade code; the accuracy gain over Tier 2 matters mainly for fast motion / weak texture / large scale, not a small, carefully captured room. | Stretch goal only |

Other options considered and ruled out for reference:
- **Depth data**: denser initial point cloud, fewer floaters; a real benefit, but adds hardware/calibration cost; not needed for Tiers 1–2.
- **Stereo**: not worth it even later: a moving single camera already gives a longer effective baseline than a small stereo rig.
- **Optical flow** (M4 candidate for indoor hold): keeps the drone stable, but gives no usable pose data for this pipeline (no yaw, no 3D). Orthogonal to this decision.

## 4a. Evaluation: what the numbers mean

Each run can hold out every Nth frame and report PSNR/SSIM on those unseen views. That checks one reconstruction. It **cannot** compare two capture strategies (autonomous vs manual vs lawnmower, M8), because each would be graded on held-out frames from its own flight, so a planner that hovers and takes easy views scores well. M8 needs a shared **test capture per room** that every run is aligned to and rendered from. Designed in `app/BRIEF.md` section 5; not built.

## 5. Vocabulary

| Term | Meaning |
|---|---|
| **Baseline** (stereo) | The physical distance between two camera lenses in a stereo pair; determines how well distance/depth can be judged, especially at range. |
| **Bundle adjustment** | The optimisation step that jointly refines all camera poses and 3D points together to minimise the error between predicted and observed image positions. |
| **COLMAP** | The standard free tool that performs Structure-from-Motion — the thing that actually works out camera positions from a set of photos. |
| **Depth / ToF camera** | A camera that measures distance directly per pixel (via a projected pattern or by timing a light pulse — "time-of-flight"), rather than inferring it from matching images. |
| **Extrinsic calibration** | Working out the fixed physical offset (position + rotation) between two sensors on the same rig — e.g. the splat camera vs. the IMU — so their data can be combined correctly. |
| **Feature matching** | Identifying the same physical point (a corner, a mark, a texture patch) across multiple photos — this is what lets COLMAP work out how the camera moved. |
| **Floaters** | Stray, wrong Gaussian blobs that appear in empty space in a finished splat, usually from bad geometry in low-texture or poorly-covered areas. |
| **Gaussian** (as in "Gaussian splat") | A small, soft, blurry 3D blob (mathematically a 3D Gaussian distribution) used as the basic building block, instead of a mesh triangle or a solid point. |
| **gsplat** | The open-source CUDA library that implements Gaussian splat rendering and training; the pipeline uses it directly (nerfstudio is a larger framework built on top of it, not used here). |
| **GLOMAP / global mapper** | A faster way for SfM to solve all camera poses at once rather than adding images one by one; built into COLMAP 4. Less robust than incremental mapping on handheld video with little parallax. |
| **SPZ** | A compressed splat file format (about 10x smaller than PLY) that the viewer loads. |
| **IMU** (Inertial Measurement Unit) | A chip with accelerometers and gyroscopes that measures acceleration and rotation, used to estimate motion between frames. |
| **Loop closure** | Recognising that a camera has returned to a place it's seen before, which lets a SLAM/VIO system correct drift that's built up since then. |
| **Metric scale** | Real-world units (metres), as opposed to the arbitrary, internally-consistent-but-unitless scale that plain photo-based SfM produces on its own. |
| **Opacity** | How transparent or solid a Gaussian blob is — one of the parameters learned per splat during training. |
| **Parallax** | The apparent shift in an object's position when viewed from different viewpoints — the effect that makes triangulating 3D position from 2D photos possible. |
| **Photometric loss** | The measured difference between a rendered image (from the current splat) and the real photo — the error the training process tries to minimise. |
| **PSNR / SSIM / LPIPS** | Three automated scores (used in the main brief's evaluation) for how close a rendered image is to a real photo: PSNR = a pixel-level signal/error ratio, SSIM = structural similarity, LPIPS = a learned "looks similar to a human" score. |
| **Rolling vs. global shutter** | Rolling shutter exposes an image line-by-line — cheap, but distorts fast-moving subjects or cameras. Global shutter captures the whole frame at once. |
| **SfM** (Structure-from-Motion) | The general technique of recovering 3D structure and camera positions purely from a set of overlapping 2D photos. |
| **SLAM** (Simultaneous Localisation and Mapping) | A moving sensor building a map of its surroundings while simultaneously working out its own position within that map, in real time. |
| **Sparse point cloud** | The rough, incomplete set of 3D points COLMAP produces as a byproduct of working out camera poses — as opposed to a dense scan. |
| **Spherical harmonics (SH)** | A compact mathematical way of storing how a Gaussian's colour changes with viewing angle, so splats can show basic reflections/sheen rather than one flat colour. |
| **VIO** (Visual-Inertial Odometry) | A real-time technique combining camera images and IMU data to continuously estimate a moving camera's position and orientation. |


## 6. Status and next step

Built and tested (Mip-NeRF 360 "room": all 311 frames posed, 30.6–30.8 dB held-out PSNR at 7k iterations, about 3 min end to end since the 2026-09-28 speed pass; details in `app/BRIEF.md` section 6). Next, in order: capture a real handheld room scan with the phone/splat-camera candidates to learn capture technique (M1's "notes on capture quality"); the rosbag importer once the capture node writes bags (M5); metric scale (Tier 1); scenes + shared evaluation for M8.
