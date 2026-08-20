#!/usr/bin/env python3
"""Tests for manifest-keyed candidate evidence cache coordination."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("candidate_evidence_cache.py")
SPEC = importlib.util.spec_from_file_location("candidate_evidence_cache", SCRIPT)
assert SPEC and SPEC.loader
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)


class CandidateEvidenceCacheTests(unittest.TestCase):
    def make_manifest(self, root: Path, text: str = "evidence") -> Path:
        source = root / "experience.md"
        source.write_text(text, encoding="utf-8")
        manifest = root / "current.json"
        manifest.write_text(json.dumps({
            "schema_version": 2,
            "version": "v001",
            "source_dir": str(root),
            "markdown_sources": ["experience.md"],
            "source_hashes": {"experience.md": hashlib.sha256(source.read_bytes()).hexdigest()},
        }), encoding="utf-8")
        return manifest

    def test_fingerprint_changes_with_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = self.make_manifest(root)
            _, first = cache.verify_manifest(manifest_path)
            manifest_path = self.make_manifest(root, "changed")
            _, second = cache.verify_manifest(manifest_path)
            self.assertNotEqual(first, second)

    def test_begin_serializes_same_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache_root = root / "cache"
            manifest, key = cache.verify_manifest(self.make_manifest(root))
            first = cache.begin(cache_root, key)
            self.assertEqual(Path(first["staging_dir"]), cache_root / key)
            with self.assertRaises(BlockingIOError):
                cache.begin(cache_root, key)

    def test_completed_entry_validates_and_becomes_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache_root = root / "cache"
            manifest_path = self.make_manifest(root)
            manifest, key = cache.verify_manifest(manifest_path)
            build = cache.begin(cache_root, key)
            entry = Path(build["staging_dir"])
            source = root / "experience.md"
            snapshot = entry / "snapshots" / "experience.md.txt"
            snapshot.write_bytes(source.read_bytes())
            evidence = entry / "candidate-evidence.json"
            record = {
                "schema_version": 2,
                "extraction_status": "complete",
                "candidate": {
                    "name": "Candidate", "headline": None, "location": None,
                    "contact": ["candidate@example.test"], "languages": [],
                },
                "sources": [{
                    "path": str(source),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "snapshot_path": str(snapshot),
                    "snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                    "pages": None,
                }],
                "facts": [{
                    "id": "E001", "category": "certification", "claim": "evidence",
                    "source_path": str(source), "quote": "evidence", "page": None,
                }],
                "field_evidence": {
                    "candidate.name": ["E001"], "candidate.contact.0": ["E001"],
                },
                "missing_fields": [], "warnings": [],
                "extracted_at": "2026-08-20T12:00:00+00:00",
            }
            evidence.write_text(json.dumps(record), encoding="utf-8")
            validator = cache.validator_module()
            receipt = entry / "candidate-evidence.receipt.json"
            receipt.write_text(json.dumps(validator.receipt_for(record, evidence)), encoding="utf-8")
            self.assertEqual(cache.validate_entry(evidence, receipt, manifest), [])
            cache.require_owner(cache_root, key, build["token"]).unlink()
            self.assertEqual(cache.validate_entry(evidence, receipt, manifest), [])


if __name__ == "__main__":
    unittest.main()
