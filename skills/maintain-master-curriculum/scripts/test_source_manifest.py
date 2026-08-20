from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resolve_current import main as resolve_main
from source_manifest import manifest_for, write_json_atomic


class SourceManifestTests(unittest.TestCase):
    def make_sources(self, root: Path) -> Path:
        source = root / "sources"
        source.mkdir()
        (source / "identity.md").write_text("# Identity\n- [MC-ID-001] Name: Test Candidate\n- [MC-ID-002] Email: test@example.com\n", encoding="utf-8")
        (source / "experience.md").write_text("# Experience\n- [MC-EXP-001] Built systems.\n", encoding="utf-8")
        return source

    def test_manifest_resolves_without_readiness_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_sources(Path(directory))
            write_json_atomic(source / "current.json", manifest_for(source, "v001"))
            original = sys.argv
            try:
                sys.argv = ["resolve_current.py", "--source-dir", str(source)]
                self.assertEqual(resolve_main(), 0)
            finally:
                sys.argv = original

    def test_manifest_detects_markdown_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_sources(Path(directory))
            write_json_atomic(source / "current.json", manifest_for(source, "v001"))
            (source / "experience.md").write_text("# Experience\n- [MC-EXP-001] Changed.\n", encoding="utf-8")
            original = sys.argv
            try:
                sys.argv = ["resolve_current.py", "--source-dir", str(source)]
                self.assertEqual(resolve_main(), 2)
            finally:
                sys.argv = original


if __name__ == "__main__":
    unittest.main()
