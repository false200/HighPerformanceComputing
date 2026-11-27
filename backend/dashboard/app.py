from __future__ import annotations

"""Live cluster console — serves frontend/ and proxies master metrics."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

BACKEND_ROOT = Path(__file__).resolve().parents[1]  # .../backend
PROJECT_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from protocol.messages import MAX_MESSAGE_BYTES, MessageType, decode, encode, make

app = Flask(
    __name__,
    static_folder=str(FRONTEND_ROOT),
    static_url_path="/static",
)
MASTER = ("127.0.0.1", 9100)
JOIN_TOKEN = ""


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
    return send_from_directory(FRONTEND_ROOT, "index.html")


@app.get("/static/css/<path:filename>")
def static_css(filename: str):
    return send_from_directory(FRONTEND_ROOT / "css", filename)


@app.get("/static/js/<path:filename>")
def static_js(filename: str):
    return send_from_directory(FRONTEND_ROOT / "js", filename)


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
    if not FRONTEND_ROOT.is_dir():
        raise SystemExit(f"frontend missing: {FRONTEND_ROOT}")
    print(
        f"[dashboard] master={MASTER[0]}:{MASTER[1]} "
        f"frontend={FRONTEND_ROOT} auth={'on' if JOIN_TOKEN else 'off'}",
        flush=True,
    )
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
