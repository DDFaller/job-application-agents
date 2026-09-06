from __future__ import annotations

import unittest

from job_application_agents.orchestration.scheduler import (
    ApplicationQueueCoordinator,
    ApplicationQueueItem,
    CapacityScheduler,
    WorkflowDemand,
)


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


class ApplicationQueueCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledgers: list[tuple[str, str, int]] = []

        def ledger_path(label: str, run_id: str, attempt: int) -> str:
            self.ledgers.append((label, run_id, attempt))
            return f"/runs/{run_id}.json"

        self.queue = ApplicationQueueCoordinator(ledger_path_factory=ledger_path)

    def test_only_one_cache_miss_is_admitted_and_next_starts_after_release(self) -> None:
        first = self.queue.enqueue(ApplicationQueueItem("first", evidence_cache_hit=False))
        second = self.queue.enqueue(ApplicationQueueItem("second", evidence_cache_hit=False))
        self.assertEqual([item.label for item in first], ["first"])
        self.assertEqual(second, ())
        self.assertEqual(self.queue.state("second").kind, "queue")
        released = self.queue.complete("first", "failed")
        self.assertEqual([item.label for item in released], ["second"])
        self.assertEqual(self.queue.scheduler.available, 1)

    def test_terminal_statuses_release_capacity_once(self) -> None:
        self.queue.enqueue(ApplicationQueueItem("prepared", evidence_cache_hit=True))
        self.queue.complete("prepared", "prepared")
        self.assertEqual(self.queue.scheduler.available, 6)
        with self.assertRaisesRegex(ValueError, "not running"):
            self.queue.complete("prepared", "prepared")

    def test_invalid_terminal_status_does_not_release_active_lease(self) -> None:
        self.queue.enqueue(ApplicationQueueItem("active", evidence_cache_hit=True))
        with self.assertRaisesRegex(ValueError, "invalid terminal status"):
            self.queue.complete("active", "running")  # type: ignore[arg-type]
        self.assertEqual(self.queue.state("active").status, "running")
        self.assertEqual(self.queue.scheduler.available, 2)

    def test_finalized_ledger_retry_uses_new_run_and_preserves_artifacts(self) -> None:
        self.queue.enqueue(ApplicationQueueItem("failed", evidence_cache_hit=True))
        self.queue.complete("failed", "failed")
        retry = self.queue.retry_stage("failed", "tailoring", ledger_finalized=True)
        self.assertEqual(retry.attempt, 2)
        self.assertTrue(retry.preserve_artifacts)
        self.assertNotEqual(retry.run_id, "failed")
        self.assertEqual(retry.ledger_path, f"/runs/{retry.run_id}.json")
        self.assertEqual(self.ledgers[0][2], 2)

    def test_finalized_retry_requires_a_new_ledger_factory(self) -> None:
        queue = ApplicationQueueCoordinator()
        queue.enqueue(ApplicationQueueItem("failed", evidence_cache_hit=True))
        queue.complete("failed", "failed")
        with self.assertRaisesRegex(ValueError, "ledger_path_factory"):
            queue.retry_stage("failed", "tailoring", ledger_finalized=True)

    def test_failed_retry_without_ledger_path_does_not_advance_attempt(self) -> None:
        queue = ApplicationQueueCoordinator()
        queue.enqueue(ApplicationQueueItem("failed", evidence_cache_hit=True))
        queue.complete("failed", "failed")
        with self.assertRaisesRegex(ValueError, "current_ledger_path"):
            queue.retry_stage("failed", "tailoring", ledger_finalized=False)
        self.assertEqual(queue.state("failed").attempt, 1)

    def test_non_finalized_retry_reuses_current_ledger(self) -> None:
        queue = ApplicationQueueCoordinator()
        queue.enqueue(ApplicationQueueItem("failed", evidence_cache_hit=True))
        queue.complete("failed", "failed")
        retry = queue.retry_stage(
            "failed",
            "tailoring",
            ledger_finalized=False,
            current_run_id="run-1",
            current_ledger_path="/runs/run-1.json",
        )
        self.assertEqual(retry.run_id, "run-1")
        self.assertEqual(retry.ledger_path, "/runs/run-1.json")


if __name__ == "__main__":
    unittest.main()
