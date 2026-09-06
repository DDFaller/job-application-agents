"""Deprecated compatibility primitives for the pre-controller scheduler.

New code must use :class:`orchestration.controller.BatchController`, which
limits active jobs and launches a flat sequence of stages. These classes remain
temporarily importable from this module so existing callers can migrate; they
are deliberately no longer exported from ``job_application_agents.orchestration``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Deque, Literal
from uuid import uuid4


@dataclass(frozen=True)
class WorkflowDemand:
    """Nested worker capacity required by one workflow phase."""

    extraction: int = 1
    evidence: int = 1
    writer: int = 1
    copy_editor: int = 1
    reviewer: int = 1

    @property
    def slots(self) -> int:
        values = (self.extraction, self.evidence, self.writer, self.copy_editor, self.reviewer)
        if any(value < 0 for value in values):
            raise ValueError("workflow demand values cannot be negative")
        return sum(values)


@dataclass(frozen=True)
class WorkflowLease:
    """An acquired capacity reservation."""

    label: str
    slots: int


@dataclass(frozen=True)
class ApplicationQueueItem:
    """One complete application awaiting nested-worker admission."""

    label: str
    evidence_cache_hit: bool


@dataclass(frozen=True)
class ApplicationQueueState:
    """Observable queue state for one application."""

    label: str
    status: Literal["queued", "running", "prepared", "needs_input", "failed", "cancelled"]
    kind: Literal["queue", "active", "terminal"]
    attempt: int
    slots: int = 0
    parallel_group: str | None = None


@dataclass(frozen=True)
class StageRetry:
    """A stage-only retry directive returned by the queue coordinator."""

    label: str
    stage: str
    attempt: int
    run_id: str
    ledger_path: str
    preserve_artifacts: bool = True


TerminalStatus = Literal["prepared", "needs_input", "failed", "cancelled"]
_TERMINAL_STATUSES = frozenset({"prepared", "needs_input", "failed", "cancelled"})


class CapacityScheduler:
    """Thread-safe FIFO-friendly capacity accounting for workflow launches."""

    def __init__(self, capacity: int = 6):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._used = 0
        self._leases: dict[str, WorkflowLease] = {}
        self._lock = Lock()

    @property
    def available(self) -> int:
        with self._lock:
            return self.capacity - self._used

    @property
    def active(self) -> tuple[WorkflowLease, ...]:
        with self._lock:
            return tuple(self._leases.values())

    def try_acquire(self, label: str, demand: WorkflowDemand | int) -> WorkflowLease | None:
        """Reserve demand if it fits; return ``None`` without blocking otherwise."""
        slots = demand.slots if isinstance(demand, WorkflowDemand) else demand
        if not label:
            raise ValueError("workflow label is required")
        if slots < 1 or slots > self.capacity:
            raise ValueError("requested slots must be between 1 and scheduler capacity")
        with self._lock:
            if label in self._leases:
                raise ValueError(f"workflow already has a lease: {label}")
            if self._used + slots > self.capacity:
                return None
            lease = WorkflowLease(label=label, slots=slots)
            self._leases[label] = lease
            self._used += slots
            return lease

    def release(self, lease_or_label: WorkflowLease | str) -> None:
        """Release a reservation exactly once."""
        label = lease_or_label.label if isinstance(lease_or_label, WorkflowLease) else lease_or_label
        with self._lock:
            lease = self._leases.pop(label, None)
            if lease is None:
                raise ValueError(f"unknown workflow lease: {label}")
            self._used -= lease.slots

    def demand_for(self, *, evidence_cache_hit: bool) -> WorkflowDemand:
        """Return the safe reservation for a complete application phase.

        A cache miss reserves extraction, evidence mapping, writing, copy
        humanization, and review. A validated evidence cache hit does not
        reserve the mapper.
        """
        return WorkflowDemand(evidence=0 if evidence_cache_hit else 1)


class ApplicationQueueCoordinator:
    """Admit complete applications only when nested capacity is reserved.

    This class deliberately does not launch agents or access external systems.
    A caller submits an item, launches every item returned by ``enqueue`` or
    ``complete``, and reports terminal results back through ``complete``.
    Keeping admission separate from launching makes oversubscription
    impossible for coordinators that follow the contract.
    """

    def __init__(
        self,
        capacity: int = 6,
        max_concurrent_applications: int = 1,
        *,
        ledger_path_factory: Callable[[str, str, int], str] | None = None,
    ) -> None:
        if max_concurrent_applications < 1:
            raise ValueError("max_concurrent_applications must be positive")
        self.scheduler = CapacityScheduler(capacity)
        self.max_concurrent_applications = max_concurrent_applications
        self._ledger_path_factory = ledger_path_factory
        self._pending: Deque[ApplicationQueueItem] = deque()
        self._items: dict[str, ApplicationQueueItem] = {}
        self._states: dict[str, ApplicationQueueState] = {}
        self._leases: dict[str, WorkflowLease] = {}
        self._attempts: dict[str, int] = {}
        self._lock = Lock()

    @property
    def queued(self) -> tuple[ApplicationQueueState, ...]:
        with self._lock:
            return tuple(state for state in self._states.values() if state.status == "queued")

    @property
    def active(self) -> tuple[ApplicationQueueState, ...]:
        with self._lock:
            return tuple(state for state in self._states.values() if state.status == "running")

    def state(self, label: str) -> ApplicationQueueState:
        with self._lock:
            try:
                return self._states[label]
            except KeyError as exc:
                raise ValueError(f"unknown application: {label}") from exc

    def enqueue(self, item: ApplicationQueueItem) -> tuple[ApplicationQueueItem, ...]:
        """Queue an item and return only items safe to launch immediately."""
        if not item.label:
            raise ValueError("application label is required")
        with self._lock:
            if item.label in self._items:
                raise ValueError(f"application already queued: {item.label}")
            self._items[item.label] = item
            self._attempts[item.label] = 1
            demand = self.scheduler.demand_for(evidence_cache_hit=item.evidence_cache_hit)
            self._states[item.label] = ApplicationQueueState(
                label=item.label,
                status="queued",
                kind="queue",
                attempt=1,
                slots=demand.slots,
                parallel_group="application-queue",
            )
            self._pending.append(item)
            return self._drain_locked()

    def complete(self, label: str, status: TerminalStatus) -> tuple[ApplicationQueueItem, ...]:
        """Release a running lease and return the next items safe to launch."""
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal status: {status}")
        with self._lock:
            if label not in self._items:
                raise ValueError(f"unknown application: {label}")
            if label not in self._leases:
                raise ValueError(f"application is not running: {label}")
            lease = self._leases.pop(label)
            self.scheduler.release(lease)
            state = self._states[label]
            self._states[label] = ApplicationQueueState(
                label=label,
                status=status,
                kind="terminal",
                attempt=state.attempt,
                slots=state.slots,
                parallel_group=state.parallel_group,
            )
            return self._drain_locked()

    def retry_stage(
        self,
        label: str,
        stage: str,
        *,
        ledger_finalized: bool,
        current_run_id: str | None = None,
        current_ledger_path: str | None = None,
        new_run_id: str | None = None,
    ) -> StageRetry:
        """Return a stage-only retry with a fresh ledger when required.

        Finalized ledgers are immutable.  A caller must configure a ledger path
        factory when a finalized run needs to be resumed; the retry never
        reopens or appends to the old ledger.
        """
        if not stage:
            raise ValueError("retry stage is required")
        with self._lock:
            if label not in self._items:
                raise ValueError(f"unknown application: {label}")
            if self._states[label].status not in {"failed", "needs_input"}:
                raise ValueError("only failed or needs_input applications can be retried")
            attempt = self._attempts[label] + 1
            old_run_id = current_run_id or label
            if ledger_finalized:
                if self._ledger_path_factory is None:
                    raise ValueError("ledger_path_factory is required for finalized-ledger retries")
                run_id = new_run_id or (f"{label}-attempt-{attempt}-{uuid4().hex[:8]}")
                ledger_path = self._ledger_path_factory(label, run_id, attempt)
            else:
                run_id = old_run_id
                if current_ledger_path:
                    ledger_path = current_ledger_path
                elif self._ledger_path_factory is not None:
                    ledger_path = self._ledger_path_factory(label, old_run_id, attempt)
                else:
                    raise ValueError(
                        "current_ledger_path or ledger_path_factory is required for ledger retries"
                    )
            self._attempts[label] = attempt
            return StageRetry(label, stage, attempt, run_id, ledger_path)

    def _drain_locked(self) -> tuple[ApplicationQueueItem, ...]:
        started: list[ApplicationQueueItem] = []
        while self._pending and len(self._leases) < self.max_concurrent_applications:
            item = self._pending.popleft()
            demand = self.scheduler.demand_for(evidence_cache_hit=item.evidence_cache_hit)
            lease = self.scheduler.try_acquire(item.label, demand)
            if lease is None:
                self._pending.appendleft(item)
                break
            self._leases[item.label] = lease
            state = self._states[item.label]
            self._states[item.label] = ApplicationQueueState(
                label=item.label,
                status="running",
                kind="active",
                attempt=state.attempt,
                slots=lease.slots,
                parallel_group="application-pipeline",
            )
            started.append(item)
        return tuple(started)
