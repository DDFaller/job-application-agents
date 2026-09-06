from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from typing import Any
from uuid import UUID, uuid4, uuid5

from .models import NotionSyncJob

NOTION_JOB_COLLECTION = "notionJobs"
NOTION_JOB_NAMESPACE = UUID("b27ac433-f81d-8189-ac22-000301d7aa86")
NOTION_EVENT_COLLECTION = "notionWebhookEvents"


class FirestoreNotionJobRepository:
    """Firestore transactional queue for Notion synchronization jobs."""

    def __init__(self, project_id: str, client: Any | None = None):
        if not project_id:
            raise ValueError("Firebase project ID is required")
        self.project_id = project_id
        self.client = client or self._client(project_id)

    @staticmethod
    def _sdk():
        try:
            import firebase_admin
            from firebase_admin import firestore
            from google.cloud.firestore_v1.base_query import FieldFilter
        except ImportError as exc:
            raise RuntimeError(
                "firebase-admin is required; install the project with 'pip install -e .'"
            ) from exc
        return firebase_admin, firestore, FieldFilter

    @classmethod
    def _client(cls, project_id: str):
        if os.environ.get("FIRESTORE_EMULATOR_HOST"):
            from google.auth.credentials import AnonymousCredentials
            from google.cloud import firestore as google_firestore

            return google_firestore.Client(
                project=project_id, credentials=AnonymousCredentials()
            )
        firebase_admin, firestore, _ = cls._sdk()
        suffix = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:12]
        app_name = f"jaa-notion-{suffix}"
        try:
            app = firebase_admin.get_app(app_name)
        except ValueError:
            app = firebase_admin.initialize_app(options={"projectId": project_id}, name=app_name)
        return firestore.client(app=app)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def job_id_for_key(cls, user_id: str, application_id: str, version: str = "") -> str:
        key = f"{user_id}:{application_id}:{version}"
        return str(uuid5(NOTION_JOB_NAMESPACE, key))

    def get(self, job_id: str) -> NotionSyncJob | None:
        doc = self.client.collection(NOTION_JOB_COLLECTION).document(job_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data["id"] = doc.id
        return NotionSyncJob.from_dict(data)

    def enqueue(
        self,
        user_id: str,
        application_id: str,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> NotionSyncJob:
        _, firestore, _ = self._sdk()
        key = idempotency_key or f"{user_id}:{application_id}:{payload.get('current_version', '')}"
        job_id = self.job_id_for_key(user_id, application_id, payload.get("current_version", ""))
        ref = self.client.collection(NOTION_JOB_COLLECTION).document(job_id)
        tx = self.client.transaction()

        @firestore.transactional
        def create_or_update(transaction):
            snap = ref.get(transaction=transaction)
            now = firestore.SERVER_TIMESTAMP
            if not snap.exists:
                transaction.create(
                    ref,
                    {
                        "user_id": user_id,
                        "application_id": application_id,
                        "action": action,
                        "state": "QUEUED",
                        "payload": payload,
                        "attempts": 0,
                        "max_attempts": 3,
                        "leased_by": None,
                        "lease_expires_at": None,
                        "result": None,
                        "error_detail": None,
                        "created_at": now,
                        "started_at": None,
                        "finished_at": None,
                    },
                )
            else:
                current = snap.to_dict() or {}
                if current.get("state") in ("QUEUED", "RUNNING"):
                    transaction.update(
                        ref,
                        {
                            "payload": payload,
                            "action": action,
                        },
                    )
                else:
                    transaction.update(
                        ref,
                        {
                            "state": "QUEUED",
                            "action": action,
                            "payload": payload,
                            "attempts": 0,
                            "leased_by": None,
                            "lease_expires_at": None,
                            "result": None,
                            "error_detail": None,
                            "started_at": None,
                            "finished_at": None,
                        },
                    )

        create_or_update(tx)
        job = self.get(job_id)
        if job is None:
            raise RuntimeError(f"failed to enqueue notion job: {job_id}")
        return job

    def enqueue_application(
        self,
        user_id: str,
        application_id: str,
        current_version: str = "v001",
        reason: str = "firestore_change",
    ) -> NotionSyncJob:
        """Enqueue the latest application snapshot using the stable idempotency key."""
        return self.enqueue(
            user_id=user_id,
            application_id=application_id,
            action="CREATE_OR_UPDATE",
            payload={
                "application_id": application_id,
                "current_version": current_version,
                "reason": reason,
            },
            idempotency_key=f"application:{user_id}:{application_id}:{current_version}",
        )

    def record_webhook_event(self, event_id: str, payload: dict[str, Any]) -> bool:
        """Atomically record an event; return False for duplicate deliveries."""
        _, firestore, _ = self._sdk()
        if not event_id:
            raise ValueError("event_id is required")
        ref = self.client.collection(NOTION_EVENT_COLLECTION).document(event_id)
        tx = self.client.transaction()

        @firestore.transactional
        def record(transaction):
            snapshot = ref.get(transaction=transaction)
            if snapshot.exists:
                return False
            transaction.create(ref, {
                "event_id": event_id,
                "type": payload.get("type"),
                "page_id": payload.get("page_id"),
                "received_at": self._now(),
            })
            return True

        return bool(record(tx))

    def webhook_event_exists(self, event_id: str) -> bool:
        if not event_id:
            return False
        return self.client.collection(NOTION_EVENT_COLLECTION).document(event_id).get().exists

    def find_application_for_notion_page(
        self, page_id: str, application_id: str | None = None
    ) -> tuple[str, str] | None:
        """Find (user_id, application_id) using the stable page/application link."""
        for user_doc in self.client.collection("users").stream():
            user_id = user_doc.id
            if application_id:
                candidate = user_doc.reference.collection("applications").document(application_id).get()
                if candidate.exists:
                    data = candidate.to_dict() or {}
                    if not page_id or data.get("notion_page_id") in (None, page_id):
                        return user_id, application_id
            apps = user_doc.reference.collection("applications").stream()
            for app_doc in apps:
                data = app_doc.to_dict() or {}
                if data.get("notion_page_id") == page_id:
                    return user_id, app_doc.id
        return None

    def claim(self, worker_id: str, lease_seconds: int = 300) -> NotionSyncJob | None:
        _, firestore, FieldFilter = self._sdk()
        try:
            query = (
                self.client.collection(NOTION_JOB_COLLECTION)
                .where(filter=FieldFilter("state", "==", "QUEUED"))
                .order_by("created_at")
                .limit(10)
            )
            candidates = list(query.stream())
        except Exception:
            query = (
                self.client.collection(NOTION_JOB_COLLECTION)
                .where(filter=FieldFilter("state", "==", "QUEUED"))
                .limit(10)
            )
            candidates = list(query.stream())

        for candidate in candidates:
            tx = self.client.transaction()

            @firestore.transactional
            def claim_candidate(transaction):
                snap = candidate.reference.get(transaction=transaction)
                row = snap.to_dict() if snap.exists else {}
                if row.get("state") != "QUEUED":
                    return False
                now = self._now()
                expires = now + timedelta(seconds=lease_seconds)
                attempts = int(row.get("attempts", 0)) + 1
                transaction.update(
                    candidate.reference,
                    {
                        "state": "RUNNING",
                        "leased_by": worker_id,
                        "lease_expires_at": expires,
                        "attempts": attempts,
                        "started_at": firestore.SERVER_TIMESTAMP,
                    },
                )
                return True

            if claim_candidate(tx):
                return self.get(candidate.id)
        return None

    def heartbeat(self, job_id: str, worker_id: str, extend_seconds: int = 300) -> bool:
        _, firestore, _ = self._sdk()
        ref = self.client.collection(NOTION_JOB_COLLECTION).document(job_id)
        tx = self.client.transaction()

        @firestore.transactional
        def renew(transaction):
            snap = ref.get(transaction=transaction)
            row = snap.to_dict() if snap.exists else {}
            if row.get("state") != "RUNNING" or row.get("leased_by") != worker_id:
                return False
            expires = self._now() + timedelta(seconds=extend_seconds)
            transaction.update(ref, {"lease_expires_at": expires})
            return True

        return bool(renew(tx))

    def succeed(self, job_id: str, worker_id: str, result: dict[str, Any]) -> None:
        _, firestore, _ = self._sdk()
        ref = self.client.collection(NOTION_JOB_COLLECTION).document(job_id)
        ref.update({
            "state": "SUCCEEDED",
            "leased_by": None,
            "lease_expires_at": None,
            "result": result,
            "error_detail": None,
            "finished_at": firestore.SERVER_TIMESTAMP,
        })

    def fail(self, job_id: str, worker_id: str, error_detail: str, retryable: bool = True) -> None:
        _, firestore, _ = self._sdk()
        ref = self.client.collection(NOTION_JOB_COLLECTION).document(job_id)
        snap = ref.get()
        row = snap.to_dict() if snap.exists else {}
        attempts = int(row.get("attempts", 0))
        max_attempts = int(row.get("max_attempts", 3))
        retry = retryable and attempts < max_attempts
        ref.update({
            "state": "QUEUED" if retry else "FAILED",
            "leased_by": None,
            "lease_expires_at": None,
            "error_detail": error_detail,
            "finished_at": None if retry else firestore.SERVER_TIMESTAMP,
        })

    def requeue_expired(self) -> int:
        _, firestore, FieldFilter = self._sdk()
        try:
            query = (
                self.client.collection(NOTION_JOB_COLLECTION)
                .where(filter=FieldFilter("state", "==", "RUNNING"))
                .where(filter=FieldFilter("lease_expires_at", "<=", self._now()))
                .limit(25)
            )
            changed = 0
            for candidate in query.stream():
                tx = self.client.transaction()

                @firestore.transactional
                def expire(transaction):
                    snap = candidate.reference.get(transaction=transaction)
                    row = snap.to_dict() if snap.exists else {}
                    expires = row.get("lease_expires_at")
                    if row.get("state") != "RUNNING" or not expires or expires > self._now():
                        return False
                    retry = int(row.get("attempts", 0)) < int(row.get("max_attempts", 3))
                    transaction.update(
                        candidate.reference,
                        {
                            "state": "QUEUED" if retry else "FAILED",
                            "leased_by": None,
                            "lease_expires_at": None,
                            "error_detail": "worker lease expired",
                            "finished_at": None if retry else firestore.SERVER_TIMESTAMP,
                        },
                    )
                    return True

                if expire(tx):
                    changed += 1
            return changed
        except Exception:
            return 0
