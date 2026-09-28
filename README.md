# GauseDrone

An autonomous indoor drone that scans a room and turns the footage into a
Gaussian splat. The project plan is in [`BRIEF.md`](BRIEF.md).

What works today (milestone M1): **Splat Lab**, a local web app that turns a
video or a set of photos into a Gaussian splat and lets you view it in the
browser. The rest of this page is a guide to running it.

---

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
3. Click **Run** on the new capture, choose **Draft**, open *Advanced
   settings* and set **Hold out every Nth frame** to `8` (so it reports a
   quality score), then **Start run**.
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
- **Blank walls, mirrors, windows and shiny surfaces** confuse it; include
  furniture and texture in every shot.
- Keep the scene **still** (no people or pets moving) and the lighting
  constant. Don't zoom.
- Landscape or portrait both work; don't switch halfway through.

**Processing:**

1. Copy the video to the computer running Splat Lab.
2. **Captures** → *Import from a path on the server* → paste the video's path
   → **Import**. (Dragging the file into *Upload* also works but is slow for
   big videos.) Tick *Link instead of copying* to avoid duplicating big files;
   the original must then stay where it is.
3. **Run** → **Draft** → **Start run**. Default settings are a good start:
   2 frames per second of video, images up to 1600 px.
4. Check the result in the viewer. If it looks right, get the full-quality
   version without redoing the slow camera-pose step: on the run page click
   **New run from this**, keep *Reuse up to Camera poses*, choose
   **Standard**, and start it (about 15–20 min of training).

### 6. Using the viewer

| Control | What it does |
|---|---|
| Drag / right-drag / scroll | Orbit / pan / zoom |
| Double-click a surface | Orbit around that point |
| Fly button, then **W A S D**, **Q / E** | Walk through the scene, down / up (hold Shift to go faster) |
| **[** and **]**, or the slider at the bottom | Jump to each position the camera was filmed from |
| Photo button | Show the original frame next to the render at that position (quickest way to spot weak areas) |
| **O** (map button) | View from above with the ceiling cut away and the filming path drawn in, to check what was covered |
| Scissors button | Ceiling cutaway on/off, with a height slider |
| Camera button | Save a screenshot |
| Download button | Download the splat as `.ply` (opens in SuperSplat, Blender add-ons, etc.) |
| **R** | Reset the view |

### 7. When something goes wrong

| Symptom | Likely cause and fix |
|---|---|
| `splat-app` says the address is in use | Something already uses port 8000, often the background service. `systemctl --user stop splat-app`, or run on another port with `splat-app --port 8001`. |
| The service won't start | `journalctl --user -u splat-app -n 50` shows why. If you moved the project folder or changed how Nix is installed, rerun `bin/splat-app install-service`. |
| "Camera poses" fails, or only some frames are posed | Too much blur, too little overlap or too many blank surfaces. Check the log (the **log** link on that step). Refilm more slowly; or in Advanced settings raise *Frames per second* to 3–4. |
| The splat is blurry or full of floating blobs | Usually the capture: blur, too few viewpoints, or areas seen from only one side. The Standard preset helps a little; better filming helps a lot. |
| Training fails with "out of memory" | Lower *Max image size* (e.g. 1200) in Advanced settings and re-run. |
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

---

For developers (running the pipeline steps by hand, tests, code layout), see
[`gaussian-scanning/README.md`](gaussian-scanning/README.md).
