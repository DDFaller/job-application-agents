from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from job_application_agents.auto_apply.local_review_server import LocalReviewServer
from job_application_agents.auto_apply.review_session import (
    EncryptedCheckpointStore,
    ReviewCheckpoint,
    public_snapshot,
)


class TestEncryptedCheckpointStore(unittest.TestCase):
    def test_round_trip_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = EncryptedCheckpointStore(root)
            checkpoint = ReviewCheckpoint(
                application_id="app-1",
                company="Acme",
                job_title="Engineer",
                target_url="https://example.test/apply",
                revision=2,
                fields=[{"id": "name", "label": "Name", "type": "text", "value": "Jane"}],
                resume_path="/private/resume.pdf",
                letter_path=None,
                step_index=2,
                page_url="https://example.test/apply?step=2",
            )
            store.save(checkpoint)

            self.assertTrue((root / "review.key").is_file())
            self.assertEqual(0o600, (root / "review.key").stat().st_mode & 0o777)
            self.assertNotIn(b"Jane", (root / "checkpoint.enc").read_bytes())
            restored = EncryptedCheckpointStore(root).load()
            self.assertIsNotNone(restored)
            self.assertEqual(2, restored.step_index)
            self.assertEqual("Jane", restored.fields[0]["value"])
            self.assertEqual(checkpoint.draft_hash, restored.draft_hash)

    def test_invalid_key_does_not_silently_open_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = EncryptedCheckpointStore(root)
            store.save(ReviewCheckpoint(
                application_id="app-1", company="Acme", job_title="Engineer",
                target_url="https://example.test", revision=1, fields=[],
                resume_path="/tmp/resume.pdf", letter_path=None,
            ))
            with self.assertRaises(ValueError):
                EncryptedCheckpointStore(root, key=b"not-a-fernet-key")


class TestReviewServer(unittest.TestCase):
    class FakeSession:
        def __init__(self) -> None:
            self.value = {
                "application_id": "app-1", "company": "Acme", "job_title": "Engineer",
                "target_url": "https://example.test", "revision": 1,
                "fields": [{"id": "name", "label": "Name", "type": "text", "value": "Jane", "source": "profile"}],
                "resume_path": "/private/resume.pdf", "letter_path": None,
                "step_index": 1, "state": "REVIEW_READY", "draft_hash": "sha256:test",
            }
            self.draft = type("Draft", (), {"resume_path": "/private/resume.pdf", "letter_path": None})()

        def snapshot(self):
            return dict(self.value)

        def update_fields(self, revision, updates):
            self.value["revision"] += 1
            self.value["fields"][0]["value"] = updates["name"]
            return self.snapshot()

        def approve_step(self, revision, digest):
            self.value["state"] = "REVIEW_READY"
            return self.snapshot()

        def skip(self, revision):
            self.value["state"] = "SKIPPED"
            return self.snapshot()

        def resume(self):
            return self.snapshot()

    def setUp(self):
        self.session = self.FakeSession()
        self.server = LocalReviewServer(self.session, host="127.0.0.1", port=0, token="test-token")
        self.base_url = self.server.start().rstrip("/")

    def tearDown(self):
        self.server.stop()

    def request(self, path, method="GET", payload=None, authorized=False):
        headers = {"Authorization": "Bearer test-token"} if authorized else {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(payload).encode()
        req = urllib.request.Request(self.base_url + path, method=method, headers=headers, data=payload)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(req, timeout=3)

    def test_root_is_public_but_api_requires_token(self):
        response = self.request("/")
        self.assertEqual(200, response.status)
        self.assertIn(b"Private application review", response.read())
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request("/api/session")
        self.assertEqual(401, ctx.exception.code)

    def test_authenticated_session_hides_private_paths(self):
        response = self.request("/api/session", authorized=True)
        payload = json.loads(response.read())
        self.assertEqual("resume.pdf", payload["resume_name"])
        self.assertNotIn("resume_path", payload)

    def test_auth_and_field_update(self):
        req = urllib.request.Request(
            self.base_url + "/api/auth", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"token": "test-token"}).encode(),
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        response = opener.open(req, timeout=3)
        self.assertEqual(200, response.status)
        update = self.request("/api/session/fields", method="PATCH", authorized=True, payload={"revision": 1, "fields": {"name": "Alex"}})
        payload = json.loads(update.read())
        self.assertEqual(2, payload["revision"])
        self.assertEqual("Alex", payload["fields"][0]["value"])


class TestPublicSnapshot(unittest.TestCase):
    def test_file_paths_and_values_are_sanitized(self):
        snapshot = public_snapshot({
            "resume_path": "/private/resume.pdf",
            "letter_path": "/private/letter.pdf",
            "fields": [{"type": "file", "value": "/private/resume.pdf"}],
        })
        self.assertEqual("resume.pdf", snapshot["fields"][0]["value"])
        self.assertNotIn("resume_path", snapshot)
        self.assertEqual("letter.pdf", snapshot["letter_name"])


if __name__ == "__main__":
    unittest.main()
