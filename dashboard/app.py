from __future__ import annotations

"""Live cluster console — draggable topology + jobs."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template_string

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from protocol.messages import MAX_MESSAGE_BYTES, MessageType, decode, encode, make

app = Flask(__name__)
MASTER = ("127.0.0.1", 9100)
JOIN_TOKEN = ""

PAGE = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Lattice</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=Fragment+Mono:wght@400&family=Sora:wght@400;500;600;700&display=swap" rel="stylesheet"/>
  <style>
    :root {
      --ink: #141820;
      --muted: #5a6573;
      --line: #d5dae0;
      --bg: #e9ecef;
      --surface: #f7f8fa;
      --white: #ffffff;
      --gateway: #0f3d2e;
      --peer: #1c4b6e;
      --cloud: #4a5568;
      --user: #6b3f1d;
      --live: #c9a227;
      --danger: #9b2c2c;
      --ok: #0f3d2e;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      font-family: Sora, system-ui, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(ellipse 80% 50% at 10% -10%, #dfe7ef 0%, transparent 55%),
        linear-gradient(165deg, #eef1f4 0%, var(--bg) 45%, #e3e7ec 100%);
      overflow: hidden;
    }
    .shell {
      display: grid;
      grid-template-columns: 1fr minmax(280px, 320px);
      grid-template-rows: auto 1fr;
      height: 100%;
    }
    header {
      grid-column: 1 / -1;
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 1rem;
      padding: 1rem 1.35rem;
      border-bottom: 1px solid #cfd5dc;
      background: rgba(247,248,250,0.92);
    }
    .brand {
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      margin: 0;
    }
    .brand span { color: var(--muted); font-weight: 500; font-size: 0.85rem; margin-left: 0.55rem; }
    .stats {
      display: flex;
      gap: 1.25rem;
      font-family: "Fragment Mono", monospace;
      font-size: 0.72rem;
      color: var(--muted);
    }
    .stats b { color: var(--ink); font-weight: 500; }
    .stage { position: relative; min-height: 0; border-right: 1px solid #cfd5dc; }
    #topo {
      width: 100%;
      height: 100%;
      display: block;
      cursor: default;
      touch-action: none;
    }
    #topo.grab { cursor: grab; }
    #topo.dragging { cursor: grabbing; }
    .hint {
      position: absolute;
      left: 1rem;
      bottom: 1rem;
      font-size: 0.75rem;
      color: var(--muted);
      background: rgba(247,248,250,0.95);
      border: 1px solid #cfd5dc;
      padding: 0.4rem 0.65rem;
      pointer-events: none;
    }
    aside {
      overflow: auto;
      background: var(--surface);
      padding: 1rem;
      display: flex;
      flex-direction: column;
      gap: 1.1rem;
    }
    section.block h2 {
      margin: 0 0 0.55rem;
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--ink);
    }
    .grid2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.45rem;
    }
    .metric {
      background: var(--white);
      border: 1px solid #d0d6dd;
      padding: 0.55rem 0.65rem;
    }
    .metric .n {
      font-family: "Fragment Mono", monospace;
      font-size: 1.15rem;
      font-weight: 500;
    }
    .metric .l { font-size: 0.68rem; color: var(--muted); margin-top: 0.15rem; }
    .nodes, .jobs { list-style: none; margin: 0; padding: 0; }
    .nodes li, .job {
      background: var(--white);
      border: 1px solid #d0d6dd;
      padding: 0.55rem 0.65rem;
      margin-bottom: 0.4rem;
      font-size: 0.78rem;
    }
    .job.active { border-left: 3px solid var(--gateway); }
    .mono { font-family: "Fragment Mono", monospace; font-size: 0.68rem; }
    .muted { color: var(--muted); }
    .bar {
      height: 4px;
      background: #dde2e8;
      margin-top: 0.4rem;
      overflow: hidden;
    }
    .bar > i {
      display: block;
      height: 100%;
      width: 0;
      background: var(--gateway);
      transition: width 0.35s ease;
    }
    .err {
      color: var(--danger);
      font-family: "Fragment Mono", monospace;
      font-size: 0.72rem;
      white-space: pre-wrap;
    }
    @media (max-width: 860px) {
      .shell { grid-template-columns: 1fr; grid-template-rows: auto 46vh 1fr; }
      .stage { border-right: 0; border-bottom: 1px solid #cfd5dc; }
      .stats { flex-wrap: wrap; justify-content: flex-end; }
    }
    @media (prefers-reduced-motion: reduce) {
      .bar > i { transition: none; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <h1 class="brand">Lattice<span id="subtitle">cluster console</span></h1>
      <div class="stats">
        <div>peers <b id="p-workers">—</b></div>
        <div>users <b id="p-users">—</b></div>
        <div>local <b id="p-campus">—</b></div>
        <div>remote <b id="p-cloud">—</b></div>
        <div>tasks <b id="p-queue">—</b></div>
        <div>intake <b id="p-intake">—</b></div>
        <div>sync <b id="p-ago">—</b></div>
      </div>
    </header>
    <section class="stage">
      <canvas id="topo"></canvas>
      <div class="hint">Drag nodes · gold = active work · brown = users</div>
    </section>
    <aside>
      <section class="block">
        <h2>Coordinator</h2>
        <div class="grid2">
          <div class="metric"><div class="n" id="g-pending">0</div><div class="l">waiting</div></div>
          <div class="metric"><div class="n" id="g-assigned">0</div><div class="l">running</div></div>
          <div class="metric"><div class="n" id="g-jobs">0</div><div class="l">jobs live</div></div>
          <div class="metric"><div class="n" id="g-intake">0</div><div class="l">intake</div></div>
          <div class="metric"><div class="n" id="g-auth">—</div><div class="l">auth</div></div>
          <div class="metric"><div class="n" id="g-burst">—</div><div class="l">overflow</div></div>
        </div>
      </section>
      <section class="block">
        <h2>Users</h2>
        <ul class="nodes" id="ulist"><li class="muted mono">No users connected</li></ul>
      </section>
      <section class="block">
        <h2>Peers</h2>
        <ul class="nodes" id="wlist"><li class="muted mono">No peers connected</li></ul>
      </section>
      <section class="block">
        <h2>Jobs</h2>
        <div id="jobs"><div class="muted">No jobs yet</div></div>
      </section>
      <section class="block" id="errbox" style="display:none"><div class="err" id="err"></div></section>
    </aside>
  </div>
  <script>
    const canvas = document.getElementById('topo');
    const ctx = canvas.getContext('2d');
    let W = 0, H = 0, dpr = 1;
    let state = null;
    let t0 = performance.now();
    let lastFetch = 0;

    // Persisted drag positions: id -> {x,y}
    const pos = Object.create(null);
    let dragId = null;
    let dragOff = { x: 0, y: 0 };
    let nodeHit = []; // {id,x,y,r} from last frame

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

    function defaultHub() {
      return { x: W * 0.5, y: H * 0.48 };
    }

    function ensurePos(id, fallback) {
      if (!pos[id]) pos[id] = { x: fallback.x, y: fallback.y };
      return pos[id];
    }

    function layoutWorkers(workers) {
      const hubP = ensurePos('gateway', defaultHub());
      const n = workers.length || 1;
      const R = Math.min(W, H) * (workers.length <= 1 ? 0.28 : 0.34);
      return workers.map((w, i) => {
        const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
        const fb = { x: hubP.x + Math.cos(a) * R, y: hubP.y + Math.sin(a) * R };
        const p = ensurePos(w.worker_id, fb);
        return { ...w, x: p.x, y: p.y };
      });
    }

    function layoutUsers(users) {
      const hubP = ensurePos('gateway', defaultHub());
      const n = users.length || 1;
      const R = Math.min(W, H) * 0.22;
      return users.map((u, i) => {
        // left arc so users sit opposite the worker ring
        const a = Math.PI / 2 + ((i + 0.5) / n) * Math.PI;
        const fb = { x: hubP.x + Math.cos(a) * R, y: hubP.y + Math.sin(a) * R };
        const p = ensurePos(u.user_id, fb);
        return { ...u, x: p.x, y: p.y };
      });
    }

    function drawLink(a, b, active, kind, paused, now) {
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      const col = paused ? '#9aa3ad'
        : (kind === 'user' ? '#6b3f1d' : (kind === 'cloud' ? '#4a5568' : '#1c4b6e'));
      ctx.strokeStyle = col;
      ctx.globalAlpha = active ? 0.85 : 0.28;
      ctx.lineWidth = active ? 2.2 : 1.2;
      ctx.setLineDash(active ? [7, 9] : [2, 5]);
      ctx.lineDashOffset = active ? -(now / 28) : 0;
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      if (active) {
        const u = (now / 900) % 1;
        ctx.beginPath();
        ctx.arc(a.x + (b.x - a.x) * u, a.y + (b.y - a.y) * u, 3.8, 0, Math.PI * 2);
        ctx.fillStyle = '#c9a227';
        ctx.fill();
      }
    }

    function drawNode(x, y, label, sub, color, ring) {
      ctx.beginPath();
      ctx.arc(x, y, 26, 0, Math.PI * 2);
      ctx.fillStyle = '#fff';
      ctx.fill();
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = color;
      ctx.stroke();
      if (ring) {
        ctx.beginPath();
        ctx.arc(x, y, 34, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(201,162,39,0.5)';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(x, y, 9, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.fillStyle = '#141820';
      ctx.font = '600 12px Sora, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(label, x, y + 46);
      ctx.fillStyle = '#5a6573';
      ctx.font = '400 10px "Fragment Mono", monospace';
      ctx.fillText(sub, x, y + 60);
    }

    function drawGrid() {
      ctx.save();
      ctx.strokeStyle = 'rgba(20,24,32,0.06)';
      const step = 40;
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
      nodeHit = [];
      const topo = state && state.topology ? state.topology : null;
      const hubP = ensurePos('gateway', defaultHub());
      const workers = topo ? layoutWorkers(topo.workers || []) : [];
      const users = topo ? layoutUsers(topo.users || []) : [];

      if (!topo) {
        drawNode(hubP.x, hubP.y, 'Coordinator', 'waiting…', '#0f3d2e', false);
        nodeHit.push({ id: 'gateway', x: hubP.x, y: hubP.y, r: 30 });
        requestAnimationFrame(render);
        return;
      }

      for (const w of workers) {
        drawLink(w, hubP, !!w.load, w.kind, !!w.paused, now);
      }
      for (const u of users) {
        const busy = ['waiting', 'submitting', 'queued'].indexOf(u.status) >= 0;
        drawLink(u, hubP, busy, 'user', false, now);
      }
      const host = (topo.gateway && topo.gateway.host) ? String(topo.gateway.host) : 'live';
      drawNode(
        hubP.x, hubP.y,
        'Coordinator',
        host,
        '#0f3d2e',
        !!(topo.gateway && topo.gateway.assigned_tasks > 0)
      );
      nodeHit.push({ id: 'gateway', x: hubP.x, y: hubP.y, r: 30 });

      for (const w of workers) {
        const short = (w.worker_id || 'peer').slice(0, 14);
        const role = w.kind === 'cloud' ? 'remote' : 'local';
        const sub = role + ' · ' + w.effective_threads + ' cpu · ' + w.effective_memory_mb + ' MiB';
        const color = w.paused ? '#9aa3ad' : (w.kind === 'cloud' ? '#4a5568' : '#1c4b6e');
        drawNode(w.x, w.y, short, sub, color, w.load > 0);
        nodeHit.push({ id: w.worker_id, x: w.x, y: w.y, r: 30 });
      }
      for (const u of users) {
        const short = (u.name || u.user_id || 'user').slice(0, 14);
        const sub = (u.status || 'online') + (u.job_id ? ' · ' + String(u.job_id).slice(0, 10) : '');
        const busy = ['waiting', 'submitting', 'queued'].indexOf(u.status) >= 0;
        drawNode(u.x, u.y, short, sub, '#6b3f1d', busy);
        nodeHit.push({ id: u.user_id, x: u.x, y: u.y, r: 30 });
      }
      requestAnimationFrame(render);
    }
    requestAnimationFrame(render);

    function canvasPoint(ev) {
      const r = canvas.getBoundingClientRect();
      return { x: ev.clientX - r.left, y: ev.clientY - r.top };
    }

    function hitTest(p) {
      for (let i = nodeHit.length - 1; i >= 0; i--) {
        const n = nodeHit[i];
        const dx = p.x - n.x, dy = p.y - n.y;
        if (dx * dx + dy * dy <= n.r * n.r) return n;
      }
      return null;
    }

    canvas.addEventListener('pointerdown', (ev) => {
      const p = canvasPoint(ev);
      const hit = hitTest(p);
      if (!hit) return;
      dragId = hit.id;
      const cur = ensurePos(dragId, { x: hit.x, y: hit.y });
      dragOff = { x: p.x - cur.x, y: p.y - cur.y };
      canvas.classList.add('dragging');
      canvas.setPointerCapture(ev.pointerId);
      ev.preventDefault();
    });
    canvas.addEventListener('pointermove', (ev) => {
      const p = canvasPoint(ev);
      if (dragId) {
        const cur = ensurePos(dragId, p);
        cur.x = Math.max(40, Math.min(W - 40, p.x - dragOff.x));
        cur.y = Math.max(40, Math.min(H - 40, p.y - dragOff.y));
        return;
      }
      canvas.classList.toggle('grab', !!hitTest(p));
    });
    function endDrag(ev) {
      if (!dragId) return;
      dragId = null;
      canvas.classList.remove('dragging');
      try { canvas.releasePointerCapture(ev.pointerId); } catch (_) {}
    }
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);

    function setText(id, v) {
      const el = document.getElementById(id);
      if (el) el.textContent = v;
    }

    function paintSidebar(topo) {
      const gw = topo.gateway || {};
      const intake = topo.intake || {};
      setText('p-workers', gw.worker_count ?? 0);
      setText('p-users', gw.user_count ?? 0);
      setText('p-campus', gw.campus_count ?? 0);
      setText('p-cloud', gw.cloud_count ?? 0);
      setText('p-queue', (gw.pending_tasks ?? 0) + ' / ' + (gw.assigned_tasks ?? 0));
      setText('p-intake', (gw.intake_depth ?? intake.depth ?? 0) + ' · ' + (gw.queue_backend || intake.backend || 'mem'));
      setText('g-pending', gw.pending_tasks ?? 0);
      setText('g-assigned', gw.assigned_tasks ?? 0);
      setText('g-jobs', gw.running_jobs ?? 0);
      setText('g-intake', gw.intake_depth ?? intake.depth ?? 0);
      setText('g-auth', gw.auth ? 'on' : 'off');
      setText('g-burst', gw.burst_mode === 'aws' ? 'cloud' : (gw.burst_mode || '—'));
      setText('subtitle', ' · ' + (gw.host || 'coordinator') + ':' + (gw.port || 9100));

      const userList = document.getElementById('ulist');
      const users = topo.users || [];
      if (!users.length) {
        userList.innerHTML = '<li class="muted mono">No users connected</li>';
      } else {
        userList.innerHTML = users.map(u => {
          return '<li><div class="mono">' + (u.name || 'user') + ' · ' + u.user_id + '</div>' +
            '<div class="muted">' + (u.status || 'online') +
            (u.job_id ? ' · job ' + u.job_id : '') +
            ' · ' + (u.connected_for_sec ?? 0) + 's</div></li>';
        }).join('');
      }

      const ul = document.getElementById('wlist');
      const workers = topo.workers || [];
      if (!workers.length) {
        ul.innerHTML = '<li class="muted mono">No peers connected</li>';
      } else {
        ul.innerHTML = workers.map(w => {
          const role = w.kind === 'cloud' ? 'remote' : 'local';
          return '<li><div class="mono">' + w.worker_id + '</div>' +
            '<div class="muted">' + role + ' · load ' + w.load + '/' + w.max_tasks +
            ' · done ' + w.tasks_done + ' · ' + w.effective_threads + ' cpu</div></li>';
        }).join('');
      }

      const jobsEl = document.getElementById('jobs');
      const jobs = topo.jobs || [];
      const waiting = (intake.waiting || []);
      let html = '';
      if (waiting.length) {
        html += waiting.map(q => {
          return '<div class="job">' +
            '<div class="mono">intake ' + q.queue_id + '</div>' +
            '<div class="muted">queued · ' + (q.kernel || '?') +
            (q.user_id ? ' · ' + q.user_id : '') +
            ' · ' + (q.wait_sec ?? 0) + 's</div></div>';
        }).join('');
      }
      if (!jobs.length && !waiting.length) {
        jobsEl.innerHTML = '<div class="muted">No jobs yet</div>';
      } else {
        html += jobs.map(j => {
          const pct = j.total ? Math.round(100 * (j.done || 0) / j.total) : 0;
          const failed = j.failed || 0;
          return '<div class="job ' + (j.active ? 'active' : '') + '">' +
            '<div class="mono">' + j.job_id + ' · ' + j.kernel + '</div>' +
            '<div class="muted">' + (j.done || 0) + '/' + j.total + ' done' +
            (failed ? ' · ' + failed + ' failed' : '') +
            (j.finished ? ' · finished' : '') + '</div>' +
            '<div class="bar"><i style="width:' + pct + '%"></i></div></div>';
        }).join('');
        jobsEl.innerHTML = html;
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
      setText('p-ago', lastFetch ? Math.max(0, Math.round((Date.now() - lastFetch) / 1000)) + 's' : '—');
    }, 500);
    tick();
    setInterval(tick, 1500);
  </script>
</body>
</html>
"""


async def _rpc(msg: dict) -> dict:
    host, port = MASTER
    reader, writer = await asyncio.open_connection(host, port, limit=MAX_MESSAGE_BYTES)
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
                "links": [],
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
        return jsonify({
            "topology": topology,
            "metrics": {"burst": metrics.get("burst"), "workers": metrics.get("workers")},
            "job": job,
        })
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
