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
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
  <title>Application Review</title>
  <style>
    :root{color-scheme:dark;font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#f8fafc}
    *{box-sizing:border-box}body{margin:0;background:#0f172a;-webkit-tap-highlight-color:transparent}
    main{max-width:760px;margin:auto;padding:12px 14px 110px}
    header{position:sticky;top:0;z-index:10;background:#0f172af0;backdrop-filter:blur(12px);border-bottom:1px solid #24344d;padding:10px 14px}
    .header-top{display:flex;justify-content:space-between;gap:8px;align-items:center}
    h1{font-size:17px;margin:0;font-weight:700;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .muted{color:#94a3b8;font-size:12px}
    .badge{font:11px ui-monospace,monospace;border:1px solid #334b70;border-radius:999px;padding:3px 8px;color:#7dd3fc;white-space:nowrap}
    .nav-pills{display:flex;gap:6px;margin-top:8px;overflow-x:auto;padding-bottom:2px}
    .nav-pill{background:#1e293b;border:1px solid #334155;color:#f1f5f9;border-radius:8px;padding:6px 12px;font-size:12px;font-weight:600;display:inline-flex;align-items:center;gap:5px;cursor:pointer;white-space:nowrap;text-decoration:none}
    .nav-pill:active{background:#334155}
    .nav-pill.primary{background:#1d4ed8;border-color:#2563eb}
    .card{background:#172338;border:1px solid #263857;border-radius:12px;padding:14px;margin-top:12px}
    .row{display:flex;justify-content:space-between;gap:10px;align-items:center}
    .status{margin-top:5px;color:#94a3b8;font-size:12px}
    .field{background:#111c33;border:1px solid #263857;border-radius:10px;padding:12px;margin-top:10px}
    .field-header{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:6px}
    .field-title{font-size:13px;font-weight:600;color:#e2e8f0;display:flex;align-items:center;gap:6px}
    .field-actions{display:flex;align-items:center;gap:6px}
    .source{font-size:10px;border-radius:4px;padding:1px 5px;font-weight:600;text-transform:uppercase}
    .source.profile{background:#064e3b;color:#a7f3d0}
    .source.resume{background:#0c4a6e;color:#7dd3fc}
    .source.user{background:#581c87;color:#e9d5ff}
    .source.ai{background:#713f12;color:#fde047}
    .copy-btn{background:transparent;border:1px solid #334155;color:#94a3b8;border-radius:6px;padding:3px 7px;font-size:11px;cursor:pointer}
    .copy-btn:active{background:#334155;color:white}
    input,textarea,select{width:100%;border:1px solid #334b70;border-radius:8px;background:#0b1324;color:#f8fafc;padding:10px 12px;font:inherit;font-size:14px}
    textarea{min-height:85px;resize:vertical}
    button{border:0;border-radius:10px;padding:12px 16px;font-weight:700;color:white;cursor:pointer;font-size:14px}
    button:disabled{opacity:.4;cursor:not-allowed}
    .danger{background:#991b1b}.danger:active{background:#b91c1c}
    .good{background:#059669}.good:active{background:#10b981}
    .secondary{background:#334155}.secondary:active{background:#475569}
    .actions{position:fixed;bottom:0;left:0;right:0;background:#0f172af2;backdrop-filter:blur(12px);border-top:1px solid #24344d;padding:10px 14px;z-index:10}
    .actions>div{max-width:760px;margin:auto;display:flex;gap:8px}
    .actions button{flex:1;min-height:46px}
    #login{max-width:400px;margin:18vh auto;padding:20px}
    .error{color:#f87171;font-size:13px;margin-top:8px}
    .hidden{display:none!important}
    /* Modal styles */
    .modal-overlay{position:fixed;inset:0;background:#000000cc;backdrop-filter:blur(8px);z-index:100;display:flex;flex-direction:column}
    .modal-header{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #263857;background:#0f172a}
    .modal-content{flex:1;overflow:auto;display:flex;justify-content:center;align-items:center;padding:10px}
    .modal-content img{max-width:100%;max-height:100%;border-radius:8px;object-fit:contain;border:1px solid #334b70}
    .modal-content iframe{width:100%;height:100%;border:0;background:#fff;border-radius:8px}
    .close-btn{background:#334155;border:0;color:white;border-radius:8px;padding:6px 12px;font-size:13px;font-weight:600}
  </style>
</head>
<body>
  <section id="login" class="card">
    <h1 style="font-size:19px;margin-bottom:6px">Private Application Review</h1>
    <p class="muted">Enter the review token printed by your computer to review on mobile.</p>
    <input id="token" type="password" autocomplete="current-password" placeholder="Review token (e.g. demo123)">
    <button id="loginButton" class="good" style="width:100%;margin-top:12px">Connect</button>
    <div id="loginError" class="error"></div>
  </section>

  <div id="app" class="hidden">
    <header>
      <div class="header-top">
        <div style="min-width:0">
          <h1 id="job">Application review</h1>
          <div id="company" class="muted"></div>
        </div>
        <span id="state" class="badge">CONNECTING</span>
      </div>
      <div class="nav-pills">
        <button class="nav-pill primary" id="btnScreenshot">📸 Live Browser</button>
        <button class="nav-pill" id="btnResume">📄 Resume</button>
        <button class="nav-pill" id="btnLetter">✉️ Motivation Letter</button>
      </div>
      <div id="status" class="status"></div>
    </header>

    <main>
      <div id="blocker" class="card hidden" style="border-color:#b91c1c;background:#450a0a"></div>
      <div id="fields"></div>
      <div class="card" style="margin-top:16px">
        <div class="row"><span class="muted">Documents Attached</span><span id="revision" class="badge"></span></div>
        <p style="margin:8px 0 0"><a id="resumeLink" class="muted" target="_blank">Resume</a> · <a id="letterLink" class="muted" target="_blank">Motivation Letter</a></p>
        <div id="hash" class="muted" style="margin-top:4px;font-size:11px"></div>
      </div>
    </main>

    <div class="actions">
      <div>
        <button id="skip" class="danger">Skip</button>
        <button id="approve" class="good">Approve step</button>
        <button id="resumeButton" class="secondary hidden">Resume</button>
      </div>
    </div>
  </div>

  <!-- Modal for Live Screenshot and PDF viewing -->
  <div id="viewerModal" class="modal-overlay hidden">
    <div class="modal-header">
      <span id="modalTitle" style="font-weight:700;font-size:15px">Live View</span>
      <div style="display:flex;gap:8px">
        <button id="modalRefresh" class="secondary" style="padding:6px 12px;font-size:12px">🔄 Refresh</button>
        <button id="modalClose" class="close-btn">✕ Close</button>
      </div>
    </div>
    <div id="modalBody" class="modal-content"></div>
  </div>

<script>
let snapshot=null, token=localStorage.getItem('jaa_review_token')||'';
const $=id=>document.getElementById(id);
function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function authHeaders(){return token?{'Authorization':'Bearer '+token,'Content-Type':'application/json'}:{'Content-Type':'application/json'};}
async function api(path,opts={}){let r=await fetch(path,{...opts,headers:{...authHeaders(),...(opts.headers||{})}});let d=await r.json().catch(()=>({}));if(!r.ok)throw Object.assign(new Error(d.error||r.statusText),{status:r.status,data:d});return d;}

function openModal(title, contentHtml, showRefresh=false, refreshAction=null){
  $('modalTitle').textContent = title;
  $('modalBody').innerHTML = contentHtml;
  $('viewerModal').classList.remove('hidden');
  $('modalRefresh').classList.toggle('hidden', !showRefresh);
  $('modalRefresh').onclick = refreshAction;
}
function closeModal(){
  $('viewerModal').classList.add('hidden');
  $('modalBody').innerHTML = '';
}
$('modalClose').onclick = closeModal;

async function showScreenshot(){
  let url = '/api/session/screenshot?t=' + Date.now();
  openModal('📸 Live Browser Screenshot', `<img src="${url}" alt="Browser Screenshot">`, true, showScreenshot);
}
function showPdf(type){
  let endpoint = type === 'resume' ? '/api/files/resume' : '/api/files/letter';
  let url = endpoint + '?token=' + encodeURIComponent(token);
  // Open directly in a new tab or trigger native PDF viewer
  window.open(url, '_blank');
}

function copyValue(val, btn){
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(String(val||'')).then(()=>{
      let orig = btn.textContent;
      btn.textContent = '✓ Copied';
      btn.style.color = '#34d399';
      setTimeout(()=>{btn.textContent = orig;btn.style.color = '';}, 1500);
    });
  }
}

function render(d){
  snapshot=d;
  $('login').classList.add('hidden');
  $('app').classList.remove('hidden');
  $('job').textContent=d.job_title||'Application review';
  $('company').textContent=d.company||'';
  $('state').textContent=d.state||'';
  $('status').textContent=`Step ${d.step_index||1} · ${d.page_url||d.target_url||''}`;
  $('revision').textContent='Revision '+(d.revision||1);
  $('hash').textContent=d.draft_hash||'';

  let qToken = token ? '?token=' + encodeURIComponent(token) : '';
  $('resumeLink').href='/api/files/resume' + qToken;
  $('letterLink').href='/api/files/letter' + qToken;
  $('btnLetter').classList.toggle('hidden',!d.letter_path && !(d.letter_name));
  $('letterLink').classList.toggle('hidden',!d.letter_path && !(d.letter_name));
  $('resumeLink').textContent=d.resume_name||'Resume';
  $('letterLink').textContent=d.letter_name||'Motivation letter';

  const blocker=$('blocker');
  blocker.classList.toggle('hidden',!d.blocker);
  blocker.textContent=d.blocker?'⚠️ Blocked: '+d.blocker:'';

  const c=$('fields');
  c.innerHTML='';
  (d.fields||[]).forEach(f=>{
    if(f.type==='file')return;
    let el=document.createElement('div');
    el.className='field';
    let cls=f.source||'';
    let fieldKey = f.id||f.label;

    let header = document.createElement('div');
    header.className = 'field-header';
    header.innerHTML = `
      <div class="field-title">${esc(f.label)}${f.required?' <span style="color:#f87171">*</span>':''}</div>
      <div class="field-actions">
        <span class="source ${cls}">${esc(f.source||'unknown')}</span>
        <button type="button" class="copy-btn" data-copy="${esc(fieldKey)}">📋 Copy</button>
      </div>
    `;
    el.appendChild(header);

    let control;
    if(f.type==='textarea'){
      control=document.createElement('textarea');
    } else if(f.type==='select'){
      control=document.createElement('select');
      (f.options||[]).forEach(o=>{
        let opt=document.createElement('option');
        opt.textContent=o;
        opt.value=o;
        control.appendChild(opt);
      });
    } else {
      control=document.createElement('input');
      control.type=f.type==='number'?'number':'text';
    }
    control.value=f.value??'';
    control.dataset.id=fieldKey;
    control.addEventListener('change',()=>{
      f.value=control.value;
      f.source='user';
    });
    el.appendChild(control);

    let copyBtn = header.querySelector('.copy-btn');
    copyBtn.onclick = () => copyValue(control.value, copyBtn);

    c.appendChild(el);
  });

  const waiting=d.state==='REVIEW_READY'||d.state==='USER_EDITING';
  $('approve').disabled=!waiting;
  $('skip').disabled=['SKIPPED','SUBMITTED_CONFIRMED'].includes(d.state);
  $('resumeButton').classList.toggle('hidden',d.state!=='BLOCKED');
}

async function refresh(){
  try{
    render(await api('/api/session'));
  }catch(e){
    if(e.status===401){
      $('app').classList.add('hidden');
      $('login').classList.remove('hidden');
    } else console.error(e);
  }
}

async function login(){
  let value=$('token').value.trim();
  if(!value)return;
  $('loginError').textContent='';
  try{
    token=value;
    localStorage.setItem('jaa_review_token',token);
    render(await api('/api/auth',{method:'POST',body:JSON.stringify({token})}));
    startEvents();
  }catch(e){
    localStorage.removeItem('jaa_review_token');
    token='';
    $('loginError').textContent=e.message;
  }
}

async function approve(){
  let updates={};
  document.querySelectorAll('[data-id]').forEach(el=>{updates[el.dataset.id]=el.value;});
  let changed={};
  (snapshot.fields||[]).forEach(f=>{
    let key=f.id||f.label;
    if(Object.prototype.hasOwnProperty.call(updates,key)&&String(updates[key])!==String(f.value??''))changed[key]=updates[key];
  });
  try{
    if(Object.keys(changed).length){
      render(await api('/api/session/fields',{method:'PATCH',body:JSON.stringify({revision:snapshot.revision,fields:changed})}));
    }
    let d=await api('/api/session/approve-step',{method:'POST',body:JSON.stringify({revision:snapshot.revision,hash:snapshot.draft_hash})});
    render(d);
  }catch(e){
    alert(e.message);
    refresh();
  }
}

async function skip(){
  if(!confirm('Skip this application and preserve its checkpoint?'))return;
  try{
    render(await api('/api/session/skip',{method:'POST',body:JSON.stringify({revision:snapshot.revision})}));
  }catch(e){alert(e.message);}
}

async function resume(){
  try{render(await api('/api/session/resume',{method:'POST'}));}catch(e){alert(e.message);}
}

function startEvents(){
  if(!window.EventSource)return;
  let es=new EventSource('/api/events');
  es.onmessage=()=>refresh();
  es.onerror=()=>{es.close();setTimeout(startEvents,3000);};
}

$('loginButton').onclick=login;
$('token').onkeydown=e=>{if(e.key==='Enter')login();};
$('approve').onclick=approve;
$('skip').onclick=skip;
$('resumeButton').onclick=resume;
$('btnScreenshot').onclick=showScreenshot;
$('btnResume').onclick=()=>showPdf('resume');
$('btnLetter').onclick=()=>showPdf('letter');

if(token)refresh().then(startEvents);
else $('login').classList.remove('hidden');
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
                parsed = urlparse(self.path)
                query_token = parse_qs(parsed.query).get("token", [""])[0]
                return (
                    secrets.compare_digest(header.removeprefix("Bearer ").strip(), owner.token)
                    or f"review_token={owner.token}" in cookie
                    or (bool(query_token) and secrets.compare_digest(query_token, owner.token))
                )

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
                if path == "/api/session/screenshot":
                    try:
                        img_bytes = owner.session.take_screenshot()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Content-Length", str(len(img_bytes)))
                        self.end_headers()
                        self.wfile.write(img_bytes)
                    except Exception as exc:
                        self._json(500, {"error": str(exc)})
                    return
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
