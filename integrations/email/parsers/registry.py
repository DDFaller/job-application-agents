"""Registry managing and dispatching specialized email alert parsers."""

from __future__ import annotations

from typing import Any

from ...base import BaseEmailParser
from ...models import EmailMessage, JobAlertItem
from .generic import GenericJobAlertParser
from .glassdoor import GlassdoorJobAlertParser
from .greenhouse_lever import DirectATSPostingParser
from .indeed import IndeedJobAlertParser
from .linkedin import LinkedInJobAlertParser


class EmailParserRegistry:
    """Manages parser priority and routing for email messages."""

    def __init__(self) -> None:
        self._parsers: list[BaseEmailParser] = []
        self._generic_fallback: BaseEmailParser = GenericJobAlertParser()
        self._register_defaults()

    def _register_defaults(self) -> None:
        # Priority order: specialized platform parsers first, generic last
        self.register(LinkedInJobAlertParser())
        self.register(IndeedJobAlertParser())
        self.register(GlassdoorJobAlertParser())
        self.register(DirectATSPostingParser())

    def register(self, parser: BaseEmailParser) -> None:
        self._parsers.append(parser)

    def get_parser(self, message: EmailMessage) -> BaseEmailParser:
        """Find the most specific parser for this message, falling back to generic."""
        for parser in self._parsers:
            if parser.can_parse(message):
                return parser
        return self._generic_fallback

    def parse_message(self, message: EmailMessage) -> list[JobAlertItem]:
        """Route message to appropriate parser and extract structured job alert items."""
        parser = self.get_parser(message)
        return parser.parse_jobs(message)


# Global default parser registry
parser_registry = EmailParserRegistry()
