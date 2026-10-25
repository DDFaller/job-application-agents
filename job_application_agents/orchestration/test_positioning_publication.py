"""Publication tests use only temporary synthetic candidate sources."""
import json
from pathlib import Path
import tempfile
import unittest

from job_application_agents.positioning import LIBRARY_POINTER, digest, load_active_library
from job_application_agents.positioning_publication import publish_library, validate_review
from job_application_agents.orchestration.test_positioning import fixture


class PublicationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        library, self.library, _ = fixture(self.root)
        refs = []
        for profile in library['profiles']:
            for ext in ('.md', '.tex', '.pdf'):
                path = self.root / (profile['id'] + ext)
                path.write_text('Synthetic reviewed preview ' + path.name)
                refs.append(dict(name=path.name, path=str(path), sha256=digest(path)))
        self.review = self.root / 'review.json'
        self.review.write_text(json.dumps(dict(schema_version=1, verdict='accept',
            library_sha256=digest(self.library), findings=[], previews=refs)))

    def test_validation_does_not_activate(self):
        validate_review(self.library, self.review, self.root)
        self.assertFalse((self.root / LIBRARY_POINTER).exists())
        with self.assertRaisesRegex(ValueError, 'approval'):
            publish_library(self.library, self.review, self.root, approval='')

    def test_approved_immutable_versions_and_stale_sources(self):
        first = publish_library(self.library, self.review, self.root, approval='APPROVED')
        second = publish_library(self.library, self.review, self.root, approval='APPROVED')
        self.assertEqual((first.name, second.name), ('p001', 'p002'))
        active, _ = load_active_library(self.root)
        self.assertEqual(active.parent, second)
        self.assertEqual(digest(first / 'positioning-library.json'), digest(self.library))
        (self.root / 'sources/engineer/experience.md').write_text('Changed')
        with self.assertRaisesRegex(ValueError, 'stale'):
            load_active_library(self.root)

    def test_unaccepted_or_changed_review_rejected(self):
        review = json.loads(self.review.read_text())
        for patch in ({'verdict': 'revise'}, {'library_sha256': 'stale'}, {'previews': []}):
            self.review.write_text(json.dumps({**review, **patch}))
            with self.assertRaises(ValueError):
                publish_library(self.library, self.review, self.root, approval='APPROVED')
            self.assertFalse((self.root / LIBRARY_POINTER).exists())

    def test_changed_preview_prevents_activation(self):
        (self.root / 'data.md').write_text('Unreviewed change')
        with self.assertRaisesRegex(ValueError, 'stale'):
            publish_library(self.library, self.review, self.root, approval='APPROVED')
        self.assertFalse((self.root / LIBRARY_POINTER).exists())


if __name__ == '__main__':
    unittest.main()
