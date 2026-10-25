#!/usr/bin/env python3
"""Validate quote-friendly Markdown used as canonical candidate evidence."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

FILE_PREFIXES = {
    "identity.md": "ID",
    "experience.md": "EXP",
    "projects.md": "PROJ",
    "education.md": "EDU",
    "skills.md": "SKILL",
    "languages.md": "LANG",
    "certifications.md": "CERT",
}
PROFILE_PHOTOS = {"profile-photo.jpg", "profile-photo.jpeg", "profile-photo.png"}
MANIFEST_FILES = {"current.json"}
REFERENCE_FILES = {"pre-formatted.tex", "international_utilities.tex"}
REFERENCE_BUILD_FILES = {"pre-formatted" + suffix for suffix in (".aux", ".log", ".out", ".pdf", ".synctex.gz")}
FACT_RE = re.compile(r"^- \[(MC-([A-Z]+)-\d{3,})\]\s+(.+\S)$")
PLACEHOLDER_RE = re.compile(
    r"(?:<!--|\bTODO\b|\bTBD\b|Example Candidate|candidate@example\.invalid|linkedin\.com/in/example)",
    re.IGNORECASE,
)
NAME_RE = re.compile(r"^Name:\s*\S", re.IGNORECASE)
CONTACT_RE = re.compile(r"^(?:Email|Phone|LinkedIn|GitHub|Website|Portfolio):\s*\S", re.IGNORECASE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_hashes(source_dir: Path) -> dict[str, str]:
    root = source_dir.expanduser().resolve()
    names = set(FILE_PREFIXES) | PROFILE_PHOTOS | REFERENCE_FILES
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.name in names and path.is_file() and not path.is_symlink()
        and not any(parent.is_symlink() for parent in path.parents if parent != root)
    }


def read_facts(source_dir: Path, allow_missing: bool = False) -> tuple[list[str], dict[str, str]]:
    root = source_dir.expanduser().resolve()
    if allow_missing and not root.exists():
        return [], {}
    errors: list[str] = []
    facts: dict[str, str] = {}
    claims_seen: dict[str, str] = {}
    identity_claims: list[str] = []
    if not root.is_dir():
        return [f"source directory does not exist: {root}"], facts
    entries = sorted(root.iterdir(), key=lambda item: item.name)
    if not entries:
        return ["source directory is empty"], facts
    profiles = [entry for entry in entries if entry.is_dir() and not entry.is_symlink()]
    if profiles:
        for entry in entries:
            allowed = set(FILE_PREFIXES) | PROFILE_PHOTOS | REFERENCE_FILES | MANIFEST_FILES
            if entry not in profiles and (entry.is_symlink() or entry.name not in allowed):
                errors.append(f"unsupported source entry: {entry.name}")
        for profile in profiles:
            if any(child.is_dir() for child in profile.iterdir()):
                errors.append(f"nested profile directories are unsupported: {profile.name}")
                continue
            profile_errors, profile_facts = read_facts(profile)
            errors.extend(f"{profile.name}: {error}" for error in profile_errors)
            for fact_id, claim in profile_facts.items():
                if fact_id in facts and facts[fact_id] != claim:
                    errors.append(f"conflicting fact across profiles: {fact_id}")
                else:
                    facts[fact_id] = claim
        return errors, facts
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            errors.append(f"unsupported source entry: {entry.name}")
        elif entry.name in PROFILE_PHOTOS:
            signature = entry.read_bytes()[:8]
            valid = signature == b"\x89PNG\r\n\x1a\n" if entry.suffix == ".png" else signature.startswith(b"\xff\xd8\xff")
            if not valid:
                errors.append(f"profile photo contents do not match its extension: {entry.name}")
        elif entry.name not in FILE_PREFIXES and entry.name not in MANIFEST_FILES and entry.name not in REFERENCE_FILES and entry.name not in REFERENCE_BUILD_FILES:
            errors.append(f"unexpected source file: {entry.name}")
    photos = [entry.name for entry in entries if entry.name in PROFILE_PHOTOS]
    if len(photos) > 1:
        errors.append("multiple profile-photo files found; keep exactly one approved image")
    if not (root / "identity.md").is_file():
        errors.append("identity.md is required")

    for filename, expected_prefix in FILE_PREFIXES.items():
        path = root / filename
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read {filename} as UTF-8: {exc}")
            continue
        if not text.strip():
            errors.append(f"{filename} is empty; omit empty optional files")
            continue
        if PLACEHOLDER_RE.search(text):
            errors.append(f"{filename} contains an instruction or placeholder")
        for line_number, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = FACT_RE.fullmatch(line)
            if not match:
                errors.append(f"{filename}:{line_number} must be a heading, blank line, or stable-ID fact bullet")
                continue
            fact_id, prefix, claim = match.groups()
            if prefix != expected_prefix:
                errors.append(f"{filename}:{line_number} uses {prefix}; expected {expected_prefix}")
            if fact_id in facts:
                errors.append(f"duplicate fact ID: {fact_id}")
            else:
                facts[fact_id] = claim
            normalized = re.sub(r"\s+", " ", claim).casefold()
            if normalized in claims_seen:
                errors.append(f"duplicate claim: {fact_id} duplicates {claims_seen[normalized]}")
            else:
                claims_seen[normalized] = fact_id
            if filename == "identity.md":
                identity_claims.append(claim)
    if not facts:
        errors.append("at least one canonical fact is required")
    if not any(NAME_RE.match(claim) for claim in identity_claims):
        errors.append("identity.md requires a 'Name:' fact")
    if not any(CONTACT_RE.match(claim) for claim in identity_claims):
        errors.append("identity.md requires at least one contact fact")
    return errors, facts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, type=Path)
    args = parser.parse_args()
    errors, facts = read_facts(args.source_dir)
    if errors:
        for error in errors:
            print(f"validation failed: {error}", file=sys.stderr)
        return 1
    print(f"valid master sources: {args.source_dir.expanduser().resolve()} ({len(facts)} facts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
