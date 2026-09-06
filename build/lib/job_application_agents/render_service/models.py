from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID


STATES = {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED"}


def safe_relative_name(value: str, field: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise ValueError(f"{field} must be a safe POSIX relative path")
    return value


@dataclass(frozen=True)
class ArtifactRef:
    key: str
    sha256: str
    bytes: int

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ArtifactRef":
        result = cls(str(value["key"]), str(value["sha256"]), int(value["bytes"]))
        if len(result.sha256) != 64 or result.bytes < 0:
            raise ValueError("invalid artifact reference")
        return result

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompileDocument:
    source: str
    output: str
    passes: int = 2
    max_pages: int = 1
    extract_raw_text: bool = False

    def __post_init__(self) -> None:
        safe_relative_name(self.source, "source")
        safe_relative_name(self.output, "output")
        if not self.source.endswith(".tex") or not self.output.endswith(".pdf"):
            raise ValueError("compile documents require .tex sources and .pdf outputs")
        if self.passes not in {1, 2, 3}:
            raise ValueError("passes must be between 1 and 3")
        if not 1 <= self.max_pages <= 10:
            raise ValueError("max_pages must be between 1 and 10")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CompileDocument":
        return cls(
            source=str(value["source"]),
            output=str(value["output"]),
            passes=int(value.get("passes", 2)),
            max_pages=int(value.get("max_pages", 1)),
            extract_raw_text=bool(value.get("extract_raw_text", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RenderRequest:
    request_id: str
    input_artifact: ArtifactRef
    documents: tuple[CompileDocument, ...]
    required_packages: tuple[str, ...] = ()
    required_fonts: tuple[str, ...] = ()
    timeout_seconds: int = 300
    user_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        UUID(self.request_id)
        if self.schema_version != 1:
            raise ValueError("unsupported render request schema")
        if not self.documents or len(self.documents) > 10:
            raise ValueError("render request must contain 1-10 documents")
        if any("/" in value or not value.endswith(".sty") for value in self.required_packages):
            raise ValueError("required packages must be .sty filenames")
        if any(not value.strip() or len(value) > 100 for value in self.required_fonts):
            raise ValueError("required fonts must be non-empty family names")
        outputs = [item.output for item in self.documents]
        if len(outputs) != len(set(outputs)):
            raise ValueError("document outputs must be unique")
        if not 30 <= self.timeout_seconds <= 600:
            raise ValueError("timeout_seconds must be between 30 and 600")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RenderRequest":
        return cls(
            schema_version=int(value.get("schema_version", 0)),
            request_id=str(value["request_id"]),
            input_artifact=ArtifactRef.from_dict(value["input_artifact"]),
            documents=tuple(CompileDocument.from_dict(item) for item in value["documents"]),
            required_packages=tuple(str(item) for item in value.get("required_packages", [])),
            required_fonts=tuple(str(item) for item in value.get("required_fonts", [])),
            timeout_seconds=int(value.get("timeout_seconds", 300)),
            user_id=value.get("user_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "input_artifact": self.input_artifact.to_dict(),
            "documents": [item.to_dict() for item in self.documents],
            "required_packages": list(self.required_packages),
            "required_fonts": list(self.required_fonts),
            "timeout_seconds": self.timeout_seconds,
            "user_id": self.user_id,
        }


@dataclass(frozen=True)
class RenderJob:
    id: str
    state: str
    request: RenderRequest
    attempts: int
    max_attempts: int
    user_id: str | None = None
    output_artifact: ArtifactRef | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        UUID(self.id)
        if self.state not in STATES:
            raise ValueError(f"invalid render job state: {self.state}")
