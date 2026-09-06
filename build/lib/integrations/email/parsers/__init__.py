"""Email parsers package."""

from .base import HTMLTextExtractor, clean_html_snippet, strip_tracking_params
from .generic import GenericJobAlertParser
from .glassdoor import GlassdoorJobAlertParser
from .greenhouse_lever import DirectATSPostingParser
from .indeed import IndeedJobAlertParser
from .linkedin import LinkedInJobAlertParser
from .registry import EmailParserRegistry, parser_registry

__all__ = [
    "HTMLTextExtractor",
    "clean_html_snippet",
    "strip_tracking_params",
    "LinkedInJobAlertParser",
    "IndeedJobAlertParser",
    "GlassdoorJobAlertParser",
    "DirectATSPostingParser",
    "GenericJobAlertParser",
    "EmailParserRegistry",
    "parser_registry",
]
