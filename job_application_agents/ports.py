"""Hexagonal boundary map: canonical ports and their adapters.

Domain code must depend on these ports, never directly on SDK clients.
Each service's tests pin conformance so phases 3-6 can extend the seams
without breaking adapters.
"""

from __future__ import annotations

from job_application_agents.orchestration.contracts import StageTask, WorkerProfile
from job_application_agents.orchestration.executors import (
    ExecutionHandle,
    ExecutionObservation,
    StageExecutor,
)
from job_application_agents.plugins.base import DocumentSinkPlugin
from job_application_agents.render_service.repository import RenderJobRepository

from integrations.base import (
    BaseEmailClient,
    BaseJobDestination,
    BaseJobScraper,
    JobSourceIntegration,
)

__all__ = [
    "StageExecutor",
    "RenderJobRepository",
    "DocumentSinkPlugin",
    "BaseEmailClient",
    "BaseJobScraper",
    "BaseJobDestination",
    "JobSourceIntegration",
    "ExecutionHandle",
    "ExecutionObservation",
    "StageTask",
    "WorkerProfile",
]
