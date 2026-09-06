"""Welcome to the Jungle job portal scraper and extractor."""

from .extract import find_job_posting, job_from_page_data
from .models import DEFAULT_SEED_URLS, WttjEvaluation, WttjJob, WttjScrapeOptions
from .scraper import WttjScraper, paginated_url
from .text import clean_text, fold, strip_html

__all__ = [
    "DEFAULT_SEED_URLS",
    "WttjEvaluation",
    "WttjJob",
    "WttjScrapeOptions",
    "WttjScraper",
    "clean_text",
    "find_job_posting",
    "fold",
    "job_from_page_data",
    "paginated_url",
    "strip_html",
]
