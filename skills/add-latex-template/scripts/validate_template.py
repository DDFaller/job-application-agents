#!/usr/bin/env python3
"""Validate and compile-test one declarative XeLaTeX résumé template."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any


TAILOR_SKILL = Path(__file__).resolve().parents[2] / "tailor-application-bundle"
sys.path.insert(0, str(TAILOR_SKILL / "scripts"))
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))
from latex_templates import fingerprint, load_manifest, render_resume, runtime_files, validate_structure  # noqa: E402
from job_application_agents.render_service.artifacts import ArtifactStore  # noqa: E402
from job_application_agents.render_service.client import RenderJobFailure, RenderServiceClient  # noqa: E402
from job_application_agents.render_service.config import artifact_root, firebase_project_id  # noqa: E402
from job_application_agents.render_service.firestore import FirestoreRenderJobRepository  # noqa: E402
from job_application_agents.render_service.models import CompileDocument  # noqa: E402


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
    bundle = synthetic_bundle()
    layout = "france" if template_dir.resolve().parent.name == "builtin" and template_dir.name == "france" else "sequential"
    with tempfile.TemporaryDirectory(prefix="jaa-template-probe-") as temporary:
        output = Path(temporary)
        copy_runtime(template_dir, output)
        (output / "resume.tex").write_text(render_resume(template_dir, bundle), encoding="utf-8")
        manifest = load_manifest(template_dir)
        client = RenderServiceClient(
            FirestoreRenderJobRepository(firebase_project_id()), ArtifactStore(artifact_root())
        )
        with tempfile.TemporaryDirectory(prefix="jaa-template-result-") as result_temporary:
            result_dir = Path(result_temporary)
            result = client.compile_and_wait(
                output,
                (CompileDocument(
                    "resume.tex", "resume.pdf", passes=2, max_pages=1,
                    extract_raw_text=layout == "france",
                ),),
                result_dir,
                idempotency_key=f"template-probe:{fingerprint(template_dir)}",
                required_packages=tuple(manifest.get("required_packages", [])),
                required_fonts=tuple(manifest.get("required_fonts", [])),
            )
            document = result["documents"]["resume.pdf"]
            text_file = document["raw_text"] if layout == "france" else document["normalized_text"]
            extracted = (result_dir / text_file).read_text(encoding="utf-8")
        text = normalized(extracted)
        cursor = 0
        for anchor in expected_anchors(bundle, layout):
            position = text.find(anchor, cursor)
            if position < 0:
                raise RuntimeError(f"synthetic résumé loses or reorders content near: {anchor}")
            cursor = position + len(anchor)
        return {
            "compiled": True, "pages": document["pages"],
            "text_chars": document["text_chars"], "reading_order": "passed",
        }


def validate_template(template_dir: Path, *, compile_template: bool = True) -> tuple[int, dict[str, Any]]:
    root = template_dir.expanduser().resolve()
    errors, dependencies, manifest = validate_structure(
        root, check_dependencies=not compile_template
    )
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
        except RenderJobFailure as exc:
            if exc.code == "MISSING_DEPENDENCY":
                report["missing_dependencies"] = [
                    value.strip() for value in exc.detail.split(",") if value.strip()
                ]
                return 2, report
            report["errors"].append(str(exc))
            return 1, report
        except (OSError, RuntimeError) as exc:
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
