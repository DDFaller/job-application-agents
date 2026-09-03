#!/usr/bin/env python3
"""Small, append-safe timing ledger for delegated application workflows."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
STATUS_HEARTBEAT_SECONDS = 45
EVENT_KINDS = ("active", "wait", "queue", "remote")


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def integrity_errors(record: dict[str, Any]) -> list[str]:
    """Return deterministic errors for impossible or tampered timelines."""
    errors: list[str] = []
    try:
        started = parse_time(record["started_at"])
        ended = parse_time(record["ended_at"]) if record.get("ended_at") else None
    except (KeyError, TypeError, ValueError) as exc:
        return [f"invalid run timestamps: {exc}"]
    if ended and ended < started:
        errors.append("run ended before it started")
    seen: set[str] = set()
    for event in record.get("events", []):
        event_id = event.get("event_id", "<missing>")
        if event_id in seen:
            errors.append(f"duplicate event_id: {event_id}")
        seen.add(event_id)
        try:
            event_started = parse_time(event["started_at"])
            event_ended = parse_time(event["ended_at"]) if event.get("ended_at") else None
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{event_id}: invalid timestamps: {exc}")
            continue
        if ended and event_ended is None:
            errors.append(f"{event_id}: event is still running after run ended")
        if ended and event_started > ended:
            errors.append(f"{event_id}: starts after run ended")
        if event_ended and event_ended < event_started:
            errors.append(f"{event_id}: ends before it starts")
        if ended and event_ended and event_ended > ended:
            errors.append(f"{event_id}: ends after run ended")
        if event.get("elapsed_ms") is not None and event_ended:
            expected = max(0, round((event_ended - event_started).total_seconds() * 1000))
            if abs(event["elapsed_ms"] - expected) > 1:
                errors.append(f"{event_id}: elapsed_ms does not match timestamps")
    return errors


def init_record(path: Path, run_id: str, opening_url: str) -> None:
    started = now()
    atomic_write(path, {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "opening_url": opening_url,
        "status": "running",
        "started_at": iso(started),
        "ended_at": None,
        "application_root": None,
        "version_directory": None,
        "events": [],
    })


def start_event(path: Path, event_id: str, skill: str, stage: str,
                attempt: int, parallel_group: str | None, kind: str) -> None:
    record = load(path)
    if record.get("ended_at") is not None:
        raise ValueError("cannot start an event after the run is finalized")
    if any(event["event_id"] == event_id for event in record["events"]):
        raise ValueError(f"event already exists: {event_id}")
    started = now()
    record["events"].append({
        "event_id": event_id,
        "skill": skill,
        "stage": stage,
        "attempt": attempt,
        "kind": kind,
        "parallel_group": parallel_group,
        "status": "running",
        "started_at": iso(started),
        "ended_at": None,
        "elapsed_ms": None,
        "details": None,
    })
    atomic_write(path, record)


def finish_event(path: Path, event_id: str, status: str, details: str | None) -> None:
    record = load(path)
    event = next((item for item in record["events"] if item["event_id"] == event_id), None)
    if event is None:
        raise ValueError(f"unknown event: {event_id}")
    if event.get("started_at") is None:
        raise ValueError(f"event has no start timestamp: {event_id}")
    if event["ended_at"] is not None:
        raise ValueError(f"event already finished: {event_id}")
    ended = now()
    event["ended_at"] = iso(ended)
    event["elapsed_ms"] = max(0, round((ended - parse_time(event["started_at"])).total_seconds() * 1000))
    event["status"] = status
    event["details"] = details
    atomic_write(path, record)


def finalize(path: Path, status: str, application_root: str | None,
             version_directory: str | None) -> None:
    record = load(path)
    ended = now()
    for event in record.get("events", []):
        if event.get("started_at") and event.get("ended_at") is None:
            event["ended_at"] = iso(ended)
            event["elapsed_ms"] = max(0, round((ended - parse_time(event["started_at"])).total_seconds() * 1000))
            event["status"] = "cancelled"
            event["details"] = event.get("details") or "Closed automatically when the run was finalized."
    record["ended_at"] = iso(ended)
    record["status"] = status
    if application_root:
        record["application_root"] = application_root
    if version_directory:
        record["version_directory"] = version_directory
    atomic_write(path, record)


def summary(record: dict[str, Any]) -> dict[str, Any]:
    ended = parse_time(record["ended_at"]) if record.get("ended_at") else now()
    total_ms = max(0, round((ended - parse_time(record["started_at"])).total_seconds() * 1000))
    def intervals(kind: str) -> list[tuple[datetime, datetime]]:
        return [
            (parse_time(event["started_at"]), parse_time(event["ended_at"]))
            for event in record["events"]
            if event.get("kind") == kind and event.get("ended_at")
        ]

    def union_ms(values: list[tuple[datetime, datetime]]) -> int:
        values.sort()
        merged: list[list[datetime]] = []
        for start, finish in values:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], finish)
            else:
                merged.append([start, finish])
        return sum(round((finish - start).total_seconds() * 1000) for start, finish in merged)

    active_ms = union_ms(intervals("active"))
    wait_ms = union_ms(intervals("wait"))
    queue_ms = union_ms(intervals("queue"))
    remote_ms = union_ms(intervals("remote"))
    classified_ms = union_ms([
        interval for kind in EVENT_KINDS for interval in intervals(kind)
    ])
    unattributed_ms = max(0, total_ms - classified_ms)
    errors = integrity_errors(record)
    return {"run_id": record["run_id"], "status": record.get("status"),
            "elapsed_ms": total_ms, "active_ms": active_ms, "wait_ms": wait_ms,
            "queue_ms": queue_ms, "remote_ms": remote_ms,
            "unattributed_ms": unattributed_ms,
            "integrity_valid": not errors, "integrity_errors": errors,
            "events": record["events"]}


def status_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    current = now()
    ended = parse_time(record["ended_at"]) if record.get("ended_at") else current
    elapsed_ms = max(0, round((ended - parse_time(record["started_at"])).total_seconds() * 1000))
    events = record.get("events", [])
    active = [
        {
            "event_id": event["event_id"], "skill": event["skill"], "stage": event["stage"],
            "attempt": event["attempt"], "parallel_group": event.get("parallel_group"),
        }
        for event in events if event.get("ended_at") is None and event.get("kind") == "active"
    ]
    queued = [
        {
            "event_id": event["event_id"], "skill": event["skill"], "stage": event["stage"],
            "attempt": event["attempt"], "parallel_group": event.get("parallel_group"),
        }
        for event in events if event.get("ended_at") is None and event.get("kind") == "queue"
    ]
    completed = [event["stage"] for event in events if event.get("ended_at") and event.get("status") == "completed"]
    latest = max(events, key=lambda event: event.get("ended_at") or event["started_at"], default=None)
    latest_time = parse_time(latest.get("ended_at") or latest["started_at"]) if latest else parse_time(record["started_at"])
    seconds_since_transition = max(0, round((current - latest_time).total_seconds()))
    return {
        "run_id": record["run_id"], "status": record.get("status"), "elapsed_ms": elapsed_ms,
        "active_agents": len(active), "active_stages": active, "queued_stages": queued,
        "completed_stages": completed,
        "latest_transition": latest, "seconds_since_transition": seconds_since_transition,
        "heartbeat_due": record.get("ended_at") is None and seconds_since_transition >= STATUS_HEARTBEAT_SECONDS,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    init_parser = sub.add_parser("init")
    init_parser.add_argument("--file", type=Path, required=True)
    init_parser.add_argument("--run-id", default=lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8])
    init_parser.add_argument("--opening-url", required=True)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--file", type=Path, required=True)
    start_parser.add_argument("--event-id", required=True)
    start_parser.add_argument("--skill", required=True)
    start_parser.add_argument("--stage", required=True)
    start_parser.add_argument("--attempt", type=int, default=1)
    start_parser.add_argument("--parallel-group")
    start_parser.add_argument("--kind", choices=EVENT_KINDS, default="active")
    finish_parser = sub.add_parser("finish")
    finish_parser.add_argument("--file", type=Path, required=True)
    finish_parser.add_argument("--event-id", required=True)
    finish_parser.add_argument("--status", required=True)
    finish_parser.add_argument("--details")
    end_parser = sub.add_parser("finalize")
    end_parser.add_argument("--file", type=Path, required=True)
    end_parser.add_argument("--status", required=True)
    end_parser.add_argument("--application-root")
    end_parser.add_argument("--version-directory")
    report_parser = sub.add_parser("report")
    report_parser.add_argument("--file", type=Path, required=True)
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--file", type=Path, required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--file", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "init":
        run_id = args.run_id() if callable(args.run_id) else args.run_id
        init_record(args.file, run_id, args.opening_url)
    elif args.command == "start":
        start_event(args.file, args.event_id, args.skill, args.stage, args.attempt, args.parallel_group, args.kind)
    elif args.command == "finish":
        finish_event(args.file, args.event_id, args.status, args.details)
    elif args.command == "finalize":
        finalize(args.file, args.status, args.application_root, args.version_directory)
    elif args.command == "report":
        print(json.dumps(summary(load(args.file)), indent=2, ensure_ascii=False))
    elif args.command == "status":
        print(json.dumps(status_snapshot(load(args.file)), indent=2, ensure_ascii=False))
    else:
        errors = integrity_errors(load(args.file))
        for error in errors:
            print(f"invalid timing ledger: {error}")
        return 1 if errors else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
