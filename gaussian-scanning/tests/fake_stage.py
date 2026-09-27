"""Stand-in pipeline stage for the server tests: writes a marker file, reports
progress/results using the real protocol, optionally sleeps or fails."""
import argparse
import time
from pathlib import Path

from pipeline.common import progress, result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--input", type=Path)
    p.add_argument("--name", required=True)
    p.add_argument("--value", type=int, default=1)
    p.add_argument("--sleep", type=float, default=0.0)
    p.add_argument("--fail", type=int, default=0)
    args = p.parse_args()

    out = args.run_dir / args.name
    out.mkdir(parents=True, exist_ok=True)
    progress(0.5, "halfway")
    print("some ordinary log output")
    time.sleep(args.sleep)
    if args.fail:
        raise SystemExit("fake stage failed on purpose")
    (out / "marker.txt").write_text(f"value={args.value}")
    progress(1.0, "done")
    result(value=args.value, had_input=args.input is not None)


if __name__ == "__main__":
    main()
