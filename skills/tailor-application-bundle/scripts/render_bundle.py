#!/usr/bin/env python3
"""Render, promote, and safely rebuild reviewed LaTeX application bundles."""

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
import unicodedata
from typing import Any
from uuid import uuid4

import latex_templates

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from job_application_agents.render_service.artifacts import ArtifactStore
from job_application_agents.render_service.client import RenderServiceClient, deterministic_key
from job_application_agents.render_service.compiler import compile_request
from job_application_agents.render_service.config import artifact_root, firebase_project_id
from job_application_agents.config import ConfigurationError, load_render_config
from job_application_agents.render_service.firestore import FirestoreRenderJobRepository
from job_application_agents.render_service.models import ArtifactRef, CompileDocument, RenderRequest

SUBPROCESS_TIMEOUT_SECONDS = 60
PROFILES = ("auto", "international", "france")
FRANCE_LOCATION_TOKENS = {
    "france", "paris", "lyon", "marseille", "toulouse", "bordeaux", "lille",
    "nantes", "strasbourg", "montpellier", "rennes", "grenoble", "nice",
    "sophia antipolis",
}
def required(value: object, name: str) -> None:
    if value is None or value == "" or value == []:
        raise ValueError(f"missing required field: {name}")


def validate(bundle: dict[str, Any]) -> None:
    if bundle.get("schema_version") != 5:
        raise ValueError("schema_version must be 5")
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
    if analysis.get("credibility_warnings"):
        lines.extend(["", "## Credibility Warnings"])
        lines.extend(f"- {warning}" for warning in analysis["credibility_warnings"])
    return "\n".join(lines).strip() + "\n"


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
        return {"template": "international", "page": {"size": "us-letter"}}, 1
    if profile != "france":
        raise ValueError(f"unknown rendering profile: {profile}")
    design: dict[str, Any] = {
        "template": "france",
        "page": {"size": "a4", "show_footer": False, "show_top_note": False},
        "layout": {"columns": 2, "sidebar": "one_line sections"},
    }
    if with_photo:
        design["photo"] = {"shape": "circle", "position": "sidebar"}
    return design, 1


LATEX_SPECIAL_CHARS = str.maketrans({
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}",
    "\\": r"\textbackslash{}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
})


def latex_escape(text: object) -> str:
    return str(text or "").translate(LATEX_SPECIAL_CHARS)


def _latex_preamble(skill_dir: Path) -> str:
    path = skill_dir / "assets" / "latex" / "preamble.tex"
    if not path.is_file():
        raise RuntimeError(f"LaTeX preamble not found: {path}")
    return path.read_text(encoding="utf-8")


def latex_preamble_for_profile(skill_dir: Path, profile: str) -> str:
    preamble = _latex_preamble(skill_dir)
    paper = "a4paper" if profile == "france" else "letterpaper"
    return preamble.replace("{{PAPER_SIZE}}", paper)


def latex_preamble_reference() -> str:
    """Keep generated documents readable and independently maintainable."""
    return "\\input{preamble.tex}"


def latex_cv_document(
    bundle: dict[str, Any],
    profile: str = "international",
    photo_name: str | None = None,
    job: dict[str, Any] | None = None,
    skill_dir: Path | None = None,
) -> str:
    del job  # Locale and content are already fixed in the reviewed bundle.
    if skill_dir is None:
        skill_dir = Path(__file__).resolve().parent.parent
    template_dir = builtin_template(skill_dir, profile)
    return latex_templates.render_resume(
        template_dir,
        bundle,
        layout=profile,
        extra_values={"PHOTO": photo_name or ""},
    )


def latex_letter_document(
    bundle: dict[str, Any],
    skill_dir: Path | None = None,
) -> str:
    if skill_dir is None:
        skill_dir = Path(__file__).resolve().parent.parent
    letter = bundle["motivation_letter"]
    candidate_name = latex_escape(bundle["candidate"]["name"])
    date = latex_escape(letter.get("date", ""))
    recipient = latex_escape(letter.get("recipient", ""))
    subject = latex_escape(letter.get("subject", ""))
    salutation = latex_escape(letter.get("salutation", "Dear Hiring Team,"))
    closing = latex_escape(letter.get("closing", "Sincerely,"))
    signature = latex_escape(letter.get("signature", bundle["candidate"]["name"]))
    paragraphs = []
    for p in letter["paragraphs"]:
        paragraphs.append(f"\\noindent {latex_escape(text_of(p))} \\par")
    body = "\n\n".join(paragraphs)
    return f"""{latex_preamble_reference()}

\\begin{{document}}

\\hfill {date}

\\vspace{{1em}}

{recipient}

\\vspace{{1em}}

\\noindent\\textbf{{{subject}}}

\\vspace{{1em}}

{salutation}

\\vspace{{0.5em}}

{body}

\\vspace{{1em}}

{closing}

\\vspace{{0.5em}}

{signature}

\\end{{document}}
"""


def render_resume_latex(tex_path: Path, out_dir: Path, max_pages: int) -> dict[str, int]:
    xelatex = shutil.which("xelatex")
    if not xelatex:
        raise RuntimeError("xelatex is required for LaTeX resume rendering")
    for _pass in range(2):
        result = subprocess.run(
            [xelatex, "-no-shell-escape", "-halt-on-error", "-file-line-error",
             "-interaction=nonstopmode", "-output-directory", str(out_dir), str(tex_path)],
            cwd=out_dir, text=True, capture_output=True, timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        if result.returncode:
            raise RuntimeError("xelatex failed: " + (result.stderr.strip() or result.stdout.strip()[-500:]))
    return inspect_pdf(out_dir / "resume.pdf", "resume", max_pages)


def to_letter_pdf_latex(tex_path: Path, out_dir: Path) -> dict[str, int]:
    xelatex = shutil.which("xelatex")
    if not xelatex:
        raise RuntimeError("xelatex is required for LaTeX letter rendering")
    for _pass in range(2):
        result = subprocess.run(
            [xelatex, "-no-shell-escape", "-halt-on-error", "-file-line-error",
             "-interaction=nonstopmode", "-output-directory", str(out_dir), str(tex_path)],
            cwd=out_dir, text=True, capture_output=True, timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        if result.returncode:
            raise RuntimeError("xelatex failed: " + (result.stderr.strip() or result.stdout.strip()[-500:]))
    src = out_dir / (tex_path.stem + ".pdf")
    dst = out_dir / "motivation-letter.pdf"
    if src != dst and src.is_file():
        src.rename(dst)
    return inspect_pdf(dst, "motivation letter", 1)


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


def normalized_pdf_text(path: Path, *, raw: bool = False) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("pdftotext is required for PDF text fingerprinting")
    command = [pdftotext, "-raw", str(path), "-"] if raw else [pdftotext, str(path), "-"]
    result = subprocess.run(
        command, text=True, capture_output=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"could not extract text from {path.name}")
    return " ".join(result.stdout.split())


def reading_order_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())


def resume_order_anchors(bundle: dict[str, Any], profile: str = "international") -> list[str]:
    primary_fields = {
        "experience": "company", "education": "institution", "normal": "name",
        "one_line": "label", "publication": "title",
        "bullet": "text", "numbered": "text", "reversed_numbered": "text", "text": "text",
    }

    def section_anchors(sections: list[dict[str, Any]]) -> list[object]:
        values: list[object] = []
        for section in sections:
            values.append(section.get("title"))
            for item in section.get("items", []):
                values.append(item.get(primary_fields.get(item.get("type"), "text")))
                values.extend(text_of(highlight) for highlight in item.get("highlights", []))
        return values

    candidate = bundle.get("candidate", {})
    summary = candidate.get("summary", {})
    sections = bundle.get("resume_sections", [])
    if profile == "france":
        sidebar = [
            section for section in sections
            if section.get("items")
            and all(item.get("type") == "one_line" for item in section["items"])
        ]
        main = [section for section in sections if section not in sidebar]
        # The France two-column template places the name, headline, and profile
        # in the main flow before the sidebar content in PDF extraction order.
        # Keep the check aligned with that deterministic template order.
        anchors = [
            candidate.get("name"), candidate.get("headline"),
            text_of(summary) if summary else None, *section_anchors(sidebar),
            *section_anchors(main),
        ]
    else:
        anchors = [
            candidate.get("name"), candidate.get("headline"),
            text_of(summary) if summary else None, *section_anchors(sections),
        ]
    return [text for value in anchors if len(text := reading_order_text(value)) >= 3]


def verify_resume_reading_order(
    bundle: dict[str, Any], pdf_path: Path, profile: str = "international",
) -> None:
    verify_resume_reading_order_text(
        bundle, normalized_pdf_text(pdf_path, raw=profile == "france"), profile
    )


def verify_resume_reading_order_text(
    bundle: dict[str, Any], extracted_text: str, profile: str = "international",
) -> None:
    extracted = reading_order_text(extracted_text)
    if profile == "france":
        # Two-column A4 layouts interleave columns by vertical position during
        # PDF extraction. Verify that every authored anchor is present, while
        # leaving strict sequence validation to the single-flow profile.
        missing = [anchor for anchor in resume_order_anchors(bundle, profile) if anchor not in extracted]
        if missing:
            raise RuntimeError(
                "resume PDF reading order is missing authored content near: "
                + missing[0][:80]
            )
        return
    cursor = 0
    for anchor in resume_order_anchors(bundle, profile):
        position = extracted.find(anchor, cursor)
        if position < 0:
            preview = anchor[:80]
            raise RuntimeError(f"resume PDF reading order is missing or reordered near: {preview}")
        cursor = position + len(anchor)


def document_text_hashes(directory: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256(normalized_pdf_text(directory / name).encode("utf-8")).hexdigest()
        for name in ("resume.pdf", "motivation-letter.pdf")
    }


def preflight_rendering(skill_dir: Path, *, builtin_latex: bool = True) -> None:
    missing = [
        tool for tool in ("xelatex", "kpsewhich", "pdfinfo", "pdftotext")
        if not shutil.which(tool)
    ]
    if builtin_latex and not missing:
        # The built-in templates depend on Font Awesome. Report the package as
        # a missing runtime dependency so callers can skip/fail clearly rather
        # than discovering it halfway through a generated document.
        package_check = subprocess.run(
            ["kpsewhich", "fontawesome5.sty"],
            capture_output=True,
            text=True,
            check=False,
        )
        if not package_check.stdout.strip():
            missing.append("fontawesome5.sty")
        for profile in ("international", "france"):
            try:
                builtin_template(skill_dir, profile)
            except ValueError as exc:
                missing.append(str(exc))
    if missing:
        raise RuntimeError("required rendering tools are missing: " + ", ".join(missing))


def render_service_client() -> RenderServiceClient:
    return RenderServiceClient(
        FirestoreRenderJobRepository(firebase_project_id()), ArtifactStore(artifact_root())
    )


def local_render_available() -> bool:
    return all(shutil.which(tool) for tool in ("xelatex", "kpsewhich", "pdfinfo", "pdftotext"))


def compile_locally(
    source_dir: Path,
    output_dir: Path,
    *,
    max_resume_pages: int,
    required_packages: tuple[str, ...],
    required_fonts: tuple[str, ...],
) -> dict[str, Any]:
    """Compile through the same bounded compiler used by the cloud worker."""
    source_paths = sorted(path for path in source_dir.rglob("*") if path.is_file())
    fingerprint = deterministic_key("local-input", *source_paths)
    request = RenderRequest(
        request_id=str(uuid4()),
        input_artifact=ArtifactRef(
            key=fingerprint,
            sha256=hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
            bytes=sum(path.stat().st_size for path in source_paths),
        ),
        documents=(
            CompileDocument(
                source="resume.tex", output="resume.pdf", passes=2,
                max_pages=max_resume_pages, extract_raw_text=True,
            ),
            CompileDocument(
                source="letter.tex", output="motivation-letter.pdf", passes=2,
                max_pages=1, extract_raw_text=False,
            ),
        ),
        required_packages=required_packages,
        required_fonts=required_fonts,
    )
    return compile_request(request, source_dir, output_dir)


def compile_with_render_service(
    source_dir: Path, output_dir: Path, *, max_resume_pages: int = 1,
    idempotency_prefix: str = "stage", required_packages: tuple[str, ...] = (),
    required_fonts: tuple[str, ...] = (),
) -> dict[str, Any]:
    source_paths = sorted(path for path in source_dir.rglob("*") if path.is_file())
    key = deterministic_key(
        idempotency_prefix, *source_paths,
        options={
            "max_resume_pages": max_resume_pages, "protocol": 1,
            "required_packages": required_packages, "required_fonts": required_fonts,
        },
    )
    render_config = load_render_config()
    if render_config.mode == "local" or (
        render_config.mode == "auto" and local_render_available()
    ):
        return compile_locally(
            source_dir, output_dir, max_resume_pages=max_resume_pages,
            required_packages=required_packages, required_fonts=required_fonts,
        )
    return render_service_client().compile_and_wait(
        source_dir,
        (
            CompileDocument(
                source="resume.tex", output="resume.pdf", passes=2,
                max_pages=max_resume_pages, extract_raw_text=True,
            ),
            CompileDocument(
                source="letter.tex", output="motivation-letter.pdf", passes=2,
                max_pages=1, extract_raw_text=False,
            ),
        ),
        output_dir,
        idempotency_key=key,
        required_packages=required_packages,
        required_fonts=required_fonts,
    )


def builtin_template(skill_dir: Path, profile: str) -> Path:
    if profile not in {"international", "france"}:
        raise ValueError(f"unknown built-in LaTeX template: {profile}")
    path = (skill_dir / "assets" / "latex" / "builtin" / profile).resolve()
    errors, dependencies, manifest = latex_templates.validate_structure(path, check_dependencies=False)
    if errors:
        raise ValueError(f"invalid built-in {profile} template: " + "; ".join(errors))
    if dependencies:
        raise ValueError(
            f"built-in {profile} template dependencies are missing: " + ", ".join(dependencies)
        )
    if not manifest or manifest.get("id") != profile:
        raise ValueError(f"built-in {profile} template identity does not match its directory")
    return path


def custom_template(skill_dir: Path, template_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", template_id):
        raise ValueError("template must be 'builtin' or a lower-case slug")
    path = (skill_dir / "assets" / "latex" / "templates" / template_id).resolve()
    expected_root = (skill_dir / "assets" / "latex" / "templates").resolve()
    if path.parent != expected_root or not path.is_dir():
        raise ValueError(f"unknown LaTeX template: {template_id}")
    errors, dependencies, manifest = latex_templates.validate_structure(path, check_dependencies=False)
    if errors:
        raise ValueError("invalid LaTeX template: " + "; ".join(errors))
    if dependencies:
        raise ValueError("LaTeX template dependencies are missing: " + ", ".join(dependencies))
    if not manifest or manifest.get("id") != template_id:
        raise ValueError("LaTeX template identity does not match its directory")
    return path


def copy_custom_template(template_dir: Path, stage_dir: Path) -> list[str]:
    snapshot = stage_dir / "template-source"
    shutil.copytree(template_dir, snapshot)
    runtime_names: list[str] = []
    for source in latex_templates.runtime_files(template_dir):
        relative = source.relative_to(template_dir)
        target = stage_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        runtime_names.append(str(relative))
    return runtime_names


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_inventory(directory: Path) -> dict[str, dict[str, Any]]:
    excluded = {"manifest.json", "staging-manifest.json"}
    return {
        str(path.relative_to(directory)): {"sha256": sha256(path), "bytes": path.stat().st_size}
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name not in excluded
    }


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


def verify_bundle_for_render(bundle_path: Path, skill_dir: Path) -> tuple[dict[str, Any], bytes, bytes, bytes, bytes]:
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
    profiles_path = Path(inputs["role_profiles_json"]).expanduser().resolve()
    job_bytes = job_path.read_bytes()
    evidence_bytes = evidence_path.read_bytes()
    profiles_bytes = profiles_path.read_bytes()
    if hashlib.sha256(job_bytes).hexdigest() != inputs["job_sha256"]:
        raise ValueError("job input changed after bundle validation")
    if hashlib.sha256(evidence_bytes).hexdigest() != inputs["candidate_evidence_sha256"]:
        raise ValueError("candidate evidence changed after bundle validation")
    if hashlib.sha256(profiles_bytes).hexdigest() != inputs["role_profiles_sha256"]:
        raise ValueError("role profile catalog changed after bundle validation")
    return bundle, bundle_bytes, job_bytes, evidence_bytes, profiles_bytes


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
    bundle, bundle_bytes, job_bytes, evidence_bytes, profiles_bytes = verify_bundle_for_render(
        args.bundle_json.expanduser().resolve(), skill_dir
    )
    job = json.loads(job_bytes.decode("utf-8"))
    template_id = getattr(args, "template", "builtin")
    is_builtin = template_id == "builtin"
    if is_builtin:
        profile = resolve_profile(bundle, args.profile, job)
        if args.photo and profile != "france":
            raise ValueError("--photo is accepted only with the France profile")
        photo = validate_photo(args.photo) if args.photo else (
            discover_approved_photo() if profile == "france" else None
        )
        if profile == "france" and photo is None:
            raise ValueError(
                "France template requires an approved photo; pass --photo or add "
                "~/Documents/job-search/sources/profile-photo.jpg"
            )
        template_dir = builtin_template(skill_dir, profile)
        design, max_pages = profile_design(profile, photo is not None)
        letter_profile = profile
    else:
        if args.profile != "auto":
            raise ValueError("custom templates control their own layout; omit --profile")
        if args.photo:
            raise ValueError("custom templates do not accept --photo")
        template_dir = custom_template(skill_dir, template_id)
        profile, photo = "custom", None
        design, max_pages = {"page": {"size": "template"}}, 1
        letter_profile = resolve_profile(bundle, "auto", job)

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
        (stage_dir / "role-profiles.json").write_bytes(profiles_bytes)
        (stage_dir / "motivation-letter.md").write_text(letter_markdown(bundle), encoding="utf-8")
        (stage_dir / "match-analysis.md").write_text(match_markdown(bundle), encoding="utf-8")
        (stage_dir / "preamble.tex").write_text(
            latex_preamble_for_profile(skill_dir, letter_profile), encoding="utf-8"
        )

        runtime_names = copy_custom_template(template_dir, stage_dir)
        extra_values = {"PHOTO": photo_name or ""} if is_builtin else None
        resume_source = latex_templates.render_resume(
            template_dir,
            bundle,
            layout=profile if is_builtin else "sequential",
            extra_values=extra_values,
        )
        template_view = {
            "id": profile if is_builtin else template_id,
            "kind": "builtin" if is_builtin else "custom",
            "fingerprint": latex_templates.fingerprint(template_dir),
            "snapshot": "template-source",
            "runtime_files": runtime_names,
        }
        (stage_dir / "resume.tex").write_text(resume_source, encoding="utf-8")
        (stage_dir / "letter.tex").write_text(
            latex_letter_document(bundle, skill_dir),
            encoding="utf-8",
        )
        compile_source = Path(tempfile.mkdtemp(prefix="latex-source-", dir=staging_root))
        compile_output = Path(tempfile.mkdtemp(prefix="latex-output-", dir=staging_root))
        compile_names = ["resume.tex", "letter.tex", "preamble.tex", *runtime_names]
        if photo_name:
            compile_names.append(photo_name)
        template_manifest = latex_templates.load_manifest(template_dir)
        try:
            for name in compile_names:
                source = latex_templates.safe_relative(stage_dir, name)
                target = latex_templates.safe_relative(compile_source, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            compile_result = compile_with_render_service(
                compile_source, compile_output, max_resume_pages=max_pages,
                idempotency_prefix=getattr(args, "idempotency_prefix", "stage"),
                required_packages=tuple(template_manifest.get("required_packages", [])),
                required_fonts=tuple(template_manifest.get("required_fonts", [])),
            )
            for name in ("resume.pdf", "motivation-letter.pdf"):
                shutil.copy2(compile_output / name, stage_dir / name)
            resume_document = compile_result["documents"]["resume.pdf"]
            letter_document = compile_result["documents"]["motivation-letter.pdf"]
            # XeTeX's raw extraction can split accented glyphs in the middle of
            # words (notably in French), which creates false reading-order
            # failures even when the normalized PDF text is correctly ordered.
            # The normalized extraction still checks ordering while avoiding
            # font-encoding artefacts.
            text_name = resume_document["normalized_text"]
            verify_resume_reading_order_text(
                bundle, (compile_output / text_name).read_text(encoding="utf-8"),
                profile if profile == "france" else "international",
            )
            resume_quality = {
                "pages": resume_document["pages"],
                "text_chars": resume_document["text_chars"],
            }
            letter_quality = {
                "pages": letter_document["pages"],
                "text_chars": letter_document["text_chars"],
            }
            text_hashes = {
                "resume.pdf": resume_document["normalized_text_sha256"],
                "motivation-letter.pdf": letter_document["normalized_text_sha256"],
            }
        finally:
            shutil.rmtree(compile_source, ignore_errors=True)
            shutil.rmtree(compile_output, ignore_errors=True)
        resume_quality["reading_order"] = "passed"
        rendering = {
            "resume_engine": "latex",
            "profile": profile,
            "page_size": design["page"]["size"],
            "max_pages": max_pages,
            "photo": photo_name,
            "letter_engine": "latex",
            "template": template_view,
        }
        generated_dir = stage_dir / "generated"
        generated_dir.mkdir()
        for name in ("resume.tex", "letter.tex", "preamble.tex", "resume.pdf", "motivation-letter.pdf"):
            shutil.copy2(stage_dir / name, generated_dir / name)

        artifacts = artifact_inventory(stage_dir)
        staging_manifest = {
            "schema_version": 2,
            "application_root": str(application_root),
            "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
            "job": bundle["job"],
            "inputs": bundle["inputs"],
            "rendering": rendering,
            "quality": {"resume": resume_quality, "motivation_letter": letter_quality},
            "document_text_sha256": text_hashes,
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
    artifacts = artifact_inventory(stage_dir)
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
            "schema_version": 3,
            "version": out_dir.name,
            "application_root": str(application_root),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "job": staging["job"],
            "inputs": staging["inputs"],
            "input_snapshots": {
                "job_json": "job.json",
                "candidate_evidence_json": "candidate-evidence.json",
                "role_profiles_json": "role-profiles.json",
            },
            "semantic_review": {
                "verdict": "accept",
                "status": "fresh",
                "snapshot": "tailoring-review.json",
                "sha256": artifacts["tailoring-review.json"]["sha256"],
                "bundle_sha256": review["inputs"]["bundle_sha256"],
            },
            "rendering": staging["rendering"],
            "document_revision": 0,
            "source_provenance": "agent_generated",
            "manual_revisions": [],
            "document_text_sha256": staging["document_text_sha256"],
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
        maybe_sync_application_to_firestore(application_root)
        return out_dir


def maybe_sync_application_to_firestore(application_root: Path) -> None:
    if os.environ.get("JAA_SYNC_FIRESTORE") == "1":
        try:
            from job_application_agents.render_service.config import firebase_project_id, get_user_id
            from job_application_agents.sync.firestore import FirestoreUserSyncRepository
            from job_application_agents.sync.service import SyncService

            data_root = application_root.parents[2] if len(application_root.parents) >= 3 else Path.home() / "Documents" / "job-search"
            project = firebase_project_id()
            user = get_user_id(data_root)
            sync_svc = SyncService(FirestoreUserSyncRepository(project), default_data_root=data_root)
            sync_svc.push_application_directory(user, application_root)
        except Exception as exc:
            print(f"note: firestore application sync skipped or failed: {exc}", file=sys.stderr)


def rebuild_current_version(version_dir: Path, skill_dir: Path) -> Path:
    version_dir = version_dir.expanduser().resolve()
    manifest_path = version_dir / "manifest.json"
    manifest = load_json_object(manifest_path)
    if manifest.get("schema_version") != 3:
        raise ValueError("manual rebuilding requires a schema-3 LaTeX version")
    if manifest.get("rendering", {}).get("resume_engine") != "latex":
        raise ValueError("manual rebuilding is available only for LaTeX versions")
    application_root = version_dir.parent.resolve()
    current_path = application_root / "current.json"
    current = load_json_object(current_path)
    if current.get("version") != version_dir.name and Path(current.get("path", "")).expanduser().resolve() != version_dir:
        raise ValueError("only the version referenced by current.json may be rebuilt")
    required = ("resume.tex", "letter.tex", "preamble.tex")
    missing = [name for name in required if not (version_dir / name).is_file()]
    if missing:
        raise ValueError("missing editable LaTeX source: " + ", ".join(missing))
    editable_outputs = set(required) | {"resume.pdf", "motivation-letter.pdf"}
    for name, metadata in manifest.get("artifacts", {}).items():
        if name in editable_outputs:
            continue
        path = version_dir / name
        if not path.is_file() or sha256(path) != metadata.get("sha256") or path.stat().st_size != metadata.get("bytes"):
            raise ValueError(f"non-editable version artifact changed or is missing: {name}")

    profile = manifest.get("rendering", {}).get("profile", "international")
    max_pages = int(manifest.get("rendering", {}).get("max_pages", 1))
    revision = int(manifest.get("document_revision", 0)) + 1
    rebuild_dir = Path(tempfile.mkdtemp(prefix=".latex-rebuild-", dir=version_dir.parent))
    try:
        for name in required:
            shutil.copy2(version_dir / name, rebuild_dir / name)
        for name in manifest.get("rendering", {}).get("template", {}).get("runtime_files", []):
            source = latex_templates.safe_relative(version_dir, name)
            if not source.is_file():
                raise ValueError(f"template runtime file is missing: {name}")
            target = latex_templates.safe_relative(rebuild_dir, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        photo_name = manifest.get("rendering", {}).get("photo")
        if photo_name:
            photo_path = version_dir / photo_name
            if not photo_path.is_file():
                raise ValueError(f"manifest photo is missing: {photo_name}")
            shutil.copy2(photo_path, rebuild_dir / photo_name)
        compile_output = Path(tempfile.mkdtemp(prefix="latex-output-", dir=version_dir.parent))
        try:
            frozen_manifest_path = version_dir / "template-source" / "template.json"
            frozen_template_manifest = (
                load_json_object(frozen_manifest_path) if frozen_manifest_path.is_file() else {}
            )
            compile_result = compile_with_render_service(
                rebuild_dir, compile_output, max_resume_pages=max_pages,
                idempotency_prefix=f"rebuild-r{revision:03d}",
                required_packages=tuple(frozen_template_manifest.get("required_packages", [])),
                required_fonts=tuple(frozen_template_manifest.get("required_fonts", [])),
            )
            for name in ("resume.pdf", "motivation-letter.pdf"):
                shutil.copy2(compile_output / name, rebuild_dir / name)
            resume_document = compile_result["documents"]["resume.pdf"]
            letter_document = compile_result["documents"]["motivation-letter.pdf"]
            resume_quality = {
                "pages": resume_document["pages"],
                "text_chars": resume_document["text_chars"],
            }
            letter_quality = {
                "pages": letter_document["pages"],
                "text_chars": letter_document["text_chars"],
            }
            new_text_hashes = {
                "resume.pdf": resume_document["normalized_text_sha256"],
                "motivation-letter.pdf": letter_document["normalized_text_sha256"],
            }
        finally:
            shutil.rmtree(compile_output, ignore_errors=True)
        previous_text_hashes = manifest.get("document_text_sha256", {})
        textual_change = new_text_hashes != previous_text_hashes

        revision_root = version_dir / "manual-revisions"
        revision_dir = revision_root / f"r{revision:03d}"
        if revision_dir.exists():
            raise ValueError(f"manual revision already exists: {revision_dir}")
        revision_dir.mkdir(parents=True)
        for name in required + ("resume.pdf", "motivation-letter.pdf"):
            source = rebuild_dir / name
            shutil.copy2(source, revision_dir / name)
        for name in ("resume.pdf", "motivation-letter.pdf"):
            os.replace(rebuild_dir / name, version_dir / name)

        rebuilt_at = datetime.now(timezone.utc).isoformat()
        revisions = list(manifest.get("manual_revisions", []))
        revisions.append({
            "revision": revision,
            "path": str(revision_dir.relative_to(version_dir)),
            "rebuilt_at": rebuilt_at,
            "textual_change": textual_change,
            "document_text_sha256": new_text_hashes,
        })
        manifest["document_revision"] = revision
        manifest["source_provenance"] = "user_modified"
        manifest["manual_revisions"] = revisions
        manifest["document_text_sha256"] = new_text_hashes
        manifest["quality_gate"]["resume"] = resume_quality
        manifest["quality_gate"]["motivation_letter"] = letter_quality
        manifest["quality_gate"]["manual_rebuild"] = "passed"
        manifest["semantic_review"]["status"] = "stale" if textual_change else "fresh"
        manifest["semantic_review"]["stale_reason"] = (
            "Rendered document text changed after the accepted bundle review."
            if textual_change else None
        )
        manifest["artifacts"] = artifact_inventory(version_dir)
        atomic_json(manifest_path, manifest)
        maybe_sync_application_to_firestore(application_root)
        return version_dir
    finally:
        shutil.rmtree(rebuild_dir, ignore_errors=True)


def accept_manual_edit_review(version_dir: Path, review_path: Path, skill_dir: Path) -> Path:
    version_dir = version_dir.expanduser().resolve()
    review_path = review_path.expanduser().resolve()
    manifest_path = version_dir / "manifest.json"
    application_root = version_dir.parent.resolve()
    current = load_json_object(application_root / "current.json")
    if current.get("version") != version_dir.name and Path(current.get("path", "")).expanduser().resolve() != version_dir:
        raise ValueError("only the current version may receive a manual-edit review")
    validator_path = skill_dir / "scripts" / "validate_manual_edit_review.py"
    spec = importlib.util.spec_from_file_location("manual_edit_validator", validator_path)
    if not spec or not spec.loader:
        raise RuntimeError("could not load manual edit review validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    review = load_json_object(review_path)
    errors = module.validate(review, version_dir)
    if errors:
        raise ValueError("manual edit review is invalid: " + "; ".join(errors))
    if review.get("verdict") != "accept":
        raise ValueError("manual edit review verdict must be accept")
    target_name = f"manual-edit-review-r{manifest['document_revision']:03d}.json"
    target = version_dir / target_name
    target.write_bytes(review_path.read_bytes())
    manifest["semantic_review"].update({
        "status": "fresh", "verdict": "accept", "stale_reason": None,
        "manual_review": target_name, "manual_review_sha256": sha256(target),
        "reviewed_document_text_sha256": manifest["document_text_sha256"],
    })
    manifest["artifacts"] = artifact_inventory(version_dir)
    atomic_json(manifest_path, manifest)
    maybe_sync_application_to_firestore(application_root)
    return version_dir


def main() -> int:
    skill_dir = Path(__file__).resolve().parent.parent
    try:
        render_config = load_render_config()
    except ConfigurationError as exc:
        print(f"render configuration invalid: {exc}", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-json", type=Path)
    parser.add_argument("--application-root", type=Path)
    parser.add_argument("--profile", choices=PROFILES, default=render_config.profile)
    parser.add_argument("--template", default=render_config.template, help="built-in renderer or an installed LaTeX template slug")
    parser.add_argument("--photo", type=Path, help="Explicitly approved local JPEG/PNG; France profile only")
    parser.add_argument("--stage", action="store_true", help="render into non-published staging")
    parser.add_argument("--promote", type=Path, metavar="STAGING_DIR", help="promote reviewed staging atomically")
    parser.add_argument("--rebuild-version", type=Path, metavar="VERSION_DIR", help="rebuild user-edited LaTeX in the current version")
    parser.add_argument("--accept-manual-review", type=Path, metavar="REVIEW_JSON", help="record an accepted evidence review for rebuilt documents")
    parser.add_argument("--manual-review-version", type=Path, metavar="VERSION_DIR", help="current version covered by --accept-manual-review")
    parser.add_argument("--review-json", type=Path, help="accepted semantic review required for promotion")
    parser.add_argument(
        "--idempotency-prefix", default="stage",
        help="render queue key prefix; use a new value to retry a terminal infrastructure failure",
    )
    parser.add_argument("--preflight", action="store_true", help="check rendering tools without rendering a bundle")
    args = parser.parse_args()
    if args.preflight:
        try:
            if render_config.mode == "cloud":
                render_service_client().preflight()
            elif render_config.mode == "auto" and not local_render_available():
                render_service_client().preflight()
            else:
                preflight_rendering(skill_dir, builtin_latex=args.template == "builtin")
            if args.template == "builtin":
                builtin_template(skill_dir, "international")
                builtin_template(skill_dir, "france")
            else:
                custom_template(skill_dir, args.template)
            print("render service ready")
            return 0
        except Exception as exc:
            print(f"render preflight failed: {exc}", file=sys.stderr)
            return 1
    if args.rebuild_version:
        if args.stage or args.promote:
            parser.error("--rebuild-version cannot be combined with --stage or --promote")
        try:
            print(rebuild_current_version(args.rebuild_version, skill_dir))
            return 0
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.accept_manual_review:
        if not args.manual_review_version:
            parser.error("--manual-review-version is required with --accept-manual-review")
        if args.stage or args.promote:
            parser.error("--accept-manual-review cannot be combined with --stage or --promote")
        try:
            print(accept_manual_edit_review(args.manual_review_version, args.accept_manual_review, skill_dir))
            return 0
        except Exception as exc:
            print(str(exc), file=sys.stderr)
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
