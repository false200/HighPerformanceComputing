from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Dict, Optional


class HealthServer:
    """Minimal HTTP /health and /ready for load balancers & ops."""

    def __init__(self, host: str, port: int, status_fn: Callable[[], Dict[str, Any]]):
        self.host = host
        self.port = port
        self.status_fn = status_fn
        self._server: Optional[asyncio.AbstractServer] = None
        self.started_at = time.time()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        print(f"[health] http://{self.host}:{self.port}/health", flush=True)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            req = await asyncio.wait_for(reader.readline(), timeout=5.0)
            # drain a bit of headers
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                if line in (b"\r\n", b"\n", b""):
                    break
            path = "/"
            try:
                path = req.decode("utf-8", errors="replace").split(" ")[1]
            except Exception:
                pass
            body_obj = self.status_fn()
            body_obj["uptime_sec"] = round(time.time() - self.started_at, 3)
            if path.startswith("/ready"):
                ok = bool(body_obj.get("running"))
                code = 200 if ok else 503
            else:
                code = 200
                ok = True
            body = json.dumps(body_obj).encode("utf-8")
            status = "OK" if code == 200 else "Service Unavailable"
            headers = (
                f"HTTP/1.1 {code} {status}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("utf-8")
            writer.write(headers + body)
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
