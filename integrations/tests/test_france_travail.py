"""Tests for France Travail API client and models."""

import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from integrations.scrapers.france_travail import (
    FranceTravailClient,
    FranceTravailOffer,
    france_travail_public_url,
    normalize_france_travail_offer,
)


class TestFranceTravail(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures"
        with open(self.fixtures_dir / "france-travail-offer.json", "r", encoding="utf-8") as f:
            self.raw_offer = json.load(f)

    def test_normalize_france_travail_offer(self):
        offer = normalize_france_travail_offer(self.raw_offer)

        self.assertEqual(offer.reference, "190ABCD")
        self.assertEqual(offer.title, "Agent administratif / Agente administrative")
        self.assertEqual(offer.company, "Employeur exemple")
        self.assertEqual(offer.location, "75 - PARIS")
        self.assertEqual(offer.postal_code, "75012")
        self.assertEqual(offer.contract_type, "Contrat à durée déterminée - 12 Mois")
        self.assertEqual(offer.salary, "Mensuel de 2100 Euros")
        self.assertIn("Classer des documents", offer.skills)
        self.assertEqual(offer.source_url, "https://candidat.francetravail.fr/offres/recherche/detail/190ABCD")

        # Test ScrapedJobContent conversion
        scraped = offer.to_scraped_job_content()
        self.assertTrue(scraped.is_success)
        self.assertEqual(scraped.title, "Agent administratif / Agente administrative")
        self.assertEqual(scraped.company, "Employeur exemple")
        self.assertEqual(scraped.meta_tags["source_portal"], "france-travail")

        # Test NormalizedJobPosting conversion
        norm = offer.to_normalized_job_posting()
        self.assertEqual(norm.schema_version, 2)
        self.assertEqual(norm.source, "FranceTravail")
        self.assertEqual(norm.source_job_id, "190ABCD")
        self.assertEqual(norm.role, "Agent administratif / Agente administrative")

    def test_client_credentials_check(self):
        client = FranceTravailClient(client_id="", client_secret="")
        self.assertFalse(client.has_credentials)
        with self.assertRaises(ValueError):
            client.get_access_token()

        client_with_creds = FranceTravailClient(client_id="test_id", client_secret="test_secret")
        self.assertTrue(client_with_creds.has_credentials)

    @patch("urllib.request.urlopen")
    def test_oauth_token_fetch_and_caching(self, mock_urlopen):
        # Mock OAuth token response
        token_response = MagicMock()
        token_response.read.return_value = json.dumps({
            "access_token": "mock_jwt_token_123",
            "expires_in": 1200,
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = token_response

        client = FranceTravailClient(client_id="test_id", client_secret="test_secret")
        token = client.get_access_token()
        self.assertEqual(token, "mock_jwt_token_123")

        # Second call should use cache without invoking urlopen again
        token2 = client.get_access_token()
        self.assertEqual(token2, "mock_jwt_token_123")
        self.assertEqual(mock_urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
