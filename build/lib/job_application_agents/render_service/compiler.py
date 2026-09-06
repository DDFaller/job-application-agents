from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

from .models import RenderRequest, safe_relative_name


class CompileFailure(RuntimeError):
    def __init__(self, code: str, detail: str, *, retryable: bool = False):
        super().__init__(detail)
        self.code = code
        self.retryable = retryable


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], cwd: Path, deadline: float) -> subprocess.CompletedProcess[str]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CompileFailure("TIMEOUT", "render request exceeded its time limit")
    try:
        return subprocess.run(
            command, cwd=cwd, text=True, capture_output=True,
            timeout=min(60.0, remaining), check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CompileFailure("TIMEOUT", f"command timed out: {Path(command[0]).name}") from exc
    except OSError as exc:
        raise CompileFailure("INFRASTRUCTURE_ERROR", str(exc), retryable=True) from exc


def tool_version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
        return (result.stdout or result.stderr).splitlines()[0][:300]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return "unknown"


def compile_request(request: RenderRequest, source_root: Path, output_root: Path) -> dict[str, Any]:
    xelatex = shutil.which("xelatex")
    pdfinfo = shutil.which("pdfinfo")
    pdftotext = shutil.which("pdftotext")
    if not all((xelatex, pdfinfo, pdftotext)):
        raise CompileFailure(
            "INFRASTRUCTURE_ERROR", "worker is missing xelatex, pdfinfo, or pdftotext", retryable=True
        )
    missing_dependencies: list[str] = []
    kpsewhich = shutil.which("kpsewhich")
    for package in request.required_packages:
        if (source_root / package).is_file():
            continue
        if not kpsewhich:
            missing_dependencies.append(package)
            continue
        result = subprocess.run(
            [kpsewhich, package], text=True, capture_output=True, timeout=60, check=False
        )
        if result.returncode or not result.stdout.strip():
            missing_dependencies.append(package)
    fc_match = shutil.which("fc-match")
    for font in request.required_fonts:
        if not fc_match:
            missing_dependencies.append(f"font:{font}")
            continue
        result = subprocess.run(
            [fc_match, "-f", "%{family}", font], text=True,
            capture_output=True, timeout=60, check=False,
        )
        families = {value.strip().casefold() for value in result.stdout.split(",") if value.strip()}
        if result.returncode or font.casefold() not in families:
            missing_dependencies.append(f"font:{font}")
    if missing_dependencies:
        raise CompileFailure("MISSING_DEPENDENCY", ", ".join(missing_dependencies))
    output_root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    deadline = started + request.timeout_seconds
    documents: dict[str, Any] = {}
    for document in request.documents:
        safe_relative_name(document.source, "source")
        source = source_root / document.source
        if not source.is_file():
            raise CompileFailure("INVALID_REQUEST", f"missing TeX source: {document.source}")
        compiled_pdf = source_root / f"{source.stem}.pdf"
        log_path = source_root / f"{source.stem}.log"
        combined_log: list[str] = []
        for pass_number in range(1, document.passes + 1):
            result = run([
                xelatex, "-no-shell-escape", "-halt-on-error", "-file-line-error",
                "-interaction=nonstopmode", "-output-directory", str(source_root), str(source),
            ], source_root, deadline)
            combined_log.append(f"pass {pass_number}\n{result.stdout}\n{result.stderr}")
            if result.returncode:
                detail = (result.stderr.strip() or result.stdout.strip())[-4000:]
                raise CompileFailure("COMPILE_ERROR", detail or f"XeLaTeX failed for {document.source}")
        if not compiled_pdf.is_file():
            raise CompileFailure("COMPILE_ERROR", f"XeLaTeX did not create {compiled_pdf.name}")
        output_pdf = output_root / document.output
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(compiled_pdf, output_pdf)
        output_log = output_root / f"{Path(document.output).stem}.log"
        output_log.write_text(
            "\n".join(combined_log) + ("\n\nengine log\n" + log_path.read_text(errors="replace") if log_path.is_file() else ""),
            encoding="utf-8",
        )
        info = run([pdfinfo, str(output_pdf)], output_root, deadline)
        pages_match = re.search(r"^Pages:\s+(\d+)$", info.stdout, re.MULTILINE)
        if info.returncode or not pages_match:
            raise CompileFailure("QUALITY_ERROR", f"could not determine page count for {document.output}")
        pages = int(pages_match.group(1))
        if pages < 1 or pages > document.max_pages:
            raise CompileFailure(
                "QUALITY_ERROR",
                f"{document.output} must contain 1-{document.max_pages} pages; rendered {pages}",
            )
        normalized = run([pdftotext, str(output_pdf), "-"], output_root, deadline)
        normalized_text = " ".join(normalized.stdout.split())
        if normalized.returncode or not normalized_text:
            raise CompileFailure("QUALITY_ERROR", f"{document.output} has no extractable text")
        normalized_name = f"{Path(document.output).stem}.txt"
        (output_root / normalized_name).write_text(normalized_text + "\n", encoding="utf-8")
        raw_name = None
        if document.extract_raw_text:
            raw = run([pdftotext, "-raw", str(output_pdf), "-"], output_root, deadline)
            if raw.returncode:
                raise CompileFailure("QUALITY_ERROR", f"could not extract raw text from {document.output}")
            raw_name = f"{Path(document.output).stem}.raw.txt"
            (output_root / raw_name).write_text(raw.stdout, encoding="utf-8")
        documents[document.output] = {
            "pages": pages,
            "text_chars": len(normalized_text),
            "sha256": sha256(output_pdf),
            "bytes": output_pdf.stat().st_size,
            "normalized_text": normalized_name,
            "normalized_text_sha256": hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
            "raw_text": raw_name,
            "log": output_log.name,
        }
    result_manifest = {
        "schema_version": 1,
        "request_id": request.request_id,
        "status": "SUCCEEDED",
        "engine": {
            "name": "xelatex",
            "version": tool_version([xelatex, "--version"]),
        },
        "documents": documents,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_root / "result.json").write_text(
        json.dumps(result_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result_manifest
