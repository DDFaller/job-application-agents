from __future__ import annotations

import unittest

from job_application_agents.orchestration.scheduler import CapacityScheduler, WorkflowDemand


class CapacitySchedulerTests(unittest.TestCase):
    def test_full_workflow_reserves_five_slots_and_blocks_second_miss(self) -> None:
        scheduler = CapacityScheduler(6)
        first = scheduler.try_acquire("first", scheduler.demand_for(evidence_cache_hit=False))
        self.assertIsNotNone(first)
        self.assertEqual(scheduler.available, 1)
        self.assertIsNone(
            scheduler.try_acquire("second", scheduler.demand_for(evidence_cache_hit=False))
        )

    def test_cache_hit_workflow_reserves_four_slots(self) -> None:
        scheduler = CapacityScheduler(6)
        first = scheduler.try_acquire("first", scheduler.demand_for(evidence_cache_hit=True))
        self.assertIsNotNone(first)
        self.assertEqual(scheduler.available, 2)
        self.assertIsNone(
            scheduler.try_acquire("second", scheduler.demand_for(evidence_cache_hit=True))
        )

    def test_release_restores_capacity_and_is_not_silent(self) -> None:
        scheduler = CapacityScheduler(6)
        lease = scheduler.try_acquire("first", 4)
        assert lease is not None
        scheduler.release(lease)
        self.assertEqual(scheduler.available, 6)
        with self.assertRaisesRegex(ValueError, "unknown workflow lease"):
            scheduler.release("first")

    def test_invalid_demand_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            WorkflowDemand(evidence=-1).slots
        with self.assertRaisesRegex(ValueError, "between 1"):
            CapacityScheduler(6).try_acquire("bad", 7)


if __name__ == "__main__":
    unittest.main()
