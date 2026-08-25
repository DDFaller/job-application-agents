from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from .extract import job_from_page_data
from .matching import evaluate_job
from .models import job_result


DEFAULT_SEED_URLS = (
    "https://www.welcometothejungle.com/fr/pages/emploi-assistant-administratif",
    "https://www.welcometothejungle.com/fr/pages/emploi-assistant-administratif-paris-75000",
    "https://www.welcometothejungle.com/fr/pages/emploi-ile-de-france",
)


@dataclass(slots=True)
class ScrapeOptions:
    pages: int = 2
    max_jobs: int = 60
    delay_seconds: float = 1.5
    timeout_ms: int = 30_000
    headed: bool = False
    minimum_score: int | None = None
    seed_urls: list[str] = field(default_factory=lambda: list(DEFAULT_SEED_URLS))


def paginated_url(url: str, page_number: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


async def _dismiss_cookie_banner(page: Page) -> None:
    for label in ("Tout accepter", "Accepter", "Continuer sans accepter", "Refuser"):
        button = page.get_by_role("button", name=label, exact=True)
        try:
            if await button.is_visible():
                await button.click(timeout=2_000)
                return
        except PlaywrightTimeoutError:
            continue


async def _job_links(page: Page) -> list[str]:
    locator = page.locator("a[href*='/fr/companies/'][href*='/jobs/']")
    try:
        await locator.first.wait_for(state="attached", timeout=10_000)
    except PlaywrightTimeoutError:
        return []
    hrefs = await locator.evaluate_all("els => els.map(el => el.href)")
    return sorted(
        {
            href.split("?")[0]
            for href in hrefs
            if isinstance(href, str)
            and href.startswith("https://www.welcometothejungle.com/fr/companies/")
            and "/jobs/" in href
        }
    )


async def discover_urls(context: BrowserContext, options: ScrapeOptions) -> tuple[list[str], list[str]]:
    page = await context.new_page()
    discovered: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    try:
        for seed in options.seed_urls:
            for page_number in range(1, options.pages + 1):
                url = paginated_url(seed, page_number)
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=options.timeout_ms)
                    if response and response.status >= 400:
                        errors.append(f"Descoberta HTTP {response.status}: {url}")
                        continue
                    await _dismiss_cookie_banner(page)
                    links = await _job_links(page)
                    for link in links:
                        if link not in seen:
                            seen.add(link)
                            discovered.append(link)
                    if not links:
                        break
                except PlaywrightTimeoutError:
                    errors.append(f"Timeout na descoberta: {url}")
                await asyncio.sleep(options.delay_seconds)
    finally:
        await page.close()
    return discovered[: options.max_jobs], errors


async def scrape_compatible_jobs(profile: dict[str, Any], options: ScrapeOptions) -> dict[str, Any]:
    started = datetime.now(UTC)
    compatible: list[dict[str, Any]] = []
    errors: list[str] = []
    processed = 0
    rejected = 0
    discovered_count = 0

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not options.headed)
        context = await browser.new_context(
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1440, "height": 1100},
        )
        await context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "media", "font"}
            else route.continue_(),
        )
        try:
            urls, discovery_errors = await discover_urls(context, options)
            discovered_count = len(urls)
            errors.extend(discovery_errors)
            page = await context.new_page()
            try:
                for index, url in enumerate(urls, start=1):
                    try:
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=options.timeout_ms)
                        if response and response.status in {202, 204}:
                            await asyncio.sleep(max(options.delay_seconds, 1.0))
                            response = await page.reload(wait_until="domcontentloaded", timeout=options.timeout_ms)
                        if response and (response.status >= 400 or response.status in {202, 204}):
                            errors.append(f"Vaga HTTP {response.status} sem conteúdo utilizável: {url}")
                            continue
                        await _dismiss_cookie_banner(page)
                        scripts = await page.locator("script[type='application/ld+json']").all_text_contents()
                        body_text = await page.locator("body").inner_text(timeout=options.timeout_ms)
                        if len(body_text.strip()) < 200:
                            errors.append(f"Página de vaga sem conteúdo utilizável: {url}")
                            continue
                        headings = await page.locator("h1, h2").all_text_contents()
                        html_title = await page.title()
                        title_hint = next(
                            (value for value in headings if value.strip()),
                            html_title.split(" - ", 1)[0].strip(),
                        )
                        job = job_from_page_data(url, scripts, body_text, title_hint)
                        if not job.title:
                            errors.append(f"Título da vaga não pôde ser extraído: {url}")
                            continue
                        evaluation = evaluate_job(job, profile, options.minimum_score)
                        processed += 1
                        if evaluation.compatible:
                            compatible.append(job_result(job, evaluation))
                        else:
                            rejected += 1
                        print(
                            f"[{index}/{len(urls)}] {evaluation.score:>3} "
                            f"{'OK' if evaluation.compatible else 'rejeitada'} — {job.title or url}"
                        )
                        if not evaluation.compatible:
                            diagnostic = evaluation.hard_rejections or evaluation.gaps
                            if diagnostic:
                                print(f"       motivo: {diagnostic[0]}")
                    except PlaywrightTimeoutError:
                        errors.append(f"Timeout ao extrair vaga: {url}")
                    except Exception as exc:  # Mantém as outras vagas processáveis.
                        errors.append(f"Falha ao extrair {url}: {type(exc).__name__}: {exc}")
                    await asyncio.sleep(options.delay_seconds)
            finally:
                await page.close()
        finally:
            await context.close()
            await browser.close()

    compatible.sort(key=lambda item: (-item["compatibility_score"], item["title"].lower()))
    cutoff = int(options.minimum_score if options.minimum_score is not None else profile["minimum_score"])
    return {
        "schema_version": 1,
        "source": "welcome-to-the-jungle",
        "profile_version": profile["profile_version"],
        "minimum_score": cutoff,
        "generated_at": datetime.now(UTC).isoformat(),
        "duration_seconds": round((datetime.now(UTC) - started).total_seconds(), 2),
        "discovered_count": discovered_count,
        "processed_count": processed,
        "compatible_count": len(compatible),
        "rejected_count": rejected,
        "extraction_failed_count": max(0, discovered_count - processed),
        "errors": errors,
        "jobs": compatible,
    }


def write_result(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_path)
