from pathlib import Path
import unittest


RULES = Path(__file__).with_name("firestore.rules")


class FirestoreRulesTests(unittest.TestCase):
    def test_rules_require_authenticated_tenant_ownership(self) -> None:
        rules = RULES.read_text(encoding="utf-8")
        self.assertIn("request.auth != null", rules)
        self.assertIn("request.auth.uid == userId", rules)
        self.assertNotIn("allow read, write: if true", rules)

    def test_submission_queue_is_server_only(self) -> None:
        rules = RULES.read_text(encoding="utf-8")
        start = rules.index("match /submissionJobs")
        end = rules.index("match /automationIncidents", start)
        self.assertIn("allow read, write: if false", rules[start:end])

    def test_client_cannot_promote_application_to_applied(self) -> None:
        rules = RULES.read_text(encoding="utf-8")
        start = rules.index("match /applications")
        end = rules.index("match /{document=**}", start)
        application_rules = rules[start:end]
        self.assertIn('request.resource.data.status != "APPLIED"', application_rules)
        self.assertIn("resource.data.status == \"APPLIED\"", application_rules)


if __name__ == "__main__":
    unittest.main()
