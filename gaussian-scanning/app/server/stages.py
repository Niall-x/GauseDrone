"""The pipeline as the app sees it: an ordered list of stages, each a CLI in
`pipeline/`, with the parameters the UI may set.

Adding a stage (VIO pose import, metric scale, evaluation...) means writing
the CLI and adding one entry here; the runner, the API and the UI's
"advanced settings" all read from this list.
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass
class Param:
    name: str  # CLI flag without leading dashes, e.g. "max-size"
    label: str
    type: Literal["int", "float", "choice"]
    default: Any
    help: str = ""
    choices: list[Any] | None = None
    min: float | None = None
    max: float | None = None


@dataclass
class Stage:
    name: str
    label: str
    module: str
    description: str
    outputs: list[str]  # paths inside the run dir this stage owns (for reuse between runs)
    params: list[Param] = field(default_factory=list)
    needs_input: bool = False  # gets --input <capture source dir>


STAGES: list[Stage] = [
    Stage(
        name="frames",
        label="Frames",
        module="pipeline.extract_frames",
        description="Pick the sharpest frames from video, or copy and resize photos",
        outputs=["frames", "frames.csv"],
        needs_input=True,
        params=[
            Param("fps", "Frames per second", "float", 4.0,
                  "Video only: frames kept per second of footage. Fewer frames lose track at fast turns and blurry moments", min=0.1, max=30),
            Param("max-size", "Max image size (px)", "int", 1600, "Longest side after resizing (0 keeps full size)", min=0, max=8000),
            Param("blur-reject", "Blur rejection", "float", 0.0,
                  "Drop frames less sharp than this fraction of the median (0 = off). Low-texture views also score low, so use with care", min=0, max=1),
        ],
    ),
    Stage(
        name="sfm",
        label="Camera poses",
        module="pipeline.sfm",
        description="COLMAP structure-from-motion: where each frame was taken from, plus a sparse point cloud; checked for errors",
        outputs=["sfm"],
        needs_input=True,  # the video, for the retry's extra frames
        params=[
            Param("matcher", "Matcher", "choice", "auto",
                  "auto = exhaustive up to 800 frames (finds loop closures), sequential beyond",
                  choices=["auto", "exhaustive", "sequential"]),
            Param("mapper", "Mapper", "choice", "auto",
                  "auto = incremental up to 800 frames, global beyond. Global (GLOMAP) is faster on big captures but "
                  "often gets handheld video wrong (turning on the spot, windows)", choices=["auto", "incremental", "global"]),
            Param("camera-model", "Camera model", "choice", "OPENCV", "Lens model COLMAP fits",
                  choices=["OPENCV", "SIMPLE_RADIAL", "PINHOLE", "OPENCV_FISHEYE"]),
            Param("single-camera", "Single camera", "choice", 1,
                  "1 if every frame came from the same camera at the same zoom", choices=[1, 0]),
            Param("use-gpu", "GPU features + matching", "choice", 1,
                  "1 = SIFT extraction and matching on the GPU (several times faster matching); 0 = CPU", choices=[1, 0]),
            Param("retry", "Automatic retry", "choice", 1,
                  "1 = if the check finds problems, retry once with the incremental mapper and extra frames around them", choices=[1, 0]),
        ],
    ),
    Stage(
        name="train",
        label="Train splat",
        module="pipeline.train",
        description="Fit 3D Gaussians to the frames with gsplat",
        outputs=["train"],
        params=[
            Param("iterations", "Iterations", "int", 30000, "Training steps (7k for a quick look, 30k for full quality)",
                  min=500, max=100000),
            Param("sh-degree", "SH degree", "choice", 3, "View-dependent colour detail (0 = flat colour)", choices=[3, 2, 1, 0]),
            Param("holdout-every", "Hold out every Nth frame", "int", 0,
                  "Leave frames out of training to measure quality on unseen views (0 = off, 8 is standard)", min=0, max=100),
            Param("max-gaussians", "Max Gaussians", "int", 0,
                  "Stop adding detail at this many Gaussians (0 = sized from free GPU memory, so noisy captures can't run it out)",
                  min=0, max=50_000_000),
        ],
    ),
    Stage(
        name="export",
        label="Export",
        module="pipeline.export",
        description="Write PLY + compressed SPZ for the viewer",
        outputs=["export"],
        params=[],
    ),
]

STAGE_BY_NAME = {s.name: s for s in STAGES}

PRESETS: dict[str, dict[str, Any]] = {
    "draft": {"label": "Draft", "description": "7k iterations, a first look in a few minutes; every 8th frame held out for a quality score",
              "config": {"train": {"iterations": 7000, "holdout-every": 8}}},
    "standard": {"label": "Standard", "description": "30k iterations, full quality",
                 "config": {"train": {"iterations": 30000}}},
}


def default_config() -> dict[str, dict[str, Any]]:
    return {s.name: {p.name: p.default for p in s.params} for s in STAGES}


def resolve_config(overrides: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Defaults merged with overrides, validated against the stage definitions."""
    config = default_config()
    for stage_name, values in (overrides or {}).items():
        stage = STAGE_BY_NAME.get(stage_name)
        if stage is None:
            raise ValueError(f"unknown stage {stage_name!r}")
        params = {p.name: p for p in stage.params}
        for key, value in values.items():
            p = params.get(key)
            if p is None:
                raise ValueError(f"unknown parameter {stage_name}.{key}")
            config[stage_name][key] = _coerce(p, value)
    return config


def _coerce(p: Param, value: Any) -> Any:
    try:
        if p.type == "int":
            value = int(value)
        elif p.type == "float":
            value = float(value)
        elif p.type == "choice":
            match = [c for c in p.choices or [] if str(c) == str(value)]
            if not match:
                raise ValueError
            value = match[0]
    except (TypeError, ValueError):
        raise ValueError(f"invalid value {value!r} for {p.name}") from None
    if p.min is not None and value < p.min or p.max is not None and value > p.max:
        raise ValueError(f"{p.name}={value} outside [{p.min}, {p.max}]")
    return value


def describe() -> dict:
    return {"stages": [asdict(s) for s in STAGES], "presets": PRESETS}
