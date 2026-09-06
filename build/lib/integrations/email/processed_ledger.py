"""Atomic, privacy-preserving ledger for checked email messages."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

from ..models import EmailMessage


def normalize_message_id(message_id: str | None) -> str:
    """Normalize a Message-ID for stable cross-folder identity."""
    value = (message_id or "").strip().casefold()
    while value.startswith("<") and value.endswith(">") and len(value) > 1:
        value = value[1:-1].strip()
    return value


def message_content_sha256(message: EmailMessage) -> str:
    """Hash message content for diagnostics without storing its body."""
    material = "\x1f".join(
        [
            message.sender,
            message.recipient,
            message.subject,
            message.date_str,
            message.body_plain,
            message.body_html,
        ]
    )
    return hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()


class ProcessedEmailLedger:
    """JSON ledger whose updates are committed with atomic replacement."""

    VERSION = 1

    def __init__(self, path: Path, folder: str = "INBOX") -> None:
        self.path = Path(path)
        self.folder = folder
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    @staticmethod
    def identity_for(message: EmailMessage, folder: str = "INBOX") -> dict[str, str]:
        return {
            "message_id": normalize_message_id(message.message_id),
            "folder": folder,
            "uid": str(message.uid or ""),
        }

    @classmethod
    def key_for_identity(cls, identity: dict[str, str]) -> str:
        message_id = normalize_message_id(identity.get("message_id"))
        if message_id:
            return f"message-id:{message_id}"
        return f"uid:{identity.get('folder', '')}:{identity.get('uid', '')}"

    def key_for(self, message: EmailMessage) -> str:
        return self.key_for_identity(self.identity_for(message, self.folder))

    def get(self, message: EmailMessage) -> dict[str, Any] | None:
        return self._records.get(self.key_for(message))

    def contains(self, message: EmailMessage) -> bool:
        return self.get(message) is not None

    def is_failed(self, message: EmailMessage) -> bool:
        record = self.get(message)
        return bool(record and (record.get("parse_status") == "failed" or record.get("error")))

    def record_message(
        self,
        message: EmailMessage,
        *,
        matched_providers: Iterable[str] = (),
        matched_aliases: Iterable[str] = (),
        filter_status: str,
        parse_status: str,
        job_keys: Iterable[str] = (),
        error: str | None = None,
        checked_at: str | None = None,
    ) -> dict[str, Any]:
        identity = self.identity_for(message, self.folder)
        record: dict[str, Any] = {
            "identity": identity,
            "content_sha256": message_content_sha256(message),
            "checked_at": checked_at or datetime.now(timezone.utc).isoformat(),
            "matched_providers": list(dict.fromkeys(matched_providers)),
            "matched_aliases": list(dict.fromkeys(matched_aliases)),
            "filter_status": filter_status,
            "parse_status": parse_status,
            "job_keys": list(dict.fromkeys(job_keys)),
            "error": error,
        }
        self._records[self.key_for_identity(identity)] = record
        self.save()
        return record

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": self.VERSION, "records": list(self._records.values())}
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def records(self) -> list[dict[str, Any]]:
        return list(self._records.values())

    def summary(self) -> dict[str, int]:
        records = self.records()
        return {
            "total": len(records),
            "matched": sum(r.get("filter_status") == "matched" for r in records),
            "no_match": sum(r.get("filter_status") == "no_match" for r in records),
            "failed": sum(
                bool(r.get("parse_status") == "failed" or r.get("error"))
                for r in records
            ),
            "staged": sum(r.get("parse_status") == "staged" for r in records),
        }

    def _load(self) -> None:
        if not self.path.is_file():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            records = raw
        elif isinstance(raw, dict) and isinstance(raw.get("records"), list):
            records = raw["records"]
        else:
            raise ValueError(f"Malformed processed-email ledger: {self.path}")
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("identity"), dict):
                raise ValueError(f"Malformed processed-email ledger record: {self.path}")
            identity = record["identity"]
            self._records[self.key_for_identity(identity)] = record
