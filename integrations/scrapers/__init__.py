"""Job scrapers package."""

from .base import BOT_BLOCK_INDICATORS, DEFAULT_HTTP_HEADERS, DEFAULT_USER_AGENT, is_bot_blocked
from .choisir_le_service_public import CspScraper
from .emploi_territorial import EmploiTerritorialScraper
from .extractor import JobPostingExtractor
from .france_travail import FranceTravailClient
from .http_scraper import HttpJobScraper
from .hybrid_scraper import HybridJobScraper
from .playwright_scraper import PlaywrightJobScraper
from .welcometothejungle import WttjScraper

__all__ = [
    "DEFAULT_USER_AGENT",
    "DEFAULT_HTTP_HEADERS",
    "BOT_BLOCK_INDICATORS",
    "is_bot_blocked",
    "HttpJobScraper",
    "PlaywrightJobScraper",
    "HybridJobScraper",
    "JobPostingExtractor",
    "WttjScraper",
    "FranceTravailClient",
    "CspScraper",
    "EmploiTerritorialScraper",
]
