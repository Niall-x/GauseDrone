# Autonomous Gaussian Splatting Drone: Project Brief (DRAFT v0.3)

Status: the drone side is still a proposal to argue about. **M1 (splat pipeline, no drone) is built**: see section 5a, and "How to run Splat Lab" below to run it. Open questions are at the end.

## 1. The idea

An ArduPilot quadcopter with a ROS 2 companion computer flies itself through a single room, choosing where to go next so the whole space gets covered, and records images and camera positions as it goes. Afterwards, that footage is turned into a Gaussian splat (a photorealistic 3D scene) and viewed in a web viewer.

**Goal:** experience and CV material in drones, robotics, state estimation, planning and 3D reconstruction. Not a product.

## 2. Prior work

Autonomous drones for Gaussian splatting are an active research area (FlyGS, DRAGON, DroneSplat, next-best-view papers), so we're not claiming novelty. Our angle is a **low-cost, open, reproducible indoor system with a proper evaluation**, built on ROS 2 and ArduPilot.

## 3. Scope

A drone that navigates autonomously, and a system that generates splats from what it captures. Indoor vs. outdoor operation is still undecided.

## 4. System architecture

Key decisions:

- **ArduPilot flies the drone.** The companion computer only sends it target positions and its own position estimate. If ROS crashes, ArduPilot's failsafes still work.
- **Splats are trained after the flight**, on the desktop GPU. The drone just records images, positions and timestamps to a rosbag.
- **Splat camera plus positioning sensing:** a separate fast-shutter camera for the splat images (motion blur ruins splats). Positioning/obstacle avoidance could be a depth camera or multi-camera SLAM — undecided.
- **The position estimate (VIO) goes two ways.** ArduPilot gets it in real time to hold the drone steady. The capture node logs it directly on the companion computer, so the splat data isn't degraded by the flight controller's latency and filtering.

## 5. Milestones (each one a CV-able deliverable)

| # | Milestone | What we can show |
|---|---|---|
| M1 | Splat pipeline, no drone | Handheld scan to splat in the web viewer, plus notes on capture quality. **Built; see 5a** |
| M2 | Simulation + ROS 2 workspace | Simulated drone flying waypoints in Gazebo; simulated room scan |
| M3 | Hardware bring-up | Airframe flies stably, companion computer connected, telemetry and rosbag logging |
| M4 | Indoor hover without GPS | VIO feeding ArduPilot, stable indoor hover (fixes the Droneye failure) |
| M6 | Scripted autonomous scan | Pre-planned pattern over one room, end to end, no manual input |
| M7 | Adaptive coverage planner | Drone explores the room on its own, avoiding obstacles, using its 3D map |
| Stretch | Quality-driven view planning | Planner picks views where the splat is weakest |

If we stop after M6, we still have a complete result.

## 5a. Where we are: M1

**Built:** Splat Lab, a local web app that turns a video or photos into a splat, viewable in-browser. Runs on the RTX 4070 Ti Super, shared over Tailscale. [pipeline brief](gaussian-scanning/BRIEF.md) · [app brief](gaussian-scanning/app/BRIEF.md).

- Public test scene: 30.7–32.1 dB PSNR, in line with published results.
- First real phone-video scans came out garbled; a better COLMAP mapper and more frames per second fixed most of it.
- Bad-capture handling now built: suspect frames dropped, one retry, pause-before-training on runs that can't be trusted.

**Still to do:** more real scans, real-world scale, a shared test capture per room for fair comparisons, and importing the drone's recorded positions once it exists.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Vibration and mass imbalance (as in Droneye) | Balanced frame, soft-mounted flight controller and camera; tune before adding software |
| Positioning fails on blank walls or in low light | Depth-based odometry as backup; add light and texture to the test room; rosbag replays |
| Motion blur ruins splats (confirmed on the first handheld scans) | Fast-shutter camera, handheld tests before flying, slow flight |
| COLMAP gets camera positions wrong when the camera rotates on the spot or looks out of a window (seen on the first handheld scans) | Plan flight paths that travel rather than spin in place; use the drone's recorded positions as priors; the app leaves suspect frames out, retries, and pauses runs it can't trust (pipeline brief 3b) |
| Companion computer too slow | Pi 5 or Jetson; offload heavy work to the ground station over Wi-Fi if needed |
| Crashes and cost | Simulation first, prop guards, net, kill switch, spare-parts budget |
| Scope creep | One room; M6 is the "done" line |
| Coordinate-frame mix-ups (ROS uses ENU, ArduPilot NED) or an unmeasured camera-to-IMU offset | Explicit, tested frame conversion in the bridge; measure and configure the offset before the first flight |
| VIO can't run with low, *steady* latency on the companion computer (jitter hurts more than average delay) | Benchmark it on the real hardware at M3/M4 before relying on it; move to a Jetson if the Pi can't keep up |
| Flight controller and companion computer clocks drift apart | MAVLink timesync, checked on the bench before trusting VIO in flight |

Outdoor flights with a camera drone over 100 g need a CAA Operator ID. Check the current rules before flying outdoors.

## 7. Rough hardware list (to be costed)

Flight controller (we have ArduPilot experience), frame, motors and ESCs, battery; Pi 5 or Jetson Orin Nano; depth/ToF camera; fast-shutter splat camera; optical flow and rangefinder as a backup (from Droneye); safety net and prop guards. Training GPU: have (RTX 4070 Ti Super, 16 GB).

## 8. Open questions

1. **Companion computer:** Pi 5 (cheaper, weaker) or Jetson Orin Nano (more capable, pricier, heavier)? Do we already own either?
2. **Positioning (SLAM/VIO) stack:** pick after checking which runs well on the chosen hardware.
3. **Depth camera:** which one, given weight and ROS 2 driver support?
4. **Splat camera:** action-cam module, Pi HQ camera or something else? Rolling or global shutter?
5. **Test space:** where can we legally and safely fly indoors, and how big is it?
6. **Time and budget:** hours per week each, deadline, and spend?
7. **Is the friend's stream big enough?** Built so far: capture-path overlay, photo comparison, top-down view. Still open: a coverage heatmap and side-by-side run comparison.
8. **Ground rover fallback** in case the drone slips?
9. **Do we still want this project,** or one of the alternatives we discussed?

Decided: splat framework is COLMAP 4 + gsplat (not nerfstudio), trained on the RTX 4070 Ti Super; see the [pipeline brief](gaussian-scanning/BRIEF.md).

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

For developers (running the pipeline steps by hand, tests, code layout), see
[`gaussian-scanning/README.md`](gaussian-scanning/README.md).
