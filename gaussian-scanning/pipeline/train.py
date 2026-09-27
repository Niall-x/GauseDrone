"""Stage 3: train a 3D Gaussian splat with gsplat.

A compact version of gsplat's reference trainer (examples/simple_trainer.py):
3DGS densification via gsplat's DefaultStrategy, L1 + SSIM loss, spherical
harmonics raised one degree every 1000 steps. The scene is trained in
COLMAP's own coordinate frame (no re-normalisation), so any later alignment
(metric scale, VIO trajectory, a room's reference frame) applies to the
exported splat directly.

With --holdout-every N, every Nth frame is left out of training and used to
report PSNR/SSIM on views the model never saw; the standard quality check.

Writes <run>/train/splats.pt and <run>/train/stats.json.
"""
import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from gsplat import DefaultStrategy, rasterization

from pipeline.colmap_io import read_model
from pipeline.common import RunPaths, fresh_dir, progress, result

SH_C0 = 0.28209479177387814


def ssim(img1: torch.Tensor, img2: torch.Tensor) -> torch.Tensor:
    """Mean SSIM of two [1,3,H,W] images in [0,1] (11x11 Gaussian window, sigma 1.5)."""
    g = torch.exp(-((torch.arange(11, device=img1.device) - 5) ** 2) / (2 * 1.5**2))
    g = (g / g.sum()).float()
    win = (g[:, None] @ g[None, :]).expand(3, 1, 11, 11).contiguous()
    conv = lambda x: F.conv2d(x, win, padding=5, groups=3)  # noqa: E731
    mu1, mu2 = conv(img1), conv(img2)
    s11 = conv(img1 * img1) - mu1**2
    s22 = conv(img2 * img2) - mu2**2
    s12 = conv(img1 * img2) - mu1 * mu2
    c1, c2 = 0.01**2, 0.03**2
    return (((2 * mu1 * mu2 + c1) * (2 * s12 + c2)) / ((mu1**2 + mu2**2 + c1) * (s11 + s22 + c2))).mean()


def psnr(a: torch.Tensor, b: torch.Tensor) -> float:
    return float(-10 * torch.log10(F.mse_loss(a, b)))


def knn_mean_dist(points: torch.Tensor, k: int = 3, chunk: int = 4096) -> torch.Tensor:
    """Mean distance from each point to its k nearest neighbours (for initial Gaussian size)."""
    out = torch.empty(len(points), device=points.device)
    for i in range(0, len(points), chunk):
        d = torch.cdist(points[i : i + chunk], points)
        out[i : i + chunk] = d.topk(k + 1, largest=False).values[:, 1:].mean(1)
    return out


class Frames:
    """Training images kept as uint8 on the CPU, moved to the GPU one at a time."""

    def __init__(self, image_dir: Path, cameras, images):
        self.names, self.viewmats, self.Ks, self.pixels = [], [], [], []
        for im in images:
            cam = cameras[im.camera_id]
            bgr = cv2.imread(str(image_dir / im.name))
            if bgr is None:
                raise SystemExit(f"missing undistorted image {im.name}")
            if bgr.shape[:2] != (cam.height, cam.width):
                bgr = cv2.resize(bgr, (cam.width, cam.height), interpolation=cv2.INTER_AREA)
            self.names.append(im.name)
            self.viewmats.append(torch.tensor(im.world_to_cam, dtype=torch.float32))
            self.Ks.append(torch.tensor(cam.K, dtype=torch.float32))
            self.pixels.append(torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).pin_memory())

    def __len__(self):
        return len(self.names)

    def get(self, i: int, device="cuda"):
        img = self.pixels[i].to(device, non_blocking=True).float() / 255.0
        return img, self.viewmats[i].to(device), self.Ks[i].to(device)


def render(splats, viewmat, K, width, height, sh_degree, packed=False):
    colors = torch.cat([splats["sh0"], splats["shN"]], 1)
    return rasterization(
        means=splats["means"],
        quats=splats["quats"],
        scales=torch.exp(splats["scales"]),
        opacities=torch.sigmoid(splats["opacities"]),
        colors=colors,
        viewmats=viewmat[None],
        Ks=K[None],
        width=width,
        height=height,
        sh_degree=sh_degree,
        packed=packed,
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--iterations", type=int, default=30_000)
    p.add_argument("--sh-degree", type=int, default=3, choices=[0, 1, 2, 3])
    p.add_argument("--holdout-every", type=int, default=0, help="hold out every Nth frame for evaluation (0 = train on all)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    dev = "cuda"
    paths = RunPaths(args.run_dir)
    out = fresh_dir(paths.train)

    cameras, images, (xyz, rgb, _) = read_model(paths.sparse_txt)
    if len(xyz) == 0:
        raise SystemExit("sparse model has no points to initialise from")
    progress(0.0, f"loading {len(images)} frames")
    frames = Frames(paths.undistorted / "images", cameras, images)
    all_ids = list(range(len(frames)))
    if args.holdout_every > 0:
        test_ids = all_ids[:: args.holdout_every]
        train_ids = [i for i in all_ids if i not in set(test_ids)]
    else:
        test_ids, train_ids = [], all_ids

    centers = np.stack([im.cam_to_world[:3, 3] for im in images])
    scene_scale = float(np.linalg.norm(centers - centers.mean(0), axis=1).max()) * 1.1
    scene_scale = max(scene_scale, 1e-3)

    # --- initialise Gaussians from the sparse point cloud ---
    pts = torch.tensor(xyz, device=dev)
    n = len(pts)
    dist = knn_mean_dist(pts).clamp_min(1e-7)
    K_sh = (args.sh_degree + 1) ** 2
    sh0 = ((torch.tensor(rgb, device=dev).float() / 255.0 - 0.5) / SH_C0)[:, None, :]
    splats = torch.nn.ParameterDict({
        "means": torch.nn.Parameter(pts),
        "scales": torch.nn.Parameter(torch.log(dist)[:, None].repeat(1, 3)),
        "quats": torch.nn.Parameter(F.normalize(torch.rand(n, 4, device=dev), dim=-1)),
        "opacities": torch.nn.Parameter(torch.logit(torch.full((n,), 0.1, device=dev))),
        "sh0": torch.nn.Parameter(sh0),
        "shN": torch.nn.Parameter(torch.zeros(n, K_sh - 1, 3, device=dev)),
    })
    lrs = {
        "means": 1.6e-4 * scene_scale,
        "scales": 5e-3,
        "quats": 1e-3,
        "opacities": 5e-2,
        "sh0": 2.5e-3,
        "shN": 2.5e-3 / 20,
    }
    optimizers = {k: torch.optim.Adam([{"params": splats[k], "lr": lr, "name": k}], eps=1e-15) for k, lr in lrs.items()}
    means_sched = torch.optim.lr_scheduler.ExponentialLR(optimizers["means"], gamma=0.01 ** (1.0 / args.iterations))

    # Standard 3DGS schedule is tuned for 30k steps; shorten the densification
    # window proportionally for quicker runs.
    frac = min(1.0, args.iterations / 30_000)
    strategy = DefaultStrategy(refine_stop_iter=int(15_000 * frac), reset_every=3000, refine_every=100)
    strategy.check_sanity(splats, optimizers)
    strategy_state = strategy.initialize_state(scene_scale=scene_scale)

    print(f"{len(train_ids)} train / {len(test_ids)} held-out frames, {n} initial Gaussians, scene scale {scene_scale:.3f}")
    t0 = time.monotonic()
    order = []
    loss_log = []
    ema = None
    for step in range(args.iterations):
        if not order:
            order = list(np.random.permutation(train_ids))
        idx = order.pop()
        gt, viewmat, K = frames.get(idx)
        h, w = gt.shape[:2]
        sh_degree = min(step // 1000, args.sh_degree)

        renders, _, info = render(splats, viewmat, K, w, h, sh_degree)
        pred = renders[0]
        strategy.step_pre_backward(splats, optimizers, strategy_state, step, info)
        l1 = F.l1_loss(pred, gt)
        ssim_loss = 1.0 - ssim(pred.permute(2, 0, 1)[None], gt.permute(2, 0, 1)[None])
        loss = 0.8 * l1 + 0.2 * ssim_loss
        loss.backward()

        for opt in optimizers.values():
            opt.step()
            opt.zero_grad(set_to_none=True)
        means_sched.step()
        strategy.step_post_backward(splats, optimizers, strategy_state, step, info, packed=False)

        if step % 10 == 0:  # .item() syncs the GPU; don't do it every step
            ema = float(loss) if ema is None else 0.7 * ema + 0.3 * float(loss)
        if step % 100 == 0 or step == args.iterations - 1:
            elapsed = time.monotonic() - t0
            rate = (step + 1) / max(elapsed, 1e-6)
            eta = (args.iterations - step - 1) / rate
            loss_log.append([step, round(ema, 5), len(splats["means"])])
            progress(
                (step + 1) / args.iterations,
                f"step {step + 1}/{args.iterations}  loss {ema:.4f}  {len(splats['means']):,} Gaussians  "
                f"{rate:.0f} it/s  ETA {int(eta // 60)}m{int(eta % 60):02d}s",
            )

    train_seconds = time.monotonic() - t0

    # --- evaluation ---
    metrics = {}
    with torch.no_grad():
        for label, ids in (("test", test_ids), ("train", train_ids[:: max(1, len(train_ids) // 20)])):
            if not ids:
                continue
            ps, ss = [], []
            for i in ids:
                gt, viewmat, K = frames.get(i)
                pred = render(splats, viewmat, K, gt.shape[1], gt.shape[0], args.sh_degree)[0][0].clamp(0, 1)
                ps.append(psnr(pred, gt))
                ss.append(float(ssim(pred.permute(2, 0, 1)[None], gt.permute(2, 0, 1)[None])))
            metrics[f"{label}_psnr"] = round(float(np.mean(ps)), 3)
            metrics[f"{label}_ssim"] = round(float(np.mean(ss)), 4)
            metrics[f"{label}_views"] = len(ids)

    torch.save(
        {
            "splats": {k: v.detach().cpu() for k, v in splats.items()},
            "sh_degree": args.sh_degree,
            "iterations": args.iterations,
        },
        paths.checkpoint,
    )
    stats = {
        "iterations": args.iterations,
        "num_gaussians": len(splats["means"]),
        "train_seconds": round(train_seconds, 1),
        "peak_gpu_mem_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
        "scene_scale": scene_scale,
        "held_out_frames": [frames.names[i] for i in test_ids],
        "loss_curve": loss_log,
        **metrics,
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps({k: v for k, v in stats.items() if k not in ("loss_curve", "held_out_frames")}, indent=2))
    result(**{k: v for k, v in stats.items() if k not in ("loss_curve", "held_out_frames")})


if __name__ == "__main__":
    main()
