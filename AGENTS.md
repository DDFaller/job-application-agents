# Repository Guidelines

## Project Structure & Module Organization

Core Python packages live in `job_application_agents/`, grouped by capability such as `auto_apply/`, `render_service/`, `sync/`, and `plugins/notion/`. Provider ingestion code and its tests are under `integrations/`. Firebase entrypoints are in `functions/`; deployment files, Docker images, Firestore rules, and indexes are in `deploy/`. Reusable agent workflows live in `skills/`, while developer and operational commands live in `scripts/`. Tests are generally colocated with their subsystem and named `test_*.py`.

## Build, Test, and Development Commands

- `python3 scripts/setup.py` creates the virtual environment and configures local services.
- `python3 scripts/setup.py --check` performs a read-only environment diagnosis.
- `python3 scripts/check.py` validates plugin metadata and runs the repository's unit tests.
- `.venv/bin/python scripts/render_service.py test` runs unit tests plus the Firebase emulator and XeLaTeX integration checks.
- `.venv/bin/python scripts/render_service.py up` starts the isolated local render stack.
- `python -m pip install -e .` installs the Python packages in editable mode.

Use the demo Firebase project for development. Live commands require explicit credentials and `--live`.

## Coding Style & Naming Conventions

Target Python 3.11 or newer. Use four-space indentation, type hints for public interfaces, `snake_case` for modules and functions, `PascalCase` for classes, and uppercase names for constants. Keep modules focused and use `pathlib.Path` for filesystem work. No repository-wide formatter or linter is configured, so follow nearby code and keep diffs focused.

## Testing Guidelines

Tests use the standard-library `unittest` framework. Add or update a `test_*.py` file alongside behavioral changes and cover success, validation, and failure paths. There is no fixed coverage threshold; `python3 scripts/check.py` must pass before review. Use the Firestore emulator for normal tests. Reserve the protected live smoke workflow for deliberate integration validation.

## Commit & Pull Request Guidelines

Write concise, imperative commit subjects. Existing history commonly uses prefixes such as `feat:`, `docs:`, `ci:`, and `style:`. Pull requests should explain the motivation and behavior change, identify affected subsystems, link relevant issues, and include commands run with their results. Add screenshots for PWA changes and call out migrations, live-service effects, or follow-up work.

## Security & Configuration

Never commit `.env` files, Firebase credentials, Notion tokens, private candidate data, or generated application records. Keep personal data under the configured external data root and verify that tests do not contact production services.
