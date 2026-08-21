#!/usr/bin/env python3
"""Focused unit tests for deterministic geographic LaTeX rendering."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("render_bundle.py")
SPEC = importlib.util.spec_from_file_location("render_bundle", SCRIPT)
assert SPEC and SPEC.loader
render_bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_bundle)


def latex_runtime_ready() -> bool:
    try:
        render_bundle.preflight_rendering(Path(__file__).resolve().parent.parent)
        return True
    except RuntimeError:
        return False


class RenderBundleTests(unittest.TestCase):
    @unittest.skipUnless(latex_runtime_ready(), "complete XeLaTeX/Poppler runtime unavailable")
    def test_international_template_preserves_real_pdf_reading_order(self) -> None:
        skill = Path(__file__).resolve().parent.parent
        bundle = {
            "candidate": {
                "name": "Ada Example", "headline": "Backend Engineer", "location": "Paris",
                "contact": ["ada@example.test"], "summary": {"text": "Builds observable data pipelines."},
            },
            "resume_sections": [{
                "title": "Experience", "items": [{
                    "type": "experience", "company": "Example GmbH", "position": "Backend Intern",
                    "location": "Paris", "dates": "2026", "summary": None,
                    "highlights": [{"text": "Built a Python pipeline."}], "evidence_ids": ["E001"],
                }],
            }],
        }
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            template = render_bundle.builtin_template(skill, "international")
            render_bundle.copy_custom_template(template, out)
            tex = render_bundle.latex_cv_document(bundle, "international", None, {}, skill)
            (out / "resume.tex").write_text(tex, encoding="utf-8")
            quality = render_bundle.render_resume_latex(out / "resume.tex", out, 1)
            render_bundle.verify_resume_reading_order(
                bundle, out / "resume.pdf", "international"
            )
            self.assertEqual(quality["pages"], 1)

    def test_geographic_template_metadata(self) -> None:
        skill = Path(__file__).resolve().parent.parent
        international = render_bundle.builtin_template(skill, "international")
        france = render_bundle.builtin_template(skill, "france")
        self.assertEqual(json.loads((international / "template.json").read_text())["id"], "international")
        self.assertTrue((france / "cv.cls").is_file())
        international_design, _ = render_bundle.profile_design("international", False)
        self.assertEqual(international_design["page"]["size"], "us-letter")
        france_design, pages = render_bundle.profile_design("france", True)
        self.assertEqual(france_design["page"]["size"], "a4")
        self.assertEqual(france_design["layout"]["columns"], 2)
        self.assertEqual(pages, 1)

    def test_preflight_checks_both_builtin_templates(self) -> None:
        with mock.patch.object(render_bundle.shutil, "which", side_effect=lambda name: name), \
                mock.patch.object(render_bundle, "builtin_template", return_value=Path("template")) as builtin:
            render_bundle.preflight_rendering(Path("skill"))
        self.assertEqual(
            builtin.call_args_list,
            [mock.call(Path("skill"), "international"), mock.call(Path("skill"), "france")],
        )

    def test_latex_profile_paper_and_escape(self) -> None:
        skill = Path(__file__).resolve().parent.parent
        self.assertIn("letterpaper", render_bundle.latex_preamble_for_profile(skill, "international"))
        self.assertIn("a4paper", render_bundle.latex_preamble_for_profile(skill, "france"))
        self.assertEqual(
            render_bundle.latex_escape("A&B_~^\\"),
            r"A\&B\_\textasciitilde{}\textasciicircum{}\textbackslash{}",
        )

    def test_custom_preflight_skips_builtin_templates(self) -> None:
        with mock.patch.object(render_bundle.shutil, "which", side_effect=lambda name: name), \
                mock.patch.object(render_bundle, "builtin_template") as builtin:
            render_bundle.preflight_rendering(Path("skill"), builtin_latex=False)
        builtin.assert_not_called()


    def test_custom_template_snapshot_copies_only_runtime_files_to_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            stage = base / "stage"
            source.mkdir()
            stage.mkdir()
            (source / "template.json").write_text(json.dumps({
                "main": "main.tmpl", "fragments": {"section": "fragment.tmpl"},
            }), encoding="utf-8")
            (source / "main.tmpl").write_text("main", encoding="utf-8")
            (source / "fragment.tmpl").write_text("fragment", encoding="utf-8")
            (source / "local.sty").write_text("runtime", encoding="utf-8")

            names = render_bundle.copy_custom_template(source, stage)

            self.assertEqual(names, ["local.sty"])
            self.assertTrue((stage / "local.sty").is_file())
            self.assertTrue((stage / "template-source" / "main.tmpl").is_file())
            self.assertFalse((stage / "main.tmpl").exists())

    def test_custom_template_rejects_explicit_geographic_profile(self) -> None:
        args = SimpleNamespace(
            bundle_json=Path("bundle.json"), application_root=Path("application"),
            template="custom-template", profile="france",
            photo=None,
        )
        inputs = ({}, b"{}", b"{}", b"{}", b"{}")
        with mock.patch.object(render_bundle, "verify_bundle_for_render", return_value=inputs):
            with self.assertRaisesRegex(ValueError, "omit --profile"):
                render_bundle.stage_bundle(args, Path("skill"))

    def test_reading_order_gate_uses_bundle_sequence(self) -> None:
        bundle = {
            "candidate": {"name": "Ada Example", "headline": "Backend Engineer", "summary": {"text": "Builds APIs."}},
            "resume_sections": [{
                "title": "Experience",
                "items": [{
                    "type": "experience", "company": "Example GmbH",
                    "highlights": [{"text": "Operated pipelines."}],
                }],
            }],
        }
        ordered = "Ada Example Backend Engineer Builds APIs Experience Example GmbH Operated pipelines"
        with mock.patch.object(render_bundle, "normalized_pdf_text", return_value=ordered):
            render_bundle.verify_resume_reading_order(bundle, Path("resume.pdf"))
        reordered = "Ada Example Backend Engineer Builds APIs Example GmbH Experience Operated pipelines"
        with mock.patch.object(render_bundle, "normalized_pdf_text", return_value=reordered):
            with self.assertRaisesRegex(RuntimeError, "reading order"):
                render_bundle.verify_resume_reading_order(bundle, Path("resume.pdf"))

    def test_france_reading_order_routes_one_line_sections_to_sidebar(self) -> None:
        bundle = {
            "candidate": {"name": "Ada", "headline": "Engineer", "summary": {"text": "Profile"}},
            "resume_sections": [
                {"title": "Experience", "items": [{"type": "experience", "company": "Company", "highlights": []}]},
                {"title": "Skills", "items": [{"type": "one_line", "label": "Languages", "details": "Python"}]},
            ],
        }
        self.assertEqual(
            render_bundle.resume_order_anchors(bundle, "france"),
            ["ada", "skills", "languages", "engineer", "profile", "experience", "company"],
        )

    def test_france_stage_requires_approved_photo(self) -> None:
        args = SimpleNamespace(
            bundle_json=Path("bundle.json"), application_root=Path("application"),
            template="builtin", profile="france", photo=None,
        )
        inputs = ({}, b"{}", b'{"location":"Paris"}', b"{}", b"{}")
        with mock.patch.object(render_bundle, "verify_bundle_for_render", return_value=inputs), \
                mock.patch.object(render_bundle, "discover_approved_photo", return_value=None):
            with self.assertRaisesRegex(ValueError, "requires an approved photo"):
                render_bundle.stage_bundle(args, Path("skill"))

    def test_auto_profile_detects_france_from_bundle_location(self) -> None:
        bundle = {"inputs": {"job_json": "/missing"}, "job": {"location": "Paris, Île-de-France"}}
        self.assertEqual(render_bundle.resolve_profile(bundle, "auto"), "france")
        self.assertEqual(render_bundle.resolve_profile(bundle, "international"), "international")

    def test_promote_requires_and_embeds_exact_accepted_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            application_root = root / "application"
            stage = application_root / ".staging" / "bundle-test"
            stage.mkdir(parents=True)
            job = root / "job.json"
            evidence = root / "candidate.json"
            profiles = root / "profiles.json"
            bundle_path = root / "bundle.json"
            review_path = root / "review.json"
            job.write_text(json.dumps({"field_evidence": {}}), encoding="utf-8")
            evidence.write_text(json.dumps({"facts": []}), encoding="utf-8")
            profiles.write_text(json.dumps({"profiles": []}), encoding="utf-8")
            job_hash = hashlib.sha256(job.read_bytes()).hexdigest()
            evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
            profiles_hash = hashlib.sha256(profiles.read_bytes()).hexdigest()
            bundle = {
                "inputs": {
                    "job_json": str(job), "job_sha256": job_hash,
                    "candidate_evidence_json": str(evidence), "candidate_evidence_sha256": evidence_hash,
                    "role_profiles_json": str(profiles), "role_profiles_sha256": profiles_hash,
                },
            }
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            (stage / "bundle.json").write_bytes(bundle_path.read_bytes())
            for name in ("job.json", "candidate-evidence.json", "role-profiles.json", "resume.pdf", "motivation-letter.pdf"):
                (stage / name).write_text(name, encoding="utf-8")
            artifacts = {
                path.name: {"sha256": render_bundle.sha256(path), "bytes": path.stat().st_size}
                for path in stage.iterdir()
            }
            render_bundle.atomic_json(stage / "staging-manifest.json", {
                "schema_version": 1,
                "application_root": str(application_root.resolve()),
                "bundle_sha256": render_bundle.sha256(stage / "bundle.json"),
                "job": {"company": "Example", "role": "Role", "canonical_url": "https://example.test"},
                "inputs": bundle["inputs"],
                "rendering": {"profile": "international"},
                "quality": {"resume": {"pages": 1}, "motivation_letter": {"pages": 1}},
                "document_text_sha256": {"resume.pdf": "a", "motivation-letter.pdf": "b"},
                "artifacts": artifacts,
            })
            template = json.loads((Path(__file__).resolve().parent.parent / "references" / "tailoring-review-template.json").read_text(encoding="utf-8"))
            template.update({
                "inputs": {
                    "job_json": str(job), "job_sha256": job_hash,
                    "candidate_evidence_json": str(evidence), "candidate_evidence_sha256": evidence_hash,
                    "role_profiles_json": str(profiles), "role_profiles_sha256": profiles_hash,
                    "bundle_json": str(bundle_path), "bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
                },
                "checks": {key: True for key in template["checks"]},
                "findings": [], "verdict": "accept", "reviewed_at": "2026-08-20T12:00:00+00:00",
            })
            review_path.write_text(json.dumps(template), encoding="utf-8")

            self.assertFalse((application_root / "current.json").exists())
            promoted = render_bundle.promote_bundle(
                stage, review_path, application_root, Path(__file__).resolve().parent.parent
            )
            manifest = json.loads((promoted / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 3)
            self.assertEqual(manifest["document_revision"], 0)
            self.assertEqual(manifest["semantic_review"]["verdict"], "accept")
            self.assertNotIn("visual_inspection", manifest["quality_gate"])
            self.assertTrue((promoted / "tailoring-review.json").is_file())
            self.assertEqual(json.loads((application_root / "current.json").read_text())["version"], "v001")

    def test_rebuild_current_latex_archives_revision_and_stales_text_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            application = Path(temporary) / "application"
            version = application / "v001"
            version.mkdir(parents=True)
            for name in ("resume.tex", "letter.tex", "preamble.tex"):
                (version / name).write_text(name + " edited", encoding="utf-8")
            for name in ("resume.pdf", "motivation-letter.pdf"):
                (version / name).write_bytes(b"old")
            render_bundle.atomic_json(version / "manifest.json", {
                "schema_version": 3,
                "version": "v001",
                "rendering": {"resume_engine": "latex", "profile": "international", "max_pages": 1},
                "quality_gate": {},
                "semantic_review": {"status": "fresh", "verdict": "accept"},
                "document_revision": 0,
                "document_text_sha256": {"resume.pdf": "old", "motivation-letter.pdf": "old"},
                "manual_revisions": [],
            })
            render_bundle.atomic_json(application / "current.json", {
                "version": "v001", "path": str(version.resolve()),
                "manifest": str((version / "manifest.json").resolve()),
            })

            def resume(_tex, out, _pages):
                (out / "resume.pdf").write_bytes(b"new resume")
                return {"pages": 1, "text_chars": 10}

            def letter(_tex, out):
                (out / "motivation-letter.pdf").write_bytes(b"new letter")
                return {"pages": 1, "text_chars": 10}

            with mock.patch.object(render_bundle, "render_resume_latex", side_effect=resume), \
                 mock.patch.object(render_bundle, "to_letter_pdf_latex", side_effect=letter), \
                 mock.patch.object(render_bundle, "document_text_hashes", return_value={"resume.pdf": "new", "motivation-letter.pdf": "new"}):
                render_bundle.rebuild_current_version(version, Path("skill"))

            manifest = json.loads((version / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["document_revision"], 1)
            self.assertEqual(manifest["source_provenance"], "user_modified")
            self.assertEqual(manifest["semantic_review"]["status"], "stale")
            self.assertTrue((version / "manual-revisions" / "r001" / "resume.tex").is_file())
            self.assertEqual((version / "resume.pdf").read_bytes(), b"new resume")


if __name__ == "__main__":
    unittest.main()
