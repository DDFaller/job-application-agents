"""Mirror one Drive folder onto a private data root outside the git repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Iterable, Protocol

from .client import DriveItem, parse_folder_id


DEFAULT_MAX_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_FILES = 5000
DEFAULT_MAX_DEPTH = 16
RECEIPT_NAME = ".drive-sync.json"


class DriveSyncError(RuntimeError):
    """Raised when a Drive folder cannot be mirrored safely."""


class DriveSource(Protocol):
    def list_children(self, folder_id: str) -> list[DriveItem]:
        """Return the direct children of a Drive folder."""

    def download(self, file_id: str) -> bytes:
        """Return the bytes of one Drive file."""


@dataclass(frozen=True)
class DriveTreeEntry:
    path: str
    item: DriveItem
    skipped_reason: str | None = None


@dataclass(frozen=True)
class DrivePullResult:
    destination: Path
    written: tuple[str, ...]
    unchanged: tuple[str, ...]
    skipped: tuple[str, ...]


def assert_outside_repository(destination: Path, repo_root: Path) -> Path:
    """Resolve a download directory that cannot land inside the plugin repository."""

    resolved = destination.expanduser().resolve()
    repo = repo_root.expanduser().resolve()
    if resolved == repo or _is_relative_to(resolved, repo) or _is_relative_to(repo, resolved):
        raise DriveSyncError(
            "Drive downloads must use a data root outside the repository. "
            "Set JAA_DATA_ROOT or pass --data-root."
        )
    return resolved


def iter_drive_tree(
    source: DriveSource,
    folder_id: str,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> tuple[DriveTreeEntry, ...]:
    """Walk a Drive folder depth-first and reject unsafe or oversized trees."""

    root_id = parse_folder_id(folder_id)
    entries: list[DriveTreeEntry] = []
    seen: set[str] = set()

    def walk(current_id: str, relative: PurePosixPath, depth: int) -> None:
        if depth > max_depth:
            raise DriveSyncError(f"Drive folder is nested more than {max_depth} levels")
        for item in source.list_children(current_id):
            name = _safe_name(item.name)
            path = str(relative / name) if relative.parts else name
            if path in seen:
                raise DriveSyncError(f"duplicate Drive path: {path}")
            seen.add(path)
            if len(seen) > max_files:
                raise DriveSyncError(f"Drive folder contains more than {max_files} entries")
            if item.is_folder:
                walk(item.id, PurePosixPath(path), depth + 1)
                continue
            reason = None if item.is_downloadable else f"skipped {item.mime_type or 'unknown type'}"
            entries.append(DriveTreeEntry(path=path, item=item, skipped_reason=reason))

    walk(root_id, PurePosixPath(), 1)
    return tuple(entries)


def pull_drive_folder(
    source: DriveSource,
    folder_id: str,
    destination: Path,
    *,
    repo_root: Path,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> DrivePullResult:
    """Download new or changed files from a Drive folder into the private data root."""

    target = assert_outside_repository(destination, repo_root)
    target.mkdir(parents=True, exist_ok=True)
    entries = iter_drive_tree(source, folder_id, max_files=max_files, max_depth=max_depth)
    written: list[str] = []
    unchanged: list[str] = []
    skipped: list[str] = []
    receipt_files: list[dict[str, object]] = []

    for entry in entries:
        if entry.skipped_reason:
            skipped.append(f"{entry.path} ({entry.skipped_reason})")
            continue
        if entry.item.size is not None and entry.item.size > max_bytes:
            raise DriveSyncError(f"{entry.path} exceeds {max_bytes} bytes")
        output = _checked_output(target, entry.path)
        if entry.item.md5 and output.is_file() and _md5_file(output) == entry.item.md5:
            unchanged.append(entry.path)
            receipt_files.append(_receipt_row(entry, output))
            continue
        payload = source.download(entry.item.id)
        if len(payload) > max_bytes:
            raise DriveSyncError(f"{entry.path} exceeds {max_bytes} bytes")
        digest = hashlib.md5(payload).hexdigest()
        if entry.item.md5 and digest != entry.item.md5:
            raise DriveSyncError(f"checksum mismatch for {entry.path}")
        _write_atomic(output, payload)
        written.append(entry.path)
        receipt_files.append(_receipt_row(entry, output, digest=digest, size=len(payload)))

    _write_atomic(
        target / RECEIPT_NAME,
        json.dumps(
            {
                "schema_version": 1,
                "folder_id": parse_folder_id(folder_id),
                "pulled_at": datetime.now(timezone.utc).isoformat(),
                "files": receipt_files,
                "skipped": skipped,
            },
            indent=2,
        ).encode("utf-8"),
    )
    return DrivePullResult(
        destination=target,
        written=tuple(written),
        unchanged=tuple(unchanged),
        skipped=tuple(skipped),
    )


def _receipt_row(entry: DriveTreeEntry, output: Path, *, digest: str | None = None, size: int | None = None) -> dict[str, object]:
    return {
        "id": entry.item.id,
        "path": entry.path,
        "md5": digest or entry.item.md5,
        "bytes": size if size is not None else output.stat().st_size,
    }


def _safe_name(name: str) -> str:
    if (
        name in {"", ".", ".."}
        or name.startswith(".")
        or "/" in name
        or "\\" in name
        or any(ord(char) < 32 for char in name)
    ):
        raise DriveSyncError(f"unsafe Drive file name: {name!r}")
    return name


def _checked_output(destination: Path, relative: str) -> Path:
    output = destination.joinpath(*PurePosixPath(relative).parts).resolve()
    if output == destination or not _is_relative_to(output, destination):
        raise DriveSyncError(f"Drive path escapes the data root: {relative}")
    return output


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _md5_file(path: Path) -> str:
    digest = hashlib.md5()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def format_tree(entries: Iterable[DriveTreeEntry]) -> str:
    """Render a remote listing for the status command."""

    lines = []
    for entry in entries:
        if entry.skipped_reason:
            lines.append(f"SKIP    {entry.path} ({entry.skipped_reason})")
        else:
            size = entry.item.size if entry.item.size is not None else "?"
            lines.append(f"FILE    {entry.path}    {size} B")
    return "\n".join(lines)
