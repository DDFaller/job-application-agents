from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from .firestore import FirestoreUserSyncRepository
from .models import (
    ApplicationSyncSnapshot,
    ApplicationVersionSnapshot,
    CandidateEvidenceSnapshot,
    CurriculumSyncSnapshot,
    CurriculumVersionSnapshot,
    ProfileSyncSnapshot,
    ProfileVersionSnapshot,
    SyncResult,
    SyncStatusReport,
)
from job_application_agents.plugins.notion.firestore import FirestoreNotionJobRepository



def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(text: str) -> str:
    value = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", value) or "unknown"


class SyncService:
    """Service to coordinate synchronization between local files and Firestore."""

    def __init__(
        self,
        repository: FirestoreUserSyncRepository,
        default_data_root: Path | None = None,
        notion_repository: FirestoreNotionJobRepository | None = None,
    ):
        self.repository = repository
        self.default_data_root = (
            default_data_root or (Path.home() / "Documents" / "job-search")
        ).expanduser().resolve()
        self.notion_repository = notion_repository

    def _resolve_data_root(self, data_root: Path | None) -> Path:
        return (data_root or self.default_data_root).expanduser().resolve()

    # =========================================================================
    # PUSH (Local -> Firestore)
    # =========================================================================

    def push_curriculum(
        self, user_id: str, data_root: Path | None = None
    ) -> CurriculumSyncSnapshot:
        root = self._resolve_data_root(data_root)
        sources_dir = root / "sources"
        if not sources_dir.is_dir():
            raise FileNotFoundError(f"sources directory not found at {sources_dir}")

        current_manifest_path = sources_dir / "current.json"
        manifest = load_json(current_manifest_path)
        markdown_sources: list[str] = []
        sources: dict[str, str] = {}
        source_hashes: dict[str, str] = {}

        for entry in sorted(sources_dir.glob("*.md")):
            name = entry.name
            markdown_sources.append(name)
            content = entry.read_text(encoding="utf-8")
            sources[name] = content
            source_hashes[name] = file_sha256(entry)

        photo_info: dict[str, Any] | None = None
        for photo_name in ("profile-photo.jpg", "profile-photo.jpeg", "profile-photo.png"):
            photo_path = sources_dir / photo_name
            if photo_path.is_file():
                photo_bytes = photo_path.read_bytes()
                photo_info = {
                    "filename": photo_name,
                    "sha256": hashlib.sha256(photo_bytes).hexdigest(),
                    "bytes": len(photo_bytes),
                }
                break

        version = str(manifest.get("version", "unversioned"))
        updated_at = str(manifest.get("updated_at", ""))

        snapshot = CurriculumSyncSnapshot(
            version=version,
            updated_at=updated_at,
            markdown_sources=markdown_sources,
            source_hashes=source_hashes,
            sources=sources,
            manifest=manifest,
            photo=photo_info,
        )

        # Build version history
        versions: list[CurriculumVersionSnapshot] = []
        versions_root = root / "master-curriculum" / "versions"
        if versions_root.is_dir():
            for v_dir in sorted(versions_root.iterdir()):
                if v_dir.is_dir() and v_dir.name.startswith("v") and (v_dir / "manifest.json").is_file():
                    v_manifest = load_json(v_dir / "manifest.json")
                    v_sources_dir = v_dir / "sources"
                    v_sources: dict[str, str] = {}
                    v_hashes: dict[str, str] = {}
                    if v_sources_dir.is_dir():
                        for f in v_sources_dir.glob("*.md"):
                            v_sources[f.name] = f.read_text(encoding="utf-8")
                            v_hashes[f.name] = file_sha256(f)
                    additions_review = (
                        load_json(v_dir / "additions-review.json")
                        if (v_dir / "additions-review.json").is_file() else None
                    )
                    versions.append(CurriculumVersionSnapshot(
                        version=v_dir.name,
                        created_at=str(v_manifest.get("created_at", "")),
                        source_hashes=v_hashes or v_manifest.get("source_hashes", {}),
                        sources=v_sources,
                        manifest=v_manifest,
                        review_sha256=v_manifest.get("review_sha256"),
                        additions_review=additions_review,
                        review_inputs=v_manifest.get("review_inputs", []),
                    ))

        # Check candidate evidence cache
        evidence_snapshot: CandidateEvidenceSnapshot | None = None
        for cache_path in root.glob(".evidence-cache/*/candidate-evidence.json"):
            if cache_path.is_file():
                evidence_data = load_json(cache_path)
                if evidence_data:
                    evidence_snapshot = CandidateEvidenceSnapshot.from_dict(evidence_data)
                    break

        self.repository.save_curriculum(
            user_id=user_id,
            snapshot=snapshot,
            versions=versions,
            candidate_evidence=evidence_snapshot,
        )
        return snapshot

    def push_profiles(
        self, user_id: str, data_root: Path | None = None
    ) -> ProfileSyncSnapshot:
        root = self._resolve_data_root(data_root)
        profiles_root = root / "master-curriculum" / "profiles"
        current_pointer = profiles_root / "current.json"
        if not current_pointer.is_file():
            raise FileNotFoundError(f"profiles current.json not found at {current_pointer}")

        pointer_data = load_json(current_pointer)
        catalog_path = Path(pointer_data.get("catalog", "")).expanduser().resolve()
        if not catalog_path.is_file():
            # Try fallback relative to current.json
            candidate = profiles_root / "versions" / pointer_data.get("version", "") / "role-profiles.json"
            if candidate.is_file():
                catalog_path = candidate
            else:
                raise FileNotFoundError(f"role profiles catalog not found at {catalog_path}")

        catalog = load_json(catalog_path)
        catalog_sha256 = file_sha256(catalog_path)
        snapshot = ProfileSyncSnapshot(
            version=str(pointer_data.get("version", "p001")),
            updated_at=str(pointer_data.get("updated_at", "")),
            catalog=catalog,
            catalog_sha256=catalog_sha256,
            source_manifest=pointer_data.get("source_manifest", catalog.get("source_manifest", {})),
        )

        versions: list[ProfileVersionSnapshot] = []
        versions_root = profiles_root / "versions"
        if versions_root.is_dir():
            for p_dir in sorted(versions_root.iterdir()):
                if p_dir.is_dir() and p_dir.name.startswith("p") and (p_dir / "role-profiles.json").is_file():
                    p_catalog_path = p_dir / "role-profiles.json"
                    p_catalog = load_json(p_catalog_path)
                    p_manifest = load_json(p_dir / "manifest.json") if (p_dir / "manifest.json").is_file() else {}
                    p_review = (
                        load_json(p_dir / "profile-review.json")
                        if (p_dir / "profile-review.json").is_file() else None
                    )
                    versions.append(ProfileVersionSnapshot(
                        version=p_dir.name,
                        created_at=str(p_manifest.get("created_at", "")),
                        catalog=p_catalog,
                        catalog_sha256=file_sha256(p_catalog_path),
                        review=p_review,
                        review_sha256=p_manifest.get("review_sha256"),
                        source_manifest=p_manifest.get("source_manifest", p_catalog.get("source_manifest", {})),
                    ))

        self.repository.save_profiles(user_id=user_id, snapshot=snapshot, versions=versions)
        return snapshot

    def push_application_directory(
        self, user_id: str, app_dir: Path
    ) -> ApplicationSyncSnapshot:
        app_dir = app_dir.expanduser().resolve()
        current_pointer = app_dir / "current.json"
        if not current_pointer.is_file():
            raise FileNotFoundError(f"application current.json not found in {app_dir}")

        current_data = load_json(current_pointer)
        current_version_name = str(current_data.get("version", "v001"))
        manifest_path = Path(current_data.get("manifest", "")).expanduser().resolve()
        if not manifest_path.is_file():
            manifest_path = app_dir / current_version_name / "manifest.json"

        manifest = load_json(manifest_path)
        job = manifest.get("job", {})
        company = job.get("company", app_dir.parents[1].name)
        role = job.get("role", app_dir.parents[0].name)
        company_slug = slugify(company)
        role_slug = slugify(role)
        job_id_or_hash = app_dir.name
        app_id = f"{company_slug}__{role_slug}__{job_id_or_hash}"

        # Collect versions
        versions: dict[str, ApplicationVersionSnapshot] = {}
        for entry in sorted(app_dir.iterdir()):
            if entry.is_dir() and re.fullmatch(r"v\d{3}", entry.name) and (entry / "manifest.json").is_file():
                v_manifest = load_json(entry / "manifest.json")
                v_bundle = load_json(entry / "bundle.json") if (entry / "bundle.json").is_file() else {}
                v_job = load_json(entry / "job.json") if (entry / "job.json").is_file() else {}
                v_sources: dict[str, str] = {}
                for text_name in ("resume.tex", "letter.tex", "preamble.tex", "motivation-letter.md", "match-analysis.md"):
                    if (entry / text_name).is_file():
                        v_sources[text_name] = (entry / text_name).read_text(encoding="utf-8")

                versions[entry.name] = ApplicationVersionSnapshot(
                    version=entry.name,
                    generated_at=str(v_manifest.get("generated_at", "")),
                    manifest=v_manifest,
                    bundle=v_bundle,
                    job=v_job,
                    sources=v_sources,
                    quality_gate=v_manifest.get("quality_gate", {}),
                    semantic_review=v_manifest.get("semantic_review", {}),
                    document_text_sha256=v_manifest.get("document_text_sha256", {}),
                    document_revision=int(v_manifest.get("document_revision", 0)),
                    source_provenance=str(v_manifest.get("source_provenance", "agent_generated")),
                    artifacts=v_manifest.get("artifacts", {}),
                    manual_revisions=v_manifest.get("manual_revisions", []),
                    local_path=str(entry),
                    notion_page_url=v_manifest.get("notion_page_url"),
                )

        current_ver_snapshot = versions.get(current_version_name)
        status = "TO_APPLY"
        canonical_url = job.get("url") or job.get("canonical_url")
        notion_page_url = manifest.get("notion_page_url")
        match_summary = None
        selected_profile = None
        gaps = []

        if current_ver_snapshot and current_ver_snapshot.bundle:
            strategy = current_ver_snapshot.bundle.get("tailoring_strategy", {})
            selected_profile = strategy.get("selected_profile") or strategy.get("job_family")
            match_analysis = current_ver_snapshot.bundle.get("match_analysis", {})
            gaps = [str(g.get("requirement", g)) if isinstance(g, dict) else str(g) for g in match_analysis.get("gaps", [])]
            match_summary = strategy.get("selection_rationale")

        app_snapshot = ApplicationSyncSnapshot(
            application_id=app_id,
            company=company,
            company_slug=company_slug,
            role=role,
            role_slug=role_slug,
            job_id_or_hash=job_id_or_hash,
            local_path=str(app_dir),
            status=status,
            current_version=current_version_name,
            canonical_url=canonical_url,
            notion_page_url=notion_page_url,
            match_summary=match_summary,
            selected_profile=selected_profile,
            gaps=gaps,
            generated_at=manifest.get("generated_at"),
            updated_at=manifest.get("generated_at"),
            applied_at=manifest.get("applied_at"),
            next_action_at=manifest.get("next_action_at"),
            notes=manifest.get("notes"),
            versions=versions,
        )

        self.repository.save_application(user_id=user_id, snapshot=app_snapshot)

        # Queue the external projection after Firestore becomes canonical.
        # The worker performs all Notion API calls and updates the page metadata.
        if self.notion_repository is not None:
            self.notion_repository.enqueue_application(
                user_id=user_id,
                application_id=app_id,
                current_version=current_version_name,
                reason="local_firestore_push",
            )

        return app_snapshot

    def push_applications(
        self, user_id: str, data_root: Path | None = None
    ) -> list[ApplicationSyncSnapshot]:
        root = self._resolve_data_root(data_root)
        apps_root = root / "applications"
        results: list[ApplicationSyncSnapshot] = []
        if not apps_root.is_dir():
            return results

        # Find all app directories with current.json
        for current_json in apps_root.rglob("current.json"):
            app_dir = current_json.parent
            if any(re.fullmatch(r"v\d{3}", child.name) for child in app_dir.iterdir() if child.is_dir()):
                try:
                    snapshot = self.push_application_directory(user_id, app_dir)
                    results.append(snapshot)
                except Exception as exc:
                    print(f"Warning: could not push app at {app_dir}: {exc}")
        return results

    def push_all(self, user_id: str, data_root: Path | None = None) -> SyncResult:
        pushed: list[str] = []
        errors: list[str] = []
        try:
            self.push_curriculum(user_id, data_root)
            pushed.append("curriculum")
        except Exception as exc:
            errors.append(f"curriculum: {exc}")

        try:
            self.push_profiles(user_id, data_root)
            pushed.append("profiles")
        except Exception as exc:
            errors.append(f"profiles: {exc}")

        try:
            app_snapshots = self.push_applications(user_id, data_root)
            for app in app_snapshots:
                pushed.append(f"application:{app.application_id}")
        except Exception as exc:
            errors.append(f"applications: {exc}")

        status = "ERROR" if errors else "OK"
        return SyncResult(pushed=pushed, pulled=[], errors=errors, status=status)

    # =========================================================================
    # PULL (Firestore -> Local)
    # =========================================================================

    def pull_curriculum(
        self, user_id: str, data_root: Path | None = None
    ) -> bool:
        snapshot = self.repository.fetch_curriculum(user_id)
        if not snapshot:
            return False

        root = self._resolve_data_root(data_root)
        sources_dir = root / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)

        for filename, content in snapshot.sources.items():
            (sources_dir / filename).write_text(content, encoding="utf-8")

        write_json_atomic(sources_dir / "current.json", snapshot.manifest)

        # Pull version history if available
        versions = self.repository.fetch_curriculum_versions(user_id)
        if versions:
            versions_root = root / "master-curriculum" / "versions"
            versions_root.mkdir(parents=True, exist_ok=True)
            for v in versions:
                v_dir = versions_root / v.version
                v_sources_dir = v_dir / "sources"
                v_sources_dir.mkdir(parents=True, exist_ok=True)
                for f_name, f_content in v.sources.items():
                    (v_sources_dir / f_name).write_text(f_content, encoding="utf-8")
                if v.manifest:
                    write_json_atomic(v_dir / "manifest.json", v.manifest)
                if v.additions_review:
                    write_json_atomic(v_dir / "additions-review.json", v.additions_review)

        return True

    def pull_profiles(
        self, user_id: str, data_root: Path | None = None
    ) -> bool:
        snapshot = self.repository.fetch_profiles(user_id)
        if not snapshot:
            return False

        root = self._resolve_data_root(data_root)
        profiles_root = root / "master-curriculum" / "profiles"
        versions_root = profiles_root / "versions"
        versions_root.mkdir(parents=True, exist_ok=True)

        # Write current version directory
        current_v_dir = versions_root / snapshot.version
        current_v_dir.mkdir(parents=True, exist_ok=True)
        catalog_path = current_v_dir / "role-profiles.json"
        catalog_path.write_text(json.dumps(snapshot.catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        write_json_atomic(profiles_root / "current.json", {
            "schema_version": 1,
            "version": snapshot.version,
            "catalog": str(catalog_path),
            "catalog_sha256": snapshot.catalog_sha256,
            "source_manifest": snapshot.source_manifest,
            "updated_at": snapshot.updated_at,
        })

        # Pull version history
        versions = self.repository.fetch_profile_versions(user_id)
        for v in versions:
            v_dir = versions_root / v.version
            v_dir.mkdir(parents=True, exist_ok=True)
            (v_dir / "role-profiles.json").write_text(json.dumps(v.catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if v.review:
                write_json_atomic(v_dir / "profile-review.json", v.review)
            write_json_atomic(v_dir / "manifest.json", {
                "schema_version": 1,
                "version": v.version,
                "created_at": v.created_at,
                "catalog": "role-profiles.json",
                "catalog_sha256": v.catalog_sha256,
                "review": "profile-review.json" if v.review else None,
                "review_sha256": v.review_sha256,
                "source_manifest": v.source_manifest,
            })

        return True

    def pull_applications(
        self, user_id: str, data_root: Path | None = None
    ) -> list[str]:
        apps = self.repository.list_applications(user_id, include_versions=True)
        pulled: list[str] = []
        root = self._resolve_data_root(data_root)

        for app in apps:
            app_dir = root / "applications" / app.company_slug / app.role_slug / app.job_id_or_hash
            app_dir.mkdir(parents=True, exist_ok=True)

            for v_name, v_data in app.versions.items():
                v_dir = app_dir / v_name
                v_dir.mkdir(parents=True, exist_ok=True)

                if v_data.manifest:
                    write_json_atomic(v_dir / "manifest.json", v_data.manifest)
                if v_data.bundle:
                    write_json_atomic(v_dir / "bundle.json", v_data.bundle)
                if v_data.job:
                    write_json_atomic(v_dir / "job.json", v_data.job)

                for src_name, src_content in v_data.sources.items():
                    (v_dir / src_name).write_text(src_content, encoding="utf-8")

            current_v_dir = app_dir / app.current_version
            write_json_atomic(app_dir / "current.json", {
                "version": app.current_version,
                "path": str(current_v_dir),
                "manifest": str(current_v_dir / "manifest.json"),
            })
            pulled.append(app.application_id)

        return pulled

    def pull_all(self, user_id: str, data_root: Path | None = None) -> SyncResult:
        pulled: list[str] = []
        errors: list[str] = []

        try:
            if self.pull_curriculum(user_id, data_root):
                pulled.append("curriculum")
        except Exception as exc:
            errors.append(f"curriculum: {exc}")

        try:
            if self.pull_profiles(user_id, data_root):
                pulled.append("profiles")
        except Exception as exc:
            errors.append(f"profiles: {exc}")

        try:
            app_ids = self.pull_applications(user_id, data_root)
            for app_id in app_ids:
                pulled.append(f"application:{app_id}")
        except Exception as exc:
            errors.append(f"applications: {exc}")

        status = "ERROR" if errors else "OK"
        return SyncResult(pushed=[], pulled=pulled, errors=errors, status=status)

    # =========================================================================
    # STATUS / DRIFT DETECTION
    # =========================================================================

    def status(self, user_id: str, data_root: Path | None = None) -> SyncStatusReport:
        root = self._resolve_data_root(data_root)
        pending_push: list[str] = []
        pending_pull: list[str] = []

        # Check Curriculum
        remote_curr = self.repository.fetch_curriculum(user_id)
        sources_dir = root / "sources"
        curriculum_synced = False
        if sources_dir.is_dir() and any(sources_dir.glob("*.md")) and remote_curr:
            local_hashes = {f.name: file_sha256(f) for f in sorted(sources_dir.glob("*.md"))}
            remote_hashes = remote_curr.source_hashes
            if local_hashes == remote_hashes:
                curriculum_synced = True
            else:
                pending_push.append("curriculum (modified locally)")
        elif sources_dir.is_dir() and any(sources_dir.glob("*.md")) and not remote_curr:
            pending_push.append("curriculum (not in cloud)")
        elif (not sources_dir.is_dir() or not any(sources_dir.glob("*.md"))) and remote_curr:
            pending_pull.append("curriculum (not local)")

        # Check Profiles
        remote_prof = self.repository.fetch_profiles(user_id)
        local_prof_path = root / "master-curriculum" / "profiles" / "current.json"
        local_prof = load_json(local_prof_path) if local_prof_path.is_file() else None

        profiles_synced = False
        if local_prof and remote_prof:
            local_sha = local_prof.get("catalog_sha256")
            if local_sha == remote_prof.catalog_sha256:
                profiles_synced = True
            else:
                pending_push.append("profiles (modified locally)")
        elif local_prof and not remote_prof:
            pending_push.append("profiles (not in cloud)")
        elif not local_prof and remote_prof:
            pending_pull.append("profiles (not local)")

        # Check Applications
        remote_apps = {app.application_id: app for app in self.repository.list_applications(user_id)}
        local_apps: dict[str, Path] = {}
        apps_root = root / "applications"
        if apps_root.is_dir():
            for current_json in apps_root.rglob("current.json"):
                app_dir = current_json.parent
                if any(re.fullmatch(r"v\d{3}", c.name) for c in app_dir.iterdir() if c.is_dir()):
                    manifest_data = load_json(current_json)
                    current_ver_name = str(manifest_data.get("version", "v001"))
                    manifest_file = Path(manifest_data.get("manifest", "")).expanduser().resolve()
                    if not manifest_file.is_file():
                        manifest_file = app_dir / current_ver_name / "manifest.json"
                    manifest = load_json(manifest_file)
                    job = manifest.get("job", {})
                    company = job.get("company", app_dir.parents[1].name)
                    role = job.get("role", app_dir.parents[0].name)
                    app_id = f"{slugify(company)}__{slugify(role)}__{app_dir.name}"
                    local_apps[app_id] = app_dir

        for app_id, app_dir in local_apps.items():
            if app_id not in remote_apps:
                pending_push.append(f"application:{app_id}")
            else:
                # Check version difference
                remote_ver = remote_apps[app_id].current_version
                local_ver = load_json(app_dir / "current.json").get("version")
                if remote_ver != local_ver:
                    pending_push.append(f"application:{app_id} (version drift)")

        for app_id in remote_apps:
            if app_id not in local_apps:
                pending_pull.append(f"application:{app_id}")

        return SyncStatusReport(
            user_id=user_id,
            curriculum_synced=curriculum_synced,
            profiles_synced=profiles_synced,
            local_apps_count=len(local_apps),
            remote_apps_count=len(remote_apps),
            pending_push=pending_push,
            pending_pull=pending_pull,
        )
