# Gaussian Splat Pipeline: Sub-Brief (DRAFT v0.3)

Status: early concept, scoped to M1 ("splat pipeline, no drone") from the main project brief. This covers Stream B's starting point only — no flying yet, and no drone-mounted sensor integration (VIO, rangefinder-on-drone) yet, though Tier 1 scale correction (section 4) already uses a manually-supplied reference measurement (e.g. a tape-measured height).

## 1. What this covers

Turning a set of photos or a walked/orbited video into a viewable Gaussian splat, by hand (phone, camera, or tripod) or later from the drone's own camera, before any other drone sensor data is brought in.

## 2. Basic pipeline

1. **Capture** — sequential, overlapping photos, or video, of the object/room. No stereo or depth sensor needed for this basic version.
2. **Structure-from-Motion (SfM)** — COLMAP takes the images and works out where each one was shot from (camera poses) plus a rough, sparse 3D point cloud, purely by matching visual features between images.
3. **Gaussian splat training** — a tool (nerfstudio or gsplat) takes the images, poses and sparse points, and iteratively fits thousands of 3D "blobs" (position, size/orientation, transparency, colour) so that rendering them from each known camera pose matches the original photo as closely as possible.
4. **Viewer** — the trained splat is exported and opened in a web viewer.

## 3. What capture needs to succeed

- High overlap between consecutive shots (roughly 60–80%)
- Enough surface texture (blank walls, mirrors, glass all break step 2)
- Sharp images — motion blur is the main enemy
- A static scene — nothing moving between frames
- Coverage from varied heights/angles, not one flat orbit

## 4. Decision: camera-only now, staged sensor fusion plan for later

**Decided:** build the splat pipeline on camera footage alone first (drone or handheld). Sensor fusion is real, but staged into three tiers of increasing effort/risk, so we don't overbuild before we need to:

| Tier | What it is | Status |
|---|---|---|
| **1. Single/few-point scale correction** | Use one or more rangefinder altitude readings, matched to the corresponding COLMAP camera pose, to solve the single unknown scale factor that monocular SfM leaves ambiguous (fit by least squares if using several readings, not just one). Simple, robust, standard photogrammetry practice (this is what `colmap model_aligner` is for). | **Building this now**, with room to expand |
| **2. Full trajectory alignment** | Align the *entire* VIO trajectory to the *entire* COLMAP camera trajectory with a similarity transform (rotation + uniform scale + translation), fit across all corresponding frames via Umeyama's method — the same technique the `evo` SLAM-evaluation package uses to compare a trajectory against ground truth. Gets scale plus a whole-trajectory sanity check, still a closed-form, well-established fit — not fragile. | **Planned expansion**, once a real VIO trajectory exists (M4/M5) |
| **3. Tight VIO/IMU fusion inside SfM's optimization** | Treating VIO/IMU as weighted residuals inside bundle adjustment, or a full visual-inertial SLAM system that outputs poses (and possibly the splat) directly. Real published research (e.g. Gaussian Splatting SLAM/MonoGS, Photo-SLAM), but research-grade code, not a mature library — and the accuracy gain over Tier 2 mainly matters for fast motion / weak texture / large scale, not a small, carefully-captured single room. | **Stretch goal only**, not core path |

Other options considered and ruled out for reference:
- **Depth data**: denser initial point cloud, fewer floaters — real benefit, but adds hardware/calibration cost; not needed to get Tier 1/2 working.
- **Stereo**: not worth it even later — a moving single camera already gives a longer, better effective baseline than a small stereo rig would.
- **Optical flow** (M4 candidate for indoor hold): keeps the drone stable, but gives no usable pose data for this pipeline (no yaw, no 3D) — orthogonal to this decision.

Nothing here blocks starting the pipeline now: COLMAP works from images alone, and Tier 1 only needs one or a few rangefinder readings bolted on afterward, not a redesign.

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
| **gsplat / nerfstudio** | Open-source software packages that implement the actual Gaussian splat training step. |
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

The Tier 1 pipeline scaffold is built (`pipeline/`: frame extraction, COLMAP orchestration, scale correction — see `pipeline/README.md` for usage). Next step is finishing the scope of the management app that runs and tracks this pipeline end to end, being worked out in [`app/BRIEF.md`](app/BRIEF.md). Drone sensing scope (VIO, optical flow, depth) is a separate decision for M4, tracked in the main brief, not blocking either of these.
