"""Capacity-aware scheduling primitives for nested application workflows.

The Codex launcher currently permits six nested threads. A complete application
needs multiple workers at once, so launching one parent per queue item can
leave every parent waiting for capacity. This module deliberately contains no
agent or network logic; it gives coordinators a small, testable reservation
contract they can use before delegating work.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


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
