from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any

from google.cloud import firestore

from .draft_models import ApplicationDraft, ApplicationState, ApprovalToken, AutomationIncident, VerificationScore
from .draft_service import DraftService
from .firestore import FirestoreDraftRepository
from .verifier import SubmissionVerifier
from ..plugins.notion.firestore import FirestoreNotionJobRepository
from ..plugins.notion.models import NotionCardPayload, NotionSyncJob

import atexit
import signal

logger = logging.getLogger("playwright-worker")

SUBMISSION_CONFIRMATION = "I_UNDERSTAND_SUBMISSION"


class PlaywrightSubmissionWorker:
    """Worker daemon that leases submission jobs from Firestore and executes hash-locked browser submissions."""

    def __init__(
        self,
        project_id: str | None = None,
        worker_id: str | None = None,
        poll_interval: float = 3.0,
    ):
        self.project_id = (
            project_id
            or os.environ.get("JAA_FIREBASE_PROJECT_ID")
            or os.environ.get("GCLOUD_PROJECT")
        )
        if not self.project_id:
            raise ValueError("JAA_FIREBASE_PROJECT_ID or --project-id is required")
        self.worker_id = worker_id or f"pw-worker-{os.getpid()}"
        self.poll_interval = poll_interval
        self.draft_repo = FirestoreDraftRepository(project_id=self.project_id)
        self.notion_repo = FirestoreNotionJobRepository(project_id=self.project_id)
        self.client = self.draft_repo.client
        self._active_browser = None
        self._setup_signals()

    def _setup_signals(self) -> None:
        """Register OS signal traps to cleanly kill Chromium on exit."""
        def _terminate(signum, frame):
            logger.info(f"Received signal {signum}, cleaning up active browser...")
            self._cleanup_browser()
            sys.exit(0)

        signal.signal(signal.SIGINT, _terminate)
        signal.signal(signal.SIGTERM, _terminate)
        atexit.register(self._cleanup_browser)

    def _cleanup_browser(self) -> None:
        if self._active_browser:
            try:
                self._active_browser.close()
            except Exception:
                pass
            self._active_browser = None

    def enqueue_notion_sync(
        self,
        user_id: str,
        application_id: str,
        revision: int,
        status: str | None = None,
        comment: str | None = None,
    ) -> str:
        """Use the shared idempotent Notion queue for application changes."""
        payload: dict[str, Any] = {"application_id": application_id, "current_version": f"v{revision:03d}"}
        if status:
            payload["status"] = status
        if comment:
            payload["comment"] = comment
        job = self.notion_repo.enqueue(
            user_id=user_id,
            application_id=application_id,
            action="CREATE_OR_UPDATE",
            payload=payload,
            idempotency_key=f"application:{user_id}:{application_id}:v{revision:03d}",
        )
        return job.id

    def claim_next_job(self) -> dict[str, Any] | None:
        """Claim next queued submission job using transactional lease (reclaiming stale leases if any)."""
        jobs_ref = self.client.collection("submissionJobs")
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(minutes=5)

        # First check QUEUED jobs, prioritized by match_score descending
        query = jobs_ref.where("state", "==", "QUEUED").limit(10)
        queued_docs = list(query.stream())
        if queued_docs:
            queued_docs.sort(key=lambda d: d.to_dict().get("match_score") or 0, reverse=True)
            docs = [queued_docs[0]]
        else:
            docs = []


        # If no new jobs, check for expired running leases (stale worker recovery)
        if not docs:
            running_query = jobs_ref.where("state", "==", "RUNNING").limit(5)
            for d in running_query.stream():
                d_data = d.to_dict()
                exp_str = d_data.get("lease_expires_at")
                if exp_str:
                    try:
                        exp_dt = datetime.fromisoformat(exp_str)
                        if exp_dt < now:
                            logger.warning(f"Reclaiming stale expired lease on job {d.id}")
                            docs = [d]
                            break
                    except Exception:
                        pass

        if not docs:
            return None

        job_doc = docs[0]

        @firestore.transactional
        def _claim(transaction, doc_ref):
            snap = doc_ref.get(transaction=transaction)
            if not snap.exists:
                return None
            state = snap.get("state")
            if state != "QUEUED" and state != "RUNNING":
                return None
            transaction.update(
                doc_ref,
                {
                    "state": "RUNNING",
                    "worker_id": self.worker_id,
                    "claimed_at": now.isoformat(),
                    "lease_expires_at": lease_expires.isoformat(),
                },
            )
            return snap.to_dict()

        transaction = self.client.transaction()

        try:
            claimed = _claim(transaction, job_doc.reference)
            return claimed
        except Exception as e:
            logger.warning(f"Failed to claim job {job_doc.id}: {e}")
            return None

    def process_job(self, job_data: dict[str, Any]) -> bool:
        """Execute the browser automation and verify submission."""
        if os.environ.get("JAA_ENABLE_SUBMISSION") != SUBMISSION_CONFIRMATION:
            logger.error(
                "Submission worker is locked. Set JAA_ENABLE_SUBMISSION=%s only "
                "in an explicitly opted-in deployment.",
                SUBMISSION_CONFIRMATION,
            )
            return False
        user_id = job_data["user_id"]
        app_id = job_data["application_id"]
        revision = job_data["revision"]
        expected_hash = job_data["draft_hash"]

        logger.info(f"Processing submission for {app_id} (Rev {revision}, User: {user_id})")

        # 1. Fetch Draft from Firestore
        draft = self.draft_repo.get_draft(user_id=user_id, application_id=app_id, revision=revision)
        if not draft:
            logger.error(f"Draft not found: {app_id} Rev {revision}")
            return False

        # 2. Verify Cryptographic Hash Match
        if draft.draft_hash != expected_hash:
            logger.error(f"Hash mismatch for {app_id}! Live: {draft.draft_hash} vs Expected: {expected_hash}")
            return False

        version_dir = Path(draft.resume_path).parent if draft.resume_path and Path(draft.resume_path).parent.is_dir() else (Path("data/submissions") / app_id / f"v{revision:03d}")
        version_dir.mkdir(parents=True, exist_ok=True)

        # 3. Launch Playwright Session (Headed or Headless based on environment/host display)
        from playwright.sync_api import sync_playwright


        headless_env = os.environ.get("PLAYWRIGHT_HEADLESS", "").lower()
        if headless_env in ("true", "1", "yes"):
            headless = True
        elif headless_env in ("false", "0", "no"):
            headless = False
        else:
            # Default to headed (visible browser) if a display is present on the host
            headless = not bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

        slow_mo = int(os.environ.get("PLAYWRIGHT_SLOWMO", "600")) if not headless else 0

        # Approval-token authorization does not authorize bypassing portal
        # access controls or bot checks.
        launch_args = ["--no-sandbox"]
        if not headless:
            launch_args.extend([
                "--window-position=820,50",
                "--window-size=980,950",
            ])

        from .agent_solver import AgentFormSolver

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                slow_mo=slow_mo,
                args=launch_args,
            )

            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            )
            page = context.new_page()

            try:
                page.goto(draft.target_url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                # Capture pre-submit screenshot
                pre_submit_path = version_dir / "pre-submit.png"
                try:
                    page.screenshot(path=str(pre_submit_path), full_page=True)
                except Exception:
                    pass

                # Run Agentic Multi-Step Form Solver
                confirmed, score, blocker_type, blocker_detail = AgentFormSolver.solve_multistep_application(page, draft)
                logger.info(f"Agentic solver outcome: confirmed={confirmed}, blocker={blocker_type} ({blocker_detail}), score={score.total_score} ({score.verdict.value})")

                if blocker_type == "AUTH_REQUIRED":
                    post_name = "login-wall.png"
                    post_path = version_dir / post_name
                    try:
                        page.screenshot(path=str(post_path), full_page=True)
                    except Exception:
                        pass

                    incident_id = f"inc_{app_id}_{int(datetime.now().timestamp())}"
                    incident = AutomationIncident(
                        incident_id=incident_id,
                        application_id=app_id,
                        company=draft.company,
                        job_title=draft.job_title,
                        category="AUTH_WALL",
                        severity="WARNING",
                        diagnostic_summary="Platform requires candidate account login or registration on employer portal.",
                        portal_url=page.url,
                        step_reached=1,
                        proof_screenshot=str(post_path),
                        error_detail=blocker_detail,
                    )
                    self.draft_repo.save_incident(incident)

                    target_status = "HUMAN_REVIEW"
                    comment_text = (
                        f"⚠️ **Human Review Required (Authentication Wall)**\n\n"
                        f"• **Barrier**: Platform requires candidate account login or registration on the employer portal.\n"
                        f"• **Portal URL**: {page.url}\n\n"
                        f"📋 **Next Steps for Candidate**:\n"
                        f"1. Open the portal link above in your browser.\n"
                        f"2. Sign in or create an account.\n"
                        f"3. Upload the tailored resume.pdf from this card and confirm submission."
                    )

                    app_ref = self.client.collection("users").document(user_id).collection("applications").document(app_id)
                    app_ref.set(
                        {
                            "state": "HUMAN_REVIEW",
                            "status": target_status,
                            "review_reason": "AUTH_REQUIRED",
                            "review_details": blocker_detail,
                            "incident_id": incident_id,
                            "target_portal_url": page.url,
                            "proof_screenshot": str(post_path),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        merge=True,
                    )

                    try:
                        notion_job_id = self.enqueue_notion_sync(user_id, app_id, revision, target_status, comment_text)
                        logger.info(f"Enqueued Notion sync job {notion_job_id} to move {app_id} to HUMAN_REVIEW.")
                    except Exception as ne:
                        logger.warning(f"Could not enqueue Notion sync: {ne}")

                    if not headless:
                        logger.info("Authentication wall reached. Keeping browser open for 5 seconds for visual inspection...")
                        page.wait_for_timeout(5000)

                    return True

                elif blocker_type == "CAPTCHA_DETECTED":
                    post_name = "captcha-challenge.png"
                    post_path = version_dir / post_name
                    try:
                        page.screenshot(path=str(post_path), full_page=True)
                    except Exception:
                        pass

                    incident_id = f"inc_{app_id}_{int(datetime.now().timestamp())}"
                    incident = AutomationIncident(
                        incident_id=incident_id,
                        application_id=app_id,
                        company=draft.company,
                        job_title=draft.job_title,
                        category="CAPTCHA",
                        severity="WARNING",
                        diagnostic_summary="Interactive CAPTCHA or Cloudflare Turnstile challenge detected on portal.",
                        portal_url=page.url,
                        step_reached=1,
                        proof_screenshot=str(post_path),
                        error_detail=blocker_detail,
                    )
                    self.draft_repo.save_incident(incident)

                    target_status = "HUMAN_REVIEW"
                    comment_text = (
                        f"🧩 **Human Review Required (CAPTCHA Challenge)**\n\n"
                        f"• **Barrier**: An interactive bot challenge (CAPTCHA / Cloudflare Turnstile) was triggered.\n"
                        f"• **Portal URL**: {page.url}\n\n"
                        f"📋 **Next Steps for Candidate**:\n"
                        f"1. Open the portal URL and solve the interactive verification challenge.\n"
                        f"2. Complete the remaining steps with the tailored resume attached."
                    )

                    app_ref = self.client.collection("users").document(user_id).collection("applications").document(app_id)
                    app_ref.set(
                        {
                            "state": "HUMAN_REVIEW",
                            "status": target_status,
                            "review_reason": "CAPTCHA_DETECTED",
                            "review_details": blocker_detail,
                            "incident_id": incident_id,
                            "target_portal_url": page.url,
                            "proof_screenshot": str(post_path),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        merge=True,
                    )

                    try:
                        self.enqueue_notion_sync(user_id, app_id, revision, target_status, comment_text)
                    except Exception as ne:
                        logger.warning(f"Could not enqueue Notion sync: {ne}")

                    if not headless:
                        page.wait_for_timeout(5000)

                    return True

                elif blocker_type == "VALIDATION_ERROR":
                    post_name = "validation-error.png"
                    post_path = version_dir / post_name
                    try:
                        page.screenshot(path=str(post_path), full_page=True)
                    except Exception:
                        pass

                    incident_id = f"inc_{app_id}_{int(datetime.now().timestamp())}"
                    incident = AutomationIncident(
                        incident_id=incident_id,
                        application_id=app_id,
                        company=draft.company,
                        job_title=draft.job_title,
                        category="VALIDATION_ERROR",
                        severity="WARNING",
                        diagnostic_summary=f"Form validation errors encountered: {blocker_detail}",
                        portal_url=page.url,
                        step_reached=1,
                        proof_screenshot=str(post_path),
                        error_detail=blocker_detail,
                    )
                    self.draft_repo.save_incident(incident)

                    target_status = "HUMAN_REVIEW"
                    comment_text = (
                        f"📝 **Human Review Required (Form Validation Error)**\n\n"
                        f"• **Barrier**: Mandatory fields or complex custom questions require human input.\n"
                        f"• **Details**: {blocker_detail}\n"
                        f"• **Portal URL**: {page.url}\n\n"
                        f"📋 **Next Steps for Candidate**:\n"
                        f"1. Open the portal URL and provide the requested custom details."
                    )

                    app_ref = self.client.collection("users").document(user_id).collection("applications").document(app_id)
                    app_ref.set(
                        {
                            "state": "HUMAN_REVIEW",
                            "status": target_status,
                            "review_reason": "VALIDATION_ERROR",
                            "review_details": blocker_detail,
                            "incident_id": incident_id,
                            "target_portal_url": page.url,
                            "proof_screenshot": str(post_path),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        merge=True,
                    )

                    try:
                        self.enqueue_notion_sync(user_id, app_id, revision, target_status, comment_text)
                    except Exception as ne:
                        logger.warning(f"Could not enqueue Notion sync: {ne}")

                    if not headless:
                        page.wait_for_timeout(5000)

                    return True

                elif blocker_type == "EXPIRED":
                    incident_id = f"inc_{app_id}_{int(datetime.now().timestamp())}"
                    incident = AutomationIncident(
                        incident_id=incident_id,
                        application_id=app_id,
                        company=draft.company,
                        job_title=draft.job_title,
                        category="VACANCY_EXPIRED",
                        severity="WARNING",
                        diagnostic_summary="Vacancy has expired/closed on employer career portal.",
                        portal_url=page.url,
                        step_reached=1,
                        error_detail=blocker_detail,
                    )
                    self.draft_repo.save_incident(incident)

                    target_status = "DROPPED"
                    app_ref = self.client.collection("users").document(user_id).collection("applications").document(app_id)
                    app_ref.set(
                        {
                            "state": "DROPPED",
                            "status": target_status,
                            "drop_reason": blocker_detail,
                            "incident_id": incident_id,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        merge=True,
                    )
                    try:
                        self.enqueue_notion_sync(
                            user_id, app_id, revision, target_status,
                            f"⚠️ **Vacancy Expired**: {blocker_detail} on employer portal ({page.url}).",
                        )
                    except Exception as ne:
                        logger.warning(f"Could not enqueue Notion sync: {ne}")

                    return True


                # Capture post-submit screenshot
                post_name = "submission-success.png" if confirmed else "submission-uncertain.png"
                post_path = version_dir / post_name
                try:
                    page.screenshot(path=str(post_path), full_page=True)
                except Exception:
                    pass

                # Update application state in Firestore
                target_status = "APPLIED" if confirmed else "SUBMISSION_UNCERTAIN"
                app_ref = self.client.collection("users").document(user_id).collection("applications").document(app_id)
                app_ref.set(
                    {
                        "state": score.verdict.value if confirmed else ApplicationState.SUBMISSION_UNCERTAIN.value,
                        "status": target_status,
                        "verification_score": score.to_dict(),
                        "applied_at": datetime.now(timezone.utc).isoformat() if confirmed else None,
                        "proof_screenshot": str(post_path),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    merge=True,
                )

                if confirmed:
                    try:
                        notion_job_id = self.enqueue_notion_sync(user_id, app_id, revision, target_status)
                        logger.info(f"Enqueued Notion sync job: {notion_job_id}")
                    except Exception as ne:
                        logger.warning(f"Could not enqueue Notion sync: {ne}")

                if not headless:
                    logger.info("Keeping browser open for 5 seconds for visual inspection...")
                    page.wait_for_timeout(5000)

                return confirmed


            finally:
                browser.close()




    def run(self, once: bool = False) -> None:
        """Run continuous worker polling loop."""
        if os.environ.get("JAA_ENABLE_SUBMISSION") != SUBMISSION_CONFIRMATION:
            logger.warning(
                "Submission worker disabled. Set JAA_ENABLE_SUBMISSION=%s only "
                "for an explicitly opted-in deployment.",
                SUBMISSION_CONFIRMATION,
            )
            return
        logger.info(f"Starting Playwright Submission Worker (ID: {self.worker_id}, Project: {self.project_id})")
        while True:
            job = self.claim_next_job()
            if job:
                job_id = job["job_id"]
                try:
                    success = self.process_job(job)
                    self.client.collection("submissionJobs").document(job_id).update(
                        {
                            "state": "SUCCEEDED" if success else "FAILED",
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                except Exception as e:
                    logger.error(f"Job {job_id} failed with error: {e}", exc_info=True)
                    app_id = job.get("application_id", "unknown")
                    u_id = job.get("user_id", "")
                    rev = job.get("revision", 1)

                    # Persist incident to /automationIncidents
                    inc_id = f"inc_{app_id}_{int(datetime.now().timestamp())}"
                    inc = AutomationIncident(
                        incident_id=inc_id,
                        application_id=app_id,
                        company=job.get("company", app_id),
                        job_title=job.get("job_title", "Application"),
                        category="UNEXPECTED_ERROR",
                        severity="ERROR",
                        diagnostic_summary=f"Unexpected automation exception: {str(e)[:200]}",
                        portal_url=job.get("target_url", ""),
                        error_detail=str(e),
                    )
                    try:
                        self.draft_repo.save_incident(inc)
                        if u_id and app_id:
                            self.client.collection("users").document(u_id).collection("applications").document(app_id).set(
                                {
                                    "state": "HUMAN_REVIEW",
                                    "status": "HUMAN_REVIEW",
                                    "review_reason": "UNEXPECTED_ERROR",
                                    "review_details": str(e)[:300],
                                    "incident_id": inc_id,
                                    "updated_at": datetime.now(timezone.utc).isoformat(),
                                },
                                merge=True,
                            )
                            self.enqueue_notion_sync(
                                u_id, app_id, rev, "HUMAN_REVIEW",
                                f"⚠️ **Human Review Required (Automation Exception)**\n\n• **Details**: {str(e)[:250]}\n• **Portal URL**: {job.get('target_url', '')}",
                            )
                    except Exception as err_log:
                        logger.warning(f"Could not persist incident for failed job {job_id}: {err_log}")

                    self.client.collection("submissionJobs").document(job_id).update(
                        {
                            "state": "FAILED",
                            "error": str(e),
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )

            elif once:
                break
            else:
                time.sleep(self.poll_interval)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if os.environ.get("JAA_ENABLE_SUBMISSION") != SUBMISSION_CONFIRMATION:
        logger.warning(
            "Submission worker disabled; no Firestore queue was opened. "
            "Set JAA_ENABLE_SUBMISSION=%s only for explicit opt-in.",
            SUBMISSION_CONFIRMATION,
        )
        return 0
    parser = argparse.ArgumentParser(description="Playwright Submission Worker Daemon")
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    parser.add_argument("--project-id", help="Firebase Project ID")
    args = parser.parse_args()

    worker = PlaywrightSubmissionWorker(project_id=args.project_id)
    worker.run(once=args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
