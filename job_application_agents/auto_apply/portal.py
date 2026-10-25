"""Stop local application runs at excluded sites or visible verification walls."""

from pathlib import Path
from typing import Any

from .interaction import SiteExclusions, form_input


class PortalGuard:
    def __init__(self, data_root: Path):
        self.exclusions = SiteExclusions(data_root)
        self.blocked_request: str | None = None

    def install(self, context: Any) -> None:
        def route_request(route: Any) -> None:
            url = route.request.url
            if url.startswith(("https://", "http://")) and self.exclusions.match(url):
                self.blocked_request = url
                route.abort()
            else:
                route.continue_()
        context.route("**/*", route_request)

    def attach(self, page: Any) -> None:
        form_input(page).before_input = lambda: self.check(page)

    def check(self, page: Any) -> None:
        if self.blocked_request:
            self.exclusions.require_allowed(self.blocked_request)
        self.exclusions.require_allowed(page.url)
        # Deliberately exclude broad [class*=captcha] matches: privacy footers
        # and hidden templates are not interactive verification challenges.
        challenge = page.locator(
            'iframe[src*="recaptcha"][title*="challenge" i], '
            'iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare.com"], '
            '.g-recaptcha, .h-captcha, .cf-turnstile'
        )
        if any(item.is_visible() for item in challenge.all()):
            self.exclusions.record(page.url, reason="captcha",
                                   evidence="Visible interactive verification widget")
            raise PermissionError("Verification challenge: website excluded from future applications")
        text = page.locator("body").inner_text(timeout=2000).lower()
        if any(message in text for message in (
            "performing security verification", "automated access has been blocked",
            "unusual traffic from your computer network", "verify you are human",
        )):
            self.exclusions.record(page.url, reason="automation_block",
                                   evidence="Visible human-verification or automated-access rejection")
            raise PermissionError("Automation rejection: website excluded from future applications")
