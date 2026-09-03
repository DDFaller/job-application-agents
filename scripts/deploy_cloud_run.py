#!/usr/bin/env python3
"""Build and deploy the XeLaTeX render worker to Google Cloud Run."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

DEFAULT_REGION = "europe-west1"
DEFAULT_SERVICE_NAME = "jaa-latex-worker"


def check_gcloud() -> bool:
    return shutil.which("gcloud") is not None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("JAA_FIREBASE_PROJECT_ID"), required=not bool(os.environ.get("JAA_FIREBASE_PROJECT_ID")), help="Google Cloud project ID")
    parser.add_argument("--region", default=os.environ.get("CLOUD_RUN_REGION", DEFAULT_REGION), help="Cloud Run region")
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME, help="Cloud Run service name")
    parser.add_argument("--memory", default="2Gi", help="Memory allocation (e.g. 2Gi, 4Gi)")
    parser.add_argument("--cpu", default="2", help="vCPU allocation (e.g. 1, 2, 4)")
    parser.add_argument("--min-instances", default="1", help="Minimum instances; keep one worker polling Firestore")
    parser.add_argument("--max-instances", default="3", help="Maximum instances for auto-burst")
    parser.add_argument("--artifact-bucket", default=os.environ.get("JAA_ARTIFACT_BUCKET"), help="Shared GCS bucket for render artifacts")
    parser.add_argument(
        "--artifact-backend", choices=("firestore", "gcs"),
        default=os.environ.get("JAA_ARTIFACT_BACKEND", "firestore"),
        help="Shared artifact transport; Firestore chunks work without Cloud Run GCS egress",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print gcloud command without executing")
    parser.add_argument("--allow-unauthenticated", action="store_true", help="Allow unauthenticated access")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    print("=== Google Cloud Run Deployment Configuration ===")
    print(f"Project ID:      {args.project}")
    print(f"Region:          {args.region}")
    print(f"Service Name:    {args.service_name}")
    print(f"Memory:          {args.memory}")
    print(f"vCPU:            {args.cpu}")
    print(f"Instances:       {args.min_instances} -> {args.max_instances} (Queue worker stays warm: {args.min_instances != '0'})")
    dockerfile = repo_root / "deploy" / "docker" / "latex-worker" / "Dockerfile"
    artifact_bucket = args.artifact_bucket or f"{args.project}-render-artifacts"
    print(f"Dockerfile:      {dockerfile}")
    print(f"Artifact bucket: {artifact_bucket}")
    print(f"Artifact backend: {args.artifact_backend}")

    image = f"gcr.io/{args.project}/latex-worker"
    build_cmd = [
        "gcloud", "builds", "submit", str(repo_root),
        "--project", args.project,
        "--config", str(repo_root / "deploy" / "cloudbuild-latex.yaml"),
    ]
    deploy_cmd = [
        "gcloud", "run", "deploy", args.service_name,
        "--image", image,
        "--project", args.project,
        "--region", args.region,
        "--memory", args.memory,
        "--cpu", args.cpu,
        "--min-instances", str(args.min_instances),
        "--max-instances", str(args.max_instances),
        "--no-cpu-throttling",
        "--set-env-vars", (
            f"JAA_FIREBASE_PROJECT_ID={args.project},"
            f"JAA_ARTIFACT_BUCKET={artifact_bucket},"
            f"JAA_ARTIFACT_BACKEND={args.artifact_backend}"
        ),
        "--command", "python",
        "--args=-m,job_application_agents.render_service.server",
        "--port", "8080",
    ]
    if args.allow_unauthenticated:
        deploy_cmd.append("--allow-unauthenticated")
    else:
        deploy_cmd.append("--no-allow-unauthenticated")

    print("\n+ " + " ".join(build_cmd))
    print("+ " + " ".join(deploy_cmd))

    if args.dry_run:
        print("\nDry-run complete. (No cloud resources deployed).")
        return 0

    if not check_gcloud():
        print("\nError: 'gcloud' CLI tool is required to deploy to Cloud Run. Install Google Cloud SDK first.", file=sys.stderr)
        return 1

    build_result = subprocess.run(build_cmd, cwd=repo_root, check=False)
    if build_result.returncode != 0:
        print(f"\nImage build failed with exit code {build_result.returncode}", file=sys.stderr)
        return build_result.returncode
    result = subprocess.run(deploy_cmd, cwd=repo_root, check=False)
    if result.returncode == 0:
        print("\nDeployment succeeded! Cloud Run XeLaTeX rendering service is active.")
    else:
        print(f"\nDeployment failed with exit code {result.returncode}", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
