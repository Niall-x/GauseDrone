# gaussian-scanning

Capture → camera poses (COLMAP) → Gaussian splat (gsplat) → web viewer, plus
**Splat Lab**, the local app that runs and tracks it. Design notes are in
[`BRIEF.md`](BRIEF.md) (pipeline) and [`app/BRIEF.md`](app/BRIEF.md) (app).

## How to access

Most people don't need to install anything — Splat Lab runs on Niall's
machine and is shared over Tailscale (the "share machine" setting, not
public). If it's been shared with you:

1. Install [Tailscale](https://tailscale.com/download) and accept the share.
2. Open **https://nialls-pc.spangled-lungfish.ts.net** in your browser
   (or, if that name doesn't resolve, `https://<the machine's 100.x.y.z
   address>` after clicking through a certificate-name warning).

btw i didnt pick the url and i refuse to change it. also a thing is currently running to test a high rez scan and could take till tmrw

No login. Anyone with the link can start, cancel and delete runs. Uploading
big videos from your own machine over the internet is slow — trim them
first, or ask for a path import on the host instead. If the page shows "bad
gateway", the app is off; ask Niall to start it.

Only want to view a finished splat someone sent you? Open it directly on
their run's page, no separate install needed.

## Install guide

Run your own copy of Splat Lab (for local scans, development, or to be the
one others access).

**Needs:** Linux with an NVIDIA GPU (8 GB+, driver installed —
`nvidia-smi` should work) and **Nix with flakes** (supplies Python, COLMAP,
Node.js and the CUDA compiler; nothing else to install by hand). ~10 GB
disk for tools, plus ~0.5–1 GB per scan. macOS isn't supported (training
needs CUDA); Windows is untested but should work under WSL2.

Getting Nix: NixOS just needs flakes enabled
(`nix.settings.experimental-features = [ "nix-command" "flakes" ];`).
Elsewhere, the [Determinate installer](https://install.determinate.systems/nix)
enables flakes for you: `curl -fsSL https://install.determinate.systems/nix | sh -s -- install`.

```sh
git clone https://github.com/Niall-x/GauseDrone
cd GauseDrone/gaussian-scanning
nix develop        # first run downloads a few GB; after that, seconds
```

**Run it as a background service** (recommended — a systemd *user* service,
no root):

```sh
bin/splat-app install-service
systemctl --user start splat-app
```

Open **http://127.0.0.1:8000**. Other useful commands: `stop` / `status` /
`logs` (shortcuts for `systemctl --user … splat-app` / `journalctl --user -u
splat-app -f`), `enable` to start on login (+ `loginctl enable-linger $USER`
for boot without logging in), `uninstall-service` to remove it. Reinstall
with `--port 8001` to use a different port.

Or run it in the foreground, inside `nix develop`: `splat-app` (Ctrl-C to
stop). Either way, stopping mid-run marks that run *interrupted* — press
**Resume** next time and it continues from where it was cut off.

**Sanity-check the setup** (~10 min): `python scripts/fetch_test_data.py`
downloads a standard 311-photo test scene; import
`data/test/mipnerf360_room/images` on the Captures page, run it as
**Draft**, and expect roughly 30 dB held-out PSNR in the viewer.

**To let others reach your copy**, forward it with `sudo tailscale serve
--bg 8000` (adds HTTPS; add them to your tailnet or use Tailscale's device
sharing) — see "How to access" above for what they'll see. Never use
Tailscale Funnel (that makes it public), and note sharing a machine exposes
all its ports by default, not just this app — restrict a sharee to 443 in
your tailnet access policy if needed. By default *Import from a path* can
read any non-hidden folder under your home directory; narrow it with
`SPLAT_IMPORT_ROOTS` (`:`-separated) via `systemctl --user edit splat-app`.

## Using it

**Scanning a room:** walk slowly (1–2 min), several loops at different
heights, moving gradually between room-scale and close-up views — don't
just turn on the spot, and avoid blank walls/windows/mirrors and quick
camera swings. Import the video (or link it with *Link instead of
copying* to avoid a duplicate), run **Draft** first, and read the
**Capture report**: it grades the run *Good* / *Usable with gaps* /
*Unreliable* and says which seconds to refilm if anything's wrong. If it
looks right, **New run from this** → **Standard** for full quality without
redoing camera poses.

**Viewer:** WASD/arrows to move (Shift to go faster), drag to look, E/Space
and Q/C for up/down, right-drag to orbit, scroll to move forward/back,
double-click a surface to focus on it, `[`/`]` to jump between capture
positions, the photo button to compare a render against the original
frame, and the map button (`O`) for a top-down view with the filming path.

**If something looks wrong:** the Capture report on the run page names the
problem and what to refilm — that's the reliable fix for a garbled or
blurry splat. Camera-pose failures are usually too much blur or too little
overlap (try raising *Frames per second* in Advanced settings). "Out of
memory" during training is now capped automatically; if it still happens,
lower *Max Gaussians* or *Max image size*. Runs, captures and results all
live under `gaussian-scanning/data/` (not in git) — copy a run folder into
someone else's `data/runs/` to share a result directly.

---

## Developer reference

### Launcher

`bin/splat-app` (on `PATH` inside `nix develop`; also works from outside the
dev shell, it enters it itself):

| Command | What it does |
|---|---|
| `splat-app` | Build the frontend if sources changed, serve everything on http://127.0.0.1:8000 |
| `splat-app dev` | API with auto-reload on :8000 + Vite dev server on :5173 (open :5173) |
| `splat-app build` | Rebuild the frontend |
| `splat-app gen-api` | Regenerate `app/frontend/src/api/schema.d.ts` after changing backend models |
| `splat-app install-service` / `uninstall-service` | Write/remove a systemd user unit (`~/.config/systemd/user/splat-app.service`) that runs `splat-app serve` |
| `splat-app start` / `stop` / `restart` / `status` / `logs` | Shortcuts for `systemctl --user … splat-app` / `journalctl` |

`--host` / `--port` work with `serve`, `dev` and `install-service`. The unit
file records the absolute project path and where `nix` lives, so rerun
`install-service` after moving the checkout. On `systemctl stop`, systemd
SIGTERMs the whole service; the runner records a stage killed that way as
interrupted (resumable) rather than as a pipeline failure. `SPLAT_DATA_DIR` moves the
data directory (default `data/`). `SPLAT_IMPORT_ROOTS` (`:`-separated, default `~`)
limits which server folders *Import from a path* may read; hidden folders are always refused.

gsplat compiles its CUDA kernels on first use (~2 min, once per machine;
cached in `~/.cache/torch_extensions`). The flake builds COLMAP with CUDA
(GPU feature extraction + matching). cache.nixos.org has no CUDA builds, so the
first `nix develop` after a nixpkgs bump compiles it locally (a few minutes);
its kernels target sm_89 (RTX 40xx), so add your GPU's capability in
`flake.nix` for other cards, or run the SfM stage with *GPU features + matching* = 0.

Uploads from the browser are resumable (`/api/uploads`): the file list is
declared first, each file then arrives in chunks appended at an explicit
offset, and the bytes on disk under `data/uploads/<id>/` are the record of
progress, so a dropped connection or server restart costs at most one chunk.

### Test data

```sh
python scripts/fetch_test_data.py          # Mip-NeRF 360 "room", 311 photos (~78 MB of a 12.5 GB archive)
```

Import `data/test/mipnerf360_room/images` on the Captures page. A Draft run
(which holds out every 8th frame) should give roughly 30–31 dB held-out PSNR.

### Tests

```sh
python -m pytest tests     # ~5 s; no GPU or COLMAP needed (the runner tests use a fake stage)
```

### Pipeline without the app

Each stage is a CLI working on one run directory:

```sh
R=data/dev/myscan
python -m pipeline.extract_frames --run-dir $R --input path/to/video.mp4 --fps 4
python -m pipeline.sfm            --run-dir $R
python -m pipeline.train          --run-dir $R --iterations 7000 --holdout-every 8
python -m pipeline.export         --run-dir $R
```

`--help` on each lists its options.

### Layout

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
