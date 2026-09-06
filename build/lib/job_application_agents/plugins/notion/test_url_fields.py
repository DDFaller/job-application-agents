from __future__ import annotations

import unittest
from unittest.mock import patch

from .client import NotionClient
from .models import NotionCardPayload


class TestNotionURLFields(unittest.TestCase):
    def test_card_properties_store_both_urls(self) -> None:
        client = NotionClient(token="test-token")
        payload = NotionCardPayload(
            application_title="Pelico - Software Engineer",
            company="Pelico",
            role="Software Engineer",
            job_url="https://jobs.ashbyhq.com/Pelico/job/application?src=LinkedIn",
            source_url="https://www.linkedin.com/jobs/view/4460010933/?trackingId=x",
            application_url="https://jobs.ashbyhq.com/Pelico/job/application?src=LinkedIn",
        )
        with patch.object(client, "_request", return_value={}) as request:
            client.create_card("db-1", payload)
        properties = request.call_args.kwargs["data"]["properties"]
        self.assertEqual(properties["Job URL"]["url"], payload.application_url)
        self.assertEqual(properties["Application URL"]["url"], payload.application_url)
        self.assertEqual(properties["Source URL"]["url"], payload.source_url)

    def test_identity_lookup_matches_old_linkedin_card_by_source_id(self) -> None:
        client = NotionClient(token="test-token")
        page = {
            "id": "page-1",
            "properties": {
                "Job URL": {"type": "url", "url": "https://www.linkedin.com/jobs/view/4460010933"},
                "Source Job ID": {"type": "rich_text", "rich_text": [{"plain_text": "4460010933"}]},
                "Company": {"type": "rich_text", "rich_text": [{"plain_text": "Pelico"}]},
                "Role": {"type": "rich_text", "rich_text": [{"plain_text": "Software Engineer"}]},
            },
        }
        with patch.object(client, "warm_database", return_value=[page]):
            result = client.find_card_by_identity(
                "db-1",
                job_url="https://jobs.ashbyhq.com/Pelico/job/application?src=LinkedIn",
                source_url="https://www.linkedin.com/jobs/view/4460010933/?trackingId=x",
                source_job_id="4460010933",
                company="Pelico",
                role="Software Engineer",
            )
        self.assertEqual(result, page)

    def test_identity_lookup_matches_existing_application_url(self) -> None:
        client = NotionClient(token="test-token")
        page = {
            "id": "page-2",
            "properties": {
                "Application URL": {
                    "type": "url",
                    "url": "https://jobs.ashbyhq.com/Pelico/job/application?src=LinkedIn",
                }
            },
        }
        with patch.object(client, "warm_database", return_value=[page]):
            result = client.find_card_by_identity(
                "db-1",
                job_url="https://jobs.ashbyhq.com/Pelico/job/application?src=LinkedIn",
            )
        self.assertEqual(result, page)


if __name__ == "__main__":
    unittest.main()
