# Tier 1 pipeline

Scale-corrected splat pipeline: video/photos → COLMAP poses → Tier 1 scale
correction → Gaussian splat training. See `../BRIEF.md` for the design
reasoning and the tiered sensor-fusion plan this fits into.

## Prerequisites

- COLMAP installed and on `PATH` (system package/conda install — not pip-installable)
- `pip install -r requirements.txt` (nerfstudio pulls in torch; check
  nerfstudio's docs for the CUDA-matched torch build for your GPU)
- A CUDA GPU for training

## 1. Extract frames

```
python3 01_extract_frames.py path/to/video.mp4 data/frames/run1 --fps 2
```

Samples at the given rate, searching a small window around each sample time
for the sharpest nearby frame (Laplacian-variance blur check) rather than
blindly taking a fixed frame — motion blur is the main enemy of splat
quality. Writes `frame_timestamps.csv` alongside the frames, needed later to
match frames to sensor readings.

Already have photos instead of a video? Skip this step and point step 2
straight at your photos directory.

## 2. Run COLMAP, scale-correct, and train

```
./02_run_pipeline.sh data/frames/run1 run1 [reference_points.csv]
```

- Runs `ns-process-data` (COLMAP feature extraction, sequential matching,
  mapping, and conversion to `transforms.json`).
- If a reference-points CSV is given, fits a Tier 1 scale factor (see
  `scale_correct.py`) and trains on the scaled poses. Without one, trains on
  COLMAP's raw, arbitrarily-scaled poses — fine for a first look, not for
  metric measurements.
- Trains a splat with `ns-train splatfacto`.

### Building a reference-points CSV

Right now this is manual: shoot (or fly) a couple of extra frames at a
known, measured height — tape measure for a handheld test, or a rangefinder
reading for a drone flight once that's wired up and time-synced (see
`../BRIEF.md` section 4 — this sync step is not built yet). List them:

```
file_name,height_m
frame_00000.jpg,1.20
frame_00042.jpg,0.45
```

`scale_correct.py` fits a single scale factor from the straight-line
distance between each pair of reference cameras. It does not assume
COLMAP's axes are gravity-aligned — only that distances are correct up to
one unknown scalar — so two or more heights, even along no particular
COLMAP-recognised axis, are enough.

## Known gaps (intentional, not bugs)

- No automated video-time ↔ rangefinder-time sync yet (`../BRIEF.md`
  section 4) — `reference_points.csv` must already line up file names with
  real-world measurements.
- No Tier 2 (full trajectory alignment) yet — planned next step once a real
  VIO trajectory exists.
- No evaluation harness (PSNR/SSIM/LPIPS/coverage) yet — separate piece of
  work per `../BRIEF.md`.
