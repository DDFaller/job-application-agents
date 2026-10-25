"""Ordinary, paced form input and durable exclusions for blocked websites."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any, Callable
from urllib.parse import urlsplit


def website_host(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("An absolute HTTP(S) website URL is required")
    return parsed.hostname.lower().rstrip(".")


class SiteExclusions:
    """Keep website exclusions outside the repository, without query tokens."""

    def __init__(self, data_root: Path):
        self.path = data_root / "auto-apply" / "excluded-sites.json"

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or not isinstance(value.get("sites"), list):
            raise ValueError("Invalid website exclusion ledger; stop automation")
        for entry in value["sites"]:
            if (not isinstance(entry, dict) or not isinstance(entry.get("host"), str)
                    or not entry["host"] or not isinstance(entry.get("include_subdomains"), bool)):
                raise ValueError("Invalid website exclusion entry; stop automation")
        return value["sites"]

    def match(self, url: str) -> dict[str, Any] | None:
        host = website_host(url)
        for entry in self.entries():
            excluded = entry["host"]
            if host == excluded or (entry["include_subdomains"] and host.endswith("." + excluded)):
                return entry
        return None

    def require_allowed(self, url: str) -> None:
        entry = self.match(url)
        if entry:
            raise PermissionError(f"Website excluded: {entry['host']} ({entry.get('reason', 'blocked')})")

    def record(self, url: str, *, reason: str, evidence: str,
               include_subdomains: bool = False) -> None:
        """Record an observed block or an explicit user exclusion, never a guess."""
        if reason not in {"captcha", "automation_block", "user_exclusion"}:
            raise ValueError("Record only a verified challenge, automation block or user exclusion")
        if not evidence.strip():
            raise ValueError("A short observation or user-instruction reference is required")
        host = website_host(url)
        entries = self.entries()
        if any(entry["host"] == host for entry in entries):
            return
        entries.append({"host": host, "include_subdomains": include_subdomains,
                        "reason": reason, "evidence": evidence,
                        "recorded_at": datetime.now(timezone.utc).isoformat()})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                         prefix=".excluded-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"schema_version": 1, "sites": entries}, handle, indent=2)
            handle.write("\n")
        try:
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)


class PacedFormInput:
    """Use Playwright's normal input events with explicit, fixed timing."""

    def __init__(self, page: Any, *, character_delay_ms: int = 50,
                 field_delay_ms: int = 1000,
                 before_input: Callable[[], None] | None = None):
        if character_delay_ms < 0 or field_delay_ms < 0:
            raise ValueError("Input delays cannot be negative")
        self.page = page
        self.character_delay_ms = character_delay_ms
        self.field_delay_ms = field_delay_ms
        self._previous_field: str | None = None
        self.before_input = before_input

    def _before(self, field: str) -> None:
        if self.before_input:
            self.before_input()
        if self._previous_field is not None and self._previous_field != field:
            self.page.wait_for_timeout(self.field_delay_ms)
        self._previous_field = field

    def text(self, field: str, locator: Any, value: str) -> None:
        self._before(field)
        locator.fill("")
        locator.press_sequentially(value, delay=self.character_delay_ms)

    def select(self, field: str, locator: Any, *, label: str) -> None:
        self._before(field)
        locator.select_option(label=label)

    def check(self, field: str, locator: Any, *, checked: bool = True) -> None:
        self._before(field)
        locator.set_checked(checked)

    def upload(self, field: str, locator: Any, path: Path) -> None:
        self._before(field)
        locator.set_input_files(str(path.resolve(strict=True)))

    def click(self, field: str, locator: Any) -> None:
        self._before(field)
        locator.click()


def form_input(page: Any) -> PacedFormInput:
    """Share pacing across driver operations on the same page."""
    existing = getattr(page, "_jaa_form_input", None)
    if isinstance(existing, PacedFormInput):
        return existing
    inputs = PacedFormInput(page)
    page._jaa_form_input = inputs
    return inputs
