"""Unit tests for the read-only Google Drive artifact folder."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest

from job_application_agents.config import ConfigurationError

from integrations.drive.client import (
    DRIVE_READONLY_SCOPE,
    DriveItem,
    GoogleDriveClient,
    parse_folder_id,
)
from integrations.drive.config import DriveConfig, load_drive_config, materialize_service_account_json
from integrations.drive.sync import DriveSyncError, iter_drive_tree, pull_drive_folder


ROOT = Path(__file__).resolve().parents[2]
FOLDER_ID = "0123456789abcdef"
SECRET = "SUPER-SECRET-KEY"


class _Request:
    def __init__(self, value: dict) -> None:
        self.value = value

    def execute(self) -> dict:
        return self.value


class _Files:
    def __init__(self) -> None:
        self.list_calls: list[dict] = []
        self.pages = {
            None: {
                "files": [
                    {
                        "id": "childfolder01",
                        "name": "applications",
                        "mimeType": "application/vnd.google-apps.folder",
                    }
                ],
                "nextPageToken": "page-2",
            },
            "page-2": {
                "files": [
                    {
                        "id": "resume-file01",
                        "name": "resume.pdf",
                        "mimeType": "application/pdf",
                        "md5Checksum": "abc",
                        "size": "12",
                    }
                ]
            },
        }

    def list(self, **kwargs: object) -> _Request:
        self.list_calls.append(kwargs)
        return _Request(self.pages[kwargs.get("pageToken")])

    def get_media(self, **kwargs: object) -> bytes:
        return b"pdf-bytes"


class _FakeService:
    def __init__(self) -> None:
        self._files = _Files()

    def files(self) -> _Files:
        return self._files


class _FakeSource:
    def __init__(self, tree: dict[str, list[DriveItem]], payloads: dict[str, bytes]) -> None:
        self.tree = tree
        self.payloads = payloads
        self.downloads: list[str] = []

    def list_children(self, folder_id: str) -> list[DriveItem]:
        return list(self.tree[folder_id])

    def download(self, file_id: str) -> bytes:
        self.downloads.append(file_id)
        return self.payloads[file_id]


def _pdf_item(file_id: str, name: str, payload: bytes, *, size: int | None = None) -> DriveItem:
    return DriveItem(
        id=file_id,
        name=name,
        mime_type="application/pdf",
        md5=hashlib.md5(payload).hexdigest(),
        size=len(payload) if size is None else size,
    )


class DriveFolderIdTests(unittest.TestCase):
    def test_accepts_id_and_drive_urls(self) -> None:
        self.assertEqual(parse_folder_id(FOLDER_ID), FOLDER_ID)
        self.assertEqual(
            parse_folder_id(f"https://drive.google.com/drive/folders/{FOLDER_ID}?usp=sharing"),
            FOLDER_ID,
        )
        self.assertEqual(
            parse_folder_id(f"https://drive.google.com/open?id={FOLDER_ID}"),
            FOLDER_ID,
        )

    def test_rejects_other_hosts_and_query_injection(self) -> None:
        with self.assertRaises(ValueError):
            parse_folder_id("https://evil.example/folders/" + FOLDER_ID)
        with self.assertRaises(ValueError):
            parse_folder_id("abc' or name contains 'secret")


class DriveConfigTests(unittest.TestCase):
    def test_environment_overrides_file_and_keeps_json_out_of_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "data_root": str(Path(directory) / "from-file"),
                        "drive": {"folder_id": "aaaaaaaaaa", "auth_mode": "oauth"},
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_drive_config(
                config_path,
                environ={
                    "JAA_DRIVE_FOLDER_ID": f"https://drive.google.com/drive/folders/{FOLDER_ID}",
                    "JAA_DRIVE_AUTH_MODE": "service_account",
                    "JAA_DATA_ROOT": str(Path(directory) / "from-env"),
                    "JAA_DRIVE_SERVICE_ACCOUNT_JSON": json.dumps({"private_key": SECRET}),
                },
            )
        self.assertEqual(loaded.folder_id, FOLDER_ID)
        self.assertEqual(loaded.auth_mode, "service_account")
        self.assertEqual(loaded.data_root, Path(directory) / "from-env")
        self.assertTrue(loaded.service_account_from_env)
        self.assertNotIn(SECRET, repr(loaded))

    def test_example_documents_read_only_drive_connection(self) -> None:
        example = (ROOT / "config.example.jsonc").read_text(encoding="utf-8")
        self.assertIn("drive.readonly", example)
        self.assertIn("service_account", example)
        self.assertIn("folder_id", example)

    def test_service_account_json_is_written_outside_the_repo_without_leaking(self) -> None:
        raw = json.dumps(
            {
                "type": "service_account",
                "client_email": "drive@example.iam.gserviceaccount.com",
                "private_key": SECRET,
            }
        )
        broken = '{"private_key": "' + SECRET
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            destination = root / "cache" / "key.json"
            written = materialize_service_account_json(raw, destination=destination, repo_root=repo)
            self.assertEqual(stat.S_IMODE(written.stat().st_mode) & 0o777, 0o600)
            self.assertIn(SECRET, written.read_text(encoding="utf-8"))
            with self.assertRaises(ConfigurationError) as caught:
                materialize_service_account_json(raw, destination=repo / "key.json", repo_root=repo)
            self.assertNotIn(SECRET, str(caught.exception))
            self.assertFalse((repo / "key.json").exists())
        with self.assertRaises(ConfigurationError) as caught:
            materialize_service_account_json(
                broken, destination=Path(tempfile.gettempdir()) / "unused-drive-key.json", repo_root=ROOT
            )
        self.assertNotIn(SECRET, str(caught.exception))


class DriveClientTests(unittest.TestCase):
    def test_listing_is_paged_and_scoped_to_the_folder(self) -> None:
        service = _FakeService()
        client = GoogleDriveClient(
            DriveConfig(folder_id=FOLDER_ID), service=service, downloader=lambda request: request
        )
        items = client.list_children(FOLDER_ID)
        self.assertEqual([item.name for item in items], ["applications", "resume.pdf"])
        self.assertEqual(service.files().list_calls[0]["q"], f"'{FOLDER_ID}' in parents and trashed = false")
        self.assertEqual(service.files().list_calls[0]["corpora"], "allDrives")
        self.assertEqual(service.files().list_calls[1]["pageToken"], "page-2")
        self.assertEqual(client.download("resume-file01"), b"pdf-bytes")
        self.assertEqual(DRIVE_READONLY_SCOPE, "https://www.googleapis.com/auth/drive.readonly")

    def test_download_rejects_a_short_file_id(self) -> None:
        client = GoogleDriveClient(DriveConfig(), service=_FakeService(), downloader=lambda request: request)
        with self.assertRaises(ValueError):
            client.download("short")


class DrivePullTests(unittest.TestCase):
    def _source(self) -> tuple[_FakeSource, bytes]:
        payload = b"%PDF-1.4 resume"
        source = _FakeSource(
            {
                FOLDER_ID: [
                    DriveItem(
                        id="childfolder01",
                        name="applications",
                        mime_type="application/vnd.google-apps.folder",
                    ),
                    DriveItem(
                        id="notes-doc-001",
                        name="Notes",
                        mime_type="application/vnd.google-apps.document",
                    ),
                ],
                "childfolder01": [
                    _pdf_item("resume-file01", "resume.pdf", payload),
                ],
            },
            {"resume-file01": payload},
        )
        return source, payload

    def test_pull_writes_outside_the_repo_and_skips_google_docs(self) -> None:
        source, payload = self._source()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "job-search"
            result = pull_drive_folder(source, FOLDER_ID, destination, repo_root=ROOT)
            written = destination / "applications" / "resume.pdf"
            self.assertEqual(written.read_bytes(), payload)
            self.assertEqual(result.written, ("applications/resume.pdf",))
            self.assertEqual(result.skipped, ("Notes (skipped application/vnd.google-apps.document)",))
            receipt = json.loads((destination / ".drive-sync.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["folder_id"], FOLDER_ID)
            self.assertNotIn(payload.decode(), json.dumps(receipt))
            self.assertEqual(source.downloads, ["resume-file01"])

            again = pull_drive_folder(source, FOLDER_ID, destination, repo_root=ROOT)
            self.assertEqual(again.unchanged, ("applications/resume.pdf",))
            self.assertEqual(source.downloads, ["resume-file01"])

    def test_pull_refuses_the_repository_and_unsafe_names(self) -> None:
        source, _payload = self._source()
        with self.assertRaises(DriveSyncError):
            pull_drive_folder(source, FOLDER_ID, ROOT / "data", repo_root=ROOT)
        unsafe = _FakeSource(
            {FOLDER_ID: [DriveItem(id="bad-name-001", name="../secret.pdf", mime_type="application/pdf")]},
            {},
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DriveSyncError):
                iter_drive_tree(unsafe, FOLDER_ID)
            self.assertEqual(unsafe.downloads, [])
            self.assertFalse(any(Path(directory).rglob("secret.pdf")))

    def test_pull_stops_on_checksum_mismatch_and_size_limit(self) -> None:
        payload = b"not-the-declared-bytes"
        mismatch = _FakeSource(
            {
                FOLDER_ID: [
                    DriveItem(
                        id="resume-file01",
                        name="resume.pdf",
                        mime_type="application/pdf",
                        md5="0" * 32,
                        size=len(payload),
                    )
                ]
            },
            {"resume-file01": payload},
        )
        oversized = _FakeSource(
            {
                FOLDER_ID: [
                    DriveItem(
                        id="huge-file-001",
                        name="huge.pdf",
                        mime_type="application/pdf",
                        size=50,
                    )
                ]
            },
            {"huge-file-001": b"x" * 50},
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "job-search"
            with self.assertRaisesRegex(DriveSyncError, "checksum mismatch"):
                pull_drive_folder(mismatch, FOLDER_ID, destination, repo_root=ROOT)
            self.assertFalse((destination / "resume.pdf").exists())
            with self.assertRaisesRegex(DriveSyncError, "exceeds"):
                pull_drive_folder(oversized, FOLDER_ID, destination, repo_root=ROOT, max_bytes=10)
            self.assertEqual(oversized.downloads, [])

    def test_duplicate_paths_are_rejected(self) -> None:
        item = DriveItem(id="resume-file01", name="resume.pdf", mime_type="application/pdf")
        other = DriveItem(id="resume-file02", name="resume.pdf", mime_type="application/pdf")
        source = _FakeSource({FOLDER_ID: [item, other]}, {})
        with self.assertRaisesRegex(DriveSyncError, "duplicate Drive path"):
            iter_drive_tree(source, FOLDER_ID)


class DriveCliTests(unittest.TestCase):
    def test_status_without_a_folder_is_blocked(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "drive_artifacts_cli", ROOT / "scripts" / "drive_artifacts.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text("{}", encoding="utf-8")
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    module.main(["--config", str(config)])
                code = module.main(["--config", str(config), "status"])
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
