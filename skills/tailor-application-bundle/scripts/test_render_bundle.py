#!/usr/bin/env python3
"""Focused unit tests for the deterministic RenderCV adapter."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("render_bundle.py")
SPEC = importlib.util.spec_from_file_location("render_bundle", SCRIPT)
assert SPEC and SPEC.loader
render_bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_bundle)


class RenderBundleTests(unittest.TestCase):
    def test_contacts_are_classified(self) -> None:
        result = render_bundle.contacts([
            "person@example.com", "+33 7 12 34 56 78",
            "https://github.com/person", "https://linkedin.com/in/person",
            "https://example.com/portfolio",
        ])
        self.assertEqual(result["email"], ["person@example.com"])
        self.assertEqual(result["custom_connections"], [{
            "fontawesome_icon": "phone",
            "placeholder": "+33 7 12 34 56 78",
            "url": None,
        }])
        self.assertEqual(result["website"], ["https://example.com/portfolio"])
        self.assertEqual(result["social_networks"], [
            {"network": "GitHub", "username": "person"},
            {"network": "LinkedIn", "username": "person"},
        ])

    def test_all_entry_types_convert(self) -> None:
        cases = [
            ({"type": "experience", "company": "C", "position": "P", "location": None, "dates": "2026", "summary": None, "highlights": [], "evidence_ids": ["E1"]}, "company"),
            ({"type": "education", "institution": "I", "area": "A", "degree": "D", "location": None, "dates": "2025", "summary": None, "highlights": [], "evidence_ids": ["E1"]}, "institution"),
            ({"type": "normal", "name": "N", "location": None, "dates": None, "summary": None, "highlights": [], "evidence_ids": ["E1"]}, "name"),
            ({"type": "one_line", "label": "L", "details": "D", "evidence_ids": ["E1"]}, "label"),
            ({"type": "publication", "title": "T", "authors": ["A"], "journal": None, "dates": None, "doi": None, "url": None, "summary": None, "evidence_ids": ["E1"]}, "title"),
            ({"type": "bullet", "text": "B", "evidence_ids": ["E1"]}, "bullet"),
            ({"type": "numbered", "text": "N", "evidence_ids": ["E1"]}, "number"),
            ({"type": "reversed_numbered", "text": "R", "evidence_ids": ["E1"]}, "reversed_number"),
            ({"type": "text", "text": "T", "evidence_ids": ["E1"]}, "text"),
        ]
        for item, expected_key in cases:
            with self.subTest(item["type"]):
                self.assertIn(expected_key, render_bundle.rendercv_entry(item))

    def test_locale_falls_back_to_english(self) -> None:
        self.assertEqual(render_bundle.job_locale({"inputs": {"job_json": "/missing"}}), "english")

    def test_international_profile_preserves_sb2nov(self) -> None:
        bundle = {
            "inputs": {"job_json": "/missing"},
            "candidate": {"name": "A", "headline": "B", "location": None, "contact": [], "summary": {"text": "C"}},
            "resume_sections": [{"title": "Skills", "items": [{"type": "one_line", "label": "Languages", "details": "Python", "evidence_ids": ["E1"]}]}],
        }
        document = render_bundle.rendercv_document(bundle)
        self.assertEqual(document["design"], {"theme": "sb2nov", "page": {"size": "us-letter"}})
        rendered = "\n".join(render_bundle.yaml_dump(document))
        self.assertIn('theme: "sb2nov"', rendered)
        self.assertIn('size: "us-letter"', rendered)
        self.assertEqual(render_bundle.profile_design("international", False)[1], 1)

    def test_render_resume_does_not_generate_png(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary)
            yaml_path = out_dir / "resume.yaml"
            yaml_path.write_text("resume", encoding="utf-8")
            (out_dir / "resume.pdf").write_bytes(b"pdf")
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if command[0] == "pdfinfo":
                    return mock.Mock(returncode=0, stdout="Pages:           1\n", stderr="")
                if command[0] == "pdftotext":
                    return mock.Mock(returncode=0, stdout="Candidate", stderr="")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(render_bundle.subprocess, "run", side_effect=run), mock.patch.object(render_bundle.shutil, "which", side_effect=lambda name: name):
                render_bundle.render_resume(Path("rendercv"), yaml_path, out_dir, 1)

            render_command = calls[0]
            self.assertIn("--dont-generate-png", render_command)
            self.assertNotIn("--png-path", render_command)
            self.assertNotIn("resume.png", render_command)

    def test_render_resume_bounds_child_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out_dir = Path(temporary)
            yaml_path = out_dir / "resume.yaml"
            yaml_path.write_text("resume", encoding="utf-8")
            (out_dir / "resume.pdf").write_bytes(b"pdf")
            calls = []

            def run(command, **kwargs):
                calls.append((command, kwargs))
                if command[0] == "pdfinfo":
                    return mock.Mock(returncode=0, stdout="Pages:           1\n", stderr="")
                if command[0] == "pdftotext":
                    return mock.Mock(returncode=0, stdout="Candidate", stderr="")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(render_bundle.subprocess, "run", side_effect=run), mock.patch.object(render_bundle.shutil, "which", side_effect=lambda name: name):
                render_bundle.render_resume(Path("rendercv"), yaml_path, out_dir, 1)

            self.assertTrue(all(kwargs.get("timeout") == render_bundle.SUBPROCESS_TIMEOUT_SECONDS for _, kwargs in calls))

    def test_rendercv_document_disables_png_generation(self) -> None:
        bundle = {
            "inputs": {"job_json": "/missing"},
            "candidate": {"name": "A", "headline": "B", "location": None, "contact": [], "summary": {"text": "C"}},
            "resume_sections": [],
        }
        self.assertTrue(render_bundle.rendercv_document(bundle)["settings"]["render_command"]["dont_generate_png"])

    def test_preflight_checks_all_rendering_tools(self) -> None:
        with mock.patch.object(render_bundle, "rendercv_binary", return_value=Path("rendercv")) as rendercv, mock.patch.object(render_bundle.shutil, "which", side_effect=lambda name: name):
            render_bundle.preflight_rendering(Path("skill"))
        rendercv.assert_called_once_with(Path("skill"))

    def test_france_profile_uses_a4_and_photo(self) -> None:
        bundle = {
            "inputs": {"job_json": "/missing"},
            "candidate": {"name": "A", "headline": "B", "location": "Paris", "contact": [], "summary": {"text": "C"}},
            "resume_sections": [],
        }
        document = render_bundle.rendercv_document(bundle, "france", "profile-photo.jpg")
        self.assertEqual(document["cv"]["photo"], "profile-photo.jpg")
        self.assertEqual(document["design"]["theme"], "classic")
        self.assertEqual(document["design"]["page"]["size"], "a4")
        self.assertEqual(document["design"]["header"]["photo_position"], "left")
        self.assertEqual(render_bundle.profile_design("france", True)[1], 1)

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
            bundle_path = root / "bundle.json"
            review_path = root / "review.json"
            job.write_text(json.dumps({"field_evidence": {}}), encoding="utf-8")
            evidence.write_text(json.dumps({"facts": []}), encoding="utf-8")
            job_hash = hashlib.sha256(job.read_bytes()).hexdigest()
            evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
            bundle = {
                "inputs": {
                    "job_json": str(job), "job_sha256": job_hash,
                    "candidate_evidence_json": str(evidence), "candidate_evidence_sha256": evidence_hash,
                },
            }
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            (stage / "bundle.json").write_bytes(bundle_path.read_bytes())
            for name in ("job.json", "candidate-evidence.json", "resume.pdf", "motivation-letter.pdf"):
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
                "artifacts": artifacts,
            })
            template = json.loads((Path(__file__).resolve().parent.parent / "references" / "tailoring-review-template.json").read_text(encoding="utf-8"))
            template.update({
                "inputs": {
                    "job_json": str(job), "job_sha256": job_hash,
                    "candidate_evidence_json": str(evidence), "candidate_evidence_sha256": evidence_hash,
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
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["semantic_review"]["verdict"], "accept")
            self.assertNotIn("visual_inspection", manifest["quality_gate"])
            self.assertTrue((promoted / "tailoring-review.json").is_file())
            self.assertEqual(json.loads((application_root / "current.json").read_text())["version"], "v001")


if __name__ == "__main__":
    unittest.main()
