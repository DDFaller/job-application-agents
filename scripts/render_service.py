#!/usr/bin/env python3
"""Manage the optional Firestore-backed XeLaTeX worker.

Local rendering is the default and does not need this command. Pass
``--cloud`` for the disposable emulator stack or ``--live`` for a configured
Firebase project.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run_tests(args: argparse.Namespace, root: Path, environment: dict[str, str], base: list[str]) -> int:
    print("=== Step 1: Running unit tests for Firebase queue ===")
    unit_env = dict(environment)
    unit_env["FIRESTORE_EMULATOR_HOST"] = ""
    res = subprocess.run(
        [sys.executable, "-m", "unittest", "job_application_agents.render_service.test_firestore.FirestoreUnitTests", "-v"],
        cwd=root, env=unit_env, check=False,
    )
    if res.returncode != 0:
        print("FAIL: Firebase unit tests failed", file=sys.stderr)
        return res.returncode

    print("\n=== Step 2: Running unit tests for LaTeX worker and render service ===")
    res = subprocess.run(
        [sys.executable, "-m", "unittest", "job_application_agents.render_service.test_render_service", "-v"],
        cwd=root, env=unit_env, check=False,
    )
    if res.returncode != 0:
        print("FAIL: LaTeX worker unit tests failed", file=sys.stderr)
        return res.returncode

    if getattr(args, "unit_only", False):
        print("\nAll unit tests passed (--unit-only).")
        return 0

    print("\n=== Step 3: Running integration test with emulator / live Firebase ===")
    started_services = False
    if not args.live:
        environment.setdefault("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
        environment.setdefault("JAA_FIREBASE_PROJECT_ID", "demo-job-application-agents")
        print("+ " + " ".join([*base, "up", "-d", "--build", "--wait"]))
        up_res = subprocess.run([*base, "up", "-d", "--build", "--wait"], cwd=root, env=environment, check=False)
        if up_res.returncode == 0:
            started_services = True
        else:
            print("Note: docker compose was not started automatically; checking existing services...")

    try:
        if not args.live and environment.get("FIRESTORE_EMULATOR_HOST"):
            print("\n--- Running Firestore repository tests against emulator ---")
            res = subprocess.run(
                [sys.executable, "-m", "unittest", "job_application_agents.render_service.test_firestore.FirestoreRepositoryTests", "-v"],
                cwd=root, env=environment, check=False,
            )
            if res.returncode != 0:
                print("FAIL: Firestore repository emulator tests failed", file=sys.stderr)
                return res.returncode

        print("\n--- Running XeLaTeX render service integration test ---")
        integration_cmd = [sys.executable, str(root / "scripts" / "check_render_service.py")]
        if not getattr(args, "no_cleanup", False):
            integration_cmd.append("--cleanup")
        res = subprocess.run(integration_cmd, cwd=root, env=environment, check=False)
        if res.returncode != 0:
            print("FAIL: XeLaTeX render service integration test failed", file=sys.stderr)
            return res.returncode

        print("\nALL AUTOMATED TESTS PASSED: Firebase unit tests -> LaTeX worker unit tests -> Integration test.")
        return 0
    finally:
        if started_services and not getattr(args, "no_cleanup", False) and not args.live:
            print("\nStopping temporary test services...")
            subprocess.run([*base, "down"], cwd=root, env=environment, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("up", "down", "status", "logs", "configure", "test", "sync"))
    parser.add_argument("--data-root", type=Path, default=Path.home() / "Documents" / "job-search")
    parser.add_argument("--cloud", action="store_true", help="opt into the Firestore worker/emulator")
    parser.add_argument("--live", action="store_true", help="opt into the live Firebase worker (implies --cloud)")
    parser.add_argument("--unit-only", action="store_true", help="run only unit tests without starting docker/integration")
    parser.add_argument("--no-cleanup", action="store_true", help="do not stop containers or delete test records after tests")
    args, extra_args = parser.parse_known_args()
    root = Path(__file__).resolve().parent.parent
    cloud = args.cloud or args.live

    if args.command == "sync":
        sync_cmd = [sys.executable, str(root / "scripts" / "sync.py"), "status", "--data-root", str(args.data_root)]
        if cloud:
            sync_cmd.append("--cloud")
        if args.live:
            sync_cmd.append("--live")
        sync_cmd.extend(extra_args)
        return subprocess.run(sync_cmd, cwd=root, check=False).returncode

    if "JAA_ARTIFACT_ROOT" in os.environ:
        artifact_root = Path(os.environ["JAA_ARTIFACT_ROOT"]).expanduser().resolve()
    else:
        artifact_root = args.data_root.expanduser().resolve() / ".render-service" / "artifacts"
    try:
        artifact_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    environment = dict(os.environ)
    environment["JAA_ARTIFACT_ROOT"] = str(artifact_root)
    if hasattr(os, "getuid"):
        environment["JAA_HOST_UID"] = str(os.getuid())
        environment["JAA_HOST_GID"] = str(os.getgid())
    if not cloud:
        parser.error(
            f"render_service {args.command!r} is optional cloud functionality; "
            "use the local renderer or pass --cloud/--live"
        )
    if not shutil.which("docker"):
        parser.error("cloud render services require Docker with Docker Compose; install it or use local rendering")

    compose_file = root / ("compose.live.yaml" if args.live else "compose.yaml")
    project = "jaa-render-live" if args.live else "jaa-render-emulator"
    base = ["docker", "compose", "-p", project, "-f", str(compose_file)]
    if args.command == "configure" and not args.live:
        parser.error("configure requires --live")
    if args.live:
        if not environment.get("JAA_FIREBASE_PROJECT_ID"):
            parser.error("--live requires JAA_FIREBASE_PROJECT_ID")
        adc = Path(environment.get(
            "JAA_ADC_PATH",
            str(Path.home() / ".config" / "gcloud" / "application_default_credentials.json"),
        )).expanduser().resolve()
        if not adc.is_file():
            parser.error("--live requires ADC; run 'gcloud auth application-default login'")
        environment["JAA_ADC_PATH"] = str(adc)
    if args.command == "test":
        return run_tests(args, root, environment, base)
    commands = {
        "up": [*base, "up", "-d", "--build"],
        "down": [*base, "down"],
        "status": [*base, "ps"],
        "logs": [*base, "logs", "--tail", "100", "latex-worker"],
        "configure": [
            "docker", "compose", "-p", "jaa-render-configure", "-f", str(root / "compose.yaml"),
            "run", "--build", "--no-deps", "--rm", "-T",
            "-v", f"{environment.get('JAA_ADC_PATH', '')}:/run/secrets/google-application-credentials.json:ro,z",
            "-e", "GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/google-application-credentials.json",
            "--entrypoint", "firebase", "firebase-emulator",
            "--config", "/firebase/firebase.json", "deploy", "--only", "firestore:indexes",
            "--project", environment.get("JAA_FIREBASE_PROJECT_ID", ""),
        ],
    }
    return subprocess.run(commands[args.command], cwd=root, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
