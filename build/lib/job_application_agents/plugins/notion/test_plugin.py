from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from job_application_agents.plugins.base import PluginRegistry, SinkResult
from job_application_agents.plugins.notion import DEFAULT_DATABASE_ID, NotionPlugin
from job_application_agents.plugins.notion.client import NotionClient
from job_application_agents.plugins.notion.firestore import FirestoreNotionJobRepository
from job_application_agents.plugins.notion.models import NotionCardPayload, NotionSyncJob


class TestNotionClient(unittest.TestCase):
    def setUp(self) -> None:
        self.token = "test-token-ntn-12345"
        self.client = NotionClient(token=self.token)

    @patch("urllib.request.urlopen")
    def test_two_step_file_upload(self, mock_urlopen: MagicMock) -> None:
        # Step 1 response
        mock_cm1 = MagicMock()
        mock_cm1.__enter__.return_value.read.return_value = json.dumps({
            "id": "file-abc-123",
            "upload_url": "https://notion-upload.test/files/upload-url",
        }).encode("utf-8")

        # Step 2 response
        mock_cm2 = MagicMock()
        mock_cm2.__enter__.return_value.status = 200
        mock_cm2.__enter__.return_value.read.return_value = b"{}"

        mock_urlopen.side_effect = [mock_cm1, mock_cm2]

        file_id = self.client.upload_file("resume.pdf", "application/pdf", b"%PDF-1.4 sample bytes")
        self.assertEqual(file_id, "file-abc-123")
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("urllib.request.urlopen")
    def test_http_requests_have_a_bounded_timeout(self, mock_urlopen: MagicMock) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        mock_urlopen.return_value = response
        self.client._request("GET", "users/me")
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 30.0)

    def test_board_snapshot_is_reused_for_duplicate_lookup(self) -> None:
        with patch.object(self.client, "query_database", return_value=[{
            "id": "page-1",
            "properties": {"Job URL": {"url": "https://example.test/job"}},
        }]) as query:
            first = self.client.find_card_by_job_url("db-1", "https://example.test/job")
            second = self.client.find_card_by_job_url("db-1", "https://example.test/job")
        self.assertEqual(first["id"], "page-1")
        self.assertEqual(second["id"], "page-1")
        query.assert_called_once_with("db-1")

    def test_database_schema_is_prepared_once_per_client(self) -> None:
        with patch.object(self.client, "_request", return_value={}) as request:
            self.assertTrue(self.client.ensure_database_properties("db-1"))
            self.assertTrue(self.client.ensure_database_properties("db-1"))
        request.assert_called_once()

    @patch("urllib.request.urlopen")
    def test_create_card_with_pdf_blocks(self, mock_urlopen: MagicMock) -> None:
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value.read.return_value = json.dumps({
            "id": "page-999",
            "url": "https://notion.so/page999",
            "object": "page",
        }).encode("utf-8")
        mock_urlopen.return_value = mock_cm

        payload = NotionCardPayload(
            application_title="Acme Corp - Lead Engineer",
            company="Acme Corp",
            role="Lead Engineer",
            status="TO_APPLY",
            current_version="v001",
            job_summary_text="Build scalable systems.",
            requirements_text="Python, XeLaTeX, Cloud",
            match_analysis_text="Strong alignment with backend architecture.",
            gaps_text="None",
        )

        res = self.client.create_card(
            database_id="db-123",
            payload=payload,
            resume_file_id="file-resume-111",
            letter_file_id="file-letter-222",
            zip_file_id="file-zip-333",
        )

        self.assertEqual(res["id"], "page-999")
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode("utf-8"))
        self.assertEqual(data["parent"]["database_id"], "db-123")
        self.assertEqual(data["properties"]["Company"]["rich_text"][0]["text"]["content"], "Acme Corp")
        pdf_blocks = [c for c in data["children"] if c.get("type") == "pdf"]
        self.assertEqual(len(pdf_blocks), 2)
        self.assertEqual(pdf_blocks[0]["pdf"]["file_upload"]["id"], "file-resume-111")
        self.assertEqual(pdf_blocks[1]["pdf"]["file_upload"]["id"], "file-letter-222")

    @patch("urllib.request.urlopen")
    def test_create_card_with_match_score_and_breakdown(self, mock_urlopen: MagicMock) -> None:
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value.read.return_value = json.dumps({"id": "page-score-123"}).encode("utf-8")
        mock_urlopen.return_value = mock_cm

        payload = NotionCardPayload(
            application_title="Gorgias - Software Engineer",
            company="Gorgias",
            role="Software Engineer",
            status="TO_APPLY",
            current_version="v001",
            match_score=88,
            match_breakdown={
                "skills_score": 26,
                "experience_score": 22,
                "role_score": 18,
                "location_score": 15,
                "company_fit_score": 4,
                "compensation_score": 3,
            },
        )

        res = self.client.create_card(database_id="db-123", payload=payload)
        self.assertEqual(res["id"], "page-score-123")
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data.decode("utf-8"))
        self.assertEqual(data["properties"]["Match Score"]["number"], 88)
        callout_blocks = [c for c in data["children"] if c.get("type") == "callout"]
        self.assertEqual(len(callout_blocks), 1)
        self.assertIn("88 / 100", callout_blocks[0]["callout"]["rich_text"][0]["text"]["content"])


    @patch("urllib.request.urlopen")
    def test_update_card_documents_replaces_old_blocks(self, mock_urlopen: MagicMock) -> None:
        mock_cm1 = MagicMock()
        mock_cm1.__enter__.return_value.read.return_value = json.dumps({
            "results": [
                {"id": "b1", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Job Summary"}]}},
                {"id": "b2", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Summary"}]}},
                {"id": "b3", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Current Documents"}]}},
                {"id": "b4", "type": "pdf", "pdf": {"file_upload": {"id": "old-resume"}}},
            ]
        }).encode("utf-8")

        mock_cm2 = MagicMock()
        mock_cm2.__enter__.return_value.read.return_value = b"{}"

        mock_cm3 = MagicMock()
        mock_cm3.__enter__.return_value.read.return_value = b"{}"

        mock_urlopen.side_effect = [mock_cm1, mock_cm2, mock_cm3]

        ok = self.client.update_card_documents(
            page_id="page-999",
            version="v002",
            resume_file_id="new-resume-file",
            letter_file_id=None,
            zip_file_id=None,
        )
        self.assertTrue(ok)
        self.assertEqual(mock_urlopen.call_count, 3)

    @patch("urllib.request.urlopen")
    def test_archive_card_on_delete(self, mock_urlopen: MagicMock) -> None:
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value.read.return_value = json.dumps({"id": "page-999", "archived": True}).encode("utf-8")
        mock_urlopen.return_value = mock_cm

        ok = self.client.archive_card("page-999")
        self.assertTrue(ok)
        req = mock_urlopen.call_args[0][0]
        self.assertIn("archived", req.data.decode("utf-8"))


class TestNotionPlugin(unittest.TestCase):
    def test_disabled_when_token_missing(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            plugin = NotionPlugin(token=None)
            self.assertFalse(plugin.is_enabled())
            res = plugin.on_application_saved("user-1", "app-1", {}, {})
            self.assertEqual(res.status, "SKIPPED")

    def test_plugin_creates_card_and_uploads_files(self) -> None:
        mock_client = MagicMock()
        mock_client.upload_file.side_effect = ["resume-id", "letter-id", "zip-id"]
        mock_client.find_card_by_job_url.return_value = None
        mock_client.create_card.return_value = {
            "id": "new-page-id",
            "url": "https://notion.so/newpageid",
        }

        plugin = NotionPlugin(token="ntn_test", client=mock_client)
        self.assertTrue(plugin.is_enabled())

        app_data = {
            "application_id": "acme__eng__123",
            "title": "Acme - Engineer",
            "job": {"company": "Acme", "role": "Engineer", "url": "https://example.com/job/1"},
        }
        version_data = {
            "version": "v001",
            "sources": {"resume.tex": "\\documentclass{article}", "letter.tex": "\\documentclass{letter}"},
        }
        files = {
            "resume.pdf": b"%PDF-resume",
            "motivation-letter.pdf": b"%PDF-letter",
        }

        result = plugin.on_application_saved("user-1", "acme__eng__123", app_data, version_data, files=files)
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.details["notion_page_id"], "new-page-id")
        self.assertIn("resume.pdf", result.details["documents"])
        self.assertIn("motivation-letter.pdf", result.details["documents"])
        self.assertEqual(mock_client.upload_file.call_count, 3)

    def test_plugin_archives_card_on_delete(self) -> None:
        mock_client = MagicMock()
        plugin = NotionPlugin(token="ntn_test", client=mock_client)
        res = plugin.on_application_deleted("user-1", "app-1", metadata={"notion_page_id": "page-123"})
        self.assertEqual(res.status, "OK")
        mock_client.archive_card.assert_called_once_with("page-123")


class TestPluginRegistry(unittest.TestCase):
    def test_registry_dispatch_gracefully_handles_disabled_and_errors(self) -> None:
        registry = PluginRegistry()

        class DummyPlugin:
            name = "dummy"
            def is_enabled(self) -> bool:
                return True
            def on_application_saved(self, **kwargs) -> SinkResult:
                return SinkResult(plugin_name="dummy", status="OK", details={"url": "https://dummy.sink/1"})
            def on_application_deleted(self, **kwargs) -> SinkResult:
                return SinkResult(plugin_name="dummy", status="OK")

        registry.register(DummyPlugin())  # type: ignore
        results = registry.dispatch_saved(
            user_id="u1",
            application_id="a1",
            application_data={},
            version_data={},
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "OK")
        self.assertEqual(results[0].details["url"], "https://dummy.sink/1")


class TestNotionWorker(unittest.TestCase):
    def test_worker_processes_create_job_and_updates_firestore(self) -> None:
        from job_application_agents.plugins.notion.worker import NotionWorker

        mock_repo = MagicMock()
        mock_sync_repo = MagicMock()
        mock_plugin = MagicMock()

        mock_sync_repo.fetch_application.return_value = None
        mock_sync_repo.fetch_application_version.return_value = None

        mock_plugin.on_application_saved.return_value = SinkResult(
            plugin_name="notion",
            status="OK",
            details={
                "notion_page_id": "page-12345",
                "notion_page_url": "https://notion.so/page12345",
                "documents": {"resume.pdf": {"file_id": "fid-1"}},
            },
        )

        worker = NotionWorker(
            repository=mock_repo,
            sync_repository=mock_sync_repo,
            plugin=mock_plugin,
            worker_id="test-worker",
        )

        job = NotionSyncJob(
            id="00000000-0000-0000-0000-000000000001",
            user_id="user-1",
            application_id="app-1",
            action="CREATE_OR_UPDATE",
            payload={"current_version": "v001"},
        )

        worker.process(job)

        mock_plugin.on_application_saved.assert_called_once()
        mock_sync_repo.update_application_fields.assert_called_once()
        update_args = mock_sync_repo.update_application_fields.call_args.args
        self.assertEqual(update_args[0:2], ("user-1", "app-1"))
        self.assertEqual(update_args[2]["notion_page_id"], "page-12345")
        self.assertEqual(update_args[2]["notion_page_url"], "https://notion.so/page12345")
        self.assertEqual(update_args[2]["documents"], {"resume.pdf": {"file_id": "fid-1"}})
        self.assertEqual(update_args[2]["sync"]["last_source"], "firestore")
        mock_repo.succeed.assert_called_once()

    def test_worker_processes_delete_job(self) -> None:
        from job_application_agents.plugins.notion.worker import NotionWorker

        mock_repo = MagicMock()
        mock_sync_repo = MagicMock()
        mock_plugin = MagicMock()

        mock_plugin.on_application_deleted.return_value = SinkResult(
            plugin_name="notion",
            status="OK",
            details={"archived_page_id": "page-12345"},
        )

        worker = NotionWorker(
            repository=mock_repo,
            sync_repository=mock_sync_repo,
            plugin=mock_plugin,
            worker_id="test-worker",
        )

        job = NotionSyncJob(
            id="00000000-0000-0000-0000-000000000002",
            user_id="user-1",
            application_id="app-1",
            action="DELETE",
            payload={"notion_page_id": "page-12345"},
        )

        worker.process(job)

        mock_plugin.on_application_deleted.assert_called_once_with(
            user_id="user-1",
            application_id="app-1",
            metadata={"notion_page_id": "page-12345"},
        )
        mock_repo.succeed.assert_called_once()

    def test_worker_dynamically_routes_to_user_configured_database(self) -> None:
        from job_application_agents.plugins.notion.worker import NotionWorker

        mock_repo = MagicMock()
        mock_sync_repo = MagicMock()
        mock_plugin = MagicMock()

        # User A has custom database db-alice
        mock_sync_repo.get_user_notion_config.side_effect = lambda uid: (
            {"database_id": "db-alice", "enabled": True} if uid == "user-alice" else {"database_id": "db-bob", "enabled": True}
        )
        mock_sync_repo.fetch_application.return_value = None
        mock_sync_repo.fetch_application_version.return_value = None

        mock_plugin.on_application_saved.return_value = SinkResult(
            plugin_name="notion",
            status="OK",
            details={"notion_page_id": "p-1"},
        )

        worker = NotionWorker(
            repository=mock_repo,
            sync_repository=mock_sync_repo,
            plugin=mock_plugin,
            worker_id="test-worker",
        )

        # 1. Process job for Alice
        job_alice = NotionSyncJob(
            id="00000000-0000-0000-0000-000000000003",
            user_id="user-alice",
            application_id="app-alice-1",
            action="CREATE_OR_UPDATE",
            payload={},
        )
        worker.process(job_alice)
        _, kwargs_alice = mock_plugin.on_application_saved.call_args
        self.assertEqual(kwargs_alice["database_id"], "db-alice")

        # 2. Process job for Bob
        job_bob = NotionSyncJob(
            id="00000000-0000-0000-0000-000000000004",
            user_id="user-bob",
            application_id="app-bob-1",
            action="CREATE_OR_UPDATE",
            payload={},
        )
        worker.process(job_bob)
        _, kwargs_bob = mock_plugin.on_application_saved.call_args
        self.assertEqual(kwargs_bob["database_id"], "db-bob")


if __name__ == "__main__":
    unittest.main()
