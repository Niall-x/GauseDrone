# gaussian-scanning

Capture → camera poses (COLMAP) → Gaussian splat (gsplat) → web viewer, plus
**Splat Lab**, the local app that runs and tracks it. Design notes are in
[`BRIEF.md`](BRIEF.md) (pipeline) and [`app/BRIEF.md`](app/BRIEF.md) (app).

## How to run Splat Lab

### 1. What you need

- **Linux with an NVIDIA GPU** and its driver installed (`nvidia-smi` should
  work). Tested on NixOS with an RTX 4070 Ti Super (16 GB). Any recent NVIDIA
  card with 8 GB+ should cope with the default settings.
- **Nix with flakes.** Nix supplies everything else at pinned versions:
  Python, COLMAP, Node.js and the CUDA compiler. You don't install any of
  those yourself.
- About **10 GB of free disk** for the tools, plus space for your scans
  (a room is roughly 0.5–1 GB per run).

Getting Nix:

| Your system | What to do |
|---|---|
| NixOS | Flakes must be enabled (`nix.settings.experimental-features = [ "nix-command" "flakes" ];`). Nothing else. |
| Ubuntu / Fedora / other Linux | Install Nix with the Determinate installer (enables flakes for you): `curl -fsSL https://install.determinate.systems/nix \| sh -s -- install`, then open a new terminal. |
| Windows | Untested. It should work inside WSL2 (Ubuntu) with the NVIDIA WSL driver, following the Linux row. |
| macOS | Not supported (training needs CUDA). |

### 2. First-time setup

```sh
git clone https://github.com/Niall-x/GauseDrone
cd GauseDrone/gaussian-scanning
nix develop
```

The first `nix develop` downloads the tools and Python packages (a few GB, a
few minutes). After that it takes a couple of seconds. Every command below is
run inside this shell (your prompt stays in `gaussian-scanning/`).

### 3. Start and stop the app

**Recommended: as a background service** (a systemd *user* service, no root
needed). Install it once, from the `gaussian-scanning/` folder:

```sh
bin/splat-app install-service
```

Then, from any terminal (no need for `nix develop`):

| To | Run |
|---|---|
| Turn it on | `systemctl --user start splat-app` |
| Turn it off | `systemctl --user stop splat-app` |
| Check it's running | `systemctl --user status splat-app` |
| Watch its log | `journalctl --user -u splat-app -f` |
| Start it automatically when you log in | `systemctl --user enable splat-app` (undo with `disable`) |
| ...and at boot, without logging in | also `loginctl enable-linger $USER` (undo with `disable-linger`; on NixOS you can set `users.users.<you>.linger = true;` instead) |
| Remove the service | `bin/splat-app uninstall-service` |

(`bin/splat-app start` / `stop` / `status` / `logs` are shortcuts for the same.)
Once it's on, open **http://127.0.0.1:8000**. The first start after an update
also rebuilds the web interface, so give it up to a minute. To serve on a
different port, reinstall with `bin/splat-app install-service --port 8001`.

**Or in a terminal**, inside `nix develop`:

```sh
splat-app
```

and press **Ctrl-C** to stop.

Either way, turning it off while a run is in progress marks that run
*interrupted*; press **Resume** on it next time and it continues from the step
that was cut off. Queued runs wait until the app is back on.

### 4. Try it on the test scene (about 10 minutes)

This checks the whole setup before you film anything.

1. In a second terminal (inside `nix develop`), download a standard test
   scene, 311 photos of a living room:
   ```sh
   python scripts/fetch_test_data.py
   ```
2. In the app, go to **Captures** → *Import from a path on the server*, paste
   the full path to `gaussian-scanning/data/test/mipnerf360_room/images`
   (e.g. `/home/you/GauseDrone/gaussian-scanning/data/test/mipnerf360_room/images`)
   and click **Import**.
3. Click **Run** on the new capture, choose **Draft** (it holds out every 8th
   frame, so it reports a quality score), then **Start run**.
4. Watch the run page. Expect roughly: camera poses 4–5 min, training 3 min
   (plus ~2 min once, the very first time, while the GPU code compiles).
5. Click **Open viewer**. A working setup scores about **30 dB** held-out PSNR
   on this scene.

### 5. Scan your own room

**Filming** (a phone is fine). This matters more than any setting:

- Walk **slowly** around the room for 1–2 minutes. Motion blur is the main
  cause of bad results.
- Film **several loops at different heights** (high, chest height, low),
  always pointing the camera into the room, and end back where you started.
- Keep plenty of **overlap**: never swing the camera quickly to a new spot.
  Move gradually between room-scale views and close-ups.
- **Walk**, don't just turn on the spot: SfM judges distance from how the view
  shifts as the camera moves.
- **Blank walls, mirrors, windows and shiny surfaces** confuse it; include
  furniture and texture in every shot.
- Keep the scene **still** (no people or pets moving) and the lighting
  constant. Don't zoom.
- Landscape or portrait both work; don't switch halfway through.

**Processing:**

1. Copy the video to the computer running Splat Lab.
2. **Captures** → *Import from a path on the server* → paste the video's path
   → **Import**. (Dragging the file into *Upload* also works but is slower for
   big videos; if an upload is interrupted, pick the same files again and press
   **Resume upload** to continue where it stopped.) Tick *Link instead of
   copying* to avoid duplicating big files; the original must then stay where it is.
3. **Run** → **Draft** → **Start run**. Default settings are a good start:
   4 frames per second of video, images up to 1600 px.
4. Read the **Capture report** on the run page. The app checks the video and
   the camera positions COLMAP worked out, and gives the run a verdict:
   - **Good**: nothing found.
   - **Usable, with gaps**: parts of the video couldn't be used (the report
     says which seconds, with thumbnails). Frames with wrong camera positions
     are left out of training automatically, so the rest of the room isn't
     garbled; those areas will just be thin or missing.
   - **Unreliable**: too many camera positions look wrong. The app has
     already retried once (with extra frames around the problems), and the
     run stops before training, marked **Needs attention**. Choose *Train
     anyway*, *Re-run camera poses…* with other settings, or *Stop here*.
     Refilming the moments on the timeline is the reliable fix.
5. Check the result in the viewer. If it looks right, get the full-quality
   version without redoing the slow camera-pose step: on the run page click
   **New run from this**, keep *Reuse up to Camera poses*, choose
   **Standard**, and start it (about 10 min of training).

### 6. Using the viewer

| Control | What it does |
|---|---|
| **W A S D** or arrow keys | Move through the scene (hold Shift to go faster) |
| **E** / Space, **Q** / C | Up / down |
| Drag | Look around (works while moving, like a game) |
| Right-drag / middle-drag / scroll | Orbit the point you're looking at / pan / move forward and back |
| Double-click a surface | Look at that point and orbit around it |
| **[** and **]**, or the slider at the bottom | Jump to each position the camera was filmed from |
| Photo button | Show the original frame next to the render at that position (quickest way to spot weak areas) |
| **O** (map button) | View from above with the ceiling cut away and the filming path drawn in, to check what was covered |
| Scissors button | Ceiling cutaway on/off, with a height slider |
| Camera button | Save a screenshot |
| Download button | Download the splat as `.ply` (opens in SuperSplat, Blender add-ons, etc.) |
| Mouse-pointer button | Mouse sensitivity: how far a drag turns the view and how far a scroll step moves (0.25x to 4x, remembered by the browser; double-click a slider to reset it) |
| **R** | Reset the view |

### 7. When something goes wrong

| Symptom | Likely cause and fix |
|---|---|
| `splat-app` says the address is in use | Something already uses port 8000, often the background service. `systemctl --user stop splat-app`, or run on another port with `splat-app --port 8001`. |
| The service won't start | `journalctl --user -u splat-app -n 50` shows why. If you moved the project folder or changed how Nix is installed, rerun `bin/splat-app install-service`. |
| "Camera poses" fails, or only some frames are posed | Too much blur, too little overlap or too many blank surfaces. Check the log (the **log** link on that step). Refilm more slowly; or in Advanced settings raise *Frames per second* (default 4) to 6. |
| A run shows *Usable, with gaps* or *Unreliable* (amber or red icon in the runs list) | See the Capture report on the run page: each problem has the seconds of video it affects and what to do. Refilming those moments more slowly is the reliable fix. |
| A run is paused with **Needs attention** | The camera positions couldn't be trusted even after an automatic retry, so it stopped before spending time on training. See the row above; *Train anyway* carries on regardless. |
| The splat is garbled (walls doubled, the room smeared or folded) | Wrong camera positions. The capture report usually says where; frames it flagged are already left out, so a garbled splat with a *Good* verdict is worth reporting. Turning on the spot, filming out of a window, and quick swings to close-ups are the usual causes. In the viewer, the camera-frustum button draws left-out cameras in red. |
| The splat is blurry or full of floating blobs | Usually the capture: blur, too few viewpoints, or areas seen from only one side. The Standard preset helps a little; better filming helps a lot. |
| Training fails with "out of memory" | Another program may be using the GPU; close it and press **Resume**. Training now caps the number of Gaussians to fit the free GPU memory, so noisy captures no longer run it out; if it still happens, lower *Max Gaussians* (e.g. 3000000) or *Max image size* (e.g. 1200) in Advanced settings and re-run training. |
| The scene looks tilted in the viewer | "Up" is guessed from how the camera was held. Cosmetic only; the splat itself is fine. |
| The first training run sits at "loading gsplat CUDA kernels" | Normal the first time on a machine: it compiles GPU code for ~2 min, once. |
| Sidebar says "no GPU found" | The NVIDIA driver isn't visible. Check `nvidia-smi` works in the same terminal. |

### 8. Where things are kept

- Everything the app makes lives in `gaussian-scanning/data/` (not in git):
  `captures/` for imported footage and `runs/` for results.
- Each run is one self-contained folder: the frames, camera poses, trained
  splat, the exported `.ply`/`.spz`, logs, and a `run.json` recording the
  settings, software versions and quality scores. **To share a result, copy
  the run folder** into someone else's `data/runs/`; it appears in their app.
- Delete runs and captures from the app (the bin icons) to free space.

### 9. Running it on another (GPU) machine

Start `splat-app` on the GPU machine as above, then from your laptop:

```sh
ssh -L 8000:127.0.0.1:8000 you@gpu-machine
```

and open http://127.0.0.1:8000 on the laptop. The app has no login, so
don't expose it to a network directly.

### 10. Sharing it with someone over Tailscale

The app only listens on the machine itself (`127.0.0.1`). To let someone on
your tailnet use it, including a friend you've shared the machine with,
forward it with **Tailscale Serve**, which adds HTTPS and leaves the app itself
unchanged.

**On the machine running Splat Lab, once:**

```sh
sudo tailscale serve --bg 8000
```

It survives reboots. `tailscale serve status` shows it;
`sudo tailscale serve --https=443 off` removes it. (Your tailnet needs MagicDNS
and HTTPS certificates enabled, both in the Tailscale admin console under DNS.)

**Everyone else opens** `https://<machine-name>.<tailnet-name>.ts.net`, the
name `tailscale serve status` prints (for Niall's PC:
https://nialls-pc.spangled-lungfish.ts.net). If that name doesn't resolve for
a friend using a shared machine, `https://<the machine's 100.x.y.z address>`
also works after clicking through a certificate-name warning.

It works whenever the app is on (`systemctl --user start splat-app`); while
it's off, visitors get a "bad gateway" page.

Things to know before sharing:

- **There is no login.** Anyone who can reach it can start, cancel and delete
  runs, and *Import from a path* can read any non-hidden folder under your home
  directory (images in it become viewable through a run). To narrow that, set
  `SPLAT_IMPORT_ROOTS` to the folders captures should come from (`:`-separated,
  e.g. `~/scans`), for the service via `systemctl --user edit splat-app`
  (`[Service]` then `Environment=SPLAT_IMPORT_ROOTS=/home/you/scans`). Only
  share with people you trust, and **never use Tailscale Funnel** (that makes it public).
- **Sharing a machine exposes all its ports** to the other person by
  default, not just this app. To limit a shared friend to Splat Lab, allow
  only port 443 for them in your tailnet access-control policy (see Tailscale's
  docs on sharing and access control).
- Training runs on the host's GPU; the viewer runs in the visitor's browser
  (it downloads the 10–35 MB splat). *Upload from this computer* sends files
  from the visitor's machine, so big videos are slow over the internet: trim
  them first. Uploads resume after a dropped connection (re-pick the same
  files). *Import from a path* only sees files on the host.

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
