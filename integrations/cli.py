"""Command-line interface for the job integrations subsystem."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any

from .config import IntegrationsConfig, default_config
from .email.factory import create_email_client
from .email.gmail_api_client import GmailApiClient, GmailApiConfigurationError
from .email.processed_ledger import ProcessedEmailLedger
from .email.parsers.base import HTMLTextExtractor
from .email.parsers.registry import parser_registry
from .email.provider_filter import load_provider_settings
from .models import EmailMessage
from .pipeline.orchestrator import JobIngestionPipeline
from .scrapers.extractor import JobPostingExtractor
from .scrapers.hybrid_scraper import HybridJobScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("integrations.cli")


def cmd_test_connection(args: argparse.Namespace) -> int:
    """Test the configured Gmail API or IMAP connection."""
    cfg = IntegrationsConfig(args.config)
    email_cfg = cfg.get_email_config()

    if args.user:
        email_cfg.email_address = args.user
    if args.password and email_cfg.auth_mode not in {"gmail_api", "oauth2"}:
        email_cfg.app_password = args.password

    try:
        client = create_email_client(email_cfg)
    except ValueError as exc:
        print(f"❌ CONNECTION FAILED: {exc}", file=sys.stderr)
        return 1
    print("\n🔍 Testing Gmail Connection...")
    print(f"• Auth mode: {email_cfg.auth_mode}")
    print(f"• User: {email_cfg.email_address or '(not set)'}")
    if email_cfg.auth_mode not in {"gmail_api", "oauth2"}:
        print(f"• Server: {email_cfg.imap_server}:{email_cfg.imap_port}")
    print(f"• Target Senders: {', '.join(email_cfg.target_senders)}")
    print("-" * 50)

    res = client.test_connection()
    status = res.get("status")

    if status == "READY":
        print("✅ SUCCESS: Connected and authenticated with Gmail.")
        if res.get("transport") == "gmail_api":
            print(f"• Sample messages visible: {res.get('message_count_sample')}")
        else:
            print(f"• Total messages in folder '{res.get('folder')}': {res.get('total_messages')}")
            print(f"• Alert messages found from target senders: {res.get('sample_target_sender_messages')}")
        return 0
    else:
        print(f"❌ CONNECTION FAILED: {status}")
        print(f"• Message: {res.get('message')}")
        print("\n💡 Tip: To configure Gmail access:")
        if email_cfg.auth_mode in {"gmail_api", "oauth2"}:
            print("  1. Download a Desktop OAuth client JSON from Google Cloud Console.")
            print("  2. Set GMAIL_CLIENT_SECRETS_PATH to that file.")
            print("  3. Run: python3 scripts/ingest_jobs.py authorize-gmail\n")
        else:
            print("  1. Enable 2-Step Verification on your Google Account.")
            print("  2. Generate an App Password at https://myaccount.google.com/apppasswords")
            print("  3. Set environment variables:")
            print("     export GMAIL_USER='your-email@gmail.com'")
            print("     export GMAIL_APP_PASSWORD='your-16-char-app-password'")
            print("  Or run: python3 scripts/ingest_jobs.py configure\n")
        return 1


def cmd_authorize_gmail(args: argparse.Namespace) -> int:
    """Authorize the configured Gmail API desktop client in a browser."""
    cfg = IntegrationsConfig(args.config)
    email_cfg = cfg.get_email_config()
    email_cfg.auth_mode = "gmail_api"
    if args.client_secrets:
        email_cfg.client_secrets_path = str(args.client_secrets.expanduser().resolve())
    client = GmailApiClient(email_cfg)
    try:
        email_address = client.authorize()
    except GmailApiConfigurationError as exc:
        print(f"❌ Gmail OAuth setup failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"❌ Gmail OAuth authorization failed: {exc}", file=sys.stderr)
        return 1
    finally:
        client.disconnect()
    print(f"✅ Gmail OAuth authorized for {email_address or email_cfg.email_address}")
    print(f"• Read-only token: {client.token_path}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Run the job alert ingestion pipeline."""
    cfg = IntegrationsConfig(args.config)
    pipeline = JobIngestionPipeline(config=cfg)

    senders = [s.strip() for s in args.sender.split(",")] if args.sender else None
    providers = [p.strip() for p in args.providers.split(",") if p.strip()] if args.providers else None
    min_score = args.min_score if args.min_score is not None else cfg.get_min_match_score()

    print("\n🚀 Starting Job Ingestion Pipeline...")
    print(f"• Target Senders: {senders or 'mailbox-wide (provider filter)'}")
    print(f"• Max items to process: {args.limit}")
    print(f"• Minimum Match Score: {min_score}")
    print(f"• Dry run: {args.dry_run}")
    print(f"• Unread only: {not args.all}")
    print(f"• Providers: {providers or pipeline.providers}")
    print(f"• Recheck mode: {'yes' if (args.force_recheck or args.recheck_message_id or args.recheck_uid or args.retry_failed) else 'no'}")
    print("-" * 60)

    result = pipeline.run_ingestion(
        limit=args.limit,
        target_senders=senders,
        min_match_score=min_score,
        dry_run=args.dry_run,
        since_days=args.since_days,
        unread_only=not args.all,
        providers=providers,
        force_recheck=args.force_recheck,
        recheck_message_id=args.recheck_message_id,
        recheck_uid=args.recheck_uid,
        retry_failed=args.retry_failed,
    )

    print("\n" + "=" * 60)
    print("📊 INGESTION SUMMARY REPORT")
    print("=" * 60)
    print(f"• Emails Scanned:     {result.total_emails_scanned}")
    print(f"• Fetched:            {result.total_emails_fetched}")
    print(f"• Already checked:    {result.total_emails_skipped_already_checked}")
    print(f"• Filtered out:       {result.total_emails_filtered_out}")
    print(f"• Provider matches:   {result.total_emails_matched}")
    print(f"• Parsed emails:      {result.total_emails_parsed}")
    print(f"• Staged emails:      {result.total_emails_staged}")
    print(f"• Failed emails:      {result.total_emails_failed}")
    print(f"• Forced rechecks:    {result.total_emails_forcibly_rechecked}")
    print(f"• Job Leads Discovered: {result.total_jobs_found}")
    print(f"• Job Postings Scraped: {result.total_jobs_scraped}")
    print(f"• Jobs Staged:        {result.total_jobs_staged}")
    print(f"• High Matches (≥80):  {result.total_high_matches}")
    print(f"• Medium Matches (60-79): {result.total_medium_matches}")
    print(f"• Low Matches (<60):   {result.total_low_matches}")
    print(f"• Duration:           {result.duration_seconds:.2f}s")
    if args.show_filter_summary:
        print(f"• Provider filter summary: {json.dumps(result.filter_summary, sort_keys=True)}")

    if result.jobs:
        print("\n📋 INGESTED JOBS:")
        for idx, job in enumerate(result.jobs, 1):
            badge = "🟢" if job.match_score >= 80 else ("🟡" if job.match_score >= 60 else "⚪")
            staged_str = f" ➔ Staged at: {job.staging_dir}" if job.staging_dir else f" (Status: {job.status})"
            print(f"  {idx}. {badge} [{job.match_score}/100] {job.job_data.role} @ {job.job_data.company}{staged_str}")

    if result.errors:
        print("\n⚠️ WARNINGS / ERRORS:")
        for err in result.errors:
            print(f"  • {err}")

    print("\n" + "=" * 60 + "\n")
    return 0


def cmd_validate_settings(args: argparse.Namespace) -> int:
    """Validate provider settings without connecting to Gmail."""
    try:
        providers, matches = load_provider_settings()
    except Exception as exc:
        print(f"❌ Invalid auto-ingest settings: {exc}", file=sys.stderr)
        return 1
    print("✅ Auto-ingest settings are valid.")
    print(f"• Enabled providers: {', '.join(providers) or '(none)'}")
    for provider in providers:
        print(f"• {provider} aliases: {', '.join(matches[provider])}")
    return 0


def cmd_show_processed(args: argparse.Namespace) -> int:
    """Display ledger statistics and metadata without email content."""
    cfg = IntegrationsConfig(args.config)
    email_cfg = cfg.get_email_config()
    ledger = ProcessedEmailLedger(
        cfg.get_data_root() / "integrations" / "processed_emails.json",
        folder=email_cfg.folder,
    )
    print(json.dumps(ledger.summary(), indent=2))
    recent = sorted(ledger.records(), key=lambda r: r.get("checked_at", ""), reverse=True)[: args.limit]
    print("Recent entries:")
    for record in recent:
        print(json.dumps({
            "identity": record.get("identity", {}),
            "checked_at": record.get("checked_at"),
            "matched_providers": record.get("matched_providers", []),
            "filter_status": record.get("filter_status"),
            "parse_status": record.get("parse_status"),
            "job_keys": record.get("job_keys", []),
            "has_error": bool(record.get("error")),
        }, ensure_ascii=False))
    return 0


def cmd_scrape(args: argparse.Namespace) -> int:
    """Test scraping a single job URL with hybrid HTTP + Playwright fallback."""
    print(f"\n🌐 Scraping Job URL: {args.url}")
    scraper = HybridJobScraper(enable_playwright_fallback=not args.no_playwright)
    extractor = JobPostingExtractor()

    scraped = scraper.scrape(args.url)
    print(f"• Status: {scraped.status_code}")
    print(f"• Playwright Used: {'YES (Fallback activated)' if scraped.used_playwright else 'NO (Fast HTTP succeeded)'}")
    print(f"• Fetch Time: {scraped.fetch_duration_seconds}s")
    print(f"• Extracted Text Length: {len(scraped.visible_text)} characters")

    if scraped.error_message:
        print(f"• Scrape Notice/Error: {scraped.error_message}")

    out_dir = Path(args.out_dir) if args.out_dir else None
    posting, source_text = extractor.extract(scraped, output_dir=out_dir)

    print("\n📄 Extracted Job Metadata:")
    print(f"• Company:       {posting.company}")
    print(f"• Role:          {posting.role}")
    print(f"• Location:      {posting.location}")
    print(f"• Work Model:    {posting.work_model}")
    print(f"• Seniority:     {posting.seniority}")
    print(f"• Technologies:  {', '.join(posting.technologies)}")
    print(f"• Responsibilities Count: {len(posting.responsibilities)}")
    print(f"• Requirements Count:     {len(posting.requirements)}")

    # Score match
    from job_application_agents.auto_apply.matcher import JobMatchScorer
    match_res = JobMatchScorer.score_job(posting.to_dict())
    print(f"\n🎯 Candidate Match Score: {match_res.total_score}/100 ({match_res.rating})")
    print(f"• Skills Score:     {match_res.skills_score}/30 (Matched: {', '.join(match_res.matched_skills[:5])})")
    print(f"• Experience Score: {match_res.experience_score}/25")
    print(f"• Role Score:       {match_res.role_score}/20")
    print(f"• Location Score:   {match_res.location_score}/15")

    if args.json:
        print("\n" + json.dumps(posting.to_dict(), indent=2))

    return 0 if scraped.is_success else 1


def cmd_parse_email(args: argparse.Namespace) -> int:
    """Parse a saved email file (.eml, .html, or .txt)."""
    path = Path(args.file)
    if not path.is_file():
        print(f"❌ File not found: {path}", file=sys.stderr)
        return 1

    content = path.read_text(encoding="utf-8", errors="replace")
    sender = args.sender or "jobalerts-noreply@linkedin.com"

    fake_msg = EmailMessage(
        uid="file-1",
        message_id="file-msg-1",
        sender=sender,
        recipient="user@example.com",
        subject=args.subject or path.stem,
        date_str="2026-08-26",
        body_html=content if "<html" in content or "<div" in content or "<table" in content else "",
        body_plain=content if "<html" not in content else "",
    )

    items = parser_registry.parse_message(fake_msg)
    print(f"\n📬 Parsed {len(items)} job alert leads from {path.name} (Sender: {sender}):")
    print("-" * 60)
    for idx, item in enumerate(items, 1):
        print(f"{idx}. {item.title} @ {item.company} ({item.location or 'Location unspecified'})")
        print(f"   URL: {item.canonical_url or item.raw_url}")
        if item.salary_text:
            print(f"   Salary: {item.salary_text}")
    print("-" * 60 + "\n")
    return 0


def cmd_configure(args: argparse.Namespace) -> int:
    """Save connection configuration interactively or from arguments."""
    cfg = IntegrationsConfig()
    email_cfg = cfg.get_email_config()

    user = args.user or input(f"Gmail Address [{email_cfg.email_address}]: ").strip() or email_cfg.email_address
    password = args.password or input("Gmail 16-character App Password: ").strip()

    if not user or not password:
        print("❌ Both email and app password are required.")
        return 1

    file_path = Path("integrations.config.json")
    data = {
        "email": {
            "email_address": user,
            "app_password": password,
            "imap_server": email_cfg.imap_server,
            "imap_port": email_cfg.imap_port,
            "target_senders": email_cfg.target_senders,
            "search_criteria": "UNSEEN",
            "max_messages": 25,
            "mark_as_read": False,
        },
        "min_match_score": cfg.get_min_match_score(),
        "staging_dir": str(cfg.get_staging_directory()),
    }
    file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"✅ Configuration saved securely to {file_path.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="integrations",
        description="Job Ingestion & Email Alerts Integration CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Ingest
    ingest_p = subparsers.add_parser("ingest", help="Run email job alert ingestion pipeline")
    ingest_p.add_argument("--sender", help="Comma-separated sender filter (e.g. jobalerts-noreply@linkedin.com)")
    ingest_p.add_argument("--limit", type=int, default=15, help="Max jobs to process (default: 15)")
    ingest_p.add_argument("--min-score", type=int, help="Minimum match score threshold (default: 60)")
    ingest_p.add_argument("--dry-run", action="store_true", help="Scan and score without writing staging files")
    ingest_p.add_argument("--all", action="store_true", help="Include already-read emails (not only UNSEEN)")
    ingest_p.add_argument("--since-days", type=int, help="Only look at emails within the last N days")
    ingest_p.add_argument("--providers", help="Comma-separated enabled providers (e.g. LINKEDIN,INDEED)")
    ingest_p.add_argument("--force-recheck", action="store_true", help="Reprocess all fetched messages, including checked ones")
    ingest_p.add_argument("--recheck-message-id", help="Reprocess one message by Message-ID")
    ingest_p.add_argument("--recheck-uid", help="Reprocess one message by IMAP UID")
    ingest_p.add_argument("--retry-failed", action="store_true", help="Retry messages with a failed ledger record")
    ingest_p.add_argument("--show-filter-summary", action="store_true", help="Print provider filtering counters")
    ingest_p.add_argument("--config", type=Path, help="Path to custom config JSON")

    # Test connection
    test_p = subparsers.add_parser("test-connection", help="Test connection to Gmail API or IMAP")
    test_p.add_argument("--user", help="Gmail address override")
    test_p.add_argument("--password", help="Gmail app password override")
    test_p.add_argument("--config", type=Path, help="Path to custom config JSON")

    # Gmail API OAuth
    auth_p = subparsers.add_parser(
        "authorize-gmail", help="Authorize the Gmail API desktop OAuth client"
    )
    auth_p.add_argument(
        "--client-secrets", type=Path,
        help="Downloaded Google Desktop OAuth client JSON",
    )
    auth_p.add_argument("--config", type=Path, help="Path to custom config JSON")

    # Scrape URL
    scrape_p = subparsers.add_parser("scrape", help="Test scraping a single job opening URL")
    scrape_p.add_argument("url", help="Job posting URL to scrape")
    scrape_p.add_argument("--no-playwright", action="store_true", help="Disable Playwright fallback")
    scrape_p.add_argument("--out-dir", type=Path, help="Directory to write source.md and job.json")
    scrape_p.add_argument("--json", action="store_true", help="Print full normalized JSON")

    # Parse local email
    parse_p = subparsers.add_parser("parse-email", help="Parse a local .eml or .html email file")
    parse_p.add_argument("file", help="Path to email HTML or raw file")
    parse_p.add_argument("--sender", default="jobalerts-noreply@linkedin.com", help="Simulated sender email")
    parse_p.add_argument("--subject", help="Simulated email subject")

    # Configure
    cfg_p = subparsers.add_parser("configure", help="Save Gmail configuration")
    cfg_p.add_argument("--user", help="Gmail address")
    cfg_p.add_argument("--password", help="Gmail app password")

    subparsers.add_parser(
        "validate-settings", help="Validate provider aliases without Gmail access"
    )
    processed_p = subparsers.add_parser(
        "show-processed", help="Show processed-email ledger metadata"
    )
    processed_p.add_argument("--limit", type=int, default=10, help="Number of recent entries to show")
    processed_p.add_argument("--config", type=Path, help="Path to custom config JSON")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "ingest":
        return cmd_ingest(args)
    elif args.command == "test-connection":
        return cmd_test_connection(args)
    elif args.command == "authorize-gmail":
        return cmd_authorize_gmail(args)
    elif args.command == "scrape":
        return cmd_scrape(args)
    elif args.command == "parse-email":
        return cmd_parse_email(args)
    elif args.command == "configure":
        return cmd_configure(args)
    elif args.command == "validate-settings":
        return cmd_validate_settings(args)
    elif args.command == "show-processed":
        return cmd_show_processed(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
