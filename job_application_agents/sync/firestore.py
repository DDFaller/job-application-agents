from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from typing import Any

from .models import (
    ApplicationSyncSnapshot,
    ApplicationVersionSnapshot,
    CandidateEvidenceSnapshot,
    CurriculumSyncSnapshot,
    CurriculumVersionSnapshot,
    ProfileSyncSnapshot,
    ProfileVersionSnapshot,
    UserContext,
)

USERS_COLLECTION = "users"
CURRICULUM_COLLECTION = "curriculum"
CURRICULUM_VERSIONS_COLLECTION = "curriculum_versions"
CANDIDATE_EVIDENCE_COLLECTION = "candidate_evidence"
PROFILES_COLLECTION = "profiles"
PROFILE_VERSIONS_COLLECTION = "profile_versions"
APPLICATIONS_COLLECTION = "applications"
APPLICATION_VERSIONS_COLLECTION = "versions"
SYSTEM_COLLECTION = "system"
NOTION_WEBHOOK_CONFIG_DOCUMENT = "notion_webhook_config"


class FirestoreUserSyncRepository:
    """Firestore repository for multi-user curriculum, profile, and application sync."""

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
        app_name = f"jaa-sync-{suffix}"
        try:
            app = firebase_admin.get_app(app_name)
        except ValueError:
            app = firebase_admin.initialize_app(options={"projectId": project_id}, name=app_name)
        return firestore.client(app=app)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _user_ref(self, user_id: str):
        if not user_id or "/" in user_id or ".." in user_id:
            raise ValueError("invalid user_id")
        return self.client.collection(USERS_COLLECTION).document(user_id)

    def ensure_user(
        self, user_id: str, email: str | None = None, display_name: str | None = None
    ) -> dict[str, Any]:
        user_ref = self._user_ref(user_id)
        snapshot = user_ref.get()
        if snapshot.exists:
            data = snapshot.to_dict() or {}
            updates = {}
            if email and data.get("email") != email:
                updates["email"] = email
            if display_name and data.get("display_name") != display_name:
                updates["display_name"] = display_name
            if updates:
                updates["updated_at"] = self._now_iso()
                user_ref.update(updates)
                data.update(updates)
            return data
        user_data = UserContext(
            user_id=user_id, email=email, display_name=display_name
        ).to_dict()
        user_ref.set(user_data)
        return user_data

    def fetch_user_meta(self, user_id: str) -> dict[str, Any] | None:
        snapshot = self._user_ref(user_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    # --- Master Curriculum Sync ---

    def save_curriculum(
        self,
        user_id: str,
        snapshot: CurriculumSyncSnapshot,
        versions: list[CurriculumVersionSnapshot] | None = None,
        candidate_evidence: CandidateEvidenceSnapshot | None = None,
    ) -> None:
        self.ensure_user(user_id)
        user_ref = self._user_ref(user_id)
        curriculum_ref = user_ref.collection(CURRICULUM_COLLECTION).document("current")
        curriculum_ref.set(snapshot.to_dict())

        if versions:
            versions_col = user_ref.collection(CURRICULUM_VERSIONS_COLLECTION)
            for version_item in versions:
                if version_item.version:
                    versions_col.document(version_item.version).set(version_item.to_dict())

        if candidate_evidence:
            evidence_ref = user_ref.collection(CANDIDATE_EVIDENCE_COLLECTION).document("current")
            evidence_ref.set(candidate_evidence.to_dict())

    def fetch_curriculum(self, user_id: str) -> CurriculumSyncSnapshot | None:
        user_ref = self._user_ref(user_id)
        snapshot = user_ref.collection(CURRICULUM_COLLECTION).document("current").get()
        if not snapshot.exists:
            return None
        return CurriculumSyncSnapshot.from_dict(snapshot.to_dict() or {})

    def fetch_curriculum_versions(self, user_id: str) -> list[CurriculumVersionSnapshot]:
        user_ref = self._user_ref(user_id)
        versions_col = user_ref.collection(CURRICULUM_VERSIONS_COLLECTION)
        results = []
        for doc in versions_col.stream():
            data = doc.to_dict()
            if data:
                results.append(CurriculumVersionSnapshot.from_dict(data))
        return sorted(results, key=lambda item: item.version)

    def fetch_candidate_evidence(self, user_id: str) -> CandidateEvidenceSnapshot | None:
        user_ref = self._user_ref(user_id)
        snapshot = user_ref.collection(CANDIDATE_EVIDENCE_COLLECTION).document("current").get()
        if not snapshot.exists:
            return None
        return CandidateEvidenceSnapshot.from_dict(snapshot.to_dict() or {})

    # --- Role Profiles Sync ---

    def save_profiles(
        self,
        user_id: str,
        snapshot: ProfileSyncSnapshot,
        versions: list[ProfileVersionSnapshot] | None = None,
    ) -> None:
        self.ensure_user(user_id)
        user_ref = self._user_ref(user_id)
        profiles_ref = user_ref.collection(PROFILES_COLLECTION).document("current")
        profiles_ref.set(snapshot.to_dict())

        if versions:
            versions_col = user_ref.collection(PROFILE_VERSIONS_COLLECTION)
            for version_item in versions:
                if version_item.version:
                    versions_col.document(version_item.version).set(version_item.to_dict())

    def fetch_profiles(self, user_id: str) -> ProfileSyncSnapshot | None:
        user_ref = self._user_ref(user_id)
        snapshot = user_ref.collection(PROFILES_COLLECTION).document("current").get()
        if not snapshot.exists:
            return None
        return ProfileSyncSnapshot.from_dict(snapshot.to_dict() or {})

    def fetch_profile_versions(self, user_id: str) -> list[ProfileVersionSnapshot]:
        user_ref = self._user_ref(user_id)
        versions_col = user_ref.collection(PROFILE_VERSIONS_COLLECTION)
        results = []
        for doc in versions_col.stream():
            data = doc.to_dict()
            if data:
                results.append(ProfileVersionSnapshot.from_dict(data))
        return sorted(results, key=lambda item: item.version)

    # --- Applications Sync ---

    def save_application(self, user_id: str, snapshot: ApplicationSyncSnapshot) -> None:
        self.ensure_user(user_id)
        user_ref = self._user_ref(user_id)
        app_ref = user_ref.collection(APPLICATIONS_COLLECTION).document(snapshot.application_id)
        app_data = snapshot.to_dict()
        app_data["user_id"] = user_id
        # Local bundle snapshots predate/omit cloud lifecycle metadata. Do not
        # let a local push erase Notion links, documents, sync state, or fields
        # that were edited in Notion; explicit edits use update_application_fields.
        for field in (
            "notion_page_id", "notion_page_url", "documents", "sync",
            "applied_at", "next_action_at", "notes",
        ):
            if app_data.get(field) in (None, {}, ""):
                app_data.pop(field, None)
        app_ref.set(app_data, merge=True)

        if snapshot.versions:
            versions_col = app_ref.collection(APPLICATION_VERSIONS_COLLECTION)
            for version_id, version_data in snapshot.versions.items():
                versions_col.document(version_id).set(version_data.to_dict())

    def save_application_version(
        self, user_id: str, application_id: str, version: ApplicationVersionSnapshot
    ) -> None:
        self.ensure_user(user_id)
        user_ref = self._user_ref(user_id)
        app_ref = user_ref.collection(APPLICATIONS_COLLECTION).document(application_id)
        versions_col = app_ref.collection(APPLICATION_VERSIONS_COLLECTION)
        versions_col.document(version.version).set(version.to_dict())
        # Update current version pointer and updated timestamp on the application parent doc
        app_ref.set({
            "current_version": version.version,
            "updated_at": self._now_iso(),
            "user_id": user_id,
        }, merge=True)

    def fetch_application(
        self, user_id: str, application_id: str, include_versions: bool = True
    ) -> ApplicationSyncSnapshot | None:
        user_ref = self._user_ref(user_id)
        app_ref = user_ref.collection(APPLICATIONS_COLLECTION).document(application_id)
        snapshot = app_ref.get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        versions: dict[str, ApplicationVersionSnapshot] = {}
        if include_versions:
            for doc in app_ref.collection(APPLICATION_VERSIONS_COLLECTION).stream():
                v_data = doc.to_dict()
                if v_data and "version" in v_data:
                    versions[v_data["version"]] = ApplicationVersionSnapshot.from_dict(v_data)
        return ApplicationSyncSnapshot.from_dict(data, versions=versions)

    def fetch_application_version(
        self, user_id: str, application_id: str, version: str
    ) -> ApplicationVersionSnapshot | None:
        user_ref = self._user_ref(user_id)
        v_ref = (
            user_ref.collection(APPLICATIONS_COLLECTION)
            .document(application_id)
            .collection(APPLICATION_VERSIONS_COLLECTION)
            .document(version)
        )
        snap = v_ref.get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        return ApplicationVersionSnapshot.from_dict(data)


    def list_applications(
        self, user_id: str, include_versions: bool = False
    ) -> list[ApplicationSyncSnapshot]:
        user_ref = self._user_ref(user_id)
        apps_col = user_ref.collection(APPLICATIONS_COLLECTION)
        results = []
        for doc in apps_col.stream():
            data = doc.to_dict()
            if data and "application_id" in data:
                versions: dict[str, ApplicationVersionSnapshot] = {}
                if include_versions:
                    for v_doc in doc.reference.collection(APPLICATION_VERSIONS_COLLECTION).stream():
                        v_data = v_doc.to_dict()
                        if v_data and "version" in v_data:
                            versions[v_data["version"]] = ApplicationVersionSnapshot.from_dict(v_data)
                results.append(ApplicationSyncSnapshot.from_dict(data, versions=versions))
        return results

    def delete_application(self, user_id: str, application_id: str) -> bool:
        user_ref = self._user_ref(user_id)
        app_ref = user_ref.collection(APPLICATIONS_COLLECTION).document(application_id)
        if not app_ref.get().exists:
            return False
        # Delete versions subcollection
        for doc in app_ref.collection(APPLICATION_VERSIONS_COLLECTION).stream():
            doc.reference.delete()
        app_ref.delete()
        return True

    def update_application_fields(
        self, user_id: str, application_id: str, fields: dict[str, Any]
    ) -> None:
        user_ref = self._user_ref(user_id)
        app_ref = user_ref.collection(APPLICATIONS_COLLECTION).document(application_id)
        app_ref.set(fields, merge=True)

    def get_user_notion_config(self, user_id: str) -> dict[str, Any] | None:
        user_ref = self._user_ref(user_id)
        snap = user_ref.get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        return data.get("notion_config")

    def set_user_notion_config(
        self, user_id: str, database_id: str, enabled: bool = True
    ) -> None:
        self.ensure_user(user_id)
        user_ref = self._user_ref(user_id)
        user_ref.set(
            {
                "notion_config": {
                    "database_id": database_id,
                    "enabled": enabled,
                    "updated_at": self._now_iso(),
                }
            },
            merge=True,
        )

    def get_notion_webhook_verification_token(self) -> str | None:
        """Return the server-side Notion webhook token, if bootstrapped."""
        ref = self.client.collection(SYSTEM_COLLECTION).document(NOTION_WEBHOOK_CONFIG_DOCUMENT)
        snapshot = ref.get()
        if not snapshot.exists:
            return None
        token = (snapshot.to_dict() or {}).get("verification_token")
        return str(token) if token else None

    def save_notion_webhook_verification_token(self, token: str) -> bool:
        """Store the first Notion verification token without allowing replacement.

        Notion's subscription verification request is unauthenticated by design.
        The token is therefore write-once: a later verification request cannot
        replace the key used to authenticate already-established webhooks.
        Returns True when this call created the configuration and False when a
        token was already present.
        """
        if not token or not token.strip():
            raise ValueError("Notion webhook verification token is required")

        _, firestore, _ = self._sdk()
        ref = self.client.collection(SYSTEM_COLLECTION).document(NOTION_WEBHOOK_CONFIG_DOCUMENT)
        tx = self.client.transaction()

        @firestore.transactional
        def create_if_absent(transaction):
            snapshot = ref.get(transaction=transaction)
            if snapshot.exists:
                return False
            transaction.create(
                ref,
                {
                    "verification_token": token,
                    "created_at": firestore.SERVER_TIMESTAMP,
                },
            )
            return True

        return bool(create_if_absent(tx))
