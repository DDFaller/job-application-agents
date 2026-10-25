"""Read-only Google Drive client for one shared artifact folder."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qs, urlparse


DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"
_FOLDER_ID = re.compile(r"[A-Za-z0-9_-]{10,}\Z")
_DRIVE_HOSTS = {"drive.google.com", "docs.google.com"}


class DriveConfigurationError(ValueError):
    """Raised when Drive OAuth or service-account configuration is incomplete."""


@dataclass(frozen=True)
class DriveItem:
    """One file or folder returned by the Drive listing."""

    id: str
    name: str
    mime_type: str
    md5: str | None = None
    size: int | None = None

    @property
    def is_folder(self) -> bool:
        return self.mime_type == GOOGLE_FOLDER_MIME

    @property
    def is_downloadable(self) -> bool:
        return not self.mime_type.startswith("application/vnd.google-apps.")


def parse_folder_id(value: str) -> str:
    """Accept a raw Drive folder id or a drive.google.com folder URL."""

    text = value.strip()
    if _FOLDER_ID.fullmatch(text):
        return text
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc not in _DRIVE_HOSTS:
            raise DriveConfigurationError("Drive folder URL must be on drive.google.com")
        match = re.search(r"/folders/([A-Za-z0-9_-]{10,})", parsed.path)
        if match:
            return match.group(1)
        identifiers = parse_qs(parsed.query).get("id", [])
        if identifiers and _FOLDER_ID.fullmatch(identifiers[0]):
            return identifiers[0]
    raise DriveConfigurationError(
        "drive folder_id must be a Drive folder id or a drive.google.com folder URL"
    )


def _item_from_api(raw: dict[str, Any]) -> DriveItem:
    size = raw.get("size")
    parsed_size = int(size) if isinstance(size, (int, str)) and str(size).isdigit() else None
    checksum = raw.get("md5Checksum")
    return DriveItem(
        id=str(raw.get("id") or ""),
        name=str(raw.get("name") or ""),
        mime_type=str(raw.get("mimeType") or ""),
        md5=str(checksum) if checksum else None,
        size=parsed_size,
    )


def _download_media_request(request: Any) -> bytes:
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise DriveConfigurationError(
            "Google Drive dependencies are missing; install google-api-python-client, "
            "google-auth-httplib2, and google-auth-oauthlib"
        ) from exc
    import io

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request, chunksize=1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


class GoogleDriveClient:
    """Drive v3 client limited to the configured read-only scope."""

    def __init__(
        self,
        config: Any,
        service: Any | None = None,
        *,
        downloader: Any | None = None,
    ) -> None:
        self.config = config
        self._service = service
        self._downloader = downloader or _download_media_request

    @property
    def service(self) -> Any:
        if self._service is None:
            raise DriveConfigurationError("Google Drive is not connected")
        return self._service

    def _save_credentials(self, credentials: Any) -> None:
        token_path = Path(self.config.token_path).expanduser()
        token_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = token_path.with_name(f".{token_path.name}.{os.getpid()}.tmp")
        temporary.write_text(credentials.to_json(), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(token_path)
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass

    def _oauth_credentials(self, *, interactive: bool) -> Any:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise DriveConfigurationError(
                "Google Drive dependencies are missing; install google-api-python-client, "
                "google-auth-httplib2, and google-auth-oauthlib"
            ) from exc

        token_path = Path(self.config.token_path).expanduser()
        credentials = None
        if token_path.is_file():
            try:
                credentials = Credentials.from_authorized_user_file(
                    str(token_path), [DRIVE_READONLY_SCOPE]
                )
            except (OSError, ValueError):
                credentials = None
        if credentials and credentials.valid:
            return credentials
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                self._save_credentials(credentials)
                return credentials
            except Exception as exc:
                if not interactive:
                    raise DriveConfigurationError(
                        "Google Drive OAuth refresh failed; run authorize again"
                    ) from exc
        if not interactive:
            raise DriveConfigurationError(
                "Google Drive authorization is required; run "
                "python3 scripts/drive_artifacts.py authorize"
            )
        secrets = Path(self.config.client_secrets_path).expanduser()
        if not secrets.is_file():
            raise DriveConfigurationError(
                f"Drive desktop OAuth client JSON not found: {secrets}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets), [DRIVE_READONLY_SCOPE])
        credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        self._save_credentials(credentials)
        return credentials

    def _service_account_credentials(self) -> Any:
        try:
            from google.oauth2 import service_account
        except ImportError as exc:
            raise DriveConfigurationError(
                "Google Drive dependencies are missing; install google-api-python-client "
                "and google-auth"
            ) from exc
        from .config import default_service_account_cache, materialize_service_account_json

        key_path = self.config.service_account_file
        if key_path is None and self.config.service_account_from_env:
            raw = os.environ.get("JAA_DRIVE_SERVICE_ACCOUNT_JSON", "")
            key_path = materialize_service_account_json(
                raw,
                destination=default_service_account_cache(),
                repo_root=Path(__file__).resolve().parents[2],
            )
        if key_path is None or not Path(key_path).expanduser().is_file():
            raise DriveConfigurationError(
                "Service account mode requires JAA_DRIVE_SERVICE_ACCOUNT_FILE "
                "or JAA_DRIVE_SERVICE_ACCOUNT_JSON"
            )
        return service_account.Credentials.from_service_account_file(
            str(Path(key_path).expanduser()), scopes=[DRIVE_READONLY_SCOPE]
        )

    def _build_service(self, credentials: Any) -> Any:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise DriveConfigurationError(
                "Google Drive dependencies are missing; install google-api-python-client, "
                "google-auth-httplib2, and google-auth-oauthlib"
            ) from exc
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    def connect(self, *, interactive: bool = False) -> None:
        """Build a Drive service from cached OAuth or a service account key."""

        if self.config.auth_mode == "service_account":
            credentials = self._service_account_credentials()
        else:
            credentials = self._oauth_credentials(interactive=interactive)
        self._service = self._build_service(credentials)

    def authorize(self) -> str:
        """Run browser OAuth, or connect a service account, and return the account email."""

        if self.config.auth_mode == "service_account":
            self.connect(interactive=False)
        else:
            self.connect(interactive=True)
        about = self.service.about().get(fields="user").execute()
        user = about.get("user") if isinstance(about, dict) else None
        email = ""
        if isinstance(user, dict):
            email = str(user.get("emailAddress") or "")
        return email

    def list_children(self, folder_id: str) -> list[DriveItem]:
        """List direct children of one folder. The folder id is not interpolated raw."""

        checked = parse_folder_id(folder_id)
        items: list[DriveItem] = []
        page_token: str | None = None
        while True:
            response = (
                self.service.files()
                .list(
                    q=f"'{checked}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name, mimeType, md5Checksum, size)",
                    pageSize=100,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                )
                .execute()
            )
            items.extend(_item_from_api(raw) for raw in response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return items

    def download(self, file_id: str) -> bytes:
        """Download one binary Drive file. Google-native files are not requested here."""

        if not _FOLDER_ID.fullmatch(file_id):
            raise DriveConfigurationError("Drive file id is invalid")
        request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        return self._downloader(request)
