import unittest

from wttj_scraper.scraper import paginated_url


class ScraperTests(unittest.TestCase):
    def test_adds_and_replaces_page_query(self):
        self.assertEqual(
            paginated_url("https://example.test/jobs?foo=bar&page=1", 3),
            "https://example.test/jobs?foo=bar&page=3",
        )


if __name__ == "__main__":
    unittest.main()

