"""Job ingestion pipeline orchestrating email scanning, scraping, matching, and staging."""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any

from job_application_agents.auto_apply.matcher import JobMatchScorer

from ..base import BaseEmailClient, BaseJobDestination, BaseJobScraper, JobSourceIntegration
from ..config import IntegrationsConfig, default_config
from ..email.factory import create_email_client
from ..email.parsers.registry import EmailParserRegistry, parser_registry
from ..email.processed_ledger import ProcessedEmailLedger, normalize_message_id
from ..email.provider_filter import (
    ProviderSettingsError,
    filter_message,
    load_provider_settings,
    validate_provider_settings,
)
from ..models import (
    EmailAccountConfig,
    EmailMessage,
    IngestedJob,
    IngestionResult,
    JobAlertItem,
    NormalizedJobPosting,
    ScrapedJobContent,
)
from ..scrapers.extractor import JobPostingExtractor
from ..scrapers.hybrid_scraper import HybridJobScraper
from .destinations import FileSystemStagingDestination

logger = logging.getLogger(__name__)


class JobIngestionPipeline(JobSourceIntegration):
    """Full-lifecycle pipeline that reads job alert emails, scrapes listings, scores candidate match, and stages jobs."""

    def __init__(
        self,
        config: IntegrationsConfig | None = None,
        email_client: BaseEmailClient | None = None,
        scraper: BaseJobScraper | None = None,
        extractor: JobPostingExtractor | None = None,
        destinations: list[BaseJobDestination] | None = None,
        ledger: ProcessedEmailLedger | None = None,
        ledger_path: Path | None = None,
    ) -> None:
        self.config = config or default_config
        # This happens before constructing or connecting GmailClient. Invalid
        # hand-edited settings therefore fail without mailbox access.
        self.providers, self.matches_dict = load_provider_settings()
        self.email_config = self.config.get_email_config()
        self.email_client = email_client or create_email_client(self.email_config)
        self.scraper = scraper or HybridJobScraper()
        self.extractor = extractor or JobPostingExtractor()

        staging_dir = self.config.get_staging_directory()
        self.destinations = destinations or [FileSystemStagingDestination(staging_dir)]
        resolved_ledger_path = ledger_path or (
            self.config.get_data_root() / "integrations" / "processed_emails.json"
        )
        self.ledger = ledger or ProcessedEmailLedger(
            resolved_ledger_path, folder=self.email_config.folder
        )

    @property
    def name(self) -> str:
        return "gmail_job_alerts_pipeline"

    def run_ingestion(
        self,
        limit: int = 15,
        target_senders: list[str] | None = None,
        min_match_score: int | None = None,
        dry_run: bool = False,
        since_days: int | None = None,
        unread_only: bool = True,
        providers: list[str] | None = None,
        force_recheck: bool = False,
        recheck_message_id: str | None = None,
        recheck_uid: str | None = None,
        retry_failed: bool = False,
    ) -> IngestionResult:
        """Execute the end-to-end ingestion workflow."""
        start_time = time.time()
        result = IngestionResult()

        senders = target_senders
        min_score = min_match_score if min_match_score is not None else self.config.get_min_match_score()
        selected_providers, selected_matches = validate_provider_settings(
            providers if providers is not None else self.providers,
            self.matches_dict,
        )
        recheck_message_id = normalize_message_id(recheck_message_id)
        needs_old_messages = force_recheck or bool(recheck_message_id or recheck_uid or retry_failed)
        criteria = "ALL" if (not unread_only or needs_old_messages) else "UNSEEN"

        logger.info(
            "Starting job alert ingestion for senders: %s (limit: %d, min_score: %d)",
            senders or "mailbox-wide",
            limit,
            min_score,
        )

        # 1. Fetch email alert messages
        messages = self.email_client.fetch_messages(
            sender_filters=senders,
            criteria=criteria,
            limit=limit,
            since_days=since_days,
            # Configured senders are an optional narrowing filter. The normal
            # ingestion path must see messages whose provider appears only in
            # subject/body, so it performs a mailbox-wide candidate search.
            search_all=senders is None,
        )
        result.total_emails_scanned = len(messages)
        result.total_emails_fetched = len(messages)

        if not messages:
            logger.info("No matching job alert emails found.")
            result.duration_seconds = time.time() - start_time
            return result

        read_uids: list[str] = []

        # 2. Check identity and provider aliases before invoking any parser.
        for msg in messages:
            known_record = self.ledger.get(msg)
            explicitly_rechecked = force_recheck
            if recheck_message_id and normalize_message_id(msg.message_id) == recheck_message_id:
                explicitly_rechecked = True
            if recheck_uid is not None and str(msg.uid) == str(recheck_uid):
                explicitly_rechecked = True
            if retry_failed and self.ledger.is_failed(msg):
                explicitly_rechecked = True

            if known_record is not None and not explicitly_rechecked:
                result.total_emails_skipped_already_checked += 1
                continue
            if explicitly_rechecked:
                result.total_emails_forcibly_rechecked += 1

            filter_result = filter_message(msg, selected_providers, selected_matches)
            if not filter_result.matched:
                result.total_emails_filtered_out += 1
                if not dry_run:
                    try:
                        self.ledger.record_message(
                            msg,
                            filter_status="no_match",
                            parse_status="filtered",
                        )
                        if msg.uid:
                            read_uids.append(msg.uid)
                    except Exception as exc:
                        self._record_ledger_error(result, msg, exc)
                continue

            result.total_emails_matched += 1
            for provider in filter_result.matched_providers:
                result.filter_summary[provider] = result.filter_summary.get(provider, 0) + 1
            message_job_keys: list[str] = []
            message_errors: list[str] = []
            message_staged = False
            try:
                alert_items = parser_registry.parse_message(msg)
                result.total_emails_parsed += 1
                unique_alerts = self._deduplicate_alerts(alert_items)
                for alert in unique_alerts[:limit]:
                    job_key = alert.canonical_url or alert.raw_url or alert.job_id
                    if job_key:
                        message_job_keys.append(job_key)
                    try:
                        ingested = self._process_single_job_alert(alert, min_score, dry_run)
                        result.jobs.append(ingested)
                        result.total_jobs_scraped += 1
                        if ingested.status == "STAGED":
                            result.total_jobs_staged += 1
                            message_staged = True
                        elif ingested.status == "FAILED":
                            message_errors.append(
                                f"Staging failed for job '{alert.title}' ({alert.canonical_url})"
                            )
                        if ingested.match_score >= 80:
                            result.total_high_matches += 1
                        elif ingested.match_score >= 60:
                            result.total_medium_matches += 1
                        else:
                            result.total_low_matches += 1
                    except Exception as exc:
                        err = f"Failed processing job '{alert.title}' ({alert.canonical_url}): {exc}"
                        logger.error(err)
                        message_errors.append(err)

                result.total_jobs_found += len(alert_items)
                if message_staged:
                    result.total_emails_staged += 1
                parse_status = "staged" if message_staged else ("failed" if message_errors else "parsed")
            except Exception as exc:
                err = f"Error parsing email {msg.uid} ({msg.subject}): {exc}"
                logger.error(err)
                parse_status = "failed"
                message_errors.append(err)

            if message_errors:
                result.total_emails_failed += 1
                result.errors.extend(message_errors)
            if not dry_run:
                try:
                    self.ledger.record_message(
                        msg,
                        matched_providers=filter_result.matched_providers,
                        matched_aliases=filter_result.matched_aliases,
                        filter_status="matched",
                        parse_status=parse_status,
                        job_keys=message_job_keys,
                        error="; ".join(message_errors) if message_errors else None,
                    )
                    if msg.uid:
                        read_uids.append(msg.uid)
                except Exception as exc:
                    self._record_ledger_error(result, msg, exc)

        # 3. Mark read only after the ledger record has been durably committed.
        if not dry_run and self.email_config.mark_as_read and read_uids:
            self.email_client.mark_as_read(read_uids)

        result.duration_seconds = time.time() - start_time
        logger.info(
            "Ingestion completed in %.2fs. Found: %d, Scraped: %d, Staged: %d, High: %d, Med: %d",
            result.duration_seconds,
            result.total_jobs_found,
            result.total_jobs_scraped,
            result.total_jobs_staged,
            result.total_high_matches,
            result.total_medium_matches,
        )
        return result

    @staticmethod
    def _record_ledger_error(result: IngestionResult, msg: EmailMessage, exc: Exception) -> None:
        err = f"Failed persisting ledger record for email {msg.uid}: {exc}"
        logger.error(err)
        result.errors.append(err)
        result.total_emails_failed += 1

    def _process_single_job_alert(
        self,
        alert: JobAlertItem,
        min_score: int,
        dry_run: bool,
    ) -> IngestedJob:
        """Fetch, scrape, extract, score, and stage a single job opening."""
        target_url = alert.canonical_url or alert.raw_url

        # A. Scrape page content (Fast HTTP with Playwright fallback)
        scraped = self.scraper.scrape(target_url)

        # B. Structure content into NormalizedJobPosting and source.md
        job_posting, source_text = self.extractor.extract(scraped, alert_hint=alert)

        # C. Score match against candidate master curriculum
        match_breakdown_obj = JobMatchScorer.score_job(job_posting.to_dict())
        match_score = match_breakdown_obj.total_score
        match_rating = match_breakdown_obj.rating
        match_dict = match_breakdown_obj.to_dict()

        job_id = job_posting.source_job_id or alert.job_id or f"job-{int(time.time()*1000)}"

        ingested = IngestedJob(
            job_id=job_id,
            job_data=job_posting,
            match_score=match_score,
            match_rating=match_rating,
            match_breakdown=match_dict,
            source_email_sender=alert.email_sender,
            source_email_subject=alert.metadata.get("email_subject"),
            status="MATCHED" if match_score >= min_score else "SKIPPED",
            notes="" if match_score >= min_score else f"Score {match_score} below minimum threshold {min_score}",
        )

        # D. Stage job if score >= threshold and not dry run
        if not dry_run and match_score >= min_score:
            enabled_destinations = 0
            successful_destinations = 0
            for dest in self.destinations:
                if dest.is_enabled():
                    enabled_destinations += 1
                    if dest.stage_job(ingested):
                        successful_destinations += 1
            if enabled_destinations and successful_destinations == 0:
                ingested.status = "FAILED"
                ingested.notes = "All enabled staging destinations failed"

        return ingested

    def _deduplicate_alerts(self, alerts: list[JobAlertItem]) -> list[JobAlertItem]:
        """Deduplicate job leads by canonical URL or job ID."""
        seen_keys: set[str] = set()
        unique: list[JobAlertItem] = []

        for alert in alerts:
            key = alert.canonical_url or alert.raw_url or alert.job_id or f"{alert.company}:{alert.title}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique.append(alert)

        return unique
