"""Role-profile candidate sources discovery and loading."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

STANDARD_SOURCE_FILES = (
    "identity.md",
    "experience.md",
    "education.md",
    "skills.md",
    "projects.md",
    "languages.md",
)

PHOTO_FILENAMES = (
    "profile-photo.jpg",
    "profile-photo.jpeg",
    "profile-photo.png",
)

PREFORMATTED_CV_FILENAMES = (
    "pre-formatted.tex",
    "cv.tex",
    "resume.tex",
)


def list_role_profiles(sources_dir: Path) -> list[str]:
    """List valid role-profile subdirectory names found under sources_dir."""
    root = sources_dir.expanduser().resolve()
    if not root.is_dir():
        return []
    profiles: list[str] = []
    for item in sorted(root.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        # A valid profile folder contains at least one markdown source file
        has_md = any(item.joinpath(f).is_file() for f in STANDARD_SOURCE_FILES)
        if has_md:
            profiles.append(item.name)
    return profiles


def load_role_profile_sources(sources_dir: Path, profile_name: str) -> dict[str, str]:
    """Load text contents of all standard markdown files for a given role profile."""
    profile_dir = sources_dir.expanduser().resolve() / profile_name
    if not profile_dir.is_dir():
        raise ValueError(f"Role profile directory not found: {profile_dir}")
    sources: dict[str, str] = {}
    for filename in STANDARD_SOURCE_FILES:
        path = profile_dir / filename
        stem = Path(filename).stem
        if path.is_file():
            try:
                sources[stem] = path.read_text(encoding="utf-8")
            except Exception as exc:
                sources[stem] = f"Error reading {filename}: {exc}"
        else:
            sources[stem] = ""

    tex_path = find_preformatted_cv(sources_dir, profile_name)
    if tex_path is not None:
        try:
            sources["pre_formatted_tex"] = tex_path.read_text(encoding="utf-8")
        except Exception as exc:
            sources["pre_formatted_tex"] = f"Error reading {tex_path.name}: {exc}"

    return sources


def match_role_profile(
    job: dict[str, Any],
    available_profiles: list[str],
    default_profile: str | None = None,
) -> str:
    """Select the best matching role profile from available profiles based on job data."""
    if not available_profiles:
        raise ValueError("No role profiles available")
    if len(available_profiles) == 1:
        return available_profiles[0]
    if default_profile and default_profile in available_profiles:
        return default_profile

    role_title = str(job.get("role", "")).lower()
    technologies = [str(t).lower() for t in job.get("technologies", [])]
    requirements = [str(r).lower() for r in job.get("requirements", [])]
    job_text = f"{role_title} {' '.join(technologies)} {' '.join(requirements)}"

    best_score = -1
    best_profile = available_profiles[0]

    for profile in available_profiles:
        score = 0
        normalized_name = profile.lower().replace("_", " ").replace("-", " ")
        tokens = [t for t in normalized_name.split() if len(t) > 2]
        for token in tokens:
            if token in role_title:
                score += 10
            elif token in job_text:
                score += 3
        if score > best_score:
            best_score = score
            best_profile = profile

    return best_profile


def find_profile_photo(sources_dir: Path, profile_name: str | None = None) -> Path | None:
    """Find a candidate photo, checking role-profile directory first, then sources root."""
    sources = sources_dir.expanduser().resolve()
    if profile_name:
        profile_dir = sources / profile_name
        if profile_dir.is_dir():
            for name in PHOTO_FILENAMES:
                target = profile_dir / name
                if target.is_file():
                    return target
    for name in PHOTO_FILENAMES:
        target = sources / name
        if target.is_file():
            return target
    return None


def find_preformatted_cv(sources_dir: Path, profile_name: str | None = None) -> Path | None:
    """Find a pre-formatted .tex CV reference, checking role-profile directory first, then sources root."""
    sources = sources_dir.expanduser().resolve()
    if profile_name:
        profile_dir = sources / profile_name
        if profile_dir.is_dir():
            for name in PREFORMATTED_CV_FILENAMES:
                target = profile_dir / name
                if target.is_file():
                    return target
    for name in PREFORMATTED_CV_FILENAMES:
        target = sources / name
        if target.is_file():
            return target
    return None
