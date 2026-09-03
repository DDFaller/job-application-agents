"""Email integration subpackage."""

from .gmail_client import GmailClient
from .gmail_api_client import GmailApiClient, GmailApiConfigurationError
from .factory import FallbackEmailClient, create_email_client
from .processed_ledger import ProcessedEmailLedger, message_content_sha256, normalize_message_id
from .provider_filter import (
    ProviderFilterResult,
    ProviderMatch,
    ProviderSettingsError,
    filter_message,
    load_provider_settings,
    normalize_search_text,
    searchable_fields,
    validate_provider_settings,
)
from .parsers import (
    DirectATSPostingParser,
    EmailParserRegistry,
    GenericJobAlertParser,
    GlassdoorJobAlertParser,
    IndeedJobAlertParser,
    LinkedInJobAlertParser,
    parser_registry,
)

__all__ = [
    "GmailClient",
    "GmailApiClient",
    "GmailApiConfigurationError",
    "create_email_client",
    "FallbackEmailClient",
    "LinkedInJobAlertParser",
    "IndeedJobAlertParser",
    "GlassdoorJobAlertParser",
    "DirectATSPostingParser",
    "GenericJobAlertParser",
    "EmailParserRegistry",
    "parser_registry",
    "ProcessedEmailLedger",
    "message_content_sha256",
    "normalize_message_id",
    "ProviderFilterResult",
    "ProviderMatch",
    "ProviderSettingsError",
    "filter_message",
    "load_provider_settings",
    "normalize_search_text",
    "searchable_fields",
    "validate_provider_settings",
]
