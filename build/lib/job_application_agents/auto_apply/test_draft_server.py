from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.parse

from job_application_agents.auto_apply.draft_models import (
    ApplicationDraft,
    ApplicationField,
    FieldSource,
    FieldType,
)
from scripts.draft_review import run_server


class TestDraftReviewServer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        # Create dummy PDF
        self.resume_pdf = self.root / "resume.pdf"
        self.resume_pdf.write_bytes(b"%PDF-1.4 test resume binary content")

        self.letter_pdf = self.root / "letter.pdf"
        self.letter_pdf.write_bytes(b"%PDF-1.4 test letter binary content")

        self.draft = ApplicationDraft(
            application_id="app-unit-test",
            company="TestCompany",
            job_title="Software Architect",
            target_url="https://example.com/jobs/1",
            revision=1,
            fields=[
                ApplicationField(id="name", label="Full Name", type=FieldType.TEXT, value="Daniel", source=FieldSource.PROFILE),
            ],
            resume_path=str(self.resume_pdf),
            letter_path=str(self.letter_pdf),
        )

        self.draft_file = self.root / "draft.json"
        self.draft_file.write_text(self.draft.to_json(), encoding="utf-8")
        self.port = 8799

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pdf_endpoints_and_auto_shutdown(self):
        server_thread = threading.Thread(
            target=run_server,
            kwargs={
                "draft": self.draft,
                "draft_path": self.draft_file,
                "port": self.port,
                "timeout_sec": 30,
            },
            daemon=True,
        )
        server_thread.start()
        time.sleep(0.5)

        base_url = f"http://127.0.0.1:{self.port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        # 1. Test HTML Dashboard
        req = urllib.request.Request(f"{base_url}/")
        with opener.open(req) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            self.assertIn("TestCompany", body)
            self.assertIn("/pdf/resume", body)
            approval_nonce = re.search(
                rb'name="approval_nonce" value="([^"]+)"', body.encode("utf-8")
            )
            self.assertIsNotNone(approval_nonce)

        # 2. Test Resume PDF Stream
        req_pdf = urllib.request.Request(f"{base_url}/pdf/resume")
        with opener.open(req_pdf) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "application/pdf")
            content = resp.read()
            self.assertTrue(content.startswith(b"%PDF-1.4"))

        # 3. Test POST /approve & Auto-Shutdown
        post_data = urllib.parse.urlencode(
            {"approval_nonce": approval_nonce.group(1).decode("ascii")}
        ).encode("ascii")
        req_approve = urllib.request.Request(f"{base_url}/approve", data=post_data, method="POST")
        with opener.open(req_approve) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            self.assertIn("Approved!", body)


        # Wait for thread shutdown
        server_thread.join(timeout=3.0)
        self.assertFalse(server_thread.is_alive())

        # Verify Approval Token was written
        token_path = self.root / "approval-token.json"
        self.assertTrue(token_path.is_file())
        token_data = json.loads(token_path.read_text(encoding="utf-8"))
        self.assertEqual(token_data["application_id"], "app-unit-test")
        self.assertEqual(token_data["draft_hash"], self.draft.draft_hash)


if __name__ == "__main__":
    unittest.main()
