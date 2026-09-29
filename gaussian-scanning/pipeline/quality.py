"""Capture-quality checks: what the pipeline can measure about a capture
(frame sharpness, the recovered camera poses) turned into structured issues,
a verdict for the reconstruction, and the frames to leave out of training.

Principles (see ../BRIEF.md section 3b): a missing area beats a garbled room,
so frames whose poses look wrong are left out rather than trained on; every
issue says where (video time ranges) and what to do; only actionable things
are warnings, the rest is info.

An issue is a plain dict so it travels unchanged through the stage protocol
into the run record and the UI:

    kind      "unplaced" | "split" | "bad_poses" | "few_placed" | "blur"
    severity  "info" (nothing to do) | "warning" (the splat is affected) |
              "error" (the reconstruction can't be trusted)
    title     one line, plain language
    detail    what was found, with the numbers
    fix       what the user (or the app) does about it
    ranges    [{start, end, first, last, frames}]: video seconds (None for
              photos), first/last frame names, frame count
    frames    total frames involved

Verdict: "good" (no warnings), "gaps" (parts missing or left out, the rest
trustworthy), "unreliable" (too much is wrong to trust any of it).
"""
import numpy as np

Frame = tuple[str, float | None]  # (frame file name, video timestamp or None for photos)

# Pose checks, calibrated on handheld room videos where the splat was visibly
# garbled (global mapper) or clean (incremental): the bad models had 3-13
# neighbouring-frame steps over 8x the median step and frames stacked on one
# spot while turning; the good ones had neither (largest step 5x median).
JUMP_FACTOR = 8.0  # a step this many times the median step between neighbouring frames
STACK_FACTOR = 0.05  # ...or this small, while the view turns by more than STACK_MIN_TURN_DEG
STACK_MIN_TURN_DEG = 2.0
FLIP_MIN_DEG = 45.0  # a turn this large between neighbouring frames, faster than FLIP_DEG_PER_SEC
FLIP_DEG_PER_SEC = 180.0
MIN_GAP_FRAMES = 3  # report runs of this many consecutive unplaced frames (photos)
MIN_GAP_SEC = 1.0  # ...or, for video, stretches leaving this much of it without a placed frame
MIN_SPLIT_FRAMES = 5  # a split matters when the other pieces hold this many frames (and 3% of the capture)

# Verdict. Leaving frames out only helps when the damage is local: in every
# garbled reconstruction the flags were spread over the whole capture (14/77,
# 15/147, 16/304 frames), while the good ones had none.
PLACE_MERGE_SEC = 2.0  # flagged stretches closer than this count as one place
UNRELIABLE_PLACES = 3
UNRELIABLE_FLAGGED_FRACTION = 0.05
UNRELIABLE_MODEL_FRACTION = 0.7  # largest piece of a split scene, as a fraction of all frames
UNRELIABLE_PLACED_FRACTION = 0.5

# Blur: frames under this fraction of the median sharpness, merged when less
# than MERGE_SEC apart, reported when the stretch lasts MIN_SEC or more. On a
# handheld room video the stretch SfM could not place scored 13-35% of the median.
BLUR_FRACTION = 0.35
BLUR_MERGE_SEC = 1.5
BLUR_MIN_SEC = 1.5

VERDICT_RANK = {"good": 0, "gaps": 1, "unreliable": 2}


def runs(indices) -> list[tuple[int, int]]:
    """Consecutive integers grouped into (first, last) runs."""
    out: list[tuple[int, int]] = []
    for i in sorted(indices):
        if out and i == out[-1][1] + 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


def span(frames: list[Frame], a: int, b: int) -> dict:
    a, b = int(a), int(b)  # indices often come from numpy, which JSON can't encode
    return {"start": frames[a][1], "end": frames[b][1], "first": frames[a][0], "last": frames[b][0], "frames": b - a + 1}


def label(r: dict) -> str:
    if r["start"] is not None:
        return f"{r['start']:.1f} s" if r["first"] == r["last"] else f"{r['start']:.1f}-{r['end']:.1f} s"
    return r["first"] if r["first"] == r["last"] else f"{r['first']} to {r['last']}"


def where(ranges: list[dict], limit: int = 4) -> str:
    """'1.5 s, 3.0-4.5 s and 2 more'."""
    labels = [label(r) for r in ranges]
    shown = ", ".join(labels[:limit])
    return f"{shown} and {len(labels) - limit} more" if len(labels) > limit else shown


def issue(kind: str, severity: str, title: str, detail: str, fix: str, ranges: list[dict] | None = None) -> dict:
    ranges = ranges or []
    return {"kind": kind, "severity": severity, "title": title, "detail": detail, "fix": fix,
            "ranges": ranges, "frames": sum(r["frames"] for r in ranges)}


# --- blur (frames stage) ---

def blur_ranges(frames: list[Frame], sharpness: list[float]) -> list[dict]:
    """Long stretches of video far less sharp than its median frame."""
    if len(frames) < 10 or any(t is None for _, t in frames):
        return []
    s = np.asarray(sharpness, float)
    median = float(np.median(s))
    stretches: list[list[int]] = []
    for i in np.flatnonzero(s < BLUR_FRACTION * median):
        if stretches and frames[i][1] - frames[stretches[-1][1]][1] <= BLUR_MERGE_SEC:
            stretches[-1][1] = i
        else:
            stretches.append([i, i])
    return [span(frames, a, b) for a, b in stretches if frames[b][1] - frames[a][1] >= BLUR_MIN_SEC]


def blur_issues(frames: list[Frame], sharpness: list[float]) -> list[dict]:
    ranges = blur_ranges(frames, sharpness)
    if not ranges:
        return []
    return [issue(
        "blur", "info", "Blurry or plain stretches of video",
        f"Much less sharp than the rest of the video at {where(ranges)}: motion blur, or plain surfaces like a blank wall.",
        "Nothing to do unless camera poses fail there; then refilm those moments more slowly.",
        ranges,
    )]


# --- camera poses (SfM stage) ---

def _overlaps(r: dict, others: list[dict]) -> bool:
    return r["start"] is not None and any(o["start"] <= r["end"] and r["start"] <= o["end"] for o in others)


def check_poses(
    frames: list[Frame],
    c2w: dict[str, np.ndarray],
    model_sizes: list[int],
    mapper: str,
    blurry: list[dict] | None = None,
) -> tuple[list[dict], str, list[str]]:
    """Issues, verdict and the frames to leave out of training.

    frames: every frame in capture order. c2w: camera-to-world 4x4 of each
    frame in the model being used (the largest). model_sizes: frames in each
    model COLMAP produced, largest first. blurry: blur ranges, used to explain
    failures. The neighbouring-frame checks only run for video, where
    consecutive frames really are close together in time and space.
    """
    blurry = blurry or []
    n = len(frames)
    issues: list[dict] = []
    unreliable = False

    def cause(ranges: list[dict]) -> str:
        return " The footage is blurry or plain there." if any(_overlaps(r, blurry) for r in ranges) else ""

    placed = sum(1 for name, _ in frames if name in c2w)
    if placed < UNRELIABLE_PLACED_FRACTION * n:
        unreliable = True
        issues.append(issue(
            "few_placed", "error", "Most of the capture couldn't be placed",
            f"Only {placed} of {n} frames could be placed.",
            "Refilm more slowly, with more overlap between views and fewer blank surfaces.",
        ))

    # Incremental mapping sometimes leaves a small duplicate model of frames the
    # main one also has, or a stray piece of 2-3 frames: that only matters if
    # the model used is missing frames and the rest amounts to something (the
    # unplaced check already covers a few stray frames).
    if len(model_sizes) > 1 and placed < n and sum(model_sizes[1:]) >= max(MIN_SPLIT_FRAMES, 0.03 * n):
        severe = model_sizes[0] < UNRELIABLE_MODEL_FRACTION * n
        unreliable |= severe
        issues.append(issue(
            "split", "error" if severe else "warning", "The capture split into separate pieces",
            f"COLMAP could not connect everything into one scene: {len(model_sizes)} pieces "
            f"({', '.join(map(str, model_sizes))} frames); only the largest is used.",
            "The pieces usually meet at blurry or blank moments; refilm those more slowly.",
        ))

    def uncovered(a: int, b: int) -> float | None:
        """Seconds of video between the placed frames either side of a..b."""
        if frames[a][1] is None:
            return None
        return frames[min(b + 1, n - 1)][1] - frames[max(a - 1, 0)][1]

    # For video, judge a gap by how much time it leaves uncovered: after the
    # retry's denser frames, 3 unplaced frames can be a 0.1 s sliver.
    gaps = [span(frames, a, b) for a, b in runs(i for i, (name, _) in enumerate(frames) if name not in c2w)
            if (uncovered(a, b) >= MIN_GAP_SEC if frames[a][1] is not None else b - a + 1 >= MIN_GAP_FRAMES)]
    if gaps:
        issues.append(issue(
            "unplaced", "warning", "Parts of the capture couldn't be placed",
            f"{sum(g['frames'] for g in gaps)} frames at {where(gaps)} have no camera position, "
            f"so the splat will be missing or thin there.{cause(gaps)}",
            "Refilm those moments more slowly.",
            gaps,
        ))

    excluded: list[str] = []
    video = all(t is not None for _, t in frames)
    pairs = [(k, k + 1) for k in range(n - 1) if frames[k][0] in c2w and frames[k + 1][0] in c2w]
    if video and len(pairs) >= 10:
        steps, turns, dts = [], [], []
        for a, b in pairs:
            A, B = c2w[frames[a][0]], c2w[frames[b][0]]
            steps.append(np.linalg.norm(B[:3, 3] - A[:3, 3]))
            cos = (np.trace(A[:3, :3].T @ B[:3, :3]) - 1) / 2
            turns.append(np.degrees(np.arccos(np.clip(cos, -1, 1))))
            dts.append(max(frames[b][1] - frames[a][1], 1e-3))
        steps, turns, dts = map(np.array, (steps, turns, dts))
        median = float(np.median(steps))
        if median > 0:
            checks = {
                "jumps": steps > JUMP_FACTOR * median,
                "stacked": (steps < STACK_FACTOR * median) & (turns > STACK_MIN_TURN_DEG),
                "flips": (turns > FLIP_MIN_DEG) & (turns / dts > FLIP_DEG_PER_SEC),
            }
            flagged: set[int] = set()
            for mask in checks.values():
                for k in np.flatnonzero(mask):
                    flagged.update(pairs[k])  # both ends: which one is wrong can't be told
            if flagged:
                ranges = [span(frames, a, b) for a, b in runs(flagged)]
                places = 1
                for prev, r in zip(ranges, ranges[1:]):
                    places += r["start"] - prev["end"] > PLACE_MERGE_SEC
                severe = places >= UNRELIABLE_PLACES or len(flagged) > UNRELIABLE_FLAGGED_FRACTION * n
                unreliable |= severe
                excluded = [frames[i][0] for i in sorted(flagged)]
                counts = [f"{int(m.sum())} {k}" for k, m in checks.items() if m.any()]
                better = " The incremental mapper usually gets these right." if mapper == "global" else ""
                issues.append(issue(
                    "bad_poses", "error" if severe else "warning", "Camera positions look wrong",
                    f"Impossible camera motion between neighbouring frames ({', '.join(counts)}) at "
                    f"{where(ranges)}.{cause(ranges)}"
                    + (" Spread over the capture like this, the other positions can't be trusted either." if severe else ""),
                    f"Those {len(flagged)} frames are left out of training.{better} If the splat is still wrong "
                    "there, refilm those moments more slowly.",
                    ranges,
                ))

    if unreliable:
        verdict = "unreliable"
    elif any(i["severity"] != "info" for i in issues):
        verdict = "gaps"
    else:
        verdict = "good"
    return issues, verdict, excluded
