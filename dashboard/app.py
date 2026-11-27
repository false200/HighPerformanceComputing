from __future__ import annotations

"""Live gateway fabric dashboard — topology + jobs (Packet Tracer–style)."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template_string

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from protocol.messages import MessageType, decode, encode, make

app = Flask(__name__)
MASTER = ("127.0.0.1", 9100)
JOIN_TOKEN = ""

PAGE = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>HPC Grid Fabric</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet"/>
  <style>
    :root {
      --ink: #132033;
      --paper: #d9e3ee;
      --panel: #f4f7fb;
      --line: #8aa0b8;
      --hub: #c45c26;
      --campus: #1f7a6c;
      --cloud: #3b6ea5;
      --pulse: #e8b84a;
      --danger: #b33a3a;
      --muted: #5c6f84;
      --ok: #1f7a6c;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      font-family: Outfit, system-ui, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 8%, #eef4fa 0%, transparent 42%),
        linear-gradient(180deg, #cfdceb 0%, var(--paper) 55%, #c5d3e3 100%);
      overflow: hidden;
    }
    .shell {
      display: grid;
      grid-template-columns: 1fr 340px;
      grid-template-rows: auto 1fr;
      height: 100%;
      gap: 0;
    }
    header {
      grid-column: 1 / -1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.85rem 1.25rem;
      border-bottom: 1px solid #a9bbcf;
      background: rgba(244,247,251,0.88);
      backdrop-filter: blur(8px);
    }
    header h1 {
      margin: 0;
      font-size: 1.15rem;
      font-weight: 650;
      letter-spacing: -0.02em;
    }
    header .sub {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.72rem;
      color: var(--muted);
      margin-top: 0.15rem;
    }
    .pills { display: flex; gap: 0.5rem; flex-wrap: wrap; justify-content: flex-end; }
    .pill {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.7rem;
      padding: 0.35rem 0.65rem;
      border: 1px solid #9eb2c8;
      background: #fff;
      border-radius: 999px;
    }
    .pill strong { color: var(--hub); }
    .pill.ok strong { color: var(--ok); }
    .stage {
      position: relative;
      min-height: 0;
      border-right: 1px solid #a9bbcf;
    }
    #topo {
      width: 100%;
      height: 100%;
      display: block;
      cursor: grab;
    }
    #topo:active { cursor: grabbing; }
    .hint {
      position: absolute;
      left: 1rem;
      bottom: 1rem;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.68rem;
      color: var(--muted);
      background: rgba(244,247,251,0.9);
      border: 1px solid #b7c7d8;
      padding: 0.45rem 0.65rem;
      border-radius: 8px;
      pointer-events: none;
    }
    aside {
      min-height: 0;
      overflow: auto;
      background: var(--panel);
      padding: 1rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }
    .card {
      background: #fff;
      border: 1px solid #b8c8d9;
      border-radius: 12px;
      padding: 0.85rem 0.95rem;
      box-shadow: 0 1px 0 rgba(19,32,51,0.04);
    }
    .card h2 {
      margin: 0 0 0.65rem;
      font-size: 0.78rem;
      font-weight: 650;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .statrow {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.5rem;
    }
    .stat {
      background: #eef3f8;
      border-radius: 8px;
      padding: 0.55rem 0.65rem;
    }
    .stat .n {
      font-family: "IBM Plex Mono", monospace;
      font-size: 1.25rem;
      font-weight: 600;
      line-height: 1.1;
    }
    .stat .l { font-size: 0.7rem; color: var(--muted); margin-top: 0.15rem; }
    .job {
      border: 1px solid #c5d2e1;
      border-radius: 10px;
      padding: 0.65rem 0.7rem;
      margin-bottom: 0.55rem;
      background: #fbfcfe;
    }
    .job.active { border-color: var(--hub); box-shadow: inset 3px 0 0 var(--hub); }
    .job .id {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.72rem;
      font-weight: 600;
    }
    .job .meta {
      font-size: 0.72rem;
      color: var(--muted);
      margin-top: 0.2rem;
    }
    .bar {
      height: 7px;
      background: #d7e1ec;
      border-radius: 99px;
      overflow: hidden;
      margin-top: 0.45rem;
    }
    .bar > i {
      display: block;
      height: 100%;
      background: linear-gradient(90deg, var(--campus), #2fa894);
      width: 0%;
      transition: width 0.4s ease;
    }
    .bar > i.fail { background: var(--danger); }
    .wlist { list-style: none; margin: 0; padding: 0; }
    .wlist li {
      display: grid;
      grid-template-columns: 10px 1fr auto;
      gap: 0.5rem;
      align-items: center;
      padding: 0.45rem 0;
      border-bottom: 1px dashed #d0dbe8;
      font-size: 0.8rem;
    }
    .wlist li:last-child { border-bottom: 0; }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--campus); }
    .dot.cloud { background: var(--cloud); }
    .dot.paused { background: #9aa8b8; }
    .dot.busy { box-shadow: 0 0 0 3px rgba(232,184,74,0.45); }
    .wid { font-family: "IBM Plex Mono", monospace; font-size: 0.68rem; }
    .err {
      color: var(--danger);
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.75rem;
      white-space: pre-wrap;
    }
    @media (max-width: 900px) {
      .shell { grid-template-columns: 1fr; grid-template-rows: auto 48vh 1fr; }
      .stage { border-right: 0; border-bottom: 1px solid #a9bbcf; }
    }
    @media (prefers-reduced-motion: reduce) {
      .bar > i { transition: none; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>HPC Grid Fabric</h1>
        <div class="sub" id="subtitle">gateway topology · live</div>
      </div>
      <div class="pills">
        <div class="pill ok">workers <strong id="p-workers">—</strong></div>
        <div class="pill">campus <strong id="p-campus">—</strong></div>
        <div class="pill">cloud <strong id="p-cloud">—</strong></div>
        <div class="pill">queue <strong id="p-queue">—</strong></div>
        <div class="pill">updated <strong id="p-ago">—</strong></div>
      </div>
    </header>
    <section class="stage">
      <canvas id="topo"></canvas>
      <div class="hint">center = AWS gateway · teal = campus · blue = cloud · dashed pulse = active traffic</div>
    </section>
    <aside>
      <div class="card">
        <h2>Gateway</h2>
        <div class="statrow">
          <div class="stat"><div class="n" id="g-pending">0</div><div class="l">pending tasks</div></div>
          <div class="stat"><div class="n" id="g-assigned">0</div><div class="l">in flight</div></div>
          <div class="stat"><div class="n" id="g-auth">—</div><div class="l">join auth</div></div>
          <div class="stat"><div class="n" id="g-burst">—</div><div class="l">burst mode</div></div>
        </div>
      </div>
      <div class="card">
        <h2>Connected nodes</h2>
        <ul class="wlist" id="wlist"><li><span class="wid">waiting for peers…</span></li></ul>
      </div>
      <div class="card">
        <h2>Jobs</h2>
        <div id="jobs"><div class="meta">no jobs yet</div></div>
      </div>
      <div class="card" id="errbox" style="display:none"><div class="err" id="err"></div></div>
    </aside>
  </div>
  <script>
    const canvas = document.getElementById('topo');
    const ctx = canvas.getContext('2d');
    let W = 0, H = 0, dpr = 1;
    let state = null;
    let t0 = performance.now();
    let lastFetch = 0;

    function resize() {
      const rect = canvas.parentElement.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = rect.width; H = rect.height;
      canvas.width = Math.floor(W * dpr);
      canvas.height = Math.floor(H * dpr);
      canvas.style.width = W + 'px';
      canvas.style.height = H + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    window.addEventListener('resize', resize);
    resize();

    function hub() { return { x: W * 0.5, y: H * 0.48 }; }

    function layoutWorkers(workers) {
      const n = workers.length;
      const cx = W * 0.5, cy = H * 0.48;
      const R = Math.min(W, H) * (n <= 1 ? 0.28 : 0.34);
      if (n === 0) return [];
      return workers.map((w, i) => {
        const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
        return { ...w, x: cx + Math.cos(a) * R, y: cy + Math.sin(a) * R };
      });
    }

    function drawLink(a, b, active, kind, paused, now) {
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = paused ? '#9aa8b8' : (kind === 'cloud' ? '#3b6ea5' : '#1f7a6c');
      ctx.globalAlpha = active ? 0.9 : 0.35;
      ctx.lineWidth = active ? 2.4 : 1.4;
      if (active) ctx.setLineDash([8, 10]); else ctx.setLineDash([2, 6]);
      ctx.lineDashOffset = active ? -(now / 30) : 0;
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      if (active) {
        const u = ((now / 900) % 1);
        const x = a.x + (b.x - a.x) * u;
        const y = a.y + (b.y - a.y) * u;
        ctx.beginPath();
        ctx.arc(x, y, 4.2, 0, Math.PI * 2);
        ctx.fillStyle = '#e8b84a';
        ctx.fill();
      }
    }

    function roundRect(x, y, w, h, r) {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.arcTo(x + w, y, x + w, y + h, r);
      ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r);
      ctx.arcTo(x, y, x + w, y, r);
      ctx.closePath();
    }

    function drawNode(x, y, label, sub, color, ring) {
      ctx.beginPath();
      ctx.arc(x, y, 28, 0, Math.PI * 2);
      ctx.fillStyle = '#fff';
      ctx.fill();
      ctx.lineWidth = 3;
      ctx.strokeStyle = color;
      ctx.stroke();
      if (ring) {
        ctx.beginPath();
        ctx.arc(x, y, 36, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(232,184,74,0.55)';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(x, y, 10, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#132033';
      ctx.font = '600 12px Outfit, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(label, x, y + 48);
      ctx.fillStyle = '#5c6f84';
      ctx.font = '500 10px "IBM Plex Mono", monospace';
      ctx.fillText(sub, x, y + 62);
    }

    function drawGrid() {
      ctx.save();
      ctx.strokeStyle = 'rgba(90,110,130,0.12)';
      ctx.lineWidth = 1;
      const step = 36;
      for (let x = 0; x < W; x += step) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      }
      for (let y = 0; y < H; y += step) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }
      ctx.restore();
    }

    function render() {
      const now = performance.now() - t0;
      ctx.clearRect(0, 0, W, H);
      drawGrid();
      const g = hub();
      const topo = state && state.topology ? state.topology : null;
      const workers = topo ? layoutWorkers(topo.workers || []) : [];

      if (!topo) {
        drawNode(g.x, g.y, 'GATEWAY', 'waiting…', '#c45c26', false);
        requestAnimationFrame(render);
        return;
      }

      for (const w of workers) {
        drawLink(w, g, !!w.load, w.kind, !!w.paused, now);
      }
      drawNode(
        g.x, g.y,
        'GATEWAY',
        (topo.gateway && topo.gateway.host) ? String(topo.gateway.host) : 'master',
        '#c45c26',
        (topo.gateway && topo.gateway.assigned_tasks > 0)
      );
      for (const w of workers) {
        const short = (w.worker_id || '').slice(0, 12);
        const sub = `${w.kind} · cpu ${w.effective_threads} · ram ${w.effective_memory_mb}MiB`;
        const color = w.paused ? '#9aa8b8' : (w.kind === 'cloud' ? '#3b6ea5' : '#1f7a6c');
        drawNode(w.x, w.y, short, sub, color, w.load > 0);
      }
      requestAnimationFrame(render);
    }
    requestAnimationFrame(render);

    function setText(id, v) {
      const el = document.getElementById(id);
      if (el) el.textContent = v;
    }

    function paintSidebar(topo) {
      const gw = topo.gateway || {};
      setText('p-workers', gw.worker_count ?? 0);
      setText('p-campus', gw.campus_count ?? 0);
      setText('p-cloud', gw.cloud_count ?? 0);
      setText('p-queue', `${gw.pending_tasks ?? 0} / ${gw.assigned_tasks ?? 0}`);
      setText('g-pending', gw.pending_tasks ?? 0);
      setText('g-assigned', gw.assigned_tasks ?? 0);
      setText('g-auth', gw.auth ? 'on' : 'off');
      setText('g-burst', gw.burst_mode || '—');
      setText('subtitle', `hub ${gw.host || 'gateway'}:${gw.port || 9100} · storage ${gw.storage || 'local'}`);

      const ul = document.getElementById('wlist');
      const workers = topo.workers || [];
      if (!workers.length) {
        ul.innerHTML = '<li><span class="wid">no workers connected</span></li>';
      } else {
        ul.innerHTML = workers.map(w => {
          const cls = ['dot', w.kind === 'cloud' ? 'cloud' : '', w.paused ? 'paused' : '', w.load > 0 ? 'busy' : ''].filter(Boolean).join(' ');
          return `<li>
            <span class="${cls}"></span>
            <div>
              <div class="wid">${w.worker_id}</div>
              <div style="color:var(--muted);font-size:0.72rem">
                ${w.kind} · load ${w.load}/${w.max_tasks} · done ${w.tasks_done}
                · hb ${w.heartbeat_age_sec}s
              </div>
            </div>
            <div class="wid">${w.gpu_count || 0} GPU</div>
          </li>`;
        }).join('');
      }

      const jobsEl = document.getElementById('jobs');
      const jobs = topo.jobs || [];
      if (!jobs.length) {
        jobsEl.innerHTML = '<div class="meta">no jobs yet</div>';
      } else {
        jobsEl.innerHTML = jobs.map(j => {
          const pct = j.total ? Math.round(100 * (j.done || 0) / j.total) : 0;
          const failed = j.failed || 0;
          return `<div class="job ${j.active ? 'active' : ''}">
            <div class="id">${j.job_id} · ${j.kernel}</div>
            <div class="meta">${j.policy} · ${j.done}/${j.total} done${failed ? ` · ${failed} failed` : ''}${j.finished ? ' · finished' : ''}</div>
            <div class="bar"><i class="${failed ? 'fail' : ''}" style="width:${pct}%"></i></div>
          </div>`;
        }).join('');
      }
    }

    async function tick() {
      try {
        const r = await fetch('/api/status');
        const j = await r.json();
        if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
        state = j;
        lastFetch = Date.now();
        document.getElementById('errbox').style.display = 'none';
        if (j.topology) paintSidebar(j.topology);
      } catch (e) {
        document.getElementById('errbox').style.display = 'block';
        document.getElementById('err').textContent = String(e.message || e);
      }
    }
    setInterval(() => {
      const ago = lastFetch ? Math.max(0, Math.round((Date.now() - lastFetch) / 1000)) + 's' : '—';
      setText('p-ago', ago);
    }, 500);
    tick();
    setInterval(tick, 1500);
  </script>
</body>
</html>
"""


async def _rpc(msg: dict) -> dict:
    host, port = MASTER
    reader, writer = await asyncio.open_connection(host, port)
    try:
        if JOIN_TOKEN and "token" not in msg:
            msg = {**msg, "token": JOIN_TOKEN}
        writer.write(encode(msg))
        await writer.drain()
        line = await reader.readline()
        return decode(line) or {}
    finally:
        writer.close()
        await writer.wait_closed()


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.get("/api/status")
def status():
    try:
        metrics = asyncio.run(_rpc(make(MessageType.METRICS)))
        if metrics.get("type") == MessageType.ERROR.value:
            return jsonify({"error": metrics.get("error", "metrics failed")}), 503
        topology = metrics.get("topology")
        if not topology:
            # older master without topology — synthesize from workers
            workers = metrics.get("workers") or []
            topology = {
                "gateway": {
                    "id": "gateway",
                    "role": "master",
                    "host": MASTER[0],
                    "port": MASTER[1],
                    "worker_count": len(workers),
                    "campus_count": sum(1 for w in workers if w.get("kind") == "campus"),
                    "cloud_count": sum(1 for w in workers if w.get("kind") == "cloud"),
                    "pending_tasks": 0,
                    "assigned_tasks": sum(int(w.get("load") or 0) for w in workers),
                    "auth": bool(JOIN_TOKEN),
                    "storage": "unknown",
                    "burst_mode": (metrics.get("burst") or {}).get("mode", "unknown"),
                },
                "workers": workers,
                "links": [
                    {
                        "from": w.get("worker_id"),
                        "to": "gateway",
                        "kind": w.get("kind"),
                        "active": int(w.get("load") or 0) > 0,
                        "paused": bool(w.get("paused")),
                    }
                    for w in workers
                ],
                "jobs": [],
                "queue": {"pending": [], "assigned": []},
                "gcs": {},
            }
        job = None
        try:
            job = asyncio.run(_rpc(make(MessageType.JOB_STATUS)))
            if job.get("type") == MessageType.ERROR.value:
                job = None
        except Exception:
            job = None
        return jsonify({"topology": topology, "metrics": {
            "burst": metrics.get("burst"),
            "workers": metrics.get("workers"),
        }, "job": job})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


def main():
    global MASTER, JOIN_TOKEN
    p = argparse.ArgumentParser()
    p.add_argument("--master", default="127.0.0.1:9100")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--token", default="")
    args = p.parse_args()
    host, port_s = args.master.split(":")
    MASTER = (host, int(port_s))
    JOIN_TOKEN = args.token or os.environ.get("HPC_JOIN_TOKEN", "")
    print(f"[dashboard] master={MASTER[0]}:{MASTER[1]} auth={'on' if JOIN_TOKEN else 'off'}", flush=True)
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
