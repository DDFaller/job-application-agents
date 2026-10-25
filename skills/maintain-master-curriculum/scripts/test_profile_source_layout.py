"""Canonical role folders retain shared facts and hash reference CVs."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_master_sources import read_facts, source_hashes

class ProfileSourceLayoutTests(unittest.TestCase):
    def make_profile(self, root: Path, name: str, level: str = 'B2') -> Path:
        p = root / name
        p.mkdir()
        (p / 'identity.md').write_text('# Identity\n- [MC-ID-001] Name: Test Person\n- [MC-ID-002] Email: test@example.com\n')
        (p / 'languages.md').write_text(f'# Languages\n- [MC-LANG-003] French — {level}.\n')
        (p / 'pre-formatted.tex').write_text('Reference CV: ' + level)
        return p

    def test_shared_facts_and_reference_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = self.make_profile(root, 'backend')
            self.make_profile(root, 'data')
            errors, facts = read_facts(root)
            self.assertEqual(errors, [])
            self.assertEqual(facts['MC-LANG-003'], 'French — B2.')
            before = source_hashes(root)
            (a / 'pre-formatted.tex').write_text('Changed reference')
            self.assertNotEqual(before['backend/pre-formatted.tex'], source_hashes(root)['backend/pre-formatted.tex'])
            self.assertEqual(len(before), 6)

    def test_conflicting_shared_fact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_profile(root, 'backend')
            self.make_profile(root, 'data', 'B1')
            self.assertIn('conflicting fact across profiles: MC-LANG-003', read_facts(root)[0])

    def test_symlink_and_nested_directory_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = self.make_profile(root, 'backend')
            (root / 'alias').symlink_to(p, target_is_directory=True)
            self.assertTrue(any('alias' in e for e in read_facts(root)[0]))
            (p / 'nested').mkdir()
            self.assertTrue(any('nested' in e for e in read_facts(root)[0]))

if __name__ == '__main__':
    unittest.main()
