"""Stage 4: export the trained splat for viewing.

- splat.ply   standard 3DGS PLY (full precision; opens in SuperSplat, Blender
              add-ons, other viewers)
- splat.spz   Niantic SPZ v2 (quantised + gzipped, ~10x smaller); what the
              web viewer loads
- view.json   camera trajectory, an estimated "up" direction and a start
              view, so the viewer can orient the scene sensibly (COLMAP's
              world frame has no inherent up or origin)

All three share the training (COLMAP) coordinate frame.
"""
import argparse
import gzip
import json
import struct
from pathlib import Path

import numpy as np
import torch

from pipeline.colmap_io import read_model
from pipeline.common import RunPaths, fresh_dir, progress, result


def write_ply(path: Path, s: dict[str, np.ndarray]) -> None:
    n = len(s["means"])
    # PLY stores the higher-order SH channel-major: all R coefficients, then G, then B.
    f_rest = s["shN"].transpose(0, 2, 1).reshape(n, -1)
    cols = [
        ("x", s["means"][:, 0]), ("y", s["means"][:, 1]), ("z", s["means"][:, 2]),
        ("nx", np.zeros(n)), ("ny", np.zeros(n)), ("nz", np.zeros(n)),
        *[(f"f_dc_{i}", s["sh0"][:, 0, i]) for i in range(3)],
        *[(f"f_rest_{i}", f_rest[:, i]) for i in range(f_rest.shape[1])],
        ("opacity", s["opacities"]),
        *[(f"scale_{i}", s["scales"][:, i]) for i in range(3)],
        *[(f"rot_{i}", s["quats"][:, i]) for i in range(4)],
    ]
    data = np.stack([c for _, c in cols], axis=1).astype("<f4")
    header = "ply\nformat binary_little_endian 1.0\n" f"element vertex {n}\n"
    header += "".join(f"property float {name}\n" for name, _ in cols) + "end_header\n"
    with open(path, "wb") as fh:
        fh.write(header.encode())
        fh.write(data.tobytes())


def write_spz(path: Path, s: dict[str, np.ndarray], sh_degree: int) -> None:
    """SPZ v2 (https://github.com/nianticlabs/spz), same axes as the PLY."""
    n = len(s["means"])
    means = s["means"].astype(np.float64)
    extent = max(float(np.abs(means).max()), 1e-6)
    frac_bits = int(np.clip(np.floor(23 - np.log2(extent)) - 1, 0, 20))

    fixed = np.round(means * (1 << frac_bits)).astype(np.int64).reshape(-1)
    fixed = np.clip(fixed, -(1 << 23), (1 << 23) - 1) & 0xFFFFFF
    positions = np.stack([fixed & 0xFF, (fixed >> 8) & 0xFF, (fixed >> 16) & 0xFF], 1).astype(np.uint8)

    u8 = lambda x: np.clip(np.round(x), 0, 255).astype(np.uint8)  # noqa: E731
    alphas = u8(1 / (1 + np.exp(-s["opacities"])) * 255)
    colors = u8((s["sh0"][:, 0, :] * 0.15 + 0.5) * 255)
    scales = u8((s["scales"] + 10.0) * 16.0)

    q = s["quats"] / np.linalg.norm(s["quats"], axis=1, keepdims=True)  # w, x, y, z
    q = q * np.where(q[:, :1] < 0, -1.0, 1.0)
    rotations = u8(q[:, 1:] * 127.5 + 127.5)

    parts = [positions.tobytes(), alphas.tobytes(), colors.tobytes(), scales.tobytes(), rotations.tobytes()]
    if sh_degree > 0:
        k = (sh_degree + 1) ** 2 - 1
        sh = s["shN"][:, :k, :] * 128.0 + 128.0
        # Same bucketing as the reference encoder: 5 bits for degree 1, 4 for higher.
        step = np.ones((k, 1))
        step[:3] = 1 << 3
        step[3:] = 1 << 4
        sh = np.round(sh / step) * step
        parts.append(u8(np.minimum(sh, 255)).tobytes())

    header = struct.pack("<IIIBBBB", 0x5053474E, 2, n, sh_degree, frac_bits, 0, 0)
    with gzip.open(path, "wb", compresslevel=6) as fh:
        fh.write(header)
        for p in parts:
            fh.write(p)


def view_info(model_dir: Path) -> dict:
    cameras, images, (xyz, _, _) = read_model(model_dir)
    c2w = np.stack([im.cam_to_world for im in images])
    centers = c2w[:, :3, 3]
    # OpenCV cameras look down +z with +y pointing down the image, so the
    # average of -y over all frames is a good guess at world "up" for a
    # handheld or drone capture (cameras are rarely held upside down).
    up = -c2w[:, :3, 1].mean(0)
    up /= np.linalg.norm(up)
    cam0 = images[0]
    K = cameras[cam0.camera_id].K
    fov_y = 2 * np.degrees(np.arctan(cameras[cam0.camera_id].height / (2 * K[1, 1])))
    # Robust bounds of the sparse cloud: ignore the far 2% of points (sky, outliers).
    lo, hi = (np.percentile(xyz, [2, 98], axis=0) if len(xyz) else (centers.min(0), centers.max(0)))
    return {
        "frame": "colmap",
        "up": up.round(6).tolist(),
        "center": centers.mean(0).round(6).tolist(),
        "bounds": [lo.round(4).tolist(), hi.round(4).tolist()],
        "fov_y_deg": round(float(fov_y), 2),
        "cameras": [
            {
                "name": im.name,
                "position": c[:3, 3].round(5).tolist(),
                "forward": c[:3, 2].round(5).tolist(),
                "up": (-c[:3, 1]).round(5).tolist(),
            }
            for im, c in zip(images, c2w)
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--min-opacity", type=float, default=0.005, help="drop near-invisible Gaussians")
    args = p.parse_args()

    paths = RunPaths(args.run_dir)
    out = fresh_dir(paths.export)
    ckpt = torch.load(paths.checkpoint, map_location="cpu", weights_only=True)
    s = {k: v.numpy().astype(np.float32) for k, v in ckpt["splats"].items()}
    sh_degree = ckpt["sh_degree"]

    keep = 1 / (1 + np.exp(-s["opacities"])) >= args.min_opacity
    s = {k: v[keep] for k, v in s.items()}
    n = len(s["means"])
    progress(0.1, f"writing PLY ({n:,} Gaussians)")
    write_ply(out / "splat.ply", s)
    progress(0.6, "writing SPZ")
    write_spz(out / "splat.spz", s, sh_degree)
    progress(0.9, "writing view.json")
    (out / "view.json").write_text(json.dumps(view_info(paths.sparse_txt)))

    progress(1.0, "exported")
    result(
        exported_gaussians=n,
        ply_mb=round((out / "splat.ply").stat().st_size / 1e6, 1),
        spz_mb=round((out / "splat.spz").stat().st_size / 1e6, 1),
        viewer_file="export/splat.spz",
    )


if __name__ == "__main__":
    main()
