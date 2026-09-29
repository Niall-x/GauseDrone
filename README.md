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
   4 frames per second of video, images up to 1600 px. Check the Frames and
   Camera poses steps for amber warnings before trusting the result.
4. Check the result in the viewer. If it looks right, get the full-quality
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
| Amber warnings on the Frames or Camera poses step (a warning icon in the runs list) | The app checks the capture for long blurry or blank stretches, and the camera poses for jumps, flips and frames stacked on one spot. Each warning gives the times in the video. Poses flagged as wrong garble the splat even though the run says "done": if the run used the *global* mapper, re-run camera poses with *incremental*; otherwise raise *Frames per second* or refilm those moments more slowly. |
| The splat is garbled (walls doubled, the room smeared or folded) | Wrong camera poses; check the Camera poses step for warnings, as above. Turning on the spot, filming out of a window, and quick swings to close-ups are the usual causes. |
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

For developers (running the pipeline steps by hand, tests, code layout), see
[`gaussian-scanning/README.md`](gaussian-scanning/README.md).
