#!/usr/bin/env python3
"""Interactive Draft Review CLI & Web Review Server with Embedded PDF Previews and Auto-Shutdown Lifecycle."""

from __future__ import annotations

import argparse
import html
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse
import webbrowser

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if __name__ == "__main__" and VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_application_agents.auto_apply.draft_models import ApplicationDraft, ApprovalToken, FieldSource


def render_terminal_draft(draft: ApplicationDraft) -> None:
    print(f"\n=======================================================")
    print(f"📄 APPLICATION DRAFT (Revision {draft.revision})")
    print(f"=======================================================")
    print(f"Company:     {draft.company}")
    print(f"Role:        {draft.job_title}")
    print(f"Target URL:  {draft.target_url}")
    print(f"Draft Hash:  {draft.draft_hash}")
    print(f"Resume:      file://{draft.resume_path}")
    if draft.letter_path:
        print(f"Letter:      file://{draft.letter_path}")
    print(f"State:       {draft.state.value}\n")

    print("--- Form Fields & Attribution ---")
    for idx, f in enumerate(draft.fields, 1):
        icon = "✓" if f.source == FieldSource.PROFILE else ("✎" if f.source == FieldSource.RESUME else ("⚠" if f.source == FieldSource.AI else "✏"))
        src_label = f"[{f.source.value.upper()}]"
        print(f"[{idx:02d}] {icon} {f.label:<35} = {str(f.value):<30} {src_label}")
    print("-------------------------------------------------------\n")


def generate_html_review_ui(draft: ApplicationDraft, approval_nonce: str = "") -> str:
    fields_html = ""
    for f in draft.fields:
        safe_label = html.escape(f.label, quote=True)
        safe_value = html.escape(str(f.value), quote=True)
        safe_id = html.escape(f.id or f.label, quote=True)
        badge_color = "#10b981" if f.source == FieldSource.PROFILE else ("#3b82f6" if f.source == FieldSource.RESUME else ("#f59e0b" if f.source == FieldSource.AI else "#8b5cf6"))
        icon = "✓ Known" if f.source == FieldSource.PROFILE else ("✎ Derived" if f.source == FieldSource.RESUME else ("⚠ AI Generated" if f.source == FieldSource.AI else "✏ User Edited"))

        fields_html += f"""
        <div style="background:#1e293b; padding:12px; margin-bottom:10px; border-radius:8px; border:1px solid #334155;">
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
            <label style="font-weight:600; color:#e2e8f0; font-size:13px;">{safe_label}</label>
                <span style="background:{badge_color}; color:#fff; font-size:10px; padding:2px 8px; border-radius:12px; font-weight:600;">{icon}</span>
            </div>
            <input type="text" name="{safe_id}" value="{safe_value}" style="width:100%; box-sizing:border-box; padding:8px 12px; background:#0f172a; border:1px solid #475569; color:#f8fafc; border-radius:6px; font-size:14px;" />
        </div>
        """

    has_letter = draft.letter_path and Path(draft.letter_path).is_file()

    safe_company = html.escape(draft.company, quote=True)
    safe_job_title = html.escape(draft.job_title, quote=True)
    safe_target_url = html.escape(draft.target_url, quote=True)
    safe_nonce = html.escape(approval_nonce, quote=True)
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Application Review: {draft.company} - {draft.job_title}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#0f172a; color:#f8fafc; margin:0; padding:16px; height:100vh; display:flex; flex-direction:column; }}
        .header {{ background:#1e293b; border-radius:12px; padding:16px 20px; margin-bottom:16px; border:1px solid #334155; display:flex; justify-content:space-between; align-items:center; }}
        .layout {{ display:grid; grid-template-columns: 1fr 1fr; gap:16px; flex:1; min-height:0; }}
        .panel {{ background:#1e293b; border-radius:12px; border:1px solid #334155; display:flex; flex-direction:column; overflow:hidden; }}
        .panel-header {{ padding:12px 16px; background:#0f172a; border-bottom:1px solid #334155; display:flex; justify-content:space-between; align-items:center; }}
        .panel-body {{ padding:16px; overflow-y:auto; flex:1; }}
        .btn {{ padding:10px 16px; border-radius:8px; font-weight:600; border:none; cursor:pointer; font-size:14px; transition:all 0.2s; }}
        .btn-tab {{ background:#334155; color:#cbd5e1; font-size:12px; padding:6px 12px; }}
        .btn-tab.active {{ background:#38bdf8; color:#0f172a; }}
        .btn-approve {{ background:#22c55e; color:#fff; width:100%; padding:14px; font-size:15px; margin-top:12px; }}
        .btn-approve:hover {{ background:#16a34a; }}
        .btn-reject {{ background:#dc2626; color:#fff; width:100%; padding:10px; font-size:13px; margin-top:8px; }}
        iframe {{ width:100%; height:100%; border:none; background:#fff; }}
        @media (max-width: 900px) {{
            .layout {{ grid-template-columns: 1fr; }}
            body {{ height:auto; }}
            .panel {{ height:600px; margin-bottom:16px; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h2 style="margin:0; font-size:18px; color:#38bdf8;">{safe_job_title}</h2>
            <div style="color:#94a3b8; font-size:13px; margin-top:4px;">{safe_company} &bull; Revision {draft.revision} &bull; <a href="{safe_target_url}" target="_blank" rel="noopener noreferrer" style="color:#38bdf8; text-decoration:none;">Open Portal ↗</a></div>
        </div>
        <div style="font-family:monospace; font-size:11px; color:#64748b; text-align:right;">
            <div>Status: <span style="color:#38bdf8; font-weight:bold;">{draft.state.value}</span></div>
            <div>{draft.draft_hash[:24]}...</div>
        </div>
    </div>

    <div class="layout">
        <!-- PDF Viewer Panel -->
        <div class="panel">
            <div class="panel-header">
                <span style="font-weight:600; font-size:13px;">📄 Tailored Documents</span>
                <div style="display:flex; gap:6px;">
                    <button class="btn btn-tab active" id="tabResume" onclick="showPDF('/pdf/resume', 'tabResume')">Resume.pdf</button>
                    {f'<button class="btn btn-tab" id="tabLetter" onclick="showPDF(\'/pdf/letter\', \'tabLetter\')">Motivation Letter.pdf</button>' if has_letter else ''}
                </div>
            </div>
            <div style="flex:1; background:#0f172a; position:relative;">
                <iframe id="pdfFrame" src="/pdf/resume"></iframe>
            </div>
        </div>

        <!-- Form Fields Panel -->
        <div class="panel">
            <div class="panel-header">
                <span style="font-weight:600; font-size:13px;">📋 Form Fields & Answers</span>
                <span style="font-size:11px; color:#94a3b8;">Review & modify answers</span>
            </div>
            <div class="panel-body">
                <form method="POST" action="/approve">
                    <input type="hidden" name="approval_nonce" value="{safe_nonce}" />
                    {fields_html}
                    <button type="submit" class="btn btn-approve">✓ Approve for gated submission</button>
                </form>
                <form method="POST" action="/reject" onsubmit="return confirm('Are you sure you want to reject this draft?');">
                    <button type="submit" class="btn btn-reject">✕ Reject Application</button>
                </form>
            </div>
        </div>
    </div>

    <script>
        function showPDF(url, tabId) {{
            document.getElementById('pdfFrame').src = url;
            document.querySelectorAll('.btn-tab').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
        }}
    </script>
</body>
</html>
"""


from http.server import HTTPServer, BaseHTTPRequestHandler

def run_server(draft: ApplicationDraft, draft_path: Path, port: int, timeout_sec: int, open_browser: bool = False) -> None:
    approval_nonce = secrets.token_urlsafe(32)
    approval_consumed = False

    class ReviewHandler(BaseHTTPRequestHandler):

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path in ("", "/"):
                page_html = generate_html_review_ui(draft, approval_nonce)
                encoded = page_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            elif parsed.path == "/pdf/resume":
                resume_file = Path(draft.resume_path)
                if resume_file.is_file():
                    pdf_bytes = resume_file.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", f"inline; filename={resume_file.name}")
                    self.send_header("Content-Length", str(len(pdf_bytes)))
                    self.end_headers()
                    self.wfile.write(pdf_bytes)
                else:
                    self.send_error(404, "Resume PDF not found")

            elif parsed.path == "/pdf/letter":
                if draft.letter_path and Path(draft.letter_path).is_file():
                    letter_file = Path(draft.letter_path)
                    pdf_bytes = letter_file.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", f"inline; filename={letter_file.name}")
                    self.send_header("Content-Length", str(len(pdf_bytes)))
                    self.end_headers()
                    self.wfile.write(pdf_bytes)
                else:
                    self.send_error(404, "Motivation Letter PDF not found")
            else:
                self.send_error(404, "Not Found")

        def do_POST(self):
            nonlocal approval_consumed
            parsed = urlparse(self.path)
            if parsed.path == "/approve":
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length).decode("utf-8")
                form = parse_qs(body, keep_blank_values=True)
                submitted_nonce = (form.get("approval_nonce") or [""])[0]
                if approval_consumed or not secrets.compare_digest(submitted_nonce, approval_nonce):
                    self.send_error(403, "Invalid or already used approval token")
                    return
                approval_consumed = True
                token = ApprovalToken(
                    application_id=draft.application_id,
                    revision=draft.revision,
                    draft_hash=draft.draft_hash,
                )
                approval_path = draft_path.parent / "approval-token.json"
                approval_path.write_text(json.dumps(token.to_dict(), indent=2), encoding="utf-8")

                resp_html = b"""<!DOCTYPE html>
<html>
<body style="background:#0f172a; color:#f8fafc; font-family:sans-serif; display:flex; justify-content:center; align-items:center; height:90vh; text-align:center;">
    <div style="background:#1e293b; padding:32px; border-radius:16px; border:1px solid #334155; max-width:480px;">
        <h1 style="color:#22c55e; margin-top:0;">&#10003; Approved!</h1>
        <p style="color:#94a3b8;">Approval token recorded. Server shutting down cleanly.</p>
        <button onclick="window.close()" style="background:#334155; color:#fff; border:none; padding:8px 16px; border-radius:8px; cursor:pointer;">Close Window</button>
    </div>
</body>
</html>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(resp_html)))
                self.end_headers()
                self.wfile.write(resp_html)
                print(f"\n[✓] Approved! Token recorded at {approval_path}. Shutting down review server...")
                threading.Thread(target=server.shutdown).start()

            elif self.path == "/reject":
                resp_html = b"""<!DOCTYPE html>
<html>
<body style="background:#0f172a; color:#f8fafc; font-family:sans-serif; display:flex; justify-content:center; align-items:center; height:90vh; text-align:center;">
    <div style="background:#1e293b; padding:32px; border-radius:16px; border:1px solid #334155; max-width:480px;">
        <h1 style="color:#ef4444; margin-top:0;">&#10005; Rejected</h1>
        <p style="color:#94a3b8;">Application was rejected. Server shutting down.</p>
        <button onclick="window.close()" style="background:#334155; color:#fff; border:none; padding:8px 16px; border-radius:8px; cursor:pointer;">Close Window</button>
    </div>
</body>
</html>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(resp_html)))
                self.end_headers()
                self.wfile.write(resp_html)
                print("\n[✕] Application rejected. Shutting down review server...")
                threading.Thread(target=server.shutdown).start()

    server = HTTPServer(("127.0.0.1", port), ReviewHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"🚀 Live Web Review Server running at: {url}")
    print(f"⏱️ Inactivity Watchdog: Server will auto-shutdown after {timeout_sec}s of inactivity.")
    print("Press Ctrl+C to abort anytime.\n")

    # Inactivity watchdog timer
    timer = threading.Timer(timeout_sec, lambda: (print(f"\n[⏱️] Inactivity timeout ({timeout_sec}s) reached. Shutting down..."), server.shutdown()))
    timer.daemon = True
    timer.start()

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass


    try:
        server.serve_forever()
    finally:
        timer.cancel()
        server.server_close()
        print("Review server terminated cleanly. No background process left.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Review and approve application drafts with embedded PDF preview and auto-shutdown.")
    parser.add_argument("--draft-file", type=Path, help="Path to draft.json file")
    parser.add_argument("--app-dir", type=Path, help="Path to application directory")
    parser.add_argument("--web", action="store_true", help="Launch interactive web review server")
    parser.add_argument("--port", type=int, default=8765, help="Port for web review server (default: 8765)")
    parser.add_argument("--timeout", type=int, default=600, help="Inactivity timeout in seconds (default: 600s / 10 min)")

    args = parser.parse_args()

    draft_path = None
    if args.draft_file and args.draft_file.is_file():
        draft_path = args.draft_file
    elif args.app_dir and args.app_dir.is_dir():
        for candidate in [args.app_dir / "draft.json", args.app_dir / "v004" / "draft.json", args.app_dir / "v001" / "draft.json"]:
            if candidate.is_file():
                draft_path = candidate
                break

    if not draft_path or not draft_path.is_file():
        print("Error: draft.json not found.", file=sys.stderr)
        return 1

    draft = ApplicationDraft.from_dict(json.loads(draft_path.read_text(encoding="utf-8")))

    if args.web:
        run_server(draft=draft, draft_path=draft_path, port=args.port, timeout_sec=args.timeout)
    else:
        render_terminal_draft(draft)

    return 0


if __name__ == "__main__":
    sys.exit(main())
