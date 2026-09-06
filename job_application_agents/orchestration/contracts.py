"""Versioned, provider-neutral contracts for one semantic worker stage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal


TASK_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1
StageResultStatus = Literal["succeeded", "blocked", "failed"]


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


@dataclass(frozen=True)
class ArtifactReference:
    name: str
    path: str
    sha256: str

    def validate(self, *, data_root: Path, require_file: bool = True) -> None:
        target = Path(self.path)
        if not self.name or not target.is_absolute() or not _inside(target.resolve(), data_root):
            raise ValueError(f"invalid artifact path for {self.name or '<unnamed>'}")
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise ValueError(f"invalid artifact hash for {self.name}")
        if require_file:
            if not target.is_file():
                raise ValueError(f"artifact does not exist: {target}")
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest != self.sha256:
                raise ValueError(f"artifact hash mismatch: {target}")


@dataclass(frozen=True)
class StageTask:
    batch_id: str
    run_id: str
    job_key: str
    opening_url: str
    stage: str
    attempt: int
    skill: str
    data_root: str
    output_dir: str
    result_path: str
    inputs: tuple[ArtifactReference, ...] = ()
    constraints: tuple[str, ...] = ()
    schema_version: int = TASK_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != TASK_SCHEMA_VERSION:
            raise ValueError("unsupported stage-task schema")
        required = (self.batch_id, self.run_id, self.job_key, self.opening_url, self.stage, self.skill)
        if not all(value.strip() for value in required):
            raise ValueError("stage task has empty required fields")
        if self.attempt < 1:
            raise ValueError("stage attempt must be positive")
        root = Path(self.data_root)
        output = Path(self.output_dir)
        result = Path(self.result_path)
        if not root.is_absolute() or not output.is_absolute() or not result.is_absolute():
            raise ValueError("task paths must be absolute")
        resolved_root = root.resolve()
        if not _inside(output.resolve(), resolved_root) or not _inside(result.resolve(), resolved_root):
            raise ValueError("task output paths must stay inside the data root")
        for artifact in self.inputs:
            artifact.validate(data_root=resolved_root)

    def write(self, path: Path) -> None:
        self.validate()
        atomic_json_write(path, asdict(self))

    @classmethod
    def read(cls, path: Path) -> "StageTask":
        value = json.loads(path.read_text(encoding="utf-8"))
        value["inputs"] = tuple(ArtifactReference(**item) for item in value.get("inputs", []))
        value["constraints"] = tuple(value.get("constraints", []))
        task = cls(**value)
        task.validate()
        return task


@dataclass(frozen=True)
class StageBlocker:
    code: str
    message: str
    retryable: bool
    user_action: str | None = None
    restart_stage: str | None = None


@dataclass(frozen=True)
class StageResult:
    run_id: str
    job_key: str
    stage: str
    attempt: int
    status: StageResultStatus
    validated: bool
    artifacts: tuple[ArtifactReference, ...] = ()
    blocker: StageBlocker | None = None
    details: str | None = None
    schema_version: int = RESULT_SCHEMA_VERSION

    def validate_for(self, task: StageTask, *, verify_files: bool = True) -> None:
        if self.schema_version != RESULT_SCHEMA_VERSION:
            raise ValueError("unsupported stage-result schema")
        if self.status not in {"succeeded", "blocked", "failed"}:
            raise ValueError(f"invalid stage-result status: {self.status}")
        identity = (self.run_id, self.job_key, self.stage, self.attempt)
        expected = (task.run_id, task.job_key, task.stage, task.attempt)
        if identity != expected:
            raise ValueError("stage result does not match its task")
        if self.status == "succeeded" and (not self.validated or not self.artifacts):
            raise ValueError("successful stage requires validated artifacts")
        if self.status == "succeeded" and self.blocker is not None:
            raise ValueError("successful stage cannot include a blocker")
        if self.status != "succeeded" and self.blocker is None:
            raise ValueError("blocked or failed stage requires a typed blocker")
        if self.blocker is not None:
            if not self.blocker.code.strip() or not self.blocker.message.strip():
                raise ValueError("stage blocker requires a code and message")
            if self.blocker.restart_stage and not self.blocker.retryable:
                raise ValueError("restart_stage requires a retryable blocker")
        names = [artifact.name for artifact in self.artifacts]
        if len(names) != len(set(names)):
            raise ValueError("stage result contains duplicate artifact names")
        root = Path(task.data_root).resolve()
        for artifact in self.artifacts:
            artifact.validate(data_root=root, require_file=verify_files)

    def write(self, path: Path) -> None:
        atomic_json_write(path, asdict(self))

    @classmethod
    def read(cls, path: Path) -> "StageResult":
        value = json.loads(path.read_text(encoding="utf-8"))
        value["artifacts"] = tuple(ArtifactReference(**item) for item in value.get("artifacts", []))
        blocker = value.get("blocker")
        value["blocker"] = StageBlocker(**blocker) if blocker else None
        return cls(**value)


@dataclass(frozen=True)
class WorkerProfile:
    harness: Literal["agy", "codex", "opencode", "muse"]
    model: str
    effort: Literal["low", "medium", "high"] | None = None
    auto_approve: bool = False
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if self.harness not in {"agy", "codex", "opencode", "muse"}:
            raise ValueError(f"unsupported worker harness: {self.harness}")
        if not self.model:
            raise ValueError("worker model is required")
        if self.harness == "opencode" and "/" not in self.model:
            raise ValueError("OpenCode models must use provider/model format")
        if self.harness == "agy" and "claude" in self.model.lower() and self.effort:
            raise ValueError("Agy Claude models do not accept --effort")
        forbidden = {
            "--add-dir", "--model", "--effort", "--print", "--prompt",
            "--prompt-interactive", "--continue", "--conversation",
            "--dangerously-skip-permissions", "--dangerously-bypass-approvals-and-sandbox",
            "--auto", "--agent", "--dir", "--format", "--pure", "--variant",
            "--interactive", "run", "resume", "fork",
            "--workspace", "--reasoning-effort", "--approval-mode",
            "--disable-approval", "--yolo", "--trust-workspace",
            "--json", "exec",
        }
        if any(argument in forbidden for argument in self.extra_args):
            raise ValueError("extra_args cannot override task isolation or managed provider flags")


__all__ = [
    "ArtifactReference",
    "StageBlocker",
    "StageResult",
    "StageResultStatus",
    "StageTask",
    "WorkerProfile",
    "atomic_json_write",
]
