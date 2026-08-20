#!/usr/bin/env python3
"""Upload one application file to a Notion MCP file-upload URL.

Supports .pdf and .tex files. The upload URL and short-lived authorization
token are supplied by Notion's create-file-upload tool.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path("/home/falluba/Documents/job-search/applications").resolve()
ALLOWED_EXTENSIONS = {".pdf", ".tex"}
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".tex": "application/x-tex",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--upload-url", required=True)
    parser.add_argument("--authorization", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.file).expanduser().resolve()
    try:
        source.relative_to(ROOT)
    except ValueError:
        raise SystemExit(f"refusing file outside {ROOT}: {source}")
    if source.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise SystemExit(f"only {', '.join(sorted(ALLOWED_EXTENSIONS))} files are permitted")
    if not source.is_file():
        raise SystemExit(f"file does not exist: {source}")

    parsed = urllib.parse.urlparse(args.upload_url)
    if parsed.scheme != "https" or parsed.netloc != "api.notion.com":
        raise SystemExit("upload URL must target https://api.notion.com")
    if not parsed.path.startswith("/v1/mcp/file_uploads/") or not parsed.path.endswith("/send"):
        raise SystemExit("upload URL is not a Notion MCP file-upload endpoint")
    if not args.authorization.startswith("Bearer "):
        raise SystemExit("authorization must be a Bearer token")

    content_type = CONTENT_TYPES[source.suffix.lower()]
    boundary = "----codex-notion-upload-boundary"
    content = source.read_bytes()
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; '
        f'filename="{source.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        args.upload_url,
        data=prefix + content + suffix,
        headers={
            "Authorization": args.authorization,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
