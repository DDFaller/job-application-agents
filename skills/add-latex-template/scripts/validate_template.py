#!/usr/bin/env python3
"""Validate and compile-test one declarative XeLaTeX résumé template."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any


TAILOR_SKILL = Path(__file__).resolve().parents[2] / "tailor-application-bundle"
sys.path.insert(0, str(TAILOR_SKILL / "scripts"))
from latex_templates import fingerprint, render_resume, runtime_files, validate_structure  # noqa: E402


TIMEOUT = 60


def synthetic_bundle() -> dict[str, Any]:
    entries = [
        ("Experience Alpha", {"type": "experience", "company": "JaaExpCompanyOne", "position": "JaaExpRoleOne", "location": "JaaExpPlaceOne", "dates": "JaaExpDateOne", "summary": "JaaExpSummaryOne", "highlights": [{"text": "JaaExpHighlightOne"}]}),
        ("Experience Beta", {"type": "experience", "company": "JaaExpCompanyTwo", "position": "JaaExpRoleTwo", "location": "JaaExpPlaceTwo", "dates": "JaaExpDateTwo", "summary": "JaaExpSummaryTwo", "highlights": [{"text": "JaaExpHighlightTwo"}]}),
        ("Education Alpha", {"type": "education", "institution": "JaaEduSchoolOne", "area": "JaaEduAreaOne", "degree": "JaaEduDegreeOne", "location": "JaaEduPlaceOne", "dates": "JaaEduDateOne", "summary": "JaaEduSummaryOne", "highlights": [{"text": "JaaEduHighlightOne"}]}),
        ("Education Beta", {"type": "education", "institution": "JaaEduSchoolTwo", "area": "JaaEduAreaTwo", "degree": "JaaEduDegreeTwo", "location": "JaaEduPlaceTwo", "dates": "JaaEduDateTwo", "summary": "JaaEduSummaryTwo", "highlights": [{"text": "JaaEduHighlightTwo"}]}),
        ("Project", {"type": "normal", "name": "JaaProjectName", "location": "JaaProjectPlace", "dates": "JaaProjectDate", "summary": "JaaProjectSummary", "highlights": [{"text": "JaaProjectHighlight"}]}),
        ("Skills", {"type": "one_line", "label": "JaaSkillLabel", "details": "JaaSkillDetails"}),
        ("Publication", {"type": "publication", "title": "JaaPublicationTitle", "authors": ["JaaAuthorOne", "JaaAuthorTwo"], "journal": "JaaJournal", "dates": "JaaPublicationDate", "doi": "JaaDoi", "url": "JaaUrl", "summary": "JaaPublicationSummary"}),
        ("Bullet", {"type": "bullet", "text": "JaaBulletText"}),
        ("Numbered", {"type": "numbered", "text": "JaaNumberedText"}),
        ("Reverse", {"type": "reversed_numbered", "text": "JaaReverseText"}),
        ("Text", {"type": "text", "text": "JaaStandaloneText"}),
    ]
    return {
        "candidate": {
            "name": "JaaCandidateName", "headline": "JaaCandidateHeadline",
            "location": "JaaCandidateLocation", "contact": ["jaa@example.test"],
            "summary": {"text": "JaaCandidateProfile"},
        },
        "resume_sections": [{"title": title, "items": [item]} for title, item in entries],
    }


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def expected_anchors(bundle: dict[str, Any], layout: str = "sequential") -> list[str]:
    candidate = bundle["candidate"]
    primary = {
        "experience": "company", "education": "institution", "normal": "name",
        "one_line": "label", "publication": "title", "bullet": "text",
        "numbered": "text", "reversed_numbered": "text", "text": "text",
    }

    def section_anchors(sections: list[dict[str, Any]]) -> list[str]:
        values: list[str] = []
        for section in sections:
            values.append(section["title"])
            for item in section["items"]:
                values.append(item[primary[item["type"]]])
                values.extend(value["text"] for value in item.get("highlights", []))
        return values

    sections = bundle["resume_sections"]
    if layout == "france":
        sidebar = [
            section for section in sections
            if section["items"] and all(item["type"] == "one_line" for item in section["items"])
        ]
        main = [section for section in sections if section not in sidebar]
        anchors = [
            candidate["name"], *section_anchors(sidebar), candidate["headline"],
            candidate["summary"]["text"], *section_anchors(main),
        ]
    else:
        anchors = [candidate["name"], candidate["headline"], candidate["summary"]["text"], *section_anchors(sections)]
    return [normalized(value) for value in anchors]


def copy_runtime(template_dir: Path, output: Path) -> None:
    for source in runtime_files(template_dir):
        relative = source.relative_to(template_dir)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def compile_probe(template_dir: Path) -> dict[str, Any]:
    xelatex = shutil.which("xelatex")
    pdfinfo = shutil.which("pdfinfo")
    pdftotext = shutil.which("pdftotext")
    missing_tools = [name for name, value in (("xelatex", xelatex), ("pdfinfo", pdfinfo), ("pdftotext", pdftotext)) if not value]
    if missing_tools:
        raise RuntimeError("missing validation tools: " + ", ".join(missing_tools))
    bundle = synthetic_bundle()
    layout = "france" if template_dir.resolve().parent.name == "builtin" and template_dir.name == "france" else "sequential"
    with tempfile.TemporaryDirectory(prefix="jaa-template-probe-") as temporary:
        output = Path(temporary)
        copy_runtime(template_dir, output)
        (output / "resume.tex").write_text(render_resume(template_dir, bundle), encoding="utf-8")
        for _ in range(2):
            result = subprocess.run(
                [xelatex, "-no-shell-escape", "-halt-on-error", "-file-line-error", "-interaction=nonstopmode", "resume.tex"],
                cwd=output, capture_output=True, text=True, check=False, timeout=TIMEOUT,
            )
            if result.returncode:
                detail = result.stderr.strip() or result.stdout.strip()[-1200:]
                raise RuntimeError("synthetic XeLaTeX compile failed: " + detail)
        info = subprocess.run([pdfinfo, "resume.pdf"], cwd=output, capture_output=True, text=True, check=False, timeout=TIMEOUT)
        match = re.search(r"^Pages:\s+(\d+)$", info.stdout, re.MULTILINE)
        if info.returncode or not match:
            raise RuntimeError("could not inspect synthetic PDF page count")
        pages = int(match.group(1))
        if pages != 1:
            raise RuntimeError(f"synthetic résumé must render exactly one page; rendered {pages}")
        text_command = [pdftotext, "-raw", "resume.pdf", "-"] if layout == "france" else [pdftotext, "resume.pdf", "-"]
        extracted = subprocess.run(text_command, cwd=output, capture_output=True, text=True, check=False, timeout=TIMEOUT)
        if extracted.returncode or not extracted.stdout.strip():
            raise RuntimeError("synthetic résumé has no extractable text")
        text = normalized(extracted.stdout)
        cursor = 0
        for anchor in expected_anchors(bundle, layout):
            position = text.find(anchor, cursor)
            if position < 0:
                raise RuntimeError(f"synthetic résumé loses or reorders content near: {anchor}")
            cursor = position + len(anchor)
        return {"compiled": True, "pages": pages, "text_chars": len(extracted.stdout.strip()), "reading_order": "passed"}


def validate_template(template_dir: Path, *, compile_template: bool = True) -> tuple[int, dict[str, Any]]:
    root = template_dir.expanduser().resolve()
    errors, dependencies, manifest = validate_structure(root)
    report: dict[str, Any] = {
        "template": str(root), "id": manifest.get("id") if manifest else None,
        "fingerprint": fingerprint(root) if manifest and not errors else None,
        "files": [str(path.relative_to(root)) for path in sorted(root.rglob("*")) if path.is_file()] if root.is_dir() else [],
        "missing_dependencies": dependencies, "errors": errors, "quality": None,
    }
    if errors:
        return 1, report
    if dependencies:
        return 2, report
    if compile_template:
        try:
            report["quality"] = compile_probe(root)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            report["errors"].append(str(exc))
            return 1, report
    return 0, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="emit the compatibility report as JSON")
    parser.add_argument("--no-compile", action="store_true", help="run structural checks only")
    args = parser.parse_args()
    try:
        status, report = validate_template(args.template, compile_template=not args.no_compile)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        status, report = 1, {"template": str(args.template), "errors": [str(exc)]}
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for error in report.get("errors", []):
            print(f"template invalid: {error}", file=sys.stderr)
        for dependency in report.get("missing_dependencies", []):
            print(f"missing dependency: {dependency}", file=sys.stderr)
        if status == 0:
            print(f"valid LaTeX template: {args.template.expanduser().resolve()}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
