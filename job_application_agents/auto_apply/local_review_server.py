"""Authenticated local HTTP/SSE review server for a PlaywrightReviewSession."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse

from .review_session import (
    PlaywrightReviewSession,
    ReviewBlockedError,
    ReviewConflictError,
    ReviewSessionError,
    public_snapshot,
)


REVIEW_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Application review</title>
  <style>
    :root{color-scheme:dark;font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#f8fafc}
    *{box-sizing:border-box}body{margin:0;background:#0f172a}main{max-width:760px;margin:auto;padding:16px 16px 100px}
    header{position:sticky;top:0;z-index:2;background:#111c33ee;backdrop-filter:blur(10px);border-bottom:1px solid #263653;padding:14px 16px}
    h1{font-size:19px;margin:0 0 3px}h2{font-size:16px;margin:0}.muted{color:#94a3b8;font-size:12px}
    .card{background:#172338;border:1px solid #2a3b5a;border-radius:12px;padding:14px;margin-top:12px}.row{display:flex;justify-content:space-between;gap:10px;align-items:center}
    .badge{font:11px ui-monospace,monospace;border:1px solid #395173;border-radius:999px;padding:3px 8px;color:#7dd3fc}.status{margin-top:9px;color:#cbd5e1;font-size:13px}
    .field{background:#111c33;border:1px solid #2a3b5a;border-radius:10px;padding:11px;margin-top:9px}.field label{display:flex;justify-content:space-between;gap:8px;font-size:13px;color:#cbd5e1;margin-bottom:6px}
    .source{font-size:10px;color:#a7f3d0}.source.ai{color:#fcd34d}.source.user{color:#d8b4fe}.source.resume{color:#7dd3fc}
    input,textarea,select{width:100%;border:1px solid #334b70;border-radius:8px;background:#0b1324;color:#f8fafc;padding:9px;font:inherit;font-size:14px}textarea{min-height:80px;resize:vertical}
    button{border:0;border-radius:9px;padding:10px 13px;font-weight:700;color:white;cursor:pointer;background:#2563eb}button:disabled{opacity:.5;cursor:wait}.danger{background:#7f1d1d}.good{background:#059669}.secondary{background:#334155}
    .actions{position:fixed;bottom:0;left:0;right:0;background:#111c33f2;border-top:1px solid #263653;padding:12px 16px}.actions>div{max-width:728px;margin:auto;display:flex;gap:8px}.actions button{flex:1}
    #login{max-width:420px;margin:18vh auto;padding:18px}.error{color:#fda4af;font-size:13px;margin-top:8px}.hidden{display:none!important}
  </style>
</head>
<body>
  <section id="login" class="card">
    <h1>Private application review</h1><p class="muted">Enter the review token printed by the computer.</p>
    <input id="token" type="password" autocomplete="current-password" placeholder="Review token">
    <button id="loginButton" style="width:100%;margin-top:10px">Connect</button><div id="loginError" class="error"></div>
  </section>
  <div id="app" class="hidden">
    <header><main style="padding:0"><div class="row"><div><h1 id="job">Application review</h1><div id="company" class="muted"></div></div><span id="state" class="badge">CONNECTING</span></div><div id="status" class="status"></div></main></header>
    <main><div id="fields"></div><div id="blocker" class="card hidden"></div><div class="card"><div class="row"><span class="muted">Documents</span><span id="revision" class="badge"></span></div><p><a id="resume" class="muted" target="_blank">Resume</a> · <a id="letter" class="muted" target="_blank">Motivation letter</a></p><div id="hash" class="muted"></div></div></main>
    <div class="actions"><div><button id="skip" class="danger">Skip</button><button id="approve" class="good">Approve step</button><button id="resumeButton" class="secondary hidden">Resume</button></div></div>
  </div>
<script>
let snapshot=null, token=localStorage.getItem('jaa_review_token')||'';
const $=id=>document.getElementById(id);
function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function authHeaders(){return token?{'Authorization':'Bearer '+token,'Content-Type':'application/json'}:{'Content-Type':'application/json'};}
async function api(path,opts={}){let r=await fetch(path,{...opts,headers:{...authHeaders(),...(opts.headers||{})}});let d=await r.json().catch(()=>({}));if(!r.ok)throw Object.assign(new Error(d.error||r.statusText),{status:r.status,data:d});return d;}
function render(d){snapshot=d;$('login').classList.add('hidden');$('app').classList.remove('hidden');$('job').textContent=d.job_title||'Application review';$('company').textContent=d.company||'';$('state').textContent=d.state||'';$('status').textContent=`Step ${d.step_index||1} · ${d.page_url||d.target_url||''}`;$('revision').textContent='Revision '+(d.revision||1);$('hash').textContent=d.draft_hash||'';
  $('resume').href='/api/files/resume';$('letter').href='/api/files/letter';$('letter').classList.toggle('hidden',!d.letter_path && !(d.letter_name));
  const blocker=$('blocker');blocker.classList.toggle('hidden',!d.blocker);blocker.textContent=d.blocker?'Blocked: '+d.blocker:'';
  $('resume').textContent=d.resume_name||'Resume';$('letter').textContent=d.letter_name||'Motivation letter';
  const c=$('fields');c.innerHTML='';(d.fields||[]).forEach(f=>{if(f.type==='file')return;let el=document.createElement('div');el.className='field';let cls=f.source||'';el.innerHTML=`<label><span>${esc(f.label)}${f.required?' *':''}</span><span class="source ${cls}">${esc(f.source||'unknown')}</span></label>`;let control;if(f.type==='textarea')control=document.createElement('textarea');else if(f.type==='select') {control=document.createElement('select');(f.options||[]).forEach(o=>{let opt=document.createElement('option');opt.textContent=o;opt.value=o;control.appendChild(opt);});}else {control=document.createElement('input');control.type=f.type==='number'?'number':'text';}control.value=f.value??'';control.dataset.id=f.id||f.label;control.addEventListener('change',()=>{f.value=control.value;f.source='user';});el.appendChild(control);c.appendChild(el);});
  const waiting=d.state==='REVIEW_READY'||d.state==='USER_EDITING';$('approve').disabled=!waiting;$('skip').disabled=['SKIPPED','SUBMITTED_CONFIRMED'].includes(d.state);$('resumeButton').classList.toggle('hidden',d.state!=='BLOCKED');}
async function refresh(){try{render(await api('/api/session'));}catch(e){if(e.status===401){$('app').classList.add('hidden');$('login').classList.remove('hidden');}else console.error(e);}}
async function login(){let value=$('token').value.trim();if(!value)return;$('loginError').textContent='';try{token=value;localStorage.setItem('jaa_review_token',token);render(await api('/api/auth',{method:'POST',body:JSON.stringify({token})}));startEvents();}catch(e){localStorage.removeItem('jaa_review_token');token='';$('loginError').textContent=e.message;}}
async function approve(){let updates={};document.querySelectorAll('[data-id]').forEach(el=>{updates[el.dataset.id]=el.value;});let changed={};(snapshot.fields||[]).forEach(f=>{let key=f.id||f.label;if(Object.prototype.hasOwnProperty.call(updates,key)&&String(updates[key])!==String(f.value??''))changed[key]=updates[key];});try{if(Object.keys(changed).length)render(await api('/api/session/fields',{method:'PATCH',body:JSON.stringify({revision:snapshot.revision,fields:changed})}));let d=await api('/api/session/approve-step',{method:'POST',body:JSON.stringify({revision:snapshot.revision,hash:snapshot.draft_hash})});render(d);}catch(e){alert(e.message);refresh();}}
async function skip(){if(!confirm('Skip this application and preserve its checkpoint?'))return;try{render(await api('/api/session/skip',{method:'POST',body:JSON.stringify({revision:snapshot.revision})}));}catch(e){alert(e.message);}}
async function resume(){try{render(await api('/api/session/resume',{method:'POST'}));}catch(e){alert(e.message);}}
function startEvents(){if(!window.EventSource)return;let es=new EventSource('/api/events');es.onmessage=()=>refresh();es.onerror=()=>{es.close();setTimeout(startEvents,3000);};}
$('loginButton').onclick=login;$('token').onkeydown=e=>{if(e.key==='Enter')login();};$('approve').onclick=approve;$('skip').onclick=skip;$('resumeButton').onclick=resume;if(token)refresh().then(startEvents);else $('login').classList.remove('hidden');
</script></body></html>'''


class LocalReviewServer:
    """Threaded local server with bearer-token auth and SSE change events."""

    def __init__(self, session: PlaywrightReviewSession, host: str = "127.0.0.1", port: int = 8765, token: str | None = None):
        self.session = session
        self.host = host
        self.port = port
        self.token = token or secrets.token_urlsafe(32)
        self._events = threading.Condition()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.session.on_change = self.notify

    def notify(self) -> None:
        with self._events:
            self._events.notify_all()

    def start(self) -> str:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "JAAReview/1.0"

            def log_message(self, *_args: Any) -> None:
                return

            def _authorized(self) -> bool:
                header = self.headers.get("Authorization", "")
                cookie = self.headers.get("Cookie", "")
                return secrets.compare_digest(header.removeprefix("Bearer ").strip(), owner.token) or f"review_token={owner.token}" in cookie

            def _json(self, status: int, payload: dict[str, Any], extra: dict[str, str] | None = None) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                if extra:
                    for key, value in extra.items(): self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers();self.wfile.write(body)

            def _body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                return json.loads(raw.decode("utf-8"))

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path == "/":
                    body = REVIEW_HTML.encode("utf-8")
                    self.send_response(200);self.send_header("Content-Type", "text/html; charset=utf-8");self.send_header("Cache-Control", "no-store");self.send_header("Content-Length", str(len(body)));self.end_headers();self.wfile.write(body);return
                if not self._authorized(): self._json(HTTPStatus.UNAUTHORIZED, {"error":"Authentication required"});return
                if path == "/api/session": self._json(200, public_snapshot(owner.session.snapshot()));return
                if path == "/api/events":
                    with owner._events:
                        owner._events.wait(timeout=20)
                    payload=json.dumps(public_snapshot(owner.session.snapshot())).encode("utf-8")
                    self.send_response(200);self.send_header("Content-Type","text/event-stream");self.send_header("Cache-Control","no-cache");self.send_header("Connection","keep-alive");self.send_header("Content-Length",str(len(payload)+8));self.end_headers();self.wfile.write(b"data: "+payload+b"\n\n");return
                if path in {"/api/files/resume", "/api/files/letter"}:
                    file_path = Path(owner.session.draft.resume_path if path.endswith("resume") else owner.session.draft.letter_path or "")
                    if not file_path.is_file(): self._json(404,{"error":"Document not found"});return
                    body=file_path.read_bytes();self.send_response(200);self.send_header("Content-Type","application/pdf");self.send_header("Content-Disposition",f"inline; filename={file_path.name}");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
                self._json(404,{"error":"Not found"})

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                if path == "/api/auth":
                    try: valid=secrets.compare_digest(str(self._body().get("token", "")), owner.token)
                    except Exception: valid=False
                    if valid: self._json(200,public_snapshot(owner.session.snapshot()),{"Set-Cookie":f"review_token={owner.token}; HttpOnly; SameSite=Strict; Path=/"})
                    else: self._json(401,{"error":"Invalid review token"})
                    return
                if not self._authorized(): self._json(401,{"error":"Authentication required"});return
                try:
                    body=self._body()
                    if path == "/api/session/approve-step": result=owner.session.approve_step(int(body["revision"]),str(body["hash"]))
                    elif path == "/api/session/skip": result=owner.session.skip(int(body["revision"]))
                    elif path == "/api/session/resume": result=owner.session.resume()
                    else: self._json(404,{"error":"Not found"});return
                    self._json(200,public_snapshot(result))
                except (ReviewConflictError, ReviewBlockedError) as exc: self._json(409 if isinstance(exc,ReviewConflictError) else 423,{"error":str(exc)})
                except (ReviewSessionError, KeyError, ValueError) as exc: self._json(400,{"error":str(exc)})

            def do_PATCH(self) -> None:
                if not self._authorized(): self._json(401,{"error":"Authentication required"});return
                if urlparse(self.path).path != "/api/session/fields": self._json(404,{"error":"Not found"});return
                try:
                    body=self._body();result=owner.session.update_fields(int(body["revision"],),dict(body["fields"]))
                    self._json(200,public_snapshot(result))
                except ReviewConflictError as exc: self._json(409,{"error":str(exc)})
                except (ReviewSessionError, KeyError, ValueError) as exc: self._json(400,{"error":str(exc)})

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="jaa-review-server", daemon=True)
        self._thread.start()
        return f"http://{self.host}:{self.port}/"

    def stop(self) -> None:
        if self._server:
            self._server.shutdown();self._server.server_close();self._server=None
