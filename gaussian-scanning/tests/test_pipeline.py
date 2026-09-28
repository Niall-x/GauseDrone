"""Unit tests for pipeline pieces that don't need COLMAP or a GPU."""
import gzip
import struct

import numpy as np

from pipeline.colmap_io import read_model
from pipeline.export import estimate_up, write_ply, write_spz


def rot(axis, deg):
    a = np.radians(deg)
    x, y, z = np.asarray(axis, float) / np.linalg.norm(axis)
    K = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K


def camera_poses(world_up, yaws, pitch_deg):
    """c2w matrices of level (no-roll) OpenCV cameras, pitched down by pitch_deg."""
    # A frame whose z is world_up; OpenCV camera looking along +x_w, level: x_c = -y_w, y_c = -z_w, z_c = x_w
    up = world_up / np.linalg.norm(world_up)
    a = np.cross(up, [1, 0, 0]) if abs(up[0]) < 0.9 else np.cross(up, [0, 1, 0])
    a /= np.linalg.norm(a)
    b = np.cross(up, a)
    W = np.stack([a, b, up], 1)  # world basis columns
    base = np.stack([[0, -1, 0], [0, 0, -1], [1, 0, 0]], 1).astype(float)  # camera axes in W-frame
    out = []
    for yaw in yaws:
        R = rot([0, 0, 1], yaw) @ rot([0, 1, 0], pitch_deg) @ base
        c2w = np.eye(4)
        c2w[:3, :3] = W @ R
        out.append(c2w)
    return np.stack(out)


def angle(a, b):
    return np.degrees(np.arccos(np.clip(a @ b / np.linalg.norm(a) / np.linalg.norm(b), -1, 1)))


def test_estimate_up_room_scan():
    true_up = np.array([0.3, -0.8, 0.52])
    c2w = camera_poses(true_up, yaws=np.linspace(0, 360, 60, endpoint=False), pitch_deg=20)
    assert angle(estimate_up(c2w), true_up) < 0.5


def test_estimate_up_one_way_pitched_flight():
    # A drone flying one way with its camera pitched 35 degrees down: averaging
    # camera up vectors would be off by ~35 degrees; the x-axis method isn't.
    true_up = np.array([0.0, 0.0, 1.0])
    c2w = camera_poses(true_up, yaws=np.linspace(-40, 40, 30), pitch_deg=35)
    mean_up = -c2w[:, :3, 1].mean(0)
    assert angle(mean_up, true_up) > 25
    assert angle(estimate_up(c2w), true_up) < 0.5


def test_estimate_up_degenerate_falls_back():
    c2w = camera_poses(np.array([0, 0, 1.0]), yaws=[10] * 5, pitch_deg=0)
    up = estimate_up(c2w)
    assert np.isclose(np.linalg.norm(up), 1) and angle(up, [0, 0, 1]) < 1


def random_splats(n=500, sh_degree=3, seed=0):
    g = np.random.default_rng(seed)
    k = (sh_degree + 1) ** 2 - 1
    return {
        "means": g.uniform(-5, 5, (n, 3)).astype(np.float32),
        "scales": g.uniform(-6, -1, (n, 3)).astype(np.float32),
        "quats": g.normal(size=(n, 4)).astype(np.float32),
        "opacities": g.normal(size=n).astype(np.float32),
        "sh0": g.normal(scale=0.8, size=(n, 1, 3)).astype(np.float32),
        "shN": g.normal(scale=0.2, size=(n, k, 3)).astype(np.float32),
    }


def read_spz(path):
    data = gzip.decompress(path.read_bytes())
    magic, version, n, sh_degree, frac_bits, _, _ = struct.unpack("<IIIBBBB", data[:16])
    assert magic == 0x5053474E and version == 2
    off = 16
    pos = np.frombuffer(data, np.uint8, n * 9, off).reshape(n, 3, 3).astype(np.int32)
    off += n * 9
    fixed = pos[..., 0] | (pos[..., 1] << 8) | (pos[..., 2] << 16)
    fixed = np.where(fixed & 0x800000, fixed - (1 << 24), fixed)
    means = fixed / (1 << frac_bits)
    alpha = np.frombuffer(data, np.uint8, n, off) / 255.0
    off += n
    colors = np.frombuffer(data, np.uint8, n * 3, off).reshape(n, 3)
    off += n * 3
    scales = np.frombuffer(data, np.uint8, n * 3, off).reshape(n, 3) / 16.0 - 10
    off += n * 3
    xyz = (np.frombuffer(data, np.uint8, n * 3, off).reshape(n, 3) - 127.5) / 127.5
    off += n * 3
    k = (sh_degree + 1) ** 2 - 1
    assert len(data) == off + n * k * 3
    w = np.sqrt(np.clip(1 - (xyz**2).sum(1), 0, 1))
    return n, sh_degree, means, alpha, colors, scales, np.column_stack([w, xyz])


def test_spz_roundtrip(tmp_path):
    s = random_splats()
    write_spz(tmp_path / "s.spz", s, sh_degree=3)
    n, deg, means, alpha, colors, scales, quats = read_spz(tmp_path / "s.spz")
    assert n == 500 and deg == 3
    assert np.abs(means - s["means"]).max() < 1e-3
    assert np.abs(alpha - 1 / (1 + np.exp(-s["opacities"]))).max() < 0.01
    expected_rgb = np.clip((s["sh0"][:, 0] * 0.15 + 0.5) * 255, 0, 255)
    assert np.abs(colors - expected_rgb).max() <= 1
    assert np.abs(scales - s["scales"]).max() < 0.05
    q = s["quats"] / np.linalg.norm(s["quats"], axis=1, keepdims=True)
    q *= np.sign(q[:, :1])
    assert np.abs(np.abs((quats * q).sum(1)) - 1).max() < 0.03  # same rotation, up to quantisation


def test_ply_header_and_size(tmp_path):
    s = random_splats(n=10)
    write_ply(tmp_path / "s.ply", s)
    raw = (tmp_path / "s.ply").read_bytes()
    header, body = raw.split(b"end_header\n", 1)
    props = [line.split()[-1].decode() for line in header.splitlines() if line.startswith(b"property")]
    assert props[:6] == ["x", "y", "z", "nx", "ny", "nz"]
    assert props[-8:] == ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    assert len(props) == 62  # 3DGS PLY with SH degree 3
    assert len(body) == 10 * 62 * 4
    vals = np.frombuffer(body, "<f4").reshape(10, 62)
    assert np.allclose(vals[:, :3], s["means"])
    # f_rest is channel-major: first 15 values are the red channel of each SH coefficient
    assert np.allclose(vals[:, 9:24], s["shN"][:, :, 0])


def test_read_colmap_text_model(tmp_path):
    (tmp_path / "cameras.txt").write_text("# comment\n1 PINHOLE 640 480 500 510 320 240\n")
    (tmp_path / "images.txt").write_text(
        "# Image list\n"
        "2 1 0 0 0 0 0 5 1 b.jpg\n"
        "\n"  # an image with no 2D points: empty second line must not break pairing
        "1 0.7071068 0 0.7071068 0 1 2 3 1 a.jpg\n"
        "10.0 20.0 -1\n"
    )
    (tmp_path / "points3D.txt").write_text("# pts\n1 0.5 1.5 2.5 255 0 10 0.7 1 0 2 0\n")
    cams, images, (xyz, rgb, err) = read_model(tmp_path)
    assert cams[1].K[0, 0] == 500 and cams[1].K[1, 2] == 240
    assert [im.name for im in images] == ["a.jpg", "b.jpg"]
    a = images[0]
    assert np.allclose(a.world_to_cam[:3, :3], rot([0, 1, 0], 90), atol=1e-6)
    assert np.allclose(a.world_to_cam[:3, 3], [1, 2, 3])
    assert np.allclose(images[1].cam_to_world[:3, 3], [0, 0, -5])
    assert xyz.shape == (1, 3) and rgb.tolist() == [[255, 0, 10]] and np.isclose(err[0], 0.7)


def jpeg_with_orientation(path, h, w, orientation, byte_order="II"):
    """A JPEG of h x w stored pixels carrying an EXIF orientation tag (what phones write)."""
    import cv2

    ok, jpg = cv2.imencode(".jpg", (np.random.default_rng(0).random((h, w, 3)) * 255).astype(np.uint8))
    o = "<" if byte_order == "II" else ">"
    tiff = byte_order.encode() + struct.pack(f"{o}HI", 42, 8) + struct.pack(f"{o}H", 1)
    tiff += struct.pack(f"{o}HHIHH", 0x0112, 3, 1, orientation, 0) + struct.pack(f"{o}I", 0)
    app1 = b"Exif\0\0" + tiff
    raw = jpg.tobytes()
    path.write_bytes(raw[:2] + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + raw[2:])


def test_jpeg_orientation(tmp_path):
    from pipeline.extract_frames import jpeg_orientation

    for order in ("II", "MM"):
        jpeg_with_orientation(tmp_path / f"r{order}.jpg", 20, 30, 6, order)
        assert jpeg_orientation(tmp_path / f"r{order}.jpg") == 6
    import cv2

    cv2.imwrite(str(tmp_path / "plain.jpg"), np.zeros((8, 8, 3), np.uint8))
    assert jpeg_orientation(tmp_path / "plain.jpg") == 1
    (tmp_path / "junk.jpg").write_bytes(b"\xff\xd8\xff\xe1\x00")  # truncated header must not crash
    assert jpeg_orientation(tmp_path / "junk.jpg") == 1


def run_frames(run_dir, src, *args):
    import subprocess
    import sys

    subprocess.run([sys.executable, "-m", "pipeline.extract_frames", "--run-dir", str(run_dir), "--input", str(src), *args],
                   check=True, capture_output=True)


def test_rotated_photos_are_stored_upright(tmp_path):
    """COLMAP ignores EXIF orientation, so a frame must never rely on it."""
    import csv

    import cv2

    src = tmp_path / "photos"
    src.mkdir()
    jpeg_with_orientation(src / "a_rotated.jpg", 200, 300, 6)  # stored landscape, shown portrait
    for i in range(3):
        cv2.imwrite(str(src / f"b{i}.jpg"), np.zeros((300, 200, 3), np.uint8))
    run_frames(tmp_path / "run", src)
    rows = list(csv.DictReader(open(tmp_path / "run" / "frames.csv")))
    for r in rows:
        raw = cv2.imread(str(tmp_path / "run" / "frames" / r["file_name"]), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        assert raw.shape[:2] == (300, 200), r["file_name"]  # the pixels COLMAP sees are upright
        assert (int(r["width"]), int(r["height"])) == (200, 300)  # and match what frames.csv says


def test_rerun_never_rewrites_a_shared_frames_csv(tmp_path):
    """'New run from this' hard-links frames.csv; re-running frames in one run must not change the other."""
    import os

    import cv2

    src = tmp_path / "photos"
    src.mkdir()
    for i in range(3):
        cv2.imwrite(str(src / f"{i}.jpg"), np.zeros((200, 300, 3), np.uint8))
    base, reuse = tmp_path / "base", tmp_path / "reuse"
    run_frames(base, src)
    reuse.mkdir()
    os.link(base / "frames.csv", reuse / "frames.csv")
    before = (base / "frames.csv").read_text()
    run_frames(reuse, src, "--max-size", "100")
    assert (base / "frames.csv").read_text() == before
    assert (reuse / "frames.csv").read_text() != before


def test_knn_handles_tiny_clouds():
    import torch

    from pipeline.train import knn_mean_dist

    for n in (1, 2, 3, 4, 5):
        d = knn_mean_dist(torch.rand(n, 3))
        assert d.shape == (n,) and torch.isfinite(d).all()
    pts = torch.tensor([[0.0, 0, 0], [1, 0, 0], [0, 2, 0], [0, 0, 3], [10, 10, 10]])
    small = knn_mean_dist(pts, max_elements=5)  # one row per chunk
    assert torch.allclose(small, knn_mean_dist(pts))
    assert torch.isclose(small[0], torch.tensor(2.0))  # neighbours at 1, 2, 3
