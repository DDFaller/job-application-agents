"""Official France Travail (Offres d'emploi v2) API client & HTML parser."""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import os
import re
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from ...base import BaseJobScraper
from ...models import ScrapedJobContent
from ..hybrid_scraper import HybridJobScraper
from .models import FranceTravailOffer, FranceTravailSearchParams, france_travail_public_url


FRANCE_TRAVAIL_TOKEN_URL = (
    "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
)
FRANCE_TRAVAIL_API_BASE_URL = (
    "https://api.francetravail.io/partenaire/offresdemploi/v2"
)
FRANCE_TRAVAIL_SCOPE = "api_offresdemploiv2 o2dsoffre"


def normalize_france_travail_offer(offer: dict[str, Any]) -> FranceTravailOffer:
    """Transform raw France Travail JSON offer into FranceTravailOffer model."""
    ref = str(offer.get("id") or "").strip()
    title = str(offer.get("intitule") or "").strip()
    desc = str(offer.get("description") or "").strip()

    entreprise = offer.get("entreprise") or {}
    company = str(entreprise.get("nom") or "").strip() if isinstance(entreprise, dict) else ""

    lieu = offer.get("lieuTravail") or {}
    location = str(lieu.get("libelle") or "").strip() if isinstance(lieu, dict) else ""
    postal_code = str(lieu.get("codePostal") or "").strip() if isinstance(lieu, dict) else ""

    contract = str(offer.get("typeContratLibelle") or offer.get("typeContrat") or "").strip()
    exp = str(offer.get("experienceLibelle") or offer.get("experienceCommentaire") or "").strip()

    salaire = offer.get("salaire") or {}
    salary = str(salaire.get("libelle") or "").strip() if isinstance(salaire, dict) else ""

    # Compétences
    skills = [
        str(comp.get("libelle") or "").strip()
        for comp in (offer.get("competences") or [])
        if isinstance(comp, dict) and comp.get("libelle")
    ]

    # Savoir-être professionnels / Qualités professionnelles
    qualities = [
        str(q.get("libelle") or "").strip()
        for q in (offer.get("qualitesProfessionnelles") or [])
        if isinstance(q, dict) and q.get("libelle")
    ]

    origine = offer.get("origineOffre") or {}
    application_url = str(origine.get("urlOrigine") or "").strip() if isinstance(origine, dict) else ""

    return FranceTravailOffer(
        reference=ref,
        title=title,
        company=company,
        description=desc,
        location=location,
        postal_code=postal_code,
        contract_type=contract,
        experience_level=exp,
        salary=salary,
        skills=skills,
        professional_qualities=qualities,
        date_posted=str(offer.get("dateCreation") or ""),
        date_modified=str(offer.get("dateActualisation") or ""),
        application_url=application_url,
        source_url=france_travail_public_url(ref),
        raw_payload=offer,
    )


def extract_france_travail_from_html(html_text: str, source_url: str = "") -> FranceTravailOffer:
    """Parse France Travail HTML page into FranceTravailOffer with experience, competences, and savoir-être."""
    title_m = re.search(r'itemprop=[\'"]title[\'"][^>]*>(.*?)</span>', html_text, re.I | re.S)
    title = html.unescape(re.sub(r'<[^>]+>', ' ', title_m.group(1)).strip()) if title_m else ""

    ref_m = re.search(r'itemprop=[\'"]value[\'"][^>]*>(.*?)</span>', html_text, re.I | re.S)
    ref = ref_m.group(1).strip() if ref_m else ""
    if not ref and source_url:
        match = re.search(r"/detail/([A-Za-z0-9]+)", source_url)
        if match:
            ref = match.group(1)

    loc_m = re.search(r'class=[\'"]location[\'"][^>]*>(.*?)</span>', html_text, re.I | re.S)
    location = loc_m.group(1).strip() if loc_m else ""

    company = ""
    company_m = re.search(r'itemprop=[\'"]hiringOrganization[\'"].*?itemprop=[\'"]name[\'"][^>]*content=[\'"]([^\'"]+)[\'"]', html_text, re.I | re.S)
    if not company_m:
        company_m = re.search(r'itemprop=[\'"]hiringOrganization[\'"].*?content=[\'"]([^\'"]+)[\'"][^>]*itemprop=[\'"]name[\'"]', html_text, re.I | re.S)
    if company_m and company_m.group(1).strip():
        company = company_m.group(1).strip()
    if not company:
        # Fallback to heading under Employeur section
        emp_m = re.search(r'<h[34][^>]*class=[\'"]t[46] title[\'"][^>]*>(.*?)</h[34]>', html_text, re.I | re.S)
        if emp_m:
            company = re.sub(r'<[^>]+>', '', emp_m.group(1)).strip()
    if not company:
        emp_m2 = re.search(r'<h[34][^>]*class=[\'"]t6 subtitle[\'"][^>]*>(.*?)</h[34]>', html_text, re.I | re.S)
        if emp_m2:
            company = re.sub(r'<[^>]+>', '', emp_m2.group(1)).strip()
    if not company:
        chez_m = re.search(r'Chez\s+([A-Za-z0-9\s]+?),\s*à', html_text)
        if chez_m:
            company = chez_m.group(1).strip()

    date_m = re.search(r'(?:itemprop=[\'"]datePosted[\'"][^>]*content=[\'"]([^\'"]+)[\'"]|content=[\'"]([^\'"]+)[\'"][^>]*itemprop=[\'"]datePosted[\'"])', html_text, re.I)
    date_posted = ((date_m.group(1) or date_m.group(2)).strip()) if date_m else ""

    # Contract Type
    contract = ""
    contract_m = re.search(r'Type de contrat\s*</h3>\s*<ul[^>]*>\s*<li>\s*<span[^>]*>(.*?)</span>', html_text, re.I | re.S)
    if contract_m:
        contract = re.sub(r'<[^>]+>', '', contract_m.group(1)).strip()
    elif "CDI" in html_text:
        contract = "CDI"
    elif "CDD" in html_text:
        contract = "CDD"

    # Expérience
    exp_m = re.search(r'itemprop=[\'"]experienceRequirements[\'"][^>]*>(.*?)</span>', html_text, re.I | re.S)
    if not exp_m:
        exp_m = re.search(r'Expérience\s*(?:</h3>|</h2>|</span>|</div>)?\s*<[^>]+>\s*([^<\n]+?(?:An\(s\)|an|ans|mois|d[ée]butant)[^<\n]*)', html_text, re.I | re.S)
    if not exp_m:
        exp_m = re.search(r'Expérience\s*[:\n]\s*([^\n\r<]+?(?:An\(s\)|an|ans|mois|d[ée]butant)[^\n\r<]*)', html_text, re.I)
    if not exp_m:
        exp_m = re.search(r'(?:Expérience\s*(?:exigée|souhaitée|requise)?\s*(?:de)?\s*(?:\d+|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix)\s*(?:An\(s\)|an|ans|mois)|Débutant accepté(?:\s*\(\d+\))?)', html_text, re.I)

    if exp_m:
        raw_val = exp_m.group(1) if exp_m.lastindex else exp_m.group(0)
        experience = html.unescape(re.sub(r'<[^>]+>', '', raw_val).strip())
    else:
        experience = ""

    # Compétences
    competences_raw = re.findall(r'itemprop=[\'"]skills[\'"][^>]*>(.*?)</span>', html_text, re.I | re.S)
    competences = [
        html.unescape(re.sub(r'<[^>]+>', '', c).strip())
        for c in competences_raw
        if c.strip()
    ]

    # Savoir-être professionnels
    savoir_raw = re.findall(r'class=[\'"]skill skill-savoir[\'"][^>]*><span class=[\'"]skill-name[\'"]>(.*?)</span>', html_text, re.I | re.S)
    savoir_etre = [
        html.unescape(re.sub(r'<[^>]+>', '', s).strip())
        for s in savoir_raw
        if s.strip()
    ]

    # Description
    desc_m = re.search(r'itemprop=[\'"]description[\'"][^>]*>(.*?)</div>\s*</div>', html_text, re.I | re.S)
    raw_desc = desc_m.group(1) if desc_m else html_text
    desc = html.unescape(re.sub(r'<br\s*/?>', '\n', raw_desc))
    desc = re.sub(r'<[^>]+>', ' ', desc)
    desc = re.sub(r'[ \t]+', ' ', desc).strip()

    return FranceTravailOffer(
        reference=ref,
        title=title,
        company=company,
        contract_type=contract,
        description=desc,
        location=location,
        experience_level=experience,
        skills=competences,
        professional_qualities=savoir_etre,
        date_posted=date_posted,
        source_url=france_travail_public_url(ref) if ref else source_url,
    )


class FranceTravailClient(BaseJobScraper):
    """Client for France Travail API with token caching, search, and detail fetching."""

    @property
    def name(self) -> str:
        return "france-travail"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout_seconds: int = 25,
    ) -> None:
        self.client_id = client_id or os.getenv("FRANCE_TRAVAIL_CLIENT_ID", "").strip()
        self.client_secret = client_secret or os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET", "").strip()
        self.timeout_seconds = timeout_seconds
        self._token_cache: dict[str, Any] | None = None
        self._hybrid_scraper = HybridJobScraper()

    @property
    def has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def get_access_token(self, force_refresh: bool = False) -> str:
        """Authenticate with client_credentials flow, caching token."""
        if not self.has_credentials:
            raise ValueError(
                "France Travail credentials missing. Set FRANCE_TRAVAIL_CLIENT_ID "
                "and FRANCE_TRAVAIL_CLIENT_SECRET."
            )

        now = time.time()
        if (
            not force_refresh
            and self._token_cache
            and self._token_cache.get("client_id") == self.client_id
            and self._token_cache.get("expires_at", 0) > now + 60
        ):
            return str(self._token_cache["access_token"])

        params = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": FRANCE_TRAVAIL_SCOPE,
        }).encode("utf-8")

        req = urllib.request.Request(
            FRANCE_TRAVAIL_TOKEN_URL,
            data=params,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"France Travail authentication failed ({exc.code}): {err_body}") from exc

        token = data.get("access_token")
        if not token:
            raise RuntimeError("France Travail authentication response missing access_token")

        expires_in = int(data.get("expires_in", 1200))
        self._token_cache = {
            "client_id": self.client_id,
            "access_token": token,
            "expires_at": now + expires_in,
        }
        return str(token)

    def api_request(self, endpoint: str, query_params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send an authenticated request to France Travail API."""
        token = self.get_access_token()
        url = f"{FRANCE_TRAVAIL_API_BASE_URL}/{endpoint.lstrip('/')}"
        if query_params:
            filtered = {k: str(v) for k, v in query_params.items() if v is not None and v != ""}
            if filtered:
                url = f"{url}?{urllib.parse.urlencode(filtered)}"

        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:  # Token expired; retry once with refresh
                token = self.get_access_token(force_refresh=True)
                req.headers["Authorization"] = f"Bearer {token}"
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"France Travail API error ({exc.code}): {err_body}") from exc

    def search_offers(
        self,
        keywords: str = "",
        departments: list[str] | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[FranceTravailOffer]:
        """Search job offers via France Travail API."""
        start = (page - 1) * page_size
        end = start + page_size - 1
        query: dict[str, Any] = {
            "range": f"{start}-{end}",
        }
        if keywords:
            query["motsCles"] = keywords
        if departments:
            query["departement"] = ",".join(departments[:5])  # API limit 5 departments

        try:
            result = self.api_request("offres/search", query)
            raw_offers = result.get("resultats") or []
            return [normalize_france_travail_offer(raw) for raw in raw_offers]
        except urllib.error.HTTPError as exc:
            if exc.code == 204:  # No content found
                return []
            raise

    def fetch_offer(self, reference: str) -> FranceTravailOffer:
        """Fetch full details for a single job reference via API."""
        clean_ref = reference.strip()
        data = self.api_request(f"offres/{urllib.parse.quote(clean_ref)}")
        return normalize_france_travail_offer(data)

    def scrape(self, url: str, timeout_seconds: int = 25) -> ScrapedJobContent:
        """Fetch and convert a France Travail job posting to ScrapedJobContent via API or HTML."""
        match = re.search(r"/detail/([A-Za-z0-9]+)", url)
        ref = match.group(1) if match else ""

        # If API credentials exist, use official API
        if self.has_credentials and ref:
            try:
                offer = self.fetch_offer(ref)
                return offer.to_scraped_job_content()
            except Exception:
                pass  # Fall back to HTML scraping

        # Otherwise scrape HTML DOM
        scraped = self._hybrid_scraper.scrape(url, timeout_seconds=timeout_seconds)
        if scraped.raw_html:
            offer = extract_france_travail_from_html(scraped.raw_html, source_url=url)
            if offer.title:
                return offer.to_scraped_job_content()

        return scraped
