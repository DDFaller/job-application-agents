from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from uuid import uuid4

from .models import ArtifactRef


MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_INPUT_BYTES = 25 * 1024 * 1024
MAX_FILES = 200
FIRESTORE_CHUNK_BYTES = 512 * 1024
FIRESTORE_ARTIFACT_COLLECTION = "renderArtifacts"


class ArtifactStore:
    """Content-addressed archive store backed by local files, GCS, or Firestore chunks."""

    def __init__(
        self, root: Path, bucket_name: str | None = None,
        firestore_project_id: str | None = None,
    ):
        self.root = root.expanduser().resolve()
        self.backend = os.environ.get("JAA_ARTIFACT_BACKEND", "").strip().lower()
        self.bucket_name = bucket_name or os.environ.get("JAA_ARTIFACT_BUCKET")
        self.bucket = None
        self.firestore = None
        if self.backend == "firestore":
            project_id = firestore_project_id or os.environ.get("JAA_FIREBASE_PROJECT_ID")
            if not project_id:
                raise RuntimeError("JAA_FIREBASE_PROJECT_ID is required for Firestore artifacts")
            from .firestore import FirestoreRenderJobRepository
            self.firestore = FirestoreRenderJobRepository._client(project_id)
        elif self.bucket_name:
            try:
                from google.cloud import storage
            except ImportError as exc:
                raise RuntimeError("google-cloud-storage is required for JAA_ARTIFACT_BUCKET") from exc
            self.bucket = storage.Client().bucket(self.bucket_name)
        self.objects = self.root / "objects"
        self.temporary = self.root / "tmp"
        try:
            self.objects.mkdir(parents=True, exist_ok=True)
            self.objects.chmod(0o777)
        except OSError:
            pass
        try:
            self.temporary.mkdir(parents=True, exist_ok=True)
            self.temporary.chmod(0o777)
        except OSError:
            pass

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _path(self, ref: ArtifactRef) -> Path:
        path = (self.root / ref.key).resolve()
        if self.root not in path.parents:
            raise ValueError("artifact key escapes store root")
        return path

    def verify(self, ref: ArtifactRef) -> Path:
        if self.firestore is not None:
            path = self.temporary / f"verify-{uuid4().hex}.tar"
            metadata = self.firestore.collection(FIRESTORE_ARTIFACT_COLLECTION).document(ref.sha256).get()
            row = metadata.to_dict() if metadata.exists else None
            if not row or row.get("bytes") != ref.bytes or row.get("sha256") != ref.sha256:
                raise ValueError(f"artifact is missing or corrupt: {ref.key}")
            chunks = self.firestore.collection(FIRESTORE_ARTIFACT_COLLECTION).document(
                ref.sha256
            ).collection("chunks").order_by("index").stream()
            try:
                with path.open("wb") as output:
                    for chunk in chunks:
                        data = chunk.to_dict().get("data")
                        if not isinstance(data, bytes):
                            raise ValueError(f"artifact is missing or corrupt: {ref.key}")
                        output.write(data)
                if path.stat().st_size != ref.bytes or self.sha256(path) != ref.sha256:
                    raise ValueError(f"artifact is missing or corrupt: {ref.key}")
                return path
            except Exception:
                path.unlink(missing_ok=True)
                raise
        if self.bucket is not None:
            blob = self.bucket.blob(ref.key)
            if not blob.exists():
                raise ValueError(f"artifact is missing or corrupt: {ref.key}")
            blob.reload()
            if blob.size != ref.bytes:
                raise ValueError(f"artifact is missing or corrupt: {ref.key}")
            path = self.temporary / f"verify-{uuid4().hex}.tar"
            blob.download_to_filename(str(path))
            if self.sha256(path) != ref.sha256:
                path.unlink(missing_ok=True)
                raise ValueError(f"artifact is missing or corrupt: {ref.key}")
            return path
        path = self._path(ref)
        if not path.is_file() or path.stat().st_size != ref.bytes or self.sha256(path) != ref.sha256:
            raise ValueError(f"artifact is missing or corrupt: {ref.key}")
        return path

    def put_directory(self, directory: Path) -> ArtifactRef:
        directory = directory.resolve()
        files = sorted(path for path in directory.rglob("*") if path.is_file())
        if len(files) > MAX_FILES:
            raise ValueError(f"artifact contains more than {MAX_FILES} files")
        total = 0
        for path in files:
            if path.is_symlink():
                raise ValueError("artifact directories may not contain symlinks")
            total += path.stat().st_size
        if total > MAX_INPUT_BYTES:
            raise ValueError("artifact input exceeds 25 MB")
        fd, temporary_name = tempfile.mkstemp(prefix="artifact-", suffix=".tar", dir=self.temporary)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with tarfile.open(temporary, "w") as archive:
                for path in files:
                    relative = path.relative_to(directory).as_posix()
                    info = archive.gettarinfo(str(path), arcname=relative)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as source:
                        archive.addfile(info, source)
            if temporary.stat().st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("artifact archive exceeds 50 MB")
            try:
                temporary.chmod(0o666)
            except OSError:
                pass
            digest = self.sha256(temporary)
            if self.firestore is not None:
                reference = self.firestore.collection(FIRESTORE_ARTIFACT_COLLECTION).document(digest)
                reference.set({
                    "key": f"objects/{digest}.tar", "sha256": digest,
                    "bytes": temporary.stat().st_size,
                    "chunk_bytes": FIRESTORE_CHUNK_BYTES,
                    "chunks": (temporary.stat().st_size + FIRESTORE_CHUNK_BYTES - 1)
                    // FIRESTORE_CHUNK_BYTES,
                }, merge=True)
                with temporary.open("rb") as source:
                    index = 0
                    while data := source.read(FIRESTORE_CHUNK_BYTES):
                        reference.collection("chunks").document(str(index).zfill(8)).set({
                            "index": index, "data": data,
                        })
                        index += 1
                return ArtifactRef(
                    key=f"objects/{digest}.tar", sha256=digest,
                    bytes=temporary.stat().st_size,
                )
            if self.bucket is not None:
                key = f"objects/{digest}.tar"
                blob = self.bucket.blob(key)
                if not blob.exists():
                    blob.upload_from_filename(str(temporary), content_type="application/x-tar")
                return ArtifactRef(key=key, sha256=digest, bytes=temporary.stat().st_size)
            destination = self.objects / f"{digest}.tar"
            if destination.exists():
                temporary.unlink()
            else:
                temporary.replace(destination)
                try:
                    destination.chmod(0o666)
                except OSError:
                    pass
            return ArtifactRef(
                key=str(destination.relative_to(self.root)),
                sha256=digest,
                bytes=destination.stat().st_size,
            )
        finally:
            temporary.unlink(missing_ok=True)

    def extract(self, ref: ArtifactRef, destination: Path) -> None:
        archive_path = self.verify(ref)
        try:
            destination.mkdir(parents=True, exist_ok=True)
            destination_root = destination.resolve()
            with tarfile.open(archive_path, "r") as archive:
                members = archive.getmembers()
                if len(members) > MAX_FILES:
                    raise ValueError("artifact archive contains more than 200 files")
                if sum(member.size for member in members) > MAX_ARCHIVE_BYTES:
                    raise ValueError("artifact archive expands beyond 50 MB")
                for member in members:
                    pure = PurePosixPath(member.name)
                    if pure.is_absolute() or ".." in pure.parts or member.issym() or member.islnk():
                        raise ValueError("artifact archive contains an unsafe path")
                    target = (destination_root / pure.as_posix()).resolve()
                    if destination_root != target and destination_root not in target.parents:
                        raise ValueError("artifact archive escapes destination")
                    if not member.isfile():
                        raise ValueError("artifact archive may contain files only")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError("artifact entry could not be read")
                    with target.open("wb") as output:
                        shutil.copyfileobj(source, output)
        finally:
            if self.bucket is not None:
                archive_path.unlink(missing_ok=True)
