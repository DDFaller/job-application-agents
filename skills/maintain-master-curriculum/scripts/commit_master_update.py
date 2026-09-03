#!/usr/bin/env python3
"""Commit an approved, agent-reviewed master curriculum update with history."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_additions_review import load as load_review
from validate_additions_review import validate as validate_review
from validate_master_sources import read_facts, source_hashes
from source_manifest import manifest_for


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def next_version(root: Path) -> str:
    values = []
    if root.is_dir():
        for entry in root.iterdir():
            if entry.is_dir() and entry.name.startswith("v") and entry.name[1:].isdigit():
                values.append(int(entry.name[1:]))
    return f"v{max(values, default=0) + 1:03d}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged-dir", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--sync-firestore", action="store_true", help="sync curriculum to Firestore after commit")
    args = parser.parse_args()
    if args.approval != "APPROVED":
        print("commit refused: --approval must be exactly APPROVED", file=sys.stderr)
        return 2

    staged = args.staged_dir.expanduser().resolve()
    review_path = args.review.expanduser().resolve()
    source = args.source_dir.expanduser().resolve()
    state = args.state_root.expanduser().resolve()
    if source.name != "sources" or any(path in {Path("/"), Path.home()} for path in (staged, source, state)):
        print("commit refused: unsafe canonical paths", file=sys.stderr)
        return 2
    unsafe_overlap = (
        inside(source, state)
        or inside(state, source)
        or inside(source, staged)
        or inside(staged, source)
        or inside(state, staged)
    )
    if unsafe_overlap:
        print("commit refused: source must be separate, and state cannot be inside staging", file=sys.stderr)
        return 2
    if source.is_symlink() or state.is_symlink():
        print("commit refused: source and state paths must not be symlinks", file=sys.stderr)
        return 2

    source_errors, _ = read_facts(staged)
    if source_errors:
        for error in source_errors:
            print(f"commit refused: {error}", file=sys.stderr)
        return 1
    try:
        review = load_review(review_path)
        review_errors = validate_review(review)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"commit refused: cannot verify review: {exc}", file=sys.stderr)
        return 1
    if review_errors:
        for error in review_errors:
            print(f"commit refused: {error}", file=sys.stderr)
        return 1
    if review.get("verdict") != "accept":
        print("commit refused: additions review is not accepted", file=sys.stderr)
        return 2
    if Path(review["staged_source_dir"]).expanduser().resolve() != staged:
        print("commit refused: review targets a different staging directory", file=sys.stderr)
        return 2
    source_initialized = source.is_dir() and any(source.iterdir())
    expected_current = source if source_initialized else None
    reviewed_current = review.get("current_source_dir")
    reviewed_current_path = Path(reviewed_current).expanduser().resolve() if reviewed_current else None
    if reviewed_current_path != expected_current:
        print("commit refused: review does not target the current canonical source directory", file=sys.stderr)
        return 2

    versions = state / "versions"
    archives = state / "archives"
    versions.mkdir(parents=True, exist_ok=True)
    archives.mkdir(parents=True, exist_ok=True)
    version = next_version(versions)
    version_dir = versions / version
    version_tmp = Path(tempfile.mkdtemp(prefix=f".{version}.", dir=versions))
    current_tmp: Path | None = None
    archived_prior: Path | None = None
    installed = False
    created_at = datetime.now(timezone.utc).astimezone().isoformat()

    try:
        shutil.copytree(staged, version_tmp / "sources")
        shutil.copy2(review_path, version_tmp / "additions-review.json")
        input_archive = version_tmp / "review-inputs"
        input_archive.mkdir()
        archived_inputs = []
        for item in review["inputs"]:
            input_id = item["id"]
            original = Path(item["path"]).expanduser().resolve()
            snapshot = Path(item["snapshot_path"]).expanduser().resolve()
            original_target = input_archive / f"{input_id}-original{original.suffix}"
            snapshot_target = input_archive / f"{input_id}-snapshot.txt"
            shutil.copy2(original, original_target)
            shutil.copy2(snapshot, snapshot_target)
            archived_inputs.append({
                "id": input_id,
                "kind": item["kind"],
                "original": str(original_target.relative_to(version_tmp)),
                "original_sha256": digest(original_target),
                "snapshot": str(snapshot_target.relative_to(version_tmp)),
                "snapshot_sha256": digest(snapshot_target),
            })
        manifest = {
            "schema_version": 1,
            "version": version,
            "created_at": created_at,
            "source_hashes": source_hashes(version_tmp / "sources"),
            "review_sha256": digest(version_tmp / "additions-review.json"),
            "review_inputs": archived_inputs,
        }
        (version_tmp / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(version_tmp, version_dir)

        source.parent.mkdir(parents=True, exist_ok=True)
        current_tmp = Path(tempfile.mkdtemp(prefix=".sources.", dir=source.parent))
        current_tmp.rmdir()
        shutil.copytree(version_dir / "sources", current_tmp)
        if source.exists():
            archived_prior = archives / f"before-{version}"
            if archived_prior.exists():
                raise RuntimeError(f"archive already exists: {archived_prior}")
            os.replace(source, archived_prior)
        os.replace(current_tmp, source)
        installed = True
        # The canonical retrieval contract lives beside the Markdown sources.
        # Keep the state-root pointer only as a legacy compatibility record.
        source_manifest = manifest_for(source, version)
        source_manifest["updated_at"] = created_at
        write_json_atomic(source / "current.json", source_manifest)
        current = {
            "schema_version": 2,
            "version": version,
            "source_dir": str(source),
            "source_hashes": source_hashes(source),
            "manifest": str(source / "current.json"),
            "updated_at": created_at,
        }
        write_json_atomic(state / "current.json", current)

        if args.sync_firestore or os.environ.get("JAA_SYNC_FIRESTORE") == "1":
            try:
                repo_root = Path(__file__).resolve().parents[3]
                if str(repo_root) not in sys.path:
                    sys.path.insert(0, str(repo_root))
                from job_application_agents.render_service.config import firebase_project_id, get_user_id
                from job_application_agents.sync.firestore import FirestoreUserSyncRepository
                from job_application_agents.sync.service import SyncService

                project = firebase_project_id()
                user = get_user_id(source.parent)
                sync_svc = SyncService(FirestoreUserSyncRepository(project), default_data_root=source.parent)
                sync_svc.push_curriculum(user, source.parent)
            except Exception as sync_exc:
                print(f"note: firestore curriculum sync skipped or failed: {sync_exc}", file=sys.stderr)

    except Exception as exc:
        if installed and source.exists():
            failed = archives / f"failed-{version}"
            os.replace(source, failed)
            installed = False
        if archived_prior is not None and archived_prior.exists() and not source.exists():
            os.replace(archived_prior, source)
        if current_tmp is not None and current_tmp.exists():
            shutil.rmtree(current_tmp)
        if version_tmp.exists():
            shutil.rmtree(version_tmp)
        print(f"commit failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"version": version, "source_dir": str(source), "version_dir": str(version_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
