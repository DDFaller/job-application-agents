#!/usr/bin/env python3
"""Focused unit tests for the deterministic RenderCV adapter."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


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


if __name__ == "__main__":
    unittest.main()
