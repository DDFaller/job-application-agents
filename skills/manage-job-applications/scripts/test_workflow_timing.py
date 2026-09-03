import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("workflow_timing.py")
SPEC = importlib.util.spec_from_file_location("workflow_timing", SCRIPT)
timing = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(timing)


class TimingTests(unittest.TestCase):
    def test_event_lifecycle_and_summary_separates_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            times = iter([
                timing.datetime(2026, 1, 1, tzinfo=timing.timezone.utc),
                timing.datetime(2026, 1, 1, 0, 0, 1, tzinfo=timing.timezone.utc),
                timing.datetime(2026, 1, 1, 0, 0, 2, tzinfo=timing.timezone.utc),
                timing.datetime(2026, 1, 1, 0, 0, 5, tzinfo=timing.timezone.utc),
                timing.datetime(2026, 1, 1, 0, 0, 6, tzinfo=timing.timezone.utc),
                timing.datetime(2026, 1, 1, 0, 0, 8, tzinfo=timing.timezone.utc),
            ])
            with mock.patch.object(timing, "now", side_effect=times):
                timing.init_record(path, "run-1", "https://example.test/job")
                timing.start_event(path, "active", "s", "a", 1, "parallel", "active")
                timing.start_event(path, "wait", "s", "w", 1, None, "wait")
                timing.finish_event(path, "active", "ok", None)
                timing.finish_event(path, "wait", "blocked", "input")
                timing.finalize(path, "needs_input", None, None)
            result = timing.summary(json.loads(path.read_text()))
            self.assertEqual(result["active_ms"], 4000)
            self.assertEqual(result["wait_ms"], 4000)

    def test_overlapping_active_events_are_counted_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            times = iter([
                timing.datetime(2026, 1, 1, tzinfo=timing.timezone.utc),
                timing.datetime(2026, 1, 1, 0, 0, 1, tzinfo=timing.timezone.utc),
                timing.datetime(2026, 1, 1, 0, 0, 2, tzinfo=timing.timezone.utc),
                timing.datetime(2026, 1, 1, 0, 0, 4, tzinfo=timing.timezone.utc),
                timing.datetime(2026, 1, 1, 0, 0, 5, tzinfo=timing.timezone.utc),
                timing.datetime(2026, 1, 1, 0, 0, 6, tzinfo=timing.timezone.utc),
            ])
            with mock.patch.object(timing, "now", side_effect=times):
                timing.init_record(path, "run-2", "https://example.test/job")
                timing.start_event(path, "a", "s", "a", 1, "parallel", "active")
                timing.start_event(path, "b", "s", "b", 1, "parallel", "active")
                timing.finish_event(path, "a", "ok", None)
                timing.finish_event(path, "b", "ok", None)
                timing.finalize(path, "prepared", None, None)
            self.assertEqual(timing.summary(json.loads(path.read_text()))["active_ms"], 4000)

    def test_integrity_rejects_events_outside_finalized_run(self):
        record = {
            "run_id": "bad",
            "status": "needs_input",
            "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": "2026-01-01T00:00:01+00:00",
            "events": [{
                "event_id": "late", "started_at": "2026-01-01T00:00:02+00:00",
                "ended_at": "2026-01-01T00:00:03+00:00", "elapsed_ms": 1000,
                "kind": "active",
            }],
        }
        errors = timing.integrity_errors(record)
        self.assertIn("late: starts after run ended", errors)
        self.assertIn("late: ends after run ended", errors)
        self.assertFalse(timing.summary(record)["integrity_valid"])

    def test_cannot_start_event_after_finalize(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            times = iter([timing.datetime(2026, 1, 1, tzinfo=timing.timezone.utc),
                          timing.datetime(2026, 1, 1, 0, 0, 1, tzinfo=timing.timezone.utc)])
            with mock.patch.object(timing, "now", side_effect=times):
                timing.init_record(path, "run-3", "https://example.test/job")
                timing.finalize(path, "needs_input", None, None)
            with self.assertRaisesRegex(ValueError, "finalized"):
                timing.start_event(path, "late", "s", "stage", 1, None, "active")

    def test_finalize_closes_open_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            times = iter([timing.datetime(2026, 1, 1, tzinfo=timing.timezone.utc),
                          timing.datetime(2026, 1, 1, 0, 0, 1, tzinfo=timing.timezone.utc),
                          timing.datetime(2026, 1, 1, 0, 0, 2, tzinfo=timing.timezone.utc)])
            with mock.patch.object(timing, "now", side_effect=times):
                timing.init_record(path, "run-4", "https://example.test/job")
                timing.start_event(path, "open", "s", "stage", 1, None, "active")
                timing.finalize(path, "cancelled", None, None)
            record = json.loads(path.read_text())
            self.assertEqual(record["events"][0]["status"], "cancelled")
            self.assertTrue(timing.integrity_errors(record) == [])

    def test_status_snapshot_reports_parallel_running_work(self):
        record = {
            "run_id": "live", "status": "running", "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": None,
            "events": [
                {"event_id": "done", "skill": "extract", "stage": "setup", "attempt": 1,
                 "kind": "active", "parallel_group": None, "status": "completed",
                 "started_at": "2026-01-01T00:00:01+00:00", "ended_at": "2026-01-01T00:00:02+00:00"},
                {"event_id": "job", "skill": "extract", "stage": "job extraction", "attempt": 1,
                 "kind": "active", "parallel_group": "inputs", "status": "running",
                 "started_at": "2026-01-01T00:00:03+00:00", "ended_at": None},
                {"event_id": "candidate", "skill": "evidence", "stage": "candidate mapping", "attempt": 1,
                 "kind": "active", "parallel_group": "inputs", "status": "running",
                 "started_at": "2026-01-01T00:00:03+00:00", "ended_at": None},
            ],
        }
        with mock.patch.object(timing, "now", return_value=timing.datetime(2026, 1, 1, 0, 0, 5, tzinfo=timing.timezone.utc)):
            result = timing.status_snapshot(record)
        self.assertEqual(result["active_agents"], 2)
        self.assertEqual(result["completed_stages"], ["setup"])
        self.assertEqual({item["parallel_group"] for item in result["active_stages"]}, {"inputs"})
        self.assertFalse(result["heartbeat_due"])
        with mock.patch.object(timing, "now", return_value=timing.datetime(2026, 1, 1, 0, 0, 50, tzinfo=timing.timezone.utc)):
            self.assertTrue(timing.status_snapshot(record)["heartbeat_due"])

    def test_summary_reports_queue_remote_and_unattributed_time(self):
        record = {
            "run_id": "classified", "status": "prepared",
            "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": "2026-01-01T00:00:10+00:00",
            "events": [
                {"event_id": "q", "kind": "queue", "started_at": "2026-01-01T00:00:01+00:00",
                 "ended_at": "2026-01-01T00:00:04+00:00", "elapsed_ms": 3000},
                {"event_id": "r", "kind": "remote", "started_at": "2026-01-01T00:00:04+00:00",
                 "ended_at": "2026-01-01T00:00:06+00:00", "elapsed_ms": 2000},
                {"event_id": "a", "kind": "active", "started_at": "2026-01-01T00:00:06+00:00",
                 "ended_at": "2026-01-01T00:00:08+00:00", "elapsed_ms": 2000},
            ],
        }
        result = timing.summary(record)
        self.assertEqual(result["queue_ms"], 3000)
        self.assertEqual(result["remote_ms"], 2000)
        self.assertEqual(result["active_ms"], 2000)
        self.assertEqual(result["unattributed_ms"], 3000)

    def test_status_snapshot_includes_queued_stages(self):
        record = {
            "run_id": "queued", "status": "running",
            "started_at": "2026-01-01T00:00:00+00:00", "ended_at": None,
            "events": [{"event_id": "q", "skill": "prepare", "stage": "writer",
                         "attempt": 1, "kind": "queue", "parallel_group": "apps",
                         "status": "running", "started_at": "2026-01-01T00:00:01+00:00",
                         "ended_at": None}],
        }
        snapshot = timing.status_snapshot(record)
        self.assertEqual(snapshot["active_agents"], 0)
        self.assertEqual(snapshot["queued_stages"][0]["stage"], "writer")


if __name__ == "__main__":
    unittest.main()
