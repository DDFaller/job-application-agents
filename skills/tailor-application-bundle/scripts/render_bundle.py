#!/usr/bin/env python3
"""Render an immutable application bundle with a regional RenderCV profile."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse

RENDERCV_VERSION = "2.8"
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


def job_locale(bundle: dict[str, Any]) -> str:
    try:
        job = json.loads(Path(bundle["inputs"]["job_json"]).read_text(encoding="utf-8"))
        language = str(job.get("language") or "english").strip().lower().replace("_", "-")
    except (OSError, ValueError, TypeError):
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


def resolve_profile(bundle: dict[str, Any], requested: str) -> str:
    if requested not in PROFILES:
        raise ValueError(f"unknown rendering profile: {requested}")
    if requested != "auto":
        return requested
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
        return {"theme": "sb2nov", "page": {"size": "us-letter"}}, 2
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


def rendercv_document(bundle: dict[str, Any], profile: str = "international", photo_name: str | None = None) -> dict[str, Any]:
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
        "locale": {"language": job_locale(bundle)},
        "settings": {"current_date": "today", "render_command": {"dont_generate_png": False}, "pdf_title": f"{candidate['name']} - CV"},
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
    groff = subprocess.run(["groff", "-Kutf8", "-Tps"], input=document.encode(), capture_output=True)
    if groff.returncode:
        raise RuntimeError(groff.stderr.decode(errors="replace").strip())
    gs = subprocess.run(["ps2pdf", "-", str(out_dir / "motivation-letter.pdf")], input=groff.stdout, capture_output=True)
    if gs.returncode:
        raise RuntimeError(gs.stderr.decode(errors="replace").strip())


def rendercv_binary(skill_dir: Path) -> Path:
    binary = skill_dir / ".venv" / "bin" / "rendercv"
    if not binary.is_file():
        raise RuntimeError(f'RenderCV preflight failed: install with `python3 -m venv "{skill_dir / ".venv"}" && "{skill_dir / ".venv" / "bin" / "pip"}" install "rendercv[full]=={RENDERCV_VERSION}"`')
    check = subprocess.run([str(binary), "--version"], text=True, capture_output=True)
    if check.returncode or RENDERCV_VERSION not in (check.stdout + check.stderr):
        raise RuntimeError(f"RenderCV preflight failed: expected version {RENDERCV_VERSION}")
    return binary


def render_resume(binary: Path, yaml_path: Path, out_dir: Path, max_pages: int) -> None:
    command = [str(binary), "render", str(yaml_path), "--pdf-path", str(out_dir / "resume.pdf"), "--typst-path", str(out_dir / "resume.typ"), "--markdown-path", str(out_dir / "resume.md"), "--png-path", str(out_dir / "resume.png"), "--dont-generate-html"]
    result = subprocess.run(command, cwd=out_dir, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("RenderCV failed: " + (result.stderr.strip() or result.stdout.strip()))
    pdfinfo = shutil.which("pdfinfo")
    pdftotext = shutil.which("pdftotext")
    if not pdfinfo or not pdftotext:
        raise RuntimeError("pdfinfo and pdftotext are required for resume quality checks")
    info = subprocess.run([pdfinfo, str(out_dir / "resume.pdf")], text=True, capture_output=True)
    match = re.search(r"^Pages:\s+(\d+)$", info.stdout, re.MULTILINE)
    if info.returncode or not match:
        raise RuntimeError("could not determine resume page count")
    pages = int(match.group(1))
    if pages > max_pages:
        raise RuntimeError(f"resume exceeds the {max_pages}-page limit: rendered {pages} pages")
    extracted = subprocess.run([pdftotext, str(out_dir / "resume.pdf"), "-"], text=True, capture_output=True)
    if extracted.returncode or not extracted.stdout.strip():
        raise RuntimeError("resume PDF has no extractable text")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    skill_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-json", required=True, type=Path)
    parser.add_argument("--application-root", required=True, type=Path)
    parser.add_argument("--style", type=Path, default=skill_dir / "assets" / "application.ms")
    parser.add_argument("--profile", choices=PROFILES, default="auto")
    parser.add_argument("--photo", type=Path, help="Explicitly approved local JPEG/PNG; France profile only")
    args = parser.parse_args()
    stage_dir: Path | None = None
    try:
        bundle = json.loads(args.bundle_json.read_text(encoding="utf-8"))
        validate(bundle)
        profile = resolve_profile(bundle, args.profile)
        if args.photo and profile != "france":
            raise ValueError("--photo is accepted only with the France profile")
        photo = validate_photo(args.photo) if args.photo else (discover_approved_photo() if profile == "france" else None)
        design, max_pages = profile_design(profile, photo is not None)
        binary = rendercv_binary(skill_dir)
        args.application_root.mkdir(parents=True, exist_ok=True)
        versions = [int(m.group(1)) for p in args.application_root.iterdir() if p.is_dir() and (p / "manifest.json").is_file() and (m := re.fullmatch(r"v(\d{3})", p.name))]
        version = max(versions, default=0) + 1
        out_dir = args.application_root / f"v{version:03d}"
        if out_dir.exists():
            raise RuntimeError(f"incomplete version directory already exists: {out_dir}")
        stage_dir = Path(tempfile.mkdtemp(prefix=f".v{version:03d}-", dir=args.application_root))
        photo_name = None
        if photo:
            photo_name = "profile-photo" + photo.suffix.lower()
            shutil.copy2(photo, stage_dir / photo_name)
        (stage_dir / "bundle.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (stage_dir / "resume.yaml").write_text("# Generated deterministically from bundle.json\n" + "\n".join(yaml_dump(rendercv_document(bundle, profile, photo_name))) + "\n", encoding="utf-8")
        (stage_dir / "motivation-letter.md").write_text(letter_markdown(bundle), encoding="utf-8")
        (stage_dir / "match-analysis.md").write_text(match_markdown(bundle), encoding="utf-8")
        render_resume(binary, stage_dir / "resume.yaml", stage_dir, max_pages)
        to_letter_pdf(letter_roff(bundle, args.style.read_text(encoding="utf-8")), stage_dir)
        for preview in stage_dir.glob("resume*.png"):
            preview.unlink()
        artifacts = {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size} for p in sorted(stage_dir.iterdir()) if p.is_file()}
        manifest = {"schema_version": 1, "version": f"v{version:03d}", "generated_at": datetime.now(timezone.utc).isoformat(), "job": bundle["job"], "inputs": bundle["inputs"], "rendering": {"resume_engine": "rendercv", "rendercv_version": RENDERCV_VERSION, "profile": profile, "theme": design["theme"], "page_size": design["page"]["size"], "max_pages": max_pages, "photo": photo_name, "letter_engine": "groff"}, "artifacts": artifacts, "notion_page_url": None}
        (stage_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        stage_dir.rename(out_dir)
        stage_dir = None
        current = {"version": manifest["version"], "path": str(out_dir.resolve()), "manifest": str((out_dir / "manifest.json").resolve())}
        (args.application_root / "current.json").write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        print(out_dir)
        return 0
    except Exception as exc:
        if stage_dir and stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        print(f"render failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
