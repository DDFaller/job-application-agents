import tempfile
from pathlib import Path
import unittest

from job_application_agents.sources import (
    find_preformatted_cv,
    find_profile_photo,
    list_role_profiles,
    load_role_profile_sources,
    match_role_profile,
)


class SourcesTests(unittest.TestCase):
    def test_list_and_load_role_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p1 = root / "backend-engineer"
            p1.mkdir()
            (p1 / "experience.md").write_text("# Experience\n- Backend dev", encoding="utf-8")
            (p1 / "identity.md").write_text("# Identity\nName: Alice", encoding="utf-8")

            p2 = root / "ai-platform-engineer"
            p2.mkdir()
            (p2 / "skills.md").write_text("# Skills\n- PyTorch", encoding="utf-8")

            # Non-profile dir
            (root / ".cache").mkdir()
            (root / "empty-dir").mkdir()

            profiles = list_role_profiles(root)
            self.assertEqual(profiles, ["ai-platform-engineer", "backend-engineer"])

            sources = load_role_profile_sources(root, "backend-engineer")
            self.assertIn("Backend dev", sources["experience"])
            self.assertIn("Alice", sources["identity"])
            self.assertEqual(sources["education"], "")

    def test_match_role_profile(self) -> None:
        profiles = ["ai-platform-engineer", "backend-engineer"]
        job_be = {"role": "Senior Backend Developer", "technologies": ["Python", "PostgreSQL"]}
        self.assertEqual(match_role_profile(job_be, profiles), "backend-engineer")

        job_ai = {"role": "Machine Learning Engineer", "technologies": ["PyTorch", "Kubeflow"]}
        self.assertEqual(match_role_profile(job_ai, profiles), "ai-platform-engineer")

        self.assertEqual(match_role_profile(job_be, profiles, default_profile="ai-platform-engineer"), "ai-platform-engineer")

    def test_find_profile_photo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p1 = root / "backend"
            p1.mkdir()
            photo1 = p1 / "profile-photo.jpg"
            photo1.write_bytes(b"photo1")

            self.assertEqual(find_profile_photo(root, "backend"), photo1)

            # Top-level fallback
            p2 = root / "frontend"
            p2.mkdir()
            photo_top = root / "profile-photo.png"
            photo_top.write_bytes(b"photo_top")
            self.assertEqual(find_profile_photo(root, "frontend"), photo_top)

    def test_find_preformatted_cv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            p1 = root / "backend-engineer"
            p1.mkdir()
            cv_tex = p1 / "pre-formatted.tex"
            cv_tex.write_text("% Resume in LaTeX\n\\documentclass{article}", encoding="utf-8")
            (p1 / "experience.md").write_text("# Experience", encoding="utf-8")

            self.assertEqual(find_preformatted_cv(root, "backend-engineer"), cv_tex)

            sources = load_role_profile_sources(root, "backend-engineer")
            self.assertIn("pre_formatted_tex", sources)
            self.assertIn("\\documentclass{article}", sources["pre_formatted_tex"])

            # Top-level fallback
            p2 = root / "other"
            p2.mkdir()
            top_tex = root / "pre-formatted.tex"
            top_tex.write_text("% Top-level CV", encoding="utf-8")
            self.assertEqual(find_preformatted_cv(root, "other"), top_tex)


if __name__ == "__main__":
    unittest.main()
