#!/usr/bin/env python3
"""Apply a constrained Humanizer rewrite receipt to an application bundle."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any


TARGET_PATTERNS = (
    re.compile(r"^candidate\.summary\.text$"),
    re.compile(r"^motivation_letter\.paragraphs\.[0-9]+\.text$"),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def path_value(bundle: dict[str, Any], path: str) -> str:
    value: Any = bundle
    for part in path.split("."):
        if part.isdigit():
            if not isinstance(value, list):
                raise ValueError(f"invalid rewrite path: {path}")
            value = value[int(part)]
        else:
            if not isinstance(value, dict) or part not in value:
                raise ValueError(f"invalid rewrite path: {path}")
            value = value[part]
    if not isinstance(value, str):
        raise ValueError(f"rewrite target is not text: {path}")
    return value


def set_path_value(bundle: dict[str, Any], path: str, text: str) -> None:
    parts = path.split(".")
    value: Any = bundle
    for part in parts[:-1]:
        value = value[int(part)] if part.isdigit() else value[part]
    final = parts[-1]
    if final.isdigit():
        value[int(final)] = text
    else:
        value[final] = text


def without_targets(value: Any, path: str = "") -> Any:
    if any(pattern.fullmatch(path) for pattern in TARGET_PATTERNS):
        return "<HUMANIZED-TARGET>"
    if isinstance(value, dict):
        return {key: without_targets(item, f"{path}.{key}" if path else key) for key, item in value.items()}
    if isinstance(value, list):
        return [without_targets(item, f"{path}.{index}" if path else str(index)) for index, item in enumerate(value)]
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--rewrites", required=True, type=Path)
    parser.add_argument("--output-bundle", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    bundle_path = args.bundle.expanduser().resolve()
    rewrites_path = args.rewrites.expanduser().resolve()
    output_path = args.output_bundle.expanduser().resolve()
    receipt_path = args.receipt.expanduser().resolve()
    if output_path == bundle_path:
        raise ValueError("humanized output must be a new staging bundle")
    bundle = load_object(bundle_path)
    rewrites = load_object(rewrites_path)
    if rewrites.get("schema_version") != 1:
        raise ValueError("humanized-copy schema_version must be 1")
    if not isinstance(rewrites.get("humanizer_version"), str) or not rewrites["humanizer_version"].strip():
        raise ValueError("humanizer_version is required")
    if not isinstance(rewrites.get("humanizer_skill_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", rewrites["humanizer_skill_sha256"]):
        raise ValueError("humanizer_skill_sha256 must be a SHA-256 checksum")
    if rewrites.get("input_bundle_sha256") != digest(bundle_path):
        raise ValueError("rewrite receipt does not match the input bundle")
    entries = rewrites.get("rewrites")
    if not isinstance(entries, list) or not entries:
        raise ValueError("rewrites must be a non-empty array")

    result = copy.deepcopy(bundle)
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "before", "after"}:
            raise ValueError("each rewrite must contain path, before, and after")
        path = entry["path"]
        if not isinstance(path, str) or not any(pattern.fullmatch(path) for pattern in TARGET_PATTERNS):
            raise ValueError(f"rewrite path is not allowed: {path}")
        if path in seen:
            raise ValueError(f"duplicate rewrite path: {path}")
        seen.add(path)
        current = path_value(bundle, path)
        if entry["before"] != current:
            raise ValueError(f"rewrite before text does not match bundle: {path}")
        if not isinstance(entry["after"], str) or not entry["after"].strip():
            raise ValueError(f"rewrite after text must be non-empty: {path}")
        set_path_value(result, path, entry["after"])

    if without_targets(bundle) != without_targets(result):
        raise ValueError("humanized rewrite changed non-target bundle data")
    write_json(output_path, result)
    output_hash = digest(output_path)
    final_receipt = dict(rewrites)
    final_receipt["output_bundle_sha256"] = output_hash
    final_receipt["status"] = "accepted"
    write_json(receipt_path, final_receipt)
    print(json.dumps({"output_bundle": str(output_path), "output_bundle_sha256": output_hash}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
