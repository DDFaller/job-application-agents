"""Provider-first filtering for untrusted email content."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Mapping, Sequence

from ..models import EmailMessage
from .parsers.base import HTMLTextExtractor


KNOWN_PROVIDERS = frozenset({"LINKEDIN", "INDEED"})


def normalize_search_text(value: str | None) -> str:
    """Normalize text for case-insensitive, punctuation/whitespace-safe search."""
    if not value:
        return ""
    # Keep words separated when punctuation is used as a boundary, while
    # preserving aliases such as ``linkedinjobs`` as one searchable token.
    value = value.casefold()
    value = re.sub(r"[\W_]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def normalize_provider(value: str) -> str:
    return str(value).strip().upper()


class ProviderSettingsError(ValueError):
    """Raised when manually edited provider settings are unsafe or malformed."""


def validate_provider_settings(
    providers: Sequence[str], matches: Mapping[str, Sequence[str]]
) -> tuple[list[str], dict[str, list[str]]]:
    """Validate and normalize provider settings without touching Gmail."""
    if not isinstance(providers, (list, tuple)):
        raise ProviderSettingsError("PROVIDERS must be a list or tuple")
    if not isinstance(matches, Mapping):
        raise ProviderSettingsError("matches_dict must be a mapping")

    normalized_providers: list[str] = []
    for provider in providers:
        if not isinstance(provider, str) or not provider.strip():
            raise ProviderSettingsError("PROVIDERS entries must be non-empty strings")
        normalized = normalize_provider(provider)
        if normalized not in KNOWN_PROVIDERS:
            raise ProviderSettingsError(f"Unknown provider: {provider!r}")
        if normalized in normalized_providers:
            raise ProviderSettingsError(f"Duplicate provider: {provider!r}")
        normalized_providers.append(normalized)

    normalized_matches: dict[str, list[str]] = {}
    seen_aliases: dict[str, str] = {}
    for provider, aliases in matches.items():
        if not isinstance(provider, str):
            raise ProviderSettingsError("matches_dict provider names must be strings")
        normalized_provider = normalize_provider(provider)
        if normalized_provider not in KNOWN_PROVIDERS:
            raise ProviderSettingsError(f"Unknown provider in matches_dict: {provider!r}")
        if not isinstance(aliases, (list, tuple)) or not aliases:
            raise ProviderSettingsError(
                f"Provider {normalized_provider} must have a non-empty alias list"
            )
        normalized_aliases: list[str] = []
        for alias in aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ProviderSettingsError(
                    f"Aliases for {normalized_provider} must be non-empty strings"
                )
            normalized_alias = normalize_search_text(alias)
            if not normalized_alias:
                raise ProviderSettingsError(
                    f"Alias {alias!r} for {normalized_provider} is empty after normalization"
                )
            if normalized_alias in normalized_aliases:
                raise ProviderSettingsError(
                    f"Duplicate alias {alias!r} for {normalized_provider}"
                )
            if normalized_alias in seen_aliases:
                raise ProviderSettingsError(
                    f"Duplicate alias {alias!r}; already used by {seen_aliases[normalized_alias]}"
                )
            seen_aliases[normalized_alias] = normalized_provider
            normalized_aliases.append(normalized_alias)
        if normalized_provider in normalized_matches:
            raise ProviderSettingsError(f"Duplicate provider: {provider!r}")
        normalized_matches[normalized_provider] = normalized_aliases

    for provider in normalized_providers:
        if not normalized_matches.get(provider):
            raise ProviderSettingsError(f"Enabled provider {provider} has no aliases")

    return normalized_providers, normalized_matches


def load_provider_settings() -> tuple[list[str], dict[str, list[str]]]:
    """Load the editable settings module and validate it before Gmail access."""
    from .. import auto_ingest_settings

    return validate_provider_settings(
        getattr(auto_ingest_settings, "PROVIDERS", None),
        getattr(auto_ingest_settings, "matches_dict", None),
    )


@dataclass(frozen=True)
class ProviderMatch:
    provider: str
    alias: str
    field: str

    def to_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "alias": self.alias, "field": self.field}


@dataclass
class ProviderFilterResult:
    matched_providers: list[str] = field(default_factory=list)
    matched_aliases: list[str] = field(default_factory=list)
    matches: list[ProviderMatch] = field(default_factory=list)
    searchable_text: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def matched(self) -> bool:
        return bool(self.matched_providers)

    @property
    def filter_status(self) -> str:
        return "matched" if self.matched else "no_match"

    def to_dict(self) -> dict[str, object]:
        return {
            "matched_providers": list(self.matched_providers),
            "matched_aliases": list(self.matched_aliases),
            "matches": [match.to_dict() for match in self.matches],
            "filter_status": self.filter_status,
        }


def searchable_fields(message: EmailMessage) -> dict[str, str]:
    """Return normalized fields; HTML is treated as data and never executed."""
    html_visible = ""
    if message.body_html:
        extractor = HTMLTextExtractor()
        try:
            extractor.feed(message.body_html)
            html_visible = extractor.get_text()
        except Exception:
            html_visible = ""
    return {
        "sender": normalize_search_text(message.sender),
        "subject": normalize_search_text(message.subject),
        "body_plain": normalize_search_text(message.body_plain),
        # Include raw HTML too: provider names can occur in link attributes.
        "body_html": normalize_search_text(f"{html_visible} {message.body_html}"),
    }


def filter_message(
    message: EmailMessage,
    providers: Sequence[str],
    matches: Mapping[str, Sequence[str]],
) -> ProviderFilterResult:
    """Find every enabled provider/alias match and its source field."""
    enabled, aliases_by_provider = validate_provider_settings(providers, matches)
    fields = searchable_fields(message)
    result = ProviderFilterResult(searchable_text=fields)
    for provider in enabled:
        for alias in aliases_by_provider[provider]:
            for field_name, value in fields.items():
                if alias in value:
                    result.matches.append(ProviderMatch(provider, alias, field_name))
                    if provider not in result.matched_providers:
                        result.matched_providers.append(provider)
                    if alias not in result.matched_aliases:
                        result.matched_aliases.append(alias)
    return result
