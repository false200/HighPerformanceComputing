"""Keep N user sessions online (hello + heartbeat) until Ctrl+C."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from protocol.messages import MessageType, decode, encode, make


async def rpc(host: str, port: int, msg: dict, timeout: float = 15.0) -> dict | None:
    from protocol.messages import MAX_MESSAGE_BYTES

    reader, writer = await asyncio.open_connection(host, port, limit=MAX_MESSAGE_BYTES)
    try:
        writer.write(encode(msg))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        return decode(line)
    finally:
        writer.close()
        await writer.wait_closed()


async def session(host: str, port: int, token: str, name: str, stop: asyncio.Event) -> None:
    hello = await rpc(host, port, make(MessageType.USER_HELLO, token=token, name=name))
    if not hello or not hello.get("ok"):
        print(f"[{name}] hello failed: {hello}", flush=True)
        return
    uid = hello["user_id"]
    print(f"[{name}] online {uid}", flush=True)
    try:
        while not stop.is_set():
            await rpc(host, port, make(MessageType.USER_HEARTBEAT, token=token, user_id=uid))
            try:
                await asyncio.wait_for(stop.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass
    finally:
        try:
            await rpc(host, port, make(MessageType.USER_BYE, token=token, user_id=uid))
            print(f"[{name}] logout {uid}", flush=True)
        except Exception as exc:
            print(f"[{name}] logout failed: {exc}", flush=True)


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--master", default="127.0.0.1:9100")
    p.add_argument("--token", default="")
    p.add_argument("--names", default="alice,bob")
    args = p.parse_args()
    host, port_s = args.master.split(":")
    port = int(port_s)
    token = (args.token or os.environ.get("HPC_JOIN_TOKEN") or "").strip()
    names = [n.strip() for n in args.names.split(",") if n.strip()]
    stop = asyncio.Event()
    tasks = [asyncio.create_task(session(host, port, token, n, stop)) for n in names]
    print(f"[users] holding {len(names)} sessions on {host}:{port} — Ctrl+C to leave", flush=True)
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(0)
