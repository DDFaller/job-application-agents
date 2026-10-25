#!/usr/bin/env python3
"""CLI utility to pre-fetch and extract a token-optimized form structure from a job application URL."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_application_agents.auto_apply.browser import BROWSER_BACKENDS, application_browser
from job_application_agents.auto_apply.portal import PortalGuard
from job_application_agents.auto_apply.preprocessor import FormDOMPreprocessor
from job_application_agents.config import resolve_data_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract token-compressed form fields from any job URL.")
    parser.add_argument("url", help="Job posting or application form URL")
    parser.add_argument("--output", "-o", type=Path, help="Optional output JSON file path")
    parser.add_argument("--timeout", type=int, default=30000, help="Page timeout in ms (default: 30000)")
    parser.add_argument("--browser", choices=BROWSER_BACKENDS, default="playwright")
    parser.add_argument("--browser-profile", type=Path, help="Private persistent profile directory")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--wait-for-login", action="store_true", help="Allow manual sign-in in the visible browser before inspection")

    args = parser.parse_args()

    root = resolve_data_root(args.data_root)
    if args.browser_profile and not args.browser_profile.expanduser().resolve().is_relative_to(root):
        parser.error("browser profile must be inside the private data root")
    guard = PortalGuard(root)
    guard.exclusions.require_allowed(args.url)
    with application_browser(backend=args.browser, headless=not (args.headed or args.wait_for_login),
                             profile_dir=args.browser_profile) as context:
        guard.install(context)
        page = context.new_page()
        page.set_default_timeout(args.timeout)

        print("[1/2] Fetching page and opening form...")
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        guard.check(page)
        if args.wait_for_login:
            print("Sign in in the browser, then press ENTER here. Do not paste credentials.")
            input()
            guard.check(page)

        # Click apply button if present
        apply_selectors = [
            'button:has-text("Apply for this job")',
            'a:has-text("Apply for this job")',
            'button:has-text("Apply Now")',
            'a:has-text("Apply Now")',
            'a[href*="/apply"]',
        ]
        for sel in apply_selectors:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                try:
                    href = loc.get_attribute("href")
                    if href:
                        from urllib.parse import urljoin
                        guard.exclusions.require_allowed(urljoin(page.url, href))
                    loc.click()
                    page.wait_for_timeout(2000)
                    guard.check(page)
                    break
                except PermissionError:
                    raise
                except Exception:
                    pass

        print("[2/2] Running DOM Preprocessor & Token Compression...")
        tree = FormDOMPreprocessor.extract_from_page(page)

    result_json = tree.to_json(indent=2)
    stats = tree.to_dict()["stats"]

    print("\n--- Form Extraction Summary ---")
    print(f"Form Title:            {tree.title}")
    print(f"Interactive Fields:    {len(tree.fields)}")
    print(f"Raw HTML Est Tokens:   ~{stats['raw_token_estimate']:,} tokens")
    print(f"Compressed Est Tokens: ~{stats['compressed_token_estimate']:,} tokens")
    print(f"Token Reduction:       📉 {stats['compression_ratio_pct']}% saved!\n")

    if args.output:
        args.output.write_text(result_json, encoding="utf-8")
        print(f"Saved compressed schema to: {args.output}")
    else:
        print(result_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
