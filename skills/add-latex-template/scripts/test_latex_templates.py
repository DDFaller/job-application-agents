#!/usr/bin/env python3
"""Tests for imported XeLaTeX template validation and rendering."""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
TAILOR_SCRIPTS = SCRIPT_DIR.parents[1] / "tailor-application-bundle" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(TAILOR_SCRIPTS))

import install_template  # noqa: E402
import latex_templates  # noqa: E402
import validate_template  # noqa: E402


def write_template(parent: Path, template_id: str = "compact-test") -> Path:
    root = parent / template_id
    fragments = root / ".jaa"
    fragments.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "id": template_id,
        "display_name": "Compact Test",
        "description": "Small deterministic one-column test template",
        "engine": "xelatex",
        "main": "resume.tex.tmpl",
        "required_packages": ["geometry.sty"],
        "required_fonts": [],
        "fragments": {
            "section": ".jaa/section.tex.tmpl",
            "highlight": ".jaa/highlight.tex.tmpl",
            "experience": ".jaa/experience.tex.tmpl",
            "education": ".jaa/education.tex.tmpl",
            "normal": ".jaa/normal.tex.tmpl",
            "one_line": ".jaa/one-line.tex.tmpl",
            "publication": ".jaa/publication.tex.tmpl",
            "bullet": ".jaa/bullet.tex.tmpl",
            "numbered": ".jaa/numbered.tex.tmpl",
            "reversed_numbered": ".jaa/reversed-numbered.tex.tmpl",
            "text": ".jaa/text.tex.tmpl",
        },
    }
    (root / "template.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (root / "resume.tex.tmpl").write_text(
        """\\documentclass{article}
\\usepackage[margin=0.22in]{geometry}
\\usepackage{local-style}
\\pagestyle{empty}
\\setlength{\\parindent}{0pt}
\\begin{document}
{\\large [[JAA:NAME]]}\\quad [[JAA:HEADLINE]]\\par
[[JAA:LOCATION]]\\quad [[JAA:CONTACT]]\\par
[[JAA:PROFILE]]\\par
[[JAA:SECTIONS]]
\\end{document}
""",
        encoding="utf-8",
    )
    (root / "local-style.sty").write_text(
        "\\ProvidesPackage{local-style}\n"
        "\\RequirePackage{fontawesome5}\n"
        "\\RequirePackage{hyperref}\n"
        "\\renewcommand{\\section}[1]{\\par\\textbf{#1}\\par}\n"
        "\\setlength{\\parskip}{0pt}\n",
        encoding="utf-8",
    )
    values = {
        "section": "\\section{[[JAA:TITLE]]}[[JAA:ITEMS]]",
        "highlight": " --- [[JAA:TEXT]]",
        "experience": "[[JAA:COMPANY]], [[JAA:POSITION]], [[JAA:LOCATION]], [[JAA:DATES]], [[JAA:SUMMARY]][[JAA:HIGHLIGHTS]]\\par\n",
        "education": "[[JAA:INSTITUTION]], [[JAA:AREA]], [[JAA:DEGREE]], [[JAA:LOCATION]], [[JAA:DATES]], [[JAA:SUMMARY]][[JAA:HIGHLIGHTS]]\\par\n",
        "normal": "[[JAA:NAME]], [[JAA:LOCATION]], [[JAA:DATES]], [[JAA:SUMMARY]][[JAA:HIGHLIGHTS]]\\par\n",
        "one-line": "[[JAA:LABEL]]: [[JAA:DETAILS]]\\par\n",
        "publication": "[[JAA:TITLE]], [[JAA:AUTHORS]], [[JAA:JOURNAL]], [[JAA:DATES]], [[JAA:DOI]], [[JAA:URL]], [[JAA:SUMMARY]]\\par\n",
        "bullet": "[[JAA:TEXT]]\\par\n",
        "numbered": "[[JAA:TEXT]]\\par\n",
        "reversed-numbered": "[[JAA:TEXT]]\\par\n",
        "text": "[[JAA:TEXT]]\\par\n",
    }
    for name, content in values.items():
        (fragments / f"{name}.tex.tmpl").write_text(content, encoding="utf-8")
    return root


class LatexTemplateTests(unittest.TestCase):
    def test_structure_and_synthetic_compile(self) -> None:
        if not all(shutil.which(tool) for tool in ("xelatex", "kpsewhich", "pdfinfo", "pdftotext")):
            self.skipTest("XeLaTeX validation toolchain is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = write_template(Path(temporary))
            status, report = validate_template.validate_template(root)
        self.assertEqual(status, 0, report)
        self.assertEqual(report["quality"]["pages"], 1)
        self.assertEqual(report["quality"]["reading_order"], "passed")

    def test_render_escapes_values_and_supports_every_entry_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = write_template(Path(temporary))
            bundle = validate_template.synthetic_bundle()
            bundle["candidate"]["name"] = "Ada & Co_100%"
            rendered = latex_templates.render_resume(root, bundle)
        self.assertIn(r"Ada \& Co\_100\%", rendered)
        for marker in (
            "JaaExpCompanyOne", "JaaEduSchoolOne", "JaaProjectName",
            "JaaSkillLabel", "JaaPublicationTitle", "JaaBulletText",
            "JaaNumberedText", "JaaReverseText", "JaaStandaloneText",
        ):
            self.assertIn(marker, rendered)

    def test_unsafe_layout_and_missing_dependencies_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = write_template(Path(temporary))
            main = root / "resume.tex.tmpl"
            main.write_text(main.read_text(encoding="utf-8") + "\\immediate\\write18{bad}\n", encoding="utf-8")
            errors, missing, _ = latex_templates.validate_structure(root)
            self.assertTrue(any("shell execution" in error for error in errors))
            self.assertEqual(missing, [])

            root = write_template(Path(temporary), "missing-dependency")
            manifest_path = root / "template.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["required_packages"].append("jaa-package-that-does-not-exist.sty")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            status, report = validate_template.validate_template(root, compile_template=False)
            self.assertEqual(status, 2)
            self.assertIn("jaa-package-that-does-not-exist.sty", report["missing_dependencies"])

    def test_installer_requires_exact_approval_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = write_template(base / "source")
            target_root = base / "installed"
            argv = [
                "install_template.py", "--template", str(source),
                "--target-root", str(target_root), "--approval", "NO",
            ]
            with mock.patch.object(sys, "argv", argv), redirect_stderr(io.StringIO()):
                self.assertEqual(install_template.main(), 2)

            report = {"id": "compact-test", "fingerprint": "abc", "errors": [], "missing_dependencies": []}
            argv[-1] = "APPROVED"
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(install_template, "validate_template", return_value=(0, report)), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(install_template.main(), 0)
            self.assertTrue((target_root / "compact-test" / "template.json").is_file())

            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(install_template, "validate_template", return_value=(0, report)), \
                    redirect_stderr(io.StringIO()):
                self.assertEqual(install_template.main(), 2)


if __name__ == "__main__":
    unittest.main()
