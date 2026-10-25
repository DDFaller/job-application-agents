"""Central low-cost model policy for worker stages.

Cost rule: heavy agent stages default to the harness's flash-tier Gemini
model at low effort. Stronger models only via explicit per-stage override,
CLI flag, or environment variable. Nothing in the pipeline may hard-code a
different model default.
"""

from __future__ import annotations

import os

DEFAULT_MODEL_ENV_VAR = "JAA_DEFAULT_MODEL"
DEFAULT_EFFORT_ENV_VAR = "JAA_DEFAULT_EFFORT"

# Matches the repo skill convention (`model: flash` in skills/*/agents front
# matter; "low-cost models (Gemini 3.8 Flash)" in automate-job-application).
DEFAULT_MODEL = os.environ.get(DEFAULT_MODEL_ENV_VAR, "flash")
DEFAULT_EFFORT = os.environ.get(DEFAULT_EFFORT_ENV_VAR, "low")
AGY_FLASH_MODEL = "gemini-3.8-flash"

# Stage -> (model, effort) overrides. Empty means "policy default".
# Add entries here — never a hard-coded model string at a call site — when a
# stage proves it needs more than flash/low. Values may still be overridden
# by JAA_DEFAULT_MODEL / explicit CLI flags.
STAGE_MODEL_OVERRIDES: dict[str, tuple[str, str]] = {}


def resolve_model(
    stage: str,
    model: str | None = None,
    effort: str | None = None,
) -> tuple[str, str]:
    """Return the (model, effort) pair for a stage.

    Precedence: explicit arguments > per-stage override > policy default.
    """
    override = STAGE_MODEL_OVERRIDES.get(stage, (DEFAULT_MODEL, DEFAULT_EFFORT))
    return (model or override[0], effort or override[1])
