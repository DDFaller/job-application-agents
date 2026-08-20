#!/usr/bin/env python3
"""Render an immutable application bundle with a regional RenderCV profile."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse

RENDERCV_VERSION = "2.8"
SUBPROCESS_TIMEOUT_SECONDS = 60
PROFILES = ("auto", "international", "france")
FRANCE_LOCATION_TOKENS = {
    "france", "paris", "lyon", "marseille", "toulouse", "bordeaux", "lille",
    "nantes", "strasbourg", "montpellier", "rennes", "grenoble", "nice",
    "sophia antipolis",
}
LOCALES = {
    "ar": "arabic", "da": "danish", "de": "german", "en": "english", "es": "spanish",
    "fa": "persian", "fr": "french", "he": "hebrew", "hi": "hindi", "hu": "hungarian",
    "id": "indonesian", "it": "italian", "ja": "japanese", "ko": "korean", "nl": "dutch",
    "no": "norwegian_bokmål", "pt": "portuguese", "ru": "russian", "tr": "turkish",
    "vi": "vietnamese", "zh": "mandarin_chinese",
}


def required(value: object, name: str) -> None:
    if value is None or value == "" or value == []:
        raise ValueError(f"missing required field: {name}")


def validate(bundle: dict[str, Any]) -> None:
    if bundle.get("schema_version") != 4:
        raise ValueError("schema_version must be 4")
    required(bundle.get("job", {}).get("company"), "job.company")
    required(bundle.get("job", {}).get("role"), "job.role")
    required(bundle.get("candidate", {}).get("name"), "candidate.name")
    required(bundle.get("resume_sections"), "resume_sections")
    required(bundle.get("motivation_letter", {}).get("paragraphs"), "motivation_letter.paragraphs")


def text_of(value: object) -> str:
    return str(value.get("text", "")) if isinstance(value, dict) else str(value or "")


def resume_markdown(bundle: dict[str, Any]) -> str:
    c = bundle["candidate"]
    lines = [f"# {c['name']}"]
    if c.get("headline"):
        lines.extend(["", c["headline"]])
    if c.get("contact"):
        lines.extend(["", " · ".join(c["contact"])])
    lines.extend(["", "## Profile", "", text_of(c["summary"])])
    for section in bundle["resume_sections"]:
        lines.extend(["", f"## {section['title']}", ""])
        for item in section["items"]:
            kind = item["type"]
            if kind == "experience":
                heading, detail = item["position"], " — ".join(x for x in (item["company"], item.get("dates")) if x)
            elif kind == "education":
                heading, detail = item["institution"], " — ".join(x for x in (item.get("degree"), item["area"], item.get("dates")) if x)
            elif kind == "normal":
                heading, detail = item["name"], item.get("dates") or ""
            elif kind == "one_line":
                lines.append(f"- **{item['label']}:** {item['details']}")
                continue
            elif kind == "publication":
                heading, detail = item["title"], ", ".join(item["authors"])
            else:
                prefix = "- " if kind in {"bullet", "text"} else "1. "
                lines.append(prefix + item["text"])
                continue
            lines.append(f"### {heading}")
            if detail:
                lines.extend(["", detail])
            if item.get("summary"):
                lines.extend(["", item["summary"]])
            lines.extend(f"- {text_of(x)}" for x in item.get("highlights", []))
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def letter_markdown(bundle: dict[str, Any]) -> str:
    letter = bundle["motivation_letter"]
    lines: list[str] = []
    for field in ("date", "recipient"):
        if letter.get(field):
            lines.extend(([""] if lines else []) + [letter[field]])
    if letter.get("subject"):
        lines.extend(["", f"**{letter['subject']}**"])
    lines.extend(["", letter.get("salutation", "Dear Hiring Team,"), ""])
    for paragraph in letter["paragraphs"]:
        lines.extend([text_of(paragraph), ""])
    lines.extend([letter.get("closing", "Sincerely,"), "", letter.get("signature", bundle["candidate"]["name"])])
    return "\n".join(lines).strip() + "\n"


def match_markdown(bundle: dict[str, Any]) -> str:
    analysis, strategy = bundle.get("match_analysis", {}), bundle.get("tailoring_strategy", {})
    lines = ["# Match Analysis", "", "## Tailoring Strategy", "", f"- Job family: {strategy.get('job_family', '')}", f"- Document focus: {strategy.get('document_focus', '')}", f"- Selection rationale: {text_of(strategy.get('selection_rationale'))}", "", "## Job Priorities"]
    lines.extend(f"- {text_of(x)}" for x in strategy.get("job_priorities", []))
    lines.extend(["", "## Fit Arguments"])
    lines.extend(f"- {text_of(x)}" for x in strategy.get("fit_arguments", []))
    for title, key in (("Matched", "matched"), ("Gaps", "gaps")):
        lines.extend(["", f"## {title}"])
        lines.extend(f"- {text_of(x)} — Evidence: {', '.join(x.get('candidate_evidence_ids', []) + x.get('job_evidence_keys', []))}" for x in analysis.get(key, []))
    return "\n".join(lines).strip() + "\n"


def yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def yaml_dump(value: Any, indent: int = 0) -> list[str]:
    pad = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if item is None or item == [] or item == {}:
                continue
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.extend(yaml_dump(item, indent + 2))
            else:
                lines.append(f"{pad}{key}: {yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                pairs = [(k, v) for k, v in item.items() if (v is not None or k == "url") and v != [] and v != {}]
                first_key, first_value = pairs[0]
                if isinstance(first_value, (dict, list)):
                    lines.append(f"{pad}- {first_key}:")
                    lines.extend(yaml_dump(first_value, indent + 4))
                else:
                    lines.append(f"{pad}- {first_key}: {yaml_scalar(first_value)}")
                for key, child in pairs[1:]:
                    if isinstance(child, (dict, list)):
                        lines.append(f"{pad}  {key}:")
                        lines.extend(yaml_dump(child, indent + 4))
                    else:
                        lines.append(f"{pad}  {key}: {yaml_scalar(child)}")
            else:
                lines.append(f"{pad}- {yaml_scalar(item)}")
        return lines
    return [pad + yaml_scalar(value)]


def contacts(values: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"social_networks": [], "custom_connections": []}
    emails, websites = [], []
    for value in values:
        clean = value.strip()
        if "@" in clean and not clean.lower().startswith(("http://", "https://")):
            emails.append(clean)
        elif clean.lower().startswith(("http://", "https://")):
            parsed = urlparse(clean)
            host = parsed.netloc.lower().removeprefix("www.")
            username = parsed.path.strip("/").split("/")[0]
            if host == "github.com" and username:
                result["social_networks"].append({"network": "GitHub", "username": username})
            elif host == "linkedin.com" and username == "in" and len(parsed.path.strip("/").split("/")) > 1:
                result["social_networks"].append({"network": "LinkedIn", "username": parsed.path.strip("/").split("/")[1]})
            else:
                websites.append(clean)
        else:
            result["custom_connections"].append({"fontawesome_icon": "phone", "placeholder": clean, "url": None})
    if emails: result["email"] = emails
    if websites: result["website"] = websites
    return {k: v for k, v in result.items() if v}


def rendercv_entry(item: dict[str, Any]) -> Any:
    kind = item["type"]
    highlights = [text_of(x) for x in item.get("highlights", [])]
    if kind == "experience":
        return {"company": item["company"], "position": item["position"], "location": item.get("location"), "date": item.get("dates"), "summary": item.get("summary"), "highlights": highlights}
    if kind == "education":
        return {"institution": item["institution"], "area": item["area"], "degree": item.get("degree"), "location": item.get("location"), "date": item.get("dates"), "summary": item.get("summary"), "highlights": highlights}
    if kind == "normal":
        return {"name": item["name"], "location": item.get("location"), "date": item.get("dates"), "summary": item.get("summary"), "highlights": highlights}
    if kind == "one_line":
        return {"label": item["label"], "details": item["details"]}
    if kind == "publication":
        return {"title": item["title"], "authors": item["authors"], "journal": item.get("journal"), "date": item.get("dates"), "doi": item.get("doi"), "url": item.get("url"), "summary": item.get("summary")}
    prefixes = {"numbered": "number", "reversed_numbered": "reversed_number"}
    return {prefixes.get(kind, "bullet" if kind == "bullet" else "text"): item["text"]}


def job_locale(bundle: dict[str, Any], job: dict[str, Any] | None = None) -> str:
    if job is None:
        job = load_job(bundle)
    try:
        language = str(job.get("language") or "english").strip().lower().replace("_", "-")
    except (AttributeError, TypeError):
        return "english"
    names = set(LOCALES.values())
    if language in names:
        return language
    return LOCALES.get(language.split("-")[0], "english")


def load_job(bundle: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(Path(bundle["inputs"]["job_json"]).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def resolve_profile(bundle: dict[str, Any], requested: str, job: dict[str, Any] | None = None) -> str:
    if requested not in PROFILES:
        raise ValueError(f"unknown rendering profile: {requested}")
    if requested != "auto":
        return requested
    if job is None:
        job = load_job(bundle)
    location = str(job.get("location") or bundle.get("job", {}).get("location") or "").casefold()
    return "france" if any(token in location for token in FRANCE_LOCATION_TOKENS) else "international"


def validate_photo(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"approved photo does not exist: {resolved}")
    if resolved.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("approved photo exceeds the 10 MB limit")
    signature = resolved.read_bytes()[:8]
    is_jpeg = signature.startswith(b"\xff\xd8\xff")
    is_png = signature == b"\x89PNG\r\n\x1a\n"
    suffix = resolved.suffix.lower()
    if not ((suffix in {".jpg", ".jpeg"} and is_jpeg) or (suffix == ".png" and is_png)):
        raise ValueError("approved photo must be a JPEG or PNG whose contents match its extension")
    return resolved


def discover_approved_photo() -> Path | None:
    source_dir = Path.home() / "Documents" / "job-search" / "sources"
    matches = [path for suffix in ("jpg", "jpeg", "png") if (path := source_dir / f"profile-photo.{suffix}").is_file()]
    if len(matches) > 1:
        raise ValueError("multiple approved profile-photo files found; pass --photo explicitly")
    return validate_photo(matches[0]) if matches else None


def profile_design(profile: str, with_photo: bool) -> tuple[dict[str, Any], int]:
    if profile == "international":
        return {"theme": "sb2nov", "page": {"size": "us-letter"}}, 1
    if profile != "france":
        raise ValueError(f"unknown rendering profile: {profile}")
    design: dict[str, Any] = {
        "theme": "classic",
        "page": {"size": "a4", "show_footer": False, "show_top_note": False},
        "header": {"alignment": "left"},
    }
    if with_photo:
        design["header"].update({"photo_width": "2.8cm", "photo_position": "left", "photo_space_right": "0.6cm"})
    return design, 1


def rendercv_document(
    bundle: dict[str, Any],
    profile: str = "international",
    photo_name: str | None = None,
    job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = bundle["candidate"]
    cv: dict[str, Any] = {"name": candidate["name"], "headline": candidate.get("headline"), "location": candidate.get("location")}
    if photo_name:
        cv["photo"] = photo_name
    cv.update(contacts(candidate.get("contact", [])))
    sections: dict[str, Any] = {"Profile": [text_of(candidate["summary"])]}
    for section in bundle["resume_sections"]:
        sections[section["title"]] = [rendercv_entry(item) for item in section["items"]]
    cv["sections"] = sections
    design, _ = profile_design(profile, bool(photo_name))
    return {
        "cv": cv,
        "design": design,
        "locale": {"language": job_locale(bundle, job)},
        "settings": {"current_date": "today", "render_command": {"dont_generate_png": True}, "pdf_title": f"{candidate['name']} - CV"},
    }


def roff_safe(value: object) -> str:
    lines = str(value or "").replace("\\", r"\e").splitlines() or [""]
    return "\n".join(r"\&" + line if line.startswith((".", "'")) else line for line in lines)


def letter_roff(bundle: dict[str, Any], style: str) -> str:
    letter = bundle["motivation_letter"]
    lines = [style, ".ps 11", roff_safe(letter.get("date", "")), ".sp 0.2i", roff_safe(letter.get("recipient", "")), ".sp 0.25i", ".ft B", roff_safe(letter.get("subject", "")), ".ft R", ".sp 0.2i", roff_safe(letter.get("salutation", "Dear Hiring Team,"))]
    for paragraph in letter["paragraphs"]:
        lines.extend([".sp 0.16i", roff_safe(text_of(paragraph))])
    lines.extend([".sp 0.2i", roff_safe(letter.get("closing", "Sincerely,")), ".br", roff_safe(letter.get("signature", bundle["candidate"]["name"]))])
    return "\n".join(lines) + "\n"


def to_letter_pdf(document: str, out_dir: Path) -> None:
    if not shutil.which("groff") or not shutil.which("ps2pdf"):
        raise RuntimeError("groff and ps2pdf are required for motivation-letter rendering")
    groff = subprocess.run(["groff", "-Kutf8", "-Tps"], input=document.encode(), capture_output=True, timeout=SUBPROCESS_TIMEOUT_SECONDS)
    if groff.returncode:
        raise RuntimeError(groff.stderr.decode(errors="replace").strip())
    gs = subprocess.run(["ps2pdf", "-", str(out_dir / "motivation-letter.pdf")], input=groff.stdout, capture_output=True, timeout=SUBPROCESS_TIMEOUT_SECONDS)
    if gs.returncode:
        raise RuntimeError(gs.stderr.decode(errors="replace").strip())


def rendercv_binary(skill_dir: Path) -> Path:
    binary = skill_dir / ".venv" / "bin" / "rendercv"
    if not binary.is_file():
        raise RuntimeError(f'RenderCV preflight failed: install with `python3 -m venv "{skill_dir / ".venv"}" && "{skill_dir / ".venv" / "bin" / "pip"}" install "rendercv[full]=={RENDERCV_VERSION}"`')
    check = subprocess.run([str(binary), "--version"], text=True, capture_output=True, timeout=SUBPROCESS_TIMEOUT_SECONDS)
    if check.returncode or RENDERCV_VERSION not in (check.stdout + check.stderr):
        raise RuntimeError(f"RenderCV preflight failed: expected version {RENDERCV_VERSION}")
    return binary


def render_resume(binary: Path, yaml_path: Path, out_dir: Path, max_pages: int) -> dict[str, int]:
    command = [str(binary), "render", str(yaml_path), "--pdf-path", str(out_dir / "resume.pdf"), "--typst-path", str(out_dir / "resume.typ"), "--markdown-path", str(out_dir / "resume.md"), "--dont-generate-html", "--dont-generate-png"]
    result = subprocess.run(command, cwd=out_dir, text=True, capture_output=True, timeout=SUBPROCESS_TIMEOUT_SECONDS)
    if result.returncode:
        raise RuntimeError("RenderCV failed: " + (result.stderr.strip() or result.stdout.strip()))
    pdfinfo = shutil.which("pdfinfo")
    pdftotext = shutil.which("pdftotext")
    if not pdfinfo or not pdftotext:
        raise RuntimeError("pdfinfo and pdftotext are required for resume quality checks")
    info = subprocess.run([pdfinfo, str(out_dir / "resume.pdf")], text=True, capture_output=True, timeout=SUBPROCESS_TIMEOUT_SECONDS)
    match = re.search(r"^Pages:\s+(\d+)$", info.stdout, re.MULTILINE)
    if info.returncode or not match:
        raise RuntimeError("could not determine resume page count")
    pages = int(match.group(1))
    if pages < 1 or pages > max_pages:
        raise RuntimeError(f"resume must contain 1-{max_pages} pages; rendered {pages} pages")
    extracted = subprocess.run([pdftotext, str(out_dir / "resume.pdf"), "-"], text=True, capture_output=True, timeout=SUBPROCESS_TIMEOUT_SECONDS)
    if extracted.returncode or not extracted.stdout.strip():
        raise RuntimeError("resume PDF has no extractable text")
    return {"pages": pages, "text_chars": len(extracted.stdout.strip())}


def inspect_pdf(path: Path, label: str, max_pages: int) -> dict[str, int]:
    """Run the same bounded, deterministic checks for every generated PDF."""
    pdfinfo = shutil.which("pdfinfo")
    pdftotext = shutil.which("pdftotext")
    if not pdfinfo or not pdftotext:
        raise RuntimeError("pdfinfo and pdftotext are required for PDF quality checks")
    info = subprocess.run([pdfinfo, str(path)], text=True, capture_output=True, timeout=SUBPROCESS_TIMEOUT_SECONDS)
    match = re.search(r"^Pages:\s+(\d+)$", info.stdout, re.MULTILINE)
    if info.returncode or not match:
        raise RuntimeError(f"could not determine {label} page count")
    pages = int(match.group(1))
    if pages < 1 or pages > max_pages:
        raise RuntimeError(f"{label} must contain 1-{max_pages} pages; rendered {pages} pages")
    extracted = subprocess.run([pdftotext, str(path), "-"], text=True, capture_output=True, timeout=SUBPROCESS_TIMEOUT_SECONDS)
    text_chars = len(extracted.stdout.strip())
    if extracted.returncode or text_chars == 0:
        raise RuntimeError(f"{label} PDF has no extractable text")
    return {"pages": pages, "text_chars": text_chars}


def preflight_rendering(skill_dir: Path) -> None:
    rendercv_binary(skill_dir)
    missing = [tool for tool in ("groff", "ps2pdf", "pdfinfo", "pdftotext") if not shutil.which(tool)]
    if missing:
        raise RuntimeError("required rendering tools are missing: " + ", ".join(missing))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def load_skill_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_bundle_for_render(bundle_path: Path, skill_dir: Path) -> tuple[dict[str, Any], bytes, bytes, bytes]:
    bundle_bytes = bundle_path.read_bytes()
    bundle = json.loads(bundle_bytes.decode("utf-8"))
    if not isinstance(bundle, dict):
        raise ValueError(f"{bundle_path} must contain an object")
    validate(bundle)
    validator = load_skill_module(skill_dir / "scripts" / "validate_bundle.py", "tailor_validate_bundle")
    template_path = skill_dir / "references" / "bundle-template.json"
    errors = validator.validate(bundle, validator.load(template_path), bundle_path)
    if errors:
        raise ValueError("bundle is not structurally valid: " + "; ".join(errors))
    inputs = bundle["inputs"]
    job_path = Path(inputs["job_json"]).expanduser().resolve()
    evidence_path = Path(inputs["candidate_evidence_json"]).expanduser().resolve()
    job_bytes = job_path.read_bytes()
    evidence_bytes = evidence_path.read_bytes()
    if hashlib.sha256(job_bytes).hexdigest() != inputs["job_sha256"]:
        raise ValueError("job input changed after bundle validation")
    if hashlib.sha256(evidence_bytes).hexdigest() != inputs["candidate_evidence_sha256"]:
        raise ValueError("candidate evidence changed after bundle validation")
    return bundle, bundle_bytes, job_bytes, evidence_bytes


def accepted_review(review_path: Path, staged_bundle: Path, skill_dir: Path) -> dict[str, Any]:
    validator = load_skill_module(
        skill_dir / "scripts" / "validate_tailoring_review.py",
        "tailor_validate_review",
    )
    review = validator.load(review_path)
    template = validator.load(skill_dir / "references" / "tailoring-review-template.json")
    errors = validator.validate(review, template)
    if errors:
        raise ValueError("tailoring review is invalid: " + "; ".join(errors))
    if review.get("verdict") != "accept":
        raise ValueError("tailoring review verdict must be accept")
    staged_hash = sha256(staged_bundle)
    if review.get("inputs", {}).get("bundle_sha256") != staged_hash:
        raise ValueError("tailoring review does not cover the staged bundle")
    return review


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def stage_bundle(args: argparse.Namespace, skill_dir: Path) -> Path:
    bundle, bundle_bytes, job_bytes, evidence_bytes = verify_bundle_for_render(
        args.bundle_json.expanduser().resolve(), skill_dir
    )
    job = json.loads(job_bytes.decode("utf-8"))
    profile = resolve_profile(bundle, args.profile, job)
    if args.photo and profile != "france":
        raise ValueError("--photo is accepted only with the France profile")
    photo = validate_photo(args.photo) if args.photo else (discover_approved_photo() if profile == "france" else None)
    design, max_pages = profile_design(profile, photo is not None)
    binary = rendercv_binary(skill_dir)
    application_root = args.application_root.expanduser().resolve()
    staging_root = application_root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix="bundle-", dir=staging_root))
    try:
        photo_name = None
        if photo:
            photo_name = "profile-photo" + photo.suffix.lower()
            shutil.copy2(photo, stage_dir / photo_name)
        (stage_dir / "bundle.json").write_bytes(bundle_bytes)
        (stage_dir / "job.json").write_bytes(job_bytes)
        (stage_dir / "candidate-evidence.json").write_bytes(evidence_bytes)
        (stage_dir / "resume.yaml").write_text(
            "# Generated deterministically from bundle.json\n"
            + "\n".join(yaml_dump(rendercv_document(bundle, profile, photo_name, job))) + "\n",
            encoding="utf-8",
        )
        (stage_dir / "motivation-letter.md").write_text(letter_markdown(bundle), encoding="utf-8")
        (stage_dir / "match-analysis.md").write_text(match_markdown(bundle), encoding="utf-8")
        resume_quality = render_resume(binary, stage_dir / "resume.yaml", stage_dir, max_pages)
        to_letter_pdf(letter_roff(bundle, args.style.read_text(encoding="utf-8")), stage_dir)
        letter_quality = inspect_pdf(stage_dir / "motivation-letter.pdf", "motivation letter", 1)
        artifacts = {
            path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in sorted(stage_dir.iterdir()) if path.is_file()
        }
        staging_manifest = {
            "schema_version": 1,
            "application_root": str(application_root),
            "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
            "job": bundle["job"],
            "inputs": bundle["inputs"],
            "rendering": {
                "resume_engine": "rendercv", "rendercv_version": RENDERCV_VERSION,
                "profile": profile, "theme": design["theme"],
                "page_size": design["page"]["size"], "max_pages": max_pages,
                "photo": photo_name, "letter_engine": "groff",
            },
            "quality": {"resume": resume_quality, "motivation_letter": letter_quality},
            "artifacts": artifacts,
        }
        atomic_json(stage_dir / "staging-manifest.json", staging_manifest)
        return stage_dir
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def promote_bundle(stage_dir: Path, review_path: Path, application_root: Path, skill_dir: Path) -> Path:
    stage_dir = stage_dir.expanduser().resolve()
    application_root = application_root.expanduser().resolve()
    expected_staging_root = application_root / ".staging"
    if stage_dir.parent != expected_staging_root or not stage_dir.is_dir():
        raise ValueError("staging directory must be an existing direct child of application-root/.staging")
    staging = load_json_object(stage_dir / "staging-manifest.json")
    if staging.get("application_root") != str(application_root):
        raise ValueError("staging manifest belongs to a different application root")
    for name, metadata in staging.get("artifacts", {}).items():
        path = stage_dir / name
        if not path.is_file() or sha256(path) != metadata.get("sha256") or path.stat().st_size != metadata.get("bytes"):
            raise ValueError(f"staged artifact changed or is missing: {name}")
    review = accepted_review(review_path.expanduser().resolve(), stage_dir / "bundle.json", skill_dir)
    review_target = stage_dir / "tailoring-review.json"
    review_target.write_bytes(review_path.expanduser().resolve().read_bytes())
    artifacts = {
        path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
        for path in sorted(stage_dir.iterdir())
        if path.is_file() and path.name not in {"staging-manifest.json", "manifest.json"}
    }
    application_root.mkdir(parents=True, exist_ok=True)
    lock_path = application_root / ".version.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        versions = [
            int(match.group(1)) for path in application_root.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
            and (match := re.fullmatch(r"v(\d{3})", path.name))
        ]
        version = max(versions, default=0) + 1
        out_dir = application_root / f"v{version:03d}"
        if out_dir.exists():
            raise RuntimeError(f"incomplete version directory already exists: {out_dir}")
        manifest = {
            "schema_version": 2,
            "version": out_dir.name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "job": staging["job"],
            "inputs": staging["inputs"],
            "input_snapshots": {"job_json": "job.json", "candidate_evidence_json": "candidate-evidence.json"},
            "semantic_review": {
                "verdict": "accept",
                "snapshot": "tailoring-review.json",
                "sha256": artifacts["tailoring-review.json"]["sha256"],
                "bundle_sha256": review["inputs"]["bundle_sha256"],
            },
            "rendering": staging["rendering"],
            "quality_gate": {
                "automated": "passed", "semantic_review": "accepted",
                "resume": staging["quality"]["resume"],
                "motivation_letter": staging["quality"]["motivation_letter"],
            },
            "artifacts": artifacts,
            "notion_page_url": None,
        }
        atomic_json(stage_dir / "manifest.json", manifest)
        (stage_dir / "staging-manifest.json").unlink()
        stage_dir.rename(out_dir)
        atomic_json(application_root / "current.json", {
            "version": manifest["version"],
            "path": str(out_dir),
            "manifest": str(out_dir / "manifest.json"),
        })
        return out_dir


def main() -> int:
    skill_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-json", type=Path)
    parser.add_argument("--application-root", type=Path)
    parser.add_argument("--style", type=Path, default=skill_dir / "assets" / "application.ms")
    parser.add_argument("--profile", choices=PROFILES, default="auto")
    parser.add_argument("--photo", type=Path, help="Explicitly approved local JPEG/PNG; France profile only")
    parser.add_argument("--stage", action="store_true", help="render into non-published staging")
    parser.add_argument("--promote", type=Path, metavar="STAGING_DIR", help="promote reviewed staging atomically")
    parser.add_argument("--review-json", type=Path, help="accepted semantic review required for promotion")
    parser.add_argument("--preflight", action="store_true", help="check rendering tools without rendering a bundle")
    args = parser.parse_args()
    if args.preflight:
        try:
            preflight_rendering(skill_dir)
            print("rendering tools ready")
            return 0
        except Exception as exc:
            print(f"render preflight failed: {exc}", file=sys.stderr)
            return 1
    if args.stage == bool(args.promote):
        parser.error("choose exactly one of --stage or --promote unless --preflight is used")
    if not args.application_root:
        parser.error("--application-root is required")
    if args.stage and not args.bundle_json:
        parser.error("--bundle-json is required with --stage")
    if args.promote and not args.review_json:
        parser.error("--review-json is required with --promote")
    try:
        output = stage_bundle(args, skill_dir) if args.stage else promote_bundle(
            args.promote, args.review_json, args.application_root, skill_dir
        )
        print(output)
        return 0
    except Exception as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
