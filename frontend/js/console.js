const COLORS = {
  ink: '#1c2421',
  muted: '#5c675f',
  faint: '#8a938a',
  peer: '#2f4f5e',
  cloud: '#4a5560',
  user: '#5a3e2b',
  hub: '#1f3d34',
  live: '#a67c00',
  paused: '#8a938a',
  paper: '#f7f8f4',
  grid: 'rgba(28, 36, 33, 0.07)',
};

const canvas = document.getElementById('topo');
const ctx = canvas.getContext('2d');
let W = 0, H = 0, dpr = 1;
let state = null;
let t0 = performance.now();
let lastFetch = 0;
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const pos = Object.create(null);
let dragId = null;
let dragOff = { x: 0, y: 0 };
let nodeHit = [];

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function resize() {
  const rect = canvas.parentElement.getBoundingClientRect();
  dpr = Math.min(window.devicePixelRatio || 1, 2);
  W = rect.width;
  H = rect.height;
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
  const col = paused
    ? COLORS.paused
    : (kind === 'user' ? COLORS.user : (kind === 'cloud' ? COLORS.cloud : COLORS.peer));
  ctx.strokeStyle = col;
  ctx.globalAlpha = active ? 0.9 : 0.28;
  ctx.lineWidth = active ? 2 : 1;
  ctx.setLineDash(active ? [6, 8] : [2, 4]);
  ctx.lineDashOffset = (!reduceMotion && active) ? -(now / 30) : 0;
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;
  if (active && !reduceMotion) {
    const u = (now / 950) % 1;
    ctx.beginPath();
    ctx.arc(a.x + (b.x - a.x) * u, a.y + (b.y - a.y) * u, 3.2, 0, Math.PI * 2);
    ctx.fillStyle = COLORS.live;
    ctx.fill();
  }
}

function drawNode(x, y, label, sub, color, ring) {
  ctx.beginPath();
  ctx.rect(x - 22, y - 22, 44, 44);
  ctx.fillStyle = COLORS.paper;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = color;
  ctx.stroke();
  if (ring) {
    ctx.beginPath();
    ctx.rect(x - 28, y - 28, 56, 56);
    ctx.strokeStyle = COLORS.live;
    ctx.globalAlpha = 0.55;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  ctx.beginPath();
  ctx.rect(x - 6, y - 6, 12, 12);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.fillStyle = COLORS.ink;
  ctx.font = '600 12px "Familjen Grotesk", sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(label, x, y + 42);
  ctx.fillStyle = COLORS.muted;
  ctx.font = '400 10px "IBM Plex Mono", monospace';
  ctx.fillText(sub, x, y + 56);
}

function drawGrid() {
  ctx.save();
  ctx.strokeStyle = COLORS.grid;
  const step = 32;
  for (let x = 0; x < W; x += step) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, H);
    ctx.stroke();
  }
  for (let y = 0; y < H; y += step) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
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
    drawNode(hubP.x, hubP.y, 'Coordinator', 'linking…', COLORS.hub, false);
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

  const hostRaw = (topo.gateway && topo.gateway.host) ? String(topo.gateway.host) : '';
  const host = (!hostRaw || hostRaw === '0.0.0.0' || hostRaw === '127.0.0.1') ? 'online' : hostRaw;
  drawNode(
    hubP.x,
    hubP.y,
    'Coordinator',
    host,
    COLORS.hub,
    !!(topo.gateway && topo.gateway.assigned_tasks > 0)
  );
  nodeHit.push({ id: 'gateway', x: hubP.x, y: hubP.y, r: 30 });

  for (const w of workers) {
    const short = String(w.name || w.worker_id || 'peer').slice(0, 14);
    const role = w.kind === 'cloud' ? 'remote' : 'local';
    const sub = role + '  ' + w.effective_threads + 'cpu  ' + w.effective_memory_mb + 'MiB';
    const color = w.paused ? COLORS.paused : (w.kind === 'cloud' ? COLORS.cloud : COLORS.peer);
    drawNode(w.x, w.y, short, sub, color, w.load > 0);
    nodeHit.push({ id: w.worker_id, x: w.x, y: w.y, r: 30 });
  }
  for (const u of users) {
    const short = String(u.name || u.user_id || 'user').slice(0, 14);
    const sub = (u.status || 'online') + (u.job_id ? '  ' + String(u.job_id).slice(0, 10) : '');
    const busy = ['waiting', 'submitting', 'queued'].indexOf(u.status) >= 0;
    drawNode(u.x, u.y, short, sub, COLORS.user, busy);
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
    const dx = p.x - n.x;
    const dy = p.y - n.y;
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
  setText('p-intake', (gw.intake_depth ?? intake.depth ?? 0) + ' ' + (gw.queue_backend || intake.backend || 'mem'));
  setText('g-pending', gw.pending_tasks ?? 0);
  setText('g-assigned', gw.assigned_tasks ?? 0);
  setText('g-jobs', gw.running_jobs ?? 0);
  setText('g-intake', gw.intake_depth ?? intake.depth ?? 0);
  setText('g-auth', gw.auth ? 'on' : 'off');
  setText('g-burst', gw.burst_mode === 'aws' ? 'cloud' : (gw.burst_mode || '—'));

  const userList = document.getElementById('ulist');
  const users = topo.users || [];
  if (!users.length) {
    userList.innerHTML = '<li class="empty">No submitters online. Run <kbd>User.bat</kbd> to appear here.</li>';
  } else {
    userList.innerHTML = users.map((u) => {
      const title = escapeHtml((u.name || 'user') + '  ' + (u.user_id || ''));
      const meta = escapeHtml(
        (u.status || 'online') +
        (u.job_id ? '  job ' + u.job_id : '') +
        '  ' + (u.connected_for_sec ?? 0) + 's'
      );
      return '<li><div class="row-title">' + title + '</div><div class="row-meta">' + meta + '</div></li>';
    }).join('');
  }

  const ul = document.getElementById('wlist');
  const workers = topo.workers || [];
  if (!workers.length) {
    ul.innerHTML = '<li class="empty">No donated machines. Run <kbd>Worker.bat</kbd> to join.</li>';
  } else {
    ul.innerHTML = workers.map((w) => {
      const role = w.kind === 'cloud' ? 'remote' : 'local';
      const label = (w.name && w.name !== w.worker_id)
        ? (w.name + '  ' + w.worker_id)
        : (w.worker_id || 'peer');
      const meta = role + '  load ' + w.load + '/' + w.max_tasks +
        '  done ' + w.tasks_done + '  ' + w.effective_threads + ' cpu';
      return '<li><div class="row-title">' + escapeHtml(label) + '</div><div class="row-meta">' +
        escapeHtml(meta) + '</div></li>';
    }).join('');
  }

  const jobsEl = document.getElementById('jobs');
  const jobs = topo.jobs || [];
  const waiting = intake.waiting || [];
  let html = '';
  if (waiting.length) {
    html += waiting.map((q) => {
      return '<div class="job">' +
        '<div class="row-title">' + escapeHtml('intake ' + q.queue_id) + '</div>' +
        '<div class="row-meta">' + escapeHtml(
          'queued  ' + (q.kernel || '?') +
          (q.user_id ? '  ' + q.user_id : '') +
          '  ' + (q.wait_sec ?? 0) + 's'
        ) + '</div></div>';
    }).join('');
  }
  if (!jobs.length && !waiting.length) {
    jobsEl.innerHTML = '<p class="empty">Idle. Submits land here once a peer is connected.</p>';
  } else {
    html += jobs.map((j) => {
      const pct = j.total ? Math.round(100 * (j.done || 0) / j.total) : 0;
      const failed = j.failed || 0;
      return '<div class="job ' + (j.active ? 'active' : '') + '">' +
        '<div class="row-title">' + escapeHtml(j.job_id + '  ' + j.kernel) + '</div>' +
        '<div class="row-meta">' + escapeHtml(
          (j.done || 0) + '/' + j.total + ' done' +
          (failed ? '  ' + failed + ' failed' : '') +
          (j.finished ? '  finished' : '')
        ) + '</div>' +
        '<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' +
        pct + '"><i style="width:' + pct + '%"></i></div></div>';
    }).join('');
    jobsEl.innerHTML = html;
  }
}

async function tick() {
  const errbox = document.getElementById('errbox');
  try {
    const r = await fetch('/api/status');
    const j = await r.json();
    if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
    state = j;
    lastFetch = Date.now();
    errbox.hidden = true;
    if (j.topology) paintSidebar(j.topology);
  } catch (e) {
    errbox.hidden = false;
    document.getElementById('err').textContent = String(e.message || e);
  }
}
setInterval(() => {
  setText('p-ago', lastFetch ? Math.max(0, Math.round((Date.now() - lastFetch) / 1000)) + 's' : '—');
}, 500);
tick();
setInterval(tick, 1500);
