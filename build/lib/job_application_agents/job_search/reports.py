"""Small, dependency-free application reporting primitives."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from typing import Any, Iterable

from .outcomes import normalize_status


def build_report(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(record) for record in records]
    statuses = Counter(normalize_status(row.get("status", "UNKNOWN")) for row in rows)
    sectors = Counter(str(row.get("sector") or "Unspecified") for row in rows)
    channels = Counter(str(row.get("channel") or row.get("source") or "Unspecified") for row in rows)
    reached_interview = sum(
        1 for row in rows
        if normalize_status(row.get("status", "")) in {"INTERVIEW", "FINAL_INTERVIEW", "OFFER", "HIRED"}
        or bool(row.get("interview_stages"))
    )
    submitted = sum(1 for row in rows if normalize_status(row.get("status", "")) not in {"TO_APPLY", "DRAFTED", "UNKNOWN"})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_records": len(rows),
        "submitted_records": submitted,
        "drafted_records": statuses.get("TO_APPLY", 0) + statuses.get("DRAFTED", 0),
        "interview_records": reached_interview,
        "interview_rate": round(reached_interview / submitted * 100, 1) if submitted else 0.0,
        "status": dict(sorted(statuses.items())),
        "sector": dict(sorted(sectors.items())),
        "channel": dict(sorted(channels.items())),
        "records": rows,
    }


def render_html_report(report: dict[str, Any], output: Path) -> Path:
    """Render a safe, self-contained HTML report and return its path."""
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = report.get("records", [])
    table = "\n".join(
        "<tr>" + "".join(
            f"<td>{escape(str(row.get(key, '')))}</td>"
            for key in ("company", "role", "status", "match_score", "generated_at", "next_action_at")
        ) + "</tr>"
        for row in rows
    )
    cards = "".join(
        f"<li><strong>{escape(str(key))}</strong>: {escape(str(value))}</li>"
        for key, value in (
            ("Total", report.get("total_records", 0)),
            ("Submitted", report.get("submitted_records", 0)),
            ("Interviews", report.get("interview_records", 0)),
            ("Interview rate", f"{report.get('interview_rate', 0)}%"),
        )
    )
    html = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Job application report</title>
<style>body{{font:16px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#202124}}ul{{display:flex;gap:2rem;list-style:none;padding:0;flex-wrap:wrap}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:.5rem;text-align:left}}th{{background:#f4f4f4}}</style>
<h1>Job application report</h1><p>Generated {escape(str(report.get('generated_at', '')))}</p>
<ul>{cards}</ul><h2>Applications</h2>
<table><thead><tr><th>Company</th><th>Role</th><th>Status</th><th>Score</th><th>Generated</th><th>Next action</th></tr></thead><tbody>{table}</tbody></table>
</html>"""
    output.write_text(html, encoding="utf-8")
    return output
