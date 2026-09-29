# Autonomous Gaussian Splatting Drone: Project Brief (DRAFT v0.3)

Status: the drone side is still a proposal to argue about. **M1 (splat pipeline, no drone) is built**: see section 5a, and [`gaussian-scanning/README.md`](gaussian-scanning/README.md) to run it. Open questions are at the end.

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

## 9. Currently working on

Niall: app to generate and view scans is in a good place. will start reconstructing the done. wiring is done, need to reprogram and calibrate ardupilot and test raspberry pi 4B acting as a coprocessor giving instructions. wont implement any sensors beyond what was used in thesis

---
