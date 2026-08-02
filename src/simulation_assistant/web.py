from __future__ import annotations

import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from simulation_assistant.storage import JobStore


JOB_PATH = re.compile(r"^/api/jobs/(\d+)$")


def serve_dashboard(database_path: str | Path, host: str, port: int) -> None:
    store = JobStore(database_path)
    store.initialize()

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            path = urlparse(self.path).path
            if path == "/":
                self._write(HTTPStatus.OK, DASHBOARD_HTML, "text/html; charset=utf-8")
                return
            if path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok"})
                return
            if path == "/api/jobs":
                self._json(
                    HTTPStatus.OK,
                    {
                        "counts": store.counts(),
                        "jobs": [job.to_dict() for job in store.list(limit=200)],
                    },
                )
                return
            match = JOB_PATH.match(path)
            if match:
                try:
                    job = store.get(int(match.group(1)))
                except KeyError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Job not found"})
                    return
                self._json(HTTPStatus.OK, job.to_dict())
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def log_message(self, format: str, *args: object) -> None:
            return None

        def _json(self, status: HTTPStatus, payload: object) -> None:
            self._write(
                status,
                json.dumps(payload, ensure_ascii=False),
                "application/json; charset=utf-8",
            )

        def _write(self, status: HTTPStatus, body: str, content_type: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Dashboard: http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Simulation Run Assistant</title>
  <style>
    :root { color-scheme: dark; --bg:#07111f; --panel:#0f1d2e; --line:#22344b;
      --text:#e7edf5; --muted:#91a4bd; --accent:#4fd1c5; }
    * { box-sizing: border-box; }
    body { margin:0; background:radial-gradient(circle at 80% 0,#12334b 0,transparent 35%),var(--bg);
      color:var(--text); font:15px/1.5 Inter,system-ui,sans-serif; }
    main { width:min(1120px,92vw); margin:54px auto; }
    header { display:flex; justify-content:space-between; align-items:end; gap:24px; margin-bottom:28px; }
    h1 { margin:0; font-size:clamp(28px,5vw,46px); letter-spacing:-.04em; }
    .eyebrow { color:var(--accent); font-weight:700; text-transform:uppercase; letter-spacing:.14em; }
    #updated { color:var(--muted); }
    .cards { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:22px; }
    .card { background:rgba(15,29,46,.88); border:1px solid var(--line); border-radius:14px; padding:18px; }
    .card b { display:block; font-size:30px; margin-top:5px; }
    .card span { color:var(--muted); text-transform:capitalize; }
    .table-wrap { overflow:auto; background:rgba(15,29,46,.9); border:1px solid var(--line); border-radius:16px; }
    table { width:100%; border-collapse:collapse; min-width:780px; }
    th,td { padding:14px 16px; text-align:left; border-bottom:1px solid var(--line); }
    th { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em; }
    tr:last-child td { border-bottom:0; }
    code { color:#c6f6d5; }
    .badge { display:inline-flex; padding:4px 9px; border-radius:999px; font-size:12px; font-weight:700; }
    .queued { background:#243449; } .running { background:#1f4a66; }
    .succeeded { background:#17483d; color:#9ff3d9; } .failed { background:#5a2530; color:#ffc0cb; }
    .empty { color:var(--muted); text-align:center; padding:42px; }
    @media(max-width:700px) { .cards { grid-template-columns:repeat(2,1fr); } header { align-items:start; flex-direction:column; } }
  </style>
</head>
<body><main>
  <header><div><div class="eyebrow">Local control plane</div><h1>Simulation runs</h1></div><div id="updated">Connecting…</div></header>
  <section class="cards" id="cards"></section>
  <section class="table-wrap"><table>
    <thead><tr><th>ID</th><th>Batch</th><th>Adapter</th><th>Status</th><th>Attempts</th><th>Created</th></tr></thead>
    <tbody id="jobs"><tr><td class="empty" colspan="6">No jobs yet.</td></tr></tbody>
  </table></section>
</main><script>
const order=['queued','running','succeeded','failed'];
const shortDate=value=>value ? new Date(value).toLocaleString() : '—';
async function refresh(){
  try {
    const response=await fetch('/api/jobs'); const data=await response.json();
    const cards=document.querySelector('#cards'); cards.replaceChildren();
    order.forEach(status=>{const card=document.createElement('div'); card.className='card';
      const label=document.createElement('span'); label.textContent=status;
      const value=document.createElement('b'); value.textContent=data.counts[status]||0;
      card.append(label,value); cards.append(card);});
    const tbody=document.querySelector('#jobs'); tbody.replaceChildren();
    if(!data.jobs.length){const row=tbody.insertRow(); const cell=row.insertCell(); cell.colSpan=6;
      cell.className='empty'; cell.textContent='No jobs yet. Enqueue a manifest from the CLI.';}
    data.jobs.forEach(job=>{const row=tbody.insertRow();
      [job.id,job.batch_name,job.adapter].forEach(value=>{const cell=row.insertCell(); cell.textContent=value;});
      const status=row.insertCell(); const badge=document.createElement('span');
      badge.className='badge '+job.status; badge.textContent=job.status; status.append(badge);
      row.insertCell().textContent=job.attempts; row.insertCell().textContent=shortDate(job.created_at);});
    document.querySelector('#updated').textContent='Updated '+new Date().toLocaleTimeString();
  } catch(error){ document.querySelector('#updated').textContent='Dashboard unavailable'; }
}
refresh(); setInterval(refresh,3000);
</script></body></html>"""
