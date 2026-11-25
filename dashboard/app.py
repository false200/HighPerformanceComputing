from __future__ import annotations

"""Optional lightweight dashboard for master status."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template_string

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from protocol.messages import MessageType, decode, encode, make

app = Flask(__name__)
MASTER = ("127.0.0.1", 9100)

PAGE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Hybrid Desktop Grid</title>
  <style>
    body { font-family: Georgia, serif; margin: 2rem; background: #f7f3ea; color: #1c1a16; }
    h1 { font-size: 1.6rem; }
    pre { background: #1c1a16; color: #e8e2d4; padding: 1rem; overflow: auto; }
    .meta { color: #5a5346; }
  </style>
</head>
<body>
  <h1>Hybrid Consent-Driven Desktop Grid</h1>
  <p class="meta">Campus-first · OpenMP workers · Cloud-burst overflow</p>
  <pre id="out">loading…</pre>
  <script>
    async function tick() {
      const r = await fetch('/api/status');
      const j = await r.json();
      document.getElementById('out').textContent = JSON.stringify(j, null, 2);
    }
    tick(); setInterval(tick, 2000);
  </script>
</body>
</html>
"""


async def _rpc(msg):
    host, port = MASTER
    reader, writer = await asyncio.open_connection(host, port)
    try:
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
        data = asyncio.run(_rpc(make(MessageType.METRICS)))
        job = asyncio.run(_rpc(make(MessageType.JOB_STATUS)))
        return jsonify({"metrics": data, "job": job})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


def main():
    global MASTER
    p = argparse.ArgumentParser()
    p.add_argument("--master", default="127.0.0.1:9100")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    host, port_s = args.master.split(":")
    MASTER = (host, int(port_s))
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
