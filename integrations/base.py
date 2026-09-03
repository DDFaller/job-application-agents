"""Abstract base classes and interfaces for the integrations subsystem."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import (
    EmailAccountConfig,
    EmailMessage,
    IngestedJob,
    IngestionResult,
    JobAlertItem,
    NormalizedJobPosting,
    ScrapedJobContent,
)


class BaseEmailClient(ABC):
    """Abstract interface for email clients (IMAP, Gmail REST API)."""

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection and authenticate with the email provider."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection gracefully."""
        pass

    @abstractmethod
    def test_connection(self) -> dict[str, Any]:
        """Perform diagnostic check and return status dictionary."""
        pass

    @abstractmethod
    def fetch_messages(
        self,
        sender_filters: list[str] | None = None,
        criteria: str = "UNSEEN",
        limit: int = 25,
        since_days: int | None = None,
        search_all: bool = False,
    ) -> list[EmailMessage]:
        """Retrieve candidates, optionally using sender search as an optimization."""
        pass

    @abstractmethod
    def mark_as_read(self, uids: list[str]) -> bool:
        """Mark specified messages as read / seen."""
        pass


class BaseEmailParser(ABC):
    """Abstract interface for parsing job alert emails into structured leads."""

    @property
    @abstractmethod
    def supported_senders(self) -> list[str]:
        """List of email sender addresses or domain patterns supported by this parser."""
        pass

    @abstractmethod
    def can_parse(self, message: EmailMessage) -> bool:
        """Check if this parser can handle the given email message."""
        pass

    @abstractmethod
    def parse_jobs(self, message: EmailMessage) -> list[JobAlertItem]:
        """Extract job alert items from an email message."""
        pass


class BaseJobScraper(ABC):
    """Abstract interface for scraping full job descriptions from URLs."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the scraper implementation."""
        pass

    @abstractmethod
    def scrape(self, url: str, timeout_seconds: int = 30) -> ScrapedJobContent:
        """Fetch and extract raw HTML, visible text, and metadata from target job URL."""
        pass


class BaseJobDestination(ABC):
    """Abstract interface for routing and storing ingested jobs."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier of the destination."""
        pass

    @abstractmethod
    def is_enabled(self) -> bool:
        """Check if destination is configured and enabled."""
        pass

    @abstractmethod
    def stage_job(self, job: IngestedJob) -> bool:
        """Process, save, or stage the ingested job."""
        pass


class JobSourceIntegration(ABC):
    """Abstract interface for an end-to-end job ingestion source integration."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of the integration."""
        pass

    @abstractmethod
    def run_ingestion(self, limit: int = 10, dry_run: bool = False) -> IngestionResult:
        """Execute the full ingestion workflow and return aggregated results."""
        pass


class IntegrationRegistry:
    """Central registry for managing email parsers, scrapers, destinations, and integrations."""

    def __init__(self) -> None:
        self._parsers: list[BaseEmailParser] = []
        self._scrapers: dict[str, BaseJobScraper] = {}
        self._destinations: dict[str, BaseJobDestination] = {}
        self._sources: dict[str, JobSourceIntegration] = {}

    def register_parser(self, parser: BaseEmailParser) -> None:
        self._parsers.append(parser)

    def register_scraper(self, scraper: BaseJobScraper) -> None:
        self._scrapers[scraper.name] = scraper

    def register_destination(self, destination: BaseJobDestination) -> None:
        self._destinations[destination.name] = destination

    def register_source(self, source: JobSourceIntegration) -> None:
        self._sources[source.name] = source

    def get_parser_for_message(self, message: EmailMessage) -> BaseEmailParser | None:
        for parser in self._parsers:
            if parser.can_parse(message):
                return parser
        return None

    def get_scraper(self, name: str) -> BaseJobScraper | None:
        return self._scrapers.get(name)

    def get_destination(self, name: str) -> BaseJobDestination | None:
        return self._destinations.get(name)

    def list_destinations(self) -> list[BaseJobDestination]:
        return list(self._destinations.values())


registry = IntegrationRegistry()
