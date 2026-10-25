"""Tests for the central low-cost model policy (phase 2)."""

from __future__ import annotations

import unittest

from job_application_agents.orchestration import model_policy
from job_application_agents.orchestration.model_policy import resolve_model


class ModelPolicyTests(unittest.TestCase):
    def test_default_is_flash_tier_low_effort(self) -> None:
        model, effort = resolve_model("bundle-writing")
        self.assertEqual(model, model_policy.DEFAULT_MODEL)
        self.assertEqual(effort, "low")

    def test_explicit_arguments_win(self) -> None:
        self.assertEqual(
            resolve_model("bundle-writing", model="other", effort="high"),
            ("other", "high"),
        )

    def test_stage_override_wins_over_default(self) -> None:
        model_policy.STAGE_MODEL_OVERRIDES["probe-stage"] = ("other", "high")
        try:
            self.assertEqual(
                resolve_model("probe-stage"), ("other", "high")
            )
            # Explicit args still beat the override.
            self.assertEqual(
                resolve_model("probe-stage", model="flash"),
                ("flash", "high"),
            )
        finally:
            del model_policy.STAGE_MODEL_OVERRIDES["probe-stage"]

    def test_no_hard_coded_premium_default(self) -> None:
        self.assertNotIn("gpt", model_policy.DEFAULT_MODEL.lower())
        self.assertNotIn("claude", model_policy.DEFAULT_MODEL.lower())


if __name__ == "__main__":
    unittest.main()
