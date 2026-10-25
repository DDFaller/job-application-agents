"""Port-conformance tests: adapters must satisfy the hexagonal ports."""

from __future__ import annotations

import unittest

from job_application_agents import ports
from job_application_agents.orchestration import executors


class PortConformanceTests(unittest.TestCase):
    def test_ports_module_exports_canonical_seams(self) -> None:
        for name in (
            "StageExecutor",
            "RenderJobRepository",
            "DocumentSinkPlugin",
            "BaseEmailClient",
            "BaseJobScraper",
            "BaseJobDestination",
            "JobSourceIntegration",
        ):
            self.assertTrue(hasattr(ports, name), name)

    def test_all_executors_satisfy_stage_executor(self) -> None:
        for cls in (
            executors.AgentDeckExecutor,
            executors.TmuxExecutor,
            executors.LocalProcessExecutor,
        ):
            for method in ("launch", "poll", "stop"):
                self.assertTrue(callable(getattr(cls, method, None)), f"{cls.__name__}.{method}")


if __name__ == "__main__":
    unittest.main()
