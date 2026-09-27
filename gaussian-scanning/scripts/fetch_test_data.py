#!/usr/bin/env python3
"""Fetch one scene of the Mip-NeRF 360 dataset as a test capture.

The official archive is a single 12.5 GB zip. Rather than download all of it,
this reads the zip's central directory over HTTP range requests and pulls only
the files for one scene/resolution (e.g. room/images_4, ~300 photos).

    python scripts/fetch_test_data.py                   # room, images_4
    python scripts/fetch_test_data.py --scene counter --res images_2
"""
import argparse
import io
import urllib.request
import zipfile
from pathlib import Path

URL = "http://storage.googleapis.com/gresearch/refraw360/360_v2.zip"


class HttpRangeFile(io.RawIOBase):
    """Minimal seekable read-only file over HTTP range requests."""

    def __init__(self, url: str):
        self.url = url
        self.pos = 0
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req) as r:
            self.size = int(r.headers["Content-Length"])

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence]
        self.pos = base + offset
        return self.pos

    def readinto(self, buf):
        n = min(len(buf), self.size - self.pos)
        if n <= 0:
            return 0
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{self.pos + n - 1}"})
        with urllib.request.urlopen(req) as r:
            data = r.read()
        buf[: len(data)] = data
        self.pos += len(data)
        return len(data)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scene", default="room")
    p.add_argument("--res", default="images_4", help="images, images_2, images_4 or images_8")
    p.add_argument("--out", type=Path, default=Path("data/test"))
    args = p.parse_args()

    out_dir = args.out / f"mipnerf360_{args.scene}" / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Buffered so zipfile's many small reads of local headers don't each cost a request.
    remote = io.BufferedReader(HttpRangeFile(URL), buffer_size=1 << 20)
    with zipfile.ZipFile(remote) as zf:
        prefix = f"{args.scene}/{args.res}/"
        members = [m for m in zf.infolist() if m.filename.startswith(prefix) and not m.is_dir()]
        if not members:
            raise SystemExit(f"nothing under {prefix} in the archive")
        print(f"fetching {len(members)} files ({sum(m.compress_size for m in members) / 1e6:.0f} MB) -> {out_dir}")
        for i, m in enumerate(members, 1):
            target = out_dir / Path(m.filename).name
            if target.exists() and target.stat().st_size == m.file_size:
                continue
            target.write_bytes(zf.read(m))
            if i % 25 == 0 or i == len(members):
                print(f"  {i}/{len(members)}")
    print("done")


if __name__ == "__main__":
    main()
