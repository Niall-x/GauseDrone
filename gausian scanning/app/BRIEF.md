# Pipeline App: Sub-Brief (DRAFT v0.1)

Status: early concept. Sits under [`../BRIEF.md`](../BRIEF.md) (the splat pipeline stream), which sits under [`../../BRIEF.md`](../../BRIEF.md) (the main project). Architecture decisions below were settled in discussion, not yet built.

## 1. What this is

A local web app that takes a capture — drone or handheld video/photos, plus optional sensor data — and runs it through the splat pipeline (frame extraction → SfM → scale/pose correction → training → evaluation), instead of running each stage by hand from the command line. It tracks every run as a reproducible record (what went in, what config was used, what came out) so autonomous, manual, and lawnmower scans can actually be compared later (main brief's M8). It also embeds a splat viewer, so the whole loop — import capture, run pipeline, view result, compare against other runs — happens in one place.

It's built to grow with the project, not for a fixed feature set: no sensor data today, rangefinder-based scale correction (Tier 1) soon, full VIO trajectory alignment (Tier 2) later — see [`../BRIEF.md`](../BRIEF.md) section 4 for the tiers themselves. The app shouldn't need a redesign each time a tier is added.

## 2. Architecture decisions (settled)

| # | Decision |
|---|---|
| 1 | Wrap the existing pipeline scripts as subprocesses; don't reimplement their logic inside the app |
| 2 | Pipeline is a chain of typed, config-driven stages — the orchestrator chains stages from a declared config, not hardcoded per-tier branching |
| 3 | Sensor data is normalized behind one internal reading format; a small adapter per real source (rangefinder CSV, later VIO trajectory) translates into it |
| 4 | Long-running jobs (COLMAP, training) run in the background with status polling; no heavyweight task-queue system |
| 5 | Every run is a tracked, reproducible record — SQLite for run metadata/config/status, filesystem for the large artifacts |
| 6 | SuperSplat (open source) is the one standardized embedded viewer |
| 7 | Backend: FastAPI. Frontend: React + Vite + Tailwind + shadcn/ui, for maximum layout control and polish |
| 8 | Hand-built screens per feature, composed from a shared internal component library — not a generic manifest-driven form renderer |
| 9 | Each person runs their own backend wherever suits them (local PC, remote server) — no shared instance requirement |
| 10 | No synced database between users for now — working separately on different results; revisit if that changes |
| 11 | Dependency/version consistency (COLMAP, nerfstudio, CUDA/PyTorch) managed by hand per machine, not containerized |

## 3. What we need to build

### Backend (FastAPI)

- **Stage framework** — a base "pipeline stage" abstraction with a typed input/output contract, so concrete stages plug into the orchestrator uniformly.
- **Stage implementations**, wrapping what already exists as standalone scripts and adding what doesn't:
  - Frame extraction (exists: `pipeline/01_extract_frames.py`)
  - COLMAP / SfM run + pose extraction (exists as a raw call in `pipeline/02_run_pipeline.sh`; needs wrapping as a stage)
  - Tier 1 scale correction (exists: `pipeline/scale_correct.py`; needs wrapping as a stage)
  - Tier 2 trajectory alignment (doesn't exist yet — planned)
  - Gaussian splat training (exists as a raw call; needs wrapping as a stage)
  - Evaluation — PSNR/SSIM/LPIPS (nerfstudio's `ns-eval` covers the metrics; needs wrapping) + a coverage metric (doesn't exist yet — needs designing from scratch, this is the project's actual novel contribution)
- **Sensor data adapters** — normalized reading format (decision 3); adapters written as each real source becomes available (none needed yet, rangefinder CSV adapter next)
- **Job runner** — background subprocess execution, status/progress polling or streaming to the frontend
- **Run tracking** — SQLite schema for runs (inputs, exact config used, status, output artifact paths, metrics); filesystem layout for the large binary artifacts (raw capture, frames, COLMAP model, trained splat)
- **API** — endpoints to start a run, check/stream status, list run history, fetch a run's full record, serve splat files to the viewer

### Frontend (React + Vite + Tailwind + shadcn/ui)

- **Shared component library** — form fields, file upload, progress/status card, run card, buttons — built once, reused across every screen for visual consistency
- **Screens**:
  - Start a run — upload video or photos, optional sensor data, set parameters
  - Run progress/status
  - Run history — list of past runs
  - Run detail — config used, artifacts, metrics for one run
  - Splat viewer — embedded SuperSplat, loads a given run's exported splat
  - Comparison view — metrics side by side across runs (the genuinely new piece, no existing tool provides this)
- **Later, bespoke, not generic**: a reference-points editor for Tier 1, a trajectory review screen for Tier 2 — these are inherently visual/spatial and were never going to come from a generic form system regardless of decision 8

### Viewer integration

- Self-host/embed SuperSplat; wire it to load whichever run's exported splat the user selects

### Environment / dependencies

- COLMAP, nerfstudio, PyTorch/CUDA installed natively on each machine, versions matched by hand via a shared pinned `requirements.txt` (decision 11) — no containerization for now

### Explicitly deferred / out of scope for now

- Syncing results between separate users/machines (decision 10)
- Tier 2/3 sensor fusion implementations (planned in `../BRIEF.md`, not built)
- Containerized deployment (decision 11)

## 4. Not yet decided (next scoping pass, before writing code)

- Exact SQLite schema (fields per run record)
- Exact API endpoint list and request/response shapes
- Exact definition of the coverage metric
- Exact per-stage input/output contract shape (what "typed" means concretely)
- App name — currently just "the app"
