# Gaussian Splat Pipeline: Sub-Brief (v0.4)

Status: M1 ("splat pipeline, no drone") from the main project brief is **built**: a pipeline plus a local app (Splat Lab) that runs it and views the result. See [`README.md`](README.md) to run it and [`app/BRIEF.md`](app/BRIEF.md) for the app's design. No drone sensor data is used yet.

## 1. What this covers

Turning a set of photos or a walked/orbited video into a viewable Gaussian splat, from a handheld camera now and from the drone's camera later, before any other drone sensor data is brought in.

## 2. Basic pipeline

1. **Capture**: sequential, overlapping photos, or video, of the object/room. No stereo or depth sensor needed.
2. **Frames**: from video, the sharpest frame in each 1/fps-second window is kept, with its real timestamp (needed later to match frames to drone logs).
3. **Structure-from-Motion (SfM)**: COLMAP 4 works out where each image was shot from (camera poses) plus a sparse 3D point cloud, purely by matching visual features. Exhaustive matching for up to 400 frames (catches loop closures when a room scan returns to its start), then the global mapper (GLOMAP, now built into COLMAP), then undistortion to a pinhole camera.
4. **Gaussian splat training**: gsplat fits hundreds of thousands of 3D Gaussians (position, size/orientation, opacity, colour) so that rendering them from each camera pose matches the photo. Standard 3DGS recipe: densification, L1 + SSIM loss, spherical harmonics up to degree 3. 7k iterations for a draft, 30k for full quality.
5. **Export + viewer**: PLY (full precision) and SPZ (about 10x smaller) plus the camera path, opened in the app's own viewer.

Tooling decided: **COLMAP 4 + gsplat**, not nerfstudio (it pins old PyTorch and was the hardest part to install; gsplat is what it uses underneath). Environment: Nix flake + `uv.lock`.

## 3. What capture needs to succeed

- High overlap between consecutive shots (roughly 60–80%)
- Enough surface texture (blank walls, mirrors, glass all break step 3)
- Sharp images: motion blur is the main enemy
- A static scene: nothing moving between frames
- Coverage from varied heights/angles, not one flat orbit

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
| **GLOMAP / global mapper** | A faster way for SfM to solve all camera poses at once rather than adding images one by one; built into COLMAP 4. |
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

Built and tested (Mip-NeRF 360 "room": all 311 frames posed, 30.8 dB held-out PSNR at 7k iterations; details in `app/BRIEF.md` section 6). Next, in order: capture a real handheld room scan with the phone/splat-camera candidates to learn capture technique (M1's "notes on capture quality"); the rosbag importer once the capture node writes bags (M5); metric scale (Tier 1); scenes + shared evaluation for M8.
