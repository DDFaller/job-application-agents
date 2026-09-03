from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from typing import Any
from uuid import UUID, uuid5

from .models import ArtifactRef, RenderJob, RenderRequest


JOB_COLLECTION = "renderJobs"
WORKER_COLLECTION = "renderWorkers"
JOB_NAMESPACE = UUID("ed07c78c-2e26-4a93-a995-73099836f9dd")


class FirestoreRenderJobRepository:
    """Firestore-backed queue with transactional lease ownership."""

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
        app_name = f"jaa-render-{suffix}"
        try:
            app = firebase_admin.get_app(app_name)
        except ValueError:
            app = firebase_admin.initialize_app(options={"projectId": project_id}, name=app_name)
        return firestore.client(app=app)

    @staticmethod
    def job_id_for_key(idempotency_key: str) -> str:
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("idempotency key must contain 1-200 characters")
        return str(uuid5(JOB_NAMESPACE, idempotency_key))

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _job(snapshot: Any) -> RenderJob:
        if not snapshot.exists:
            raise KeyError(f"unknown render job: {snapshot.id}")
        row = snapshot.to_dict()
        output = row.get("output_artifact")
        return RenderJob(
            id=snapshot.id, state=row["state"],
            request=RenderRequest.from_dict(row["request"]),
            attempts=int(row.get("attempts", 0)), max_attempts=int(row.get("max_attempts", 3)),
            user_id=row.get("user_id") or (row.get("request") or {}).get("user_id"),
            output_artifact=ArtifactRef.from_dict(output) if output else None,
            result=row.get("result"), error_code=row.get("error_code"),
            error_detail=row.get("error_detail"), created_at=row.get("created_at"),
            started_at=row.get("started_at"), finished_at=row.get("finished_at"),
        )

    def enqueue(self, request: RenderRequest, idempotency_key: str) -> RenderJob:
        _, firestore, _ = self._sdk()
        job_id = self.job_id_for_key(idempotency_key)
        reference = self.client.collection(JOB_COLLECTION).document(job_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def create_if_missing(current_transaction):
            snapshot = reference.get(transaction=current_transaction)
            if not snapshot.exists:
                current_transaction.create(reference, {
                    "schema_version": 1,
                    "idempotency_key_hash": hashlib.sha256(idempotency_key.encode()).hexdigest(),
                    "user_id": request.user_id,
                    "state": "QUEUED", "request": request.to_dict(),
                    "attempts": 0, "max_attempts": 3,
                    "leased_by": None, "lease_expires_at": None, "heartbeat_at": None,
                    "output_artifact": None, "result": None,
                    "error_code": None, "error_detail": None,
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "started_at": None, "finished_at": None,
                })

        create_if_missing(transaction)
        return self.get(job_id)

    def requeue_expired(self) -> int:
        _, firestore, FieldFilter = self._sdk()
        query = (self.client.collection(JOB_COLLECTION)
            .where(filter=FieldFilter("state", "==", "RUNNING"))
            .where(filter=FieldFilter("lease_expires_at", "<=", self._now())).limit(25))
        changed = 0
        for candidate in query.stream():
            transaction = self.client.transaction()

            @firestore.transactional
            def expire(current_transaction):
                snapshot = candidate.reference.get(transaction=current_transaction)
                row = snapshot.to_dict() if snapshot.exists else {}
                expires = row.get("lease_expires_at")
                if row.get("state") != "RUNNING" or not expires or expires > self._now():
                    return False
                retry = int(row.get("attempts", 0)) < int(row.get("max_attempts", 3))
                current_transaction.update(candidate.reference, {
                    "state": "QUEUED" if retry else "FAILED", "leased_by": None,
                    "lease_expires_at": None, "error_code": "WORKER_LOST",
                    "error_detail": "worker lease expired",
                    "finished_at": None if retry else firestore.SERVER_TIMESTAMP,
                })
                return True

            if expire(transaction):
                changed += 1
        return changed

    def claim(self, worker_id: str, lease_seconds: int = 360) -> RenderJob | None:
        _, firestore, FieldFilter = self._sdk()
        query = (self.client.collection(JOB_COLLECTION)
            .where(filter=FieldFilter("state", "==", "QUEUED"))
            .order_by("created_at").limit(10))
        for candidate in query.stream():
            transaction = self.client.transaction()

            @firestore.transactional
            def claim_candidate(current_transaction):
                snapshot = candidate.reference.get(transaction=current_transaction)
                row = snapshot.to_dict() if snapshot.exists else {}
                if row.get("state") != "QUEUED":
                    return False
                now = self._now()
                current_transaction.update(candidate.reference, {
                    "state": "RUNNING", "attempts": int(row.get("attempts", 0)) + 1,
                    "leased_by": worker_id,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "heartbeat_at": now,
                    "started_at": row.get("started_at") or firestore.SERVER_TIMESTAMP,
                    "error_code": None, "error_detail": None,
                })
                return True

            if claim_candidate(transaction):
                return self.get(candidate.id)
        return None

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int = 360) -> bool:
        _, firestore, _ = self._sdk()
        reference = self.client.collection(JOB_COLLECTION).document(job_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def renew(current_transaction):
            snapshot = reference.get(transaction=current_transaction)
            row = snapshot.to_dict() if snapshot.exists else {}
            if row.get("state") != "RUNNING" or row.get("leased_by") != worker_id:
                return False
            now = self._now()
            current_transaction.update(reference, {
                "heartbeat_at": now,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
            })
            return True

        return bool(renew(transaction))

    def succeed(self, job_id: str, worker_id: str, output: ArtifactRef, result: dict[str, Any]) -> None:
        self._finish(job_id, worker_id, {
            "state": "SUCCEEDED", "output_artifact": output.to_dict(), "result": result,
            "error_code": None, "error_detail": None,
        })

    def _finish(self, job_id: str, worker_id: str, updates: dict[str, Any]) -> None:
        _, firestore, _ = self._sdk()
        reference = self.client.collection(JOB_COLLECTION).document(job_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def finish(current_transaction):
            snapshot = reference.get(transaction=current_transaction)
            row = snapshot.to_dict() if snapshot.exists else {}
            if row.get("state") != "RUNNING" or row.get("leased_by") != worker_id:
                raise RuntimeError("render job lease was lost before completion")
            current_transaction.update(reference, {
                **updates, "lease_expires_at": None, "finished_at": firestore.SERVER_TIMESTAMP,
            })

        finish(transaction)

    def fail(self, job_id: str, worker_id: str, code: str, detail: str, retryable: bool) -> None:
        _, firestore, _ = self._sdk()
        reference = self.client.collection(JOB_COLLECTION).document(job_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def record_failure(current_transaction):
            snapshot = reference.get(transaction=current_transaction)
            row = snapshot.to_dict() if snapshot.exists else {}
            if row.get("state") != "RUNNING" or row.get("leased_by") != worker_id:
                raise RuntimeError("render job lease was lost before failure recording")
            retry = retryable and int(row.get("attempts", 0)) < int(row.get("max_attempts", 3))
            current_transaction.update(reference, {
                "state": "QUEUED" if retry else "FAILED", "leased_by": None,
                "lease_expires_at": None, "error_code": code, "error_detail": detail[:4000],
                "finished_at": None if retry else firestore.SERVER_TIMESTAMP,
            })

        record_failure(transaction)

    def get(self, job_id: str) -> RenderJob:
        return self._job(self.client.collection(JOB_COLLECTION).document(job_id).get())

    def register_worker(self, worker_id: str, image_version: str, capabilities: dict[str, Any]) -> None:
        _, firestore, _ = self._sdk()
        self.client.collection(WORKER_COLLECTION).document(worker_id).set({
            "protocol_version": 1, "image_version": image_version,
            "capabilities": capabilities, "last_seen_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)

    def worker_ready(self, maximum_age_seconds: int = 90) -> bool:
        _, _, FieldFilter = self._sdk()
        cutoff = self._now() - timedelta(seconds=maximum_age_seconds)
        try:
            query = (self.client.collection(WORKER_COLLECTION)
                .where(filter=FieldFilter("last_seen_at", ">=", cutoff)).limit(10))
            for snapshot in query.stream():
                row = snapshot.to_dict()
                capabilities = row.get("capabilities", {})
                if row.get("protocol_version") == 1 and all(
                    capabilities.get(name) is True for name in ("xelatex", "pdfinfo", "pdftotext")
                ):
                    return True
        except Exception:
            pass
        for snapshot in self.client.collection(WORKER_COLLECTION).limit(10).stream():
            row = snapshot.to_dict()
            capabilities = row.get("capabilities", {})
            if row.get("protocol_version") == 1 and all(
                capabilities.get(name) is True for name in ("xelatex", "pdfinfo", "pdftotext")
            ):
                return True
        return False
