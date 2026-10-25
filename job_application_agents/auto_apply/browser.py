"""Browser lifecycle shared by local form inspection and application runs."""

import os
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterator

INVISIBLE_VERSION = "0.39.0"
BROWSER_BACKENDS = ("playwright", "invisible")


@contextmanager
def application_browser(*, backend: str = "playwright", headless: bool = True,
                        profile_dir: Path | None = None) -> Iterator[Any]:
    """Yield a BrowserContext, including for persistent Firefox sessions.

    A requested backend never silently falls back to another engine. Browser
    profiles contain credentials and must live under the private data root.
    """
    if backend not in BROWSER_BACKENDS:
        raise ValueError(f"Unknown browser backend: {backend}")
    if profile_dir is not None:
        profile_dir = profile_dir.expanduser().resolve()
        profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        profile_dir.chmod(0o700)
    if backend == "invisible":
        # Check before importing: this upstream package can repair dependencies
        # at import time. Installation is an explicit setup operation here.
        expected = {"invisible-playwright": INVISIBLE_VERSION, "invisible-core": "50.47.0"}
        for package, pinned in expected.items():
            try:
                installed = version(package)
            except PackageNotFoundError as exc:
                raise RuntimeError("Install .[browser-invisible], then run python -m invisible_playwright fetch") from exc
            if installed != pinned:
                raise RuntimeError(f"{package} must be {pinned}; reinstall .[browser-invisible]")
        from invisible_playwright import InvisiblePlaywright

        with InvisiblePlaywright(headless=headless, profile_dir=profile_dir,
                                 humanize=False, prep_recaptcha=False,
                                 locale="en-US", timezone="Europe/Paris") as handle:
            if profile_dir is not None:
                yield handle  # Upstream returns a context in persistent mode.
            else:
                context = handle.new_context()
                try:
                    yield context
                finally:
                    context.close()
        return

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        options = {
            "headless": headless,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        }
        chrome_bin = "/usr/bin/google-chrome" if os.path.isfile("/usr/bin/google-chrome") else None
        if not chrome_bin and os.path.isfile("/usr/bin/chromium"):
            chrome_bin = "/usr/bin/chromium"

        if profile_dir is not None:
            try:
                context = playwright.chromium.launch_persistent_context(str(profile_dir), **options)
            except Exception as exc:
                if chrome_bin and "Executable doesn't exist" in str(exc):
                    options["executable_path"] = chrome_bin
                    context = playwright.chromium.launch_persistent_context(str(profile_dir), **options)
                else:
                    raise
            try:
                yield context
            finally:
                context.close()
        else:
            try:
                browser = playwright.chromium.launch(**options)
            except Exception as exc:
                if chrome_bin and "Executable doesn't exist" in str(exc):
                    options["executable_path"] = chrome_bin
                    browser = playwright.chromium.launch(**options)
                else:
                    raise
            try:
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                yield context
            finally:
                browser.close()
