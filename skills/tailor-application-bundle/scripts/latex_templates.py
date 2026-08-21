#!/usr/bin/env python3
"""Declarative runtime and structural validation for imported XeLaTeX CV templates."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


ENTRY_FIELDS = {
    "experience": ("COMPANY", "POSITION", "LOCATION", "DATES", "SUMMARY", "HIGHLIGHTS"),
    "education": ("INSTITUTION", "AREA", "DEGREE", "LOCATION", "DATES", "SUMMARY", "HIGHLIGHTS"),
    "normal": ("NAME", "LOCATION", "DATES", "SUMMARY", "HIGHLIGHTS"),
    "one_line": ("LABEL", "DETAILS"),
    "publication": ("TITLE", "AUTHORS", "JOURNAL", "DATES", "DOI", "URL", "SUMMARY"),
    "bullet": ("TEXT",),
    "numbered": ("TEXT",),
    "reversed_numbered": ("TEXT",),
    "text": ("TEXT",),
}
FRAGMENT_NAMES = {"section", "highlight", *ENTRY_FIELDS}
MANIFEST_FIELDS = {
    "schema_version", "id", "display_name", "description", "engine", "main",
    "required_packages", "required_fonts", "fragments",
}
RESERVED_RUNTIME_NAMES = {
    "bundle.json", "job.json", "candidate-evidence.json", "role-profiles.json",
    "resume.tex", "resume.pdf", "letter.tex", "motivation-letter.pdf",
    "preamble.tex", "manifest.json", "staging-manifest.json", "generated",
    "template-source", "tailoring-review.json", "match-analysis.md",
    "motivation-letter.md",
}
BANNED_TEX = (
    (re.compile(r"\\(?:immediate\s*)?write18\b", re.I), "shell execution"),
    (re.compile(r"\\(?:openin|openout|read|write)\b", re.I), "arbitrary file I/O"),
    (re.compile(r"\\directlua\b", re.I), "Lua execution"),
    (re.compile(r"\\usepackage(?:\[[^]]*\])?\{(?:shellesc|minted)\}", re.I), "shell-dependent package"),
    (re.compile(r"\\(?:input|include)\s*\{?\s*(?:/|\.\.)", re.I), "external include"),
    (re.compile(r"\\(?:documentclass|begin)\s*(?:\[[^]]*\])?\{(?:[^}]*(?:two column|twocolumn|multicol)[^}]*)\}", re.I | re.X), "multi-column layout"),
    (re.compile(r"\\documentclass\s*\[[^]]*\btwocolumn\b[^]]*\]", re.I), "multi-column layout"),
    (re.compile(r"\\begin\{multicols?\}|\\twocolumn\b", re.I), "multi-column layout"),
)
TOKEN = re.compile(r"\[\[JAA:([A-Z][A-Z0-9_]*)\]\]")
CONDITIONAL = re.compile(
    r"\[\[JAA:IF ([A-Z][A-Z0-9_]*)\]\](.*?)\[\[JAA:END \1\]\]",
    re.DOTALL,
)


def latex_escape(value: object) -> str:
    translations = str.maketrans({
        "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
        "{": r"\{", "}": r"\}", "\\": r"\textbackslash{}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    })
    return str(value or "").translate(translations)


def text_of(value: Any) -> str:
    return str(value.get("text", "")) if isinstance(value, dict) else str(value or "")


def safe_relative(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("template path must be a non-empty string")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"template path escapes its root: {value}")
    resolved = (root / relative).resolve()
    if root.resolve() not in resolved.parents:
        raise ValueError(f"template path escapes its root: {value}")
    return resolved


def load_manifest(template_dir: Path) -> dict[str, Any]:
    path = template_dir / "template.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("template.json must contain an object")
    return value


def template_files(template_dir: Path) -> list[Path]:
    root = template_dir.resolve()
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"template contains a symlink: {path.relative_to(root)}")
        if path.is_file():
            files.append(path)
    return files


def fingerprint(template_dir: Path) -> str:
    digest = hashlib.sha256()
    root = template_dir.resolve()
    for path in template_files(root):
        relative = str(path.relative_to(root)).replace("\\", "/")
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def runtime_files(template_dir: Path, manifest: dict[str, Any] | None = None) -> list[Path]:
    root = template_dir.resolve()
    manifest = manifest or load_manifest(root)
    excluded = {safe_relative(root, manifest["main"])}
    excluded.update(safe_relative(root, value) for value in manifest["fragments"].values())
    excluded.add(root / "template.json")
    return [path for path in template_files(root) if path not in excluded]


def missing_dependencies(template_dir: Path, manifest: dict[str, Any]) -> list[str]:
    kpsewhich = shutil.which("kpsewhich")
    missing: list[str] = []
    local_names = {path.name for path in template_files(template_dir)}
    for package in manifest.get("required_packages", []):
        if package in local_names:
            continue
        if not kpsewhich:
            missing.append(package)
            continue
        result = subprocess.run(
            [kpsewhich, package], capture_output=True, text=True, check=False, timeout=30,
        )
        if result.returncode or not result.stdout.strip():
            missing.append(package)
    fc_match = shutil.which("fc-match")
    for font in manifest.get("required_fonts", []):
        if not fc_match:
            missing.append(f"font:{font}")
            continue
        result = subprocess.run(
            [fc_match, "-f", "%{family}", font],
            capture_output=True, text=True, check=False, timeout=30,
        )
        families = {part.strip().casefold() for part in result.stdout.split(",") if part.strip()}
        if result.returncode or font.casefold() not in families:
            missing.append(f"font:{font}")
    return missing


def validate_structure(template_dir: Path) -> tuple[list[str], list[str], dict[str, Any] | None]:
    errors: list[str] = []
    root = template_dir.expanduser().resolve()
    if not root.is_dir():
        return [f"template directory does not exist: {root}"], [], None
    try:
        files = template_files(root)
    except (OSError, ValueError) as exc:
        return [str(exc)], [], None
    if len(files) > 500:
        errors.append("template contains more than 500 files")
    if sum(path.stat().st_size for path in files) > 50 * 1024 * 1024:
        errors.append("template exceeds 50 MB")
    try:
        manifest = load_manifest(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot load template.json: {exc}"], [], None
    if set(manifest) != MANIFEST_FIELDS or manifest.get("schema_version") != 1:
        errors.append("template.json must match schema version 1")
    slug = manifest.get("id")
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        errors.append("template id must be a lower-case slug")
    elif root.name != slug:
        errors.append("template directory name must equal template id")
    if not isinstance(manifest.get("display_name"), str) or not manifest["display_name"].strip():
        errors.append("display_name is required")
    if not isinstance(manifest.get("description"), str) or not manifest["description"].strip():
        errors.append("description is required")
    if manifest.get("engine") != "xelatex":
        errors.append("engine must be xelatex")
    packages = manifest.get("required_packages")
    if not isinstance(packages, list) or any(
        not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]+\.sty", item)
        for item in packages
    ) or len(set(packages or [])) != len(packages or []):
        errors.append("required_packages must be a unique array of .sty filenames")
    fonts = manifest.get("required_fonts")
    if not isinstance(fonts, list) or any(
        not isinstance(item, str) or not item.strip() or len(item) > 100
        for item in fonts
    ) or len(set(fonts or [])) != len(fonts or []):
        errors.append("required_fonts must be a unique array of non-empty font family names")
    fragments = manifest.get("fragments")
    if not isinstance(fragments, dict) or set(fragments) != FRAGMENT_NAMES:
        errors.append("fragments must map every required fragment name")
        fragments = {}
    sources: dict[str, str] = {}
    for label, value in (("main", manifest.get("main")), *fragments.items()):
        try:
            path = safe_relative(root, value)
            if not path.is_file():
                errors.append(f"{label} template does not exist")
                continue
            sources[label] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"cannot read {label} template: {exc}")
    required_tokens = {
        "main": {"NAME", "HEADLINE", "LOCATION", "CONTACT", "PROFILE", "SECTIONS"},
        "section": {"TITLE", "ITEMS"}, "highlight": {"TEXT"},
        **{name: set(fields) for name, fields in ENTRY_FIELDS.items()},
    }
    for label, required in required_tokens.items():
        source = sources.get(label, "")
        present = set(TOKEN.findall(source)) | {match.group(1) for match in CONDITIONAL.finditer(source)}
        missing = required - present
        if missing:
            errors.append(f"{label} template lacks tokens: {', '.join(sorted(missing))}")
    if "main" in sources:
        if "\\documentclass" not in sources["main"] or "\\begin{document}" not in sources["main"]:
            errors.append("main template must contain a complete LaTeX document")
    for path in files:
        if path.suffix.lower() not in {".tex", ".tmpl", ".cls", ".sty"}:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeError:
            errors.append(f"TeX source is not UTF-8: {path.relative_to(root)}")
            continue
        for pattern, reason in BANNED_TEX:
            if pattern.search(source):
                errors.append(f"unsafe {reason} in {path.relative_to(root)}")
    try:
        for path in runtime_files(root, manifest):
            relative = path.relative_to(root)
            if relative.parts and relative.parts[0] in RESERVED_RUNTIME_NAMES:
                errors.append(f"runtime file uses reserved name: {relative}")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"cannot resolve runtime files: {exc}")
    missing = missing_dependencies(root, manifest) if not errors else []
    return errors, missing, manifest


def apply_tokens(source: str, values: dict[str, object]) -> str:
    def conditional(match: re.Match[str]) -> str:
        return match.group(2) if str(values.get(match.group(1), "")) else ""

    rendered = CONDITIONAL.sub(conditional, source)
    rendered = TOKEN.sub(lambda match: str(values.get(match.group(1), "")), rendered)
    leftovers = re.findall(r"\[\[JAA:[^]]+\]\]", rendered)
    if leftovers:
        raise ValueError("unresolved template tokens: " + ", ".join(sorted(set(leftovers))))
    return rendered


def render_resume(
    template_dir: Path,
    bundle: dict[str, Any],
    *,
    layout: str | None = None,
    extra_values: dict[str, object] | None = None,
) -> str:
    root = template_dir.expanduser().resolve()
    manifest = load_manifest(root)
    fragments = {
        name: safe_relative(root, path).read_text(encoding="utf-8")
        for name, path in manifest["fragments"].items()
    }

    def render_highlights(item: dict[str, Any]) -> str:
        return "".join(
            apply_tokens(fragments["highlight"], {"TEXT": latex_escape(text_of(value))})
            for value in item.get("highlights", [])
        )

    def render_item(item: dict[str, Any]) -> str:
        kind = item["type"]
        fields = ENTRY_FIELDS[kind]
        values: dict[str, object] = {}
        for field in fields:
            key = field.lower()
            if field == "HIGHLIGHTS":
                values[field] = render_highlights(item)
            elif field == "AUTHORS":
                values[field] = latex_escape(", ".join(item.get("authors", [])))
            else:
                values[field] = latex_escape(item.get(key, ""))
        return apply_tokens(fragments[kind], values)

    def render_section(section: dict[str, Any]) -> str:
        return apply_tokens(fragments["section"], {
            "TITLE": latex_escape(section["title"]),
            "ITEMS": "".join(render_item(item) for item in section["items"]),
        })

    sections = bundle.get("resume_sections", [])
    if layout is None:
        layout = manifest["id"] if root.parent.name == "builtin" else "sequential"
    if layout not in {"sequential", "international", "france"}:
        raise ValueError(f"unknown LaTeX template layout: {layout}")
    if layout == "france":
        sidebar_sections = [
            section for section in sections
            if section.get("items")
            and all(item.get("type") == "one_line" for item in section["items"])
        ]
        main_sections = [section for section in sections if section not in sidebar_sections]
    else:
        sidebar_sections, main_sections = [], sections

    candidate = bundle["candidate"]
    contact = r" \textbar\ ".join(latex_escape(value) for value in candidate.get("contact", []))
    main = safe_relative(root, manifest["main"]).read_text(encoding="utf-8")
    values: dict[str, object] = {
        "NAME": latex_escape(candidate.get("name", "")),
        "HEADLINE": latex_escape(candidate.get("headline", "")),
        "LOCATION": latex_escape(candidate.get("location", "")),
        "CONTACT": contact,
        "PROFILE": latex_escape(text_of(candidate.get("summary", ""))),
        "SIDEBAR_SECTIONS": "".join(render_section(section) for section in sidebar_sections),
        "SECTIONS": "".join(render_section(section) for section in main_sections),
    }
    for key, value in (extra_values or {}).items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"invalid extra template token: {key}")
        if key in values:
            raise ValueError(f"extra template token overrides a reserved field: {key}")
        values[key] = latex_escape(value)
    return apply_tokens(main, values)
