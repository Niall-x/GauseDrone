"""Record types. Each capture and run is one JSON file in its own folder under
the data directory; the folders are the source of truth (copy a run folder to
another machine and it shows up there), so there is no separate database."""
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

StageStatus = Literal["pending", "running", "done", "failed", "cancelled"]
RunStatus = Literal["queued", "running", "done", "failed", "cancelled"]
CaptureKind = Literal["video", "images"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Capture(BaseModel):
    # Responses always include defaulted fields; mark them required in the OpenAPI schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    name: str
    kind: CaptureKind
    created: str = Field(default_factory=now)
    files: list[str]  # relative to the capture's source/ folder
    num_images: int = 0
    duration_sec: float | None = None
    resolution: list[int] | None = None
    size_bytes: int = 0
    origin: str = ""  # where it was imported from ("upload" or a path)
    linked: bool = False  # source/ is a symlink to the original rather than a copy
    notes: str = ""


class StageState(BaseModel):
    # Responses always include defaulted fields; mark them required in the OpenAPI schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    name: str
    status: StageStatus = "pending"
    progress: float = 0.0
    message: str = ""
    started: str | None = None
    finished: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    reused_from: str | None = None  # run id whose outputs this stage reused


class Run(BaseModel):
    # Responses always include defaulted fields; mark them required in the OpenAPI schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    name: str
    capture_id: str
    created: str = Field(default_factory=now)
    status: RunStatus = "queued"
    config: dict[str, dict[str, Any]]
    stages: list[StageState]
    env: dict[str, Any] = Field(default_factory=dict)
    base_run_id: str | None = None
    notes: str = ""

    def stage(self, name: str) -> StageState:
        return next(s for s in self.stages if s.name == name)


# --- API request bodies ---

class ImportCaptureRequest(BaseModel):
    path: str
    name: str | None = None
    link: bool = False


class CreateRunRequest(BaseModel):
    capture_id: str
    name: str | None = None
    preset: str | None = None
    config: dict[str, dict[str, Any]] | None = None
    base_run_id: str | None = None
    reuse_until: str | None = None  # last stage (inclusive) to reuse from base_run_id


class RerunRequest(BaseModel):
    from_stage: str
    config: dict[str, dict[str, Any]] | None = None


class UpdateRequest(BaseModel):
    name: str | None = None
    notes: str | None = None
