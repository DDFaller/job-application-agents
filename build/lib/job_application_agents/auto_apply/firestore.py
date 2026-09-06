from __future__ import annotations

from datetime import datetime, timezone, timedelta
import os
from typing import Any, Sequence

from google.cloud import firestore

from .draft_models import ApplicationDraft, ApprovalToken, ApplicationState, AutomationIncident
from ..sync.models import UserContext



class FirestoreDraftRepository:
    """Firestore repository for managing multi-tenant application drafts, revisions, and approval tokens."""

    def __init__(self, project_id: str | None = None, client: firestore.Client | None = None):
        self.project_id = (
            project_id
            or os.environ.get("JAA_FIREBASE_PROJECT_ID")
            or os.environ.get("GCLOUD_PROJECT")
        )
        if not self.project_id:
            raise ValueError("JAA_FIREBASE_PROJECT_ID is required")
        self.client = client or firestore.Client(project=self.project_id)

    def save_draft(self, user_id: str, draft: ApplicationDraft) -> str:
        """Save a new draft revision under /users/{userId}/applications/{appId}/drafts/{revision}."""
        user_ref = self.client.collection("users").document(user_id)
        app_ref = user_ref.collection("applications").document(draft.application_id)
        draft_ref = app_ref.collection("drafts").document(str(draft.revision))

        payload = draft.to_dict()
        draft_ref.set(payload)

        # Update root application draft pointer
        app_ref.set(
            {
                "active_draft_revision": draft.revision,
                "active_draft_hash": draft.draft_hash,
                "state": draft.state.value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            merge=True,
        )

        return draft_ref.path

    def get_draft(self, user_id: str, application_id: str, revision: int | None = None) -> ApplicationDraft | None:
        """Fetch a specific revision or the active draft for an application."""
        user_ref = self.client.collection("users").document(user_id)
        app_ref = user_ref.collection("applications").document(application_id)

        if revision is None:
            app_snap = app_ref.get()
            if not app_snap.exists:
                return None
            rev = app_snap.to_dict().get("active_draft_revision", 1)
        else:
            rev = revision

        draft_snap = app_ref.collection("drafts").document(str(rev)).get()
        if not draft_snap.exists:
            return None

        return ApplicationDraft.from_dict(draft_snap.to_dict())

    def save_approval_token(self, user_id: str, token: ApprovalToken) -> None:
        """Record an approval token authorizing submission of a specific draft revision."""
        user_ref = self.client.collection("users").document(user_id)
        app_ref = user_ref.collection("applications").document(token.application_id)
        approval_ref = app_ref.collection("approval").document("current")

        approval_ref.set(token.to_dict())

        # Update application state to APPROVED
        app_ref.set(
            {
                "state": ApplicationState.APPROVED.value,
                "approved_revision": token.revision,
                "approved_hash": token.draft_hash,
                "approved_at": token.approved_at,
            },
            merge=True,
        )

    def enqueue_submission_job(
        self,
        user_id: str,
        application_id: str,
        token: ApprovalToken,
    ) -> str:
        """Enqueue an approved submission job into /submissionJobs for the Playwright worker daemon."""
        jobs_ref = self.client.collection("submissionJobs")
        job_id = f"sub_{token.application_id}_r{token.revision}"

        job_payload = {
            "job_id": job_id,
            "user_id": user_id,
            "application_id": application_id,
            "revision": token.revision,
            "draft_hash": token.draft_hash,
            "state": "QUEUED",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "lease_expires_at": None,
            "worker_id": None,
        }

        jobs_ref.document(job_id).set(job_payload)
        return job_id

    def save_incident(self, incident: AutomationIncident) -> str:
        """Save a structured automation failure/blocker incident to /automationIncidents."""
        incidents_ref = self.client.collection("automationIncidents")
        incidents_ref.document(incident.incident_id).set(incident.to_dict())
        return incident.incident_id
