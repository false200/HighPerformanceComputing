"""Continuous job firehose from Eliza — submit without waiting between jobs.

Completions are tracked in the background so the submit loop never stalls
on a DONE. Overflow lands in RabbitMQ intake when the cluster is saturated.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from protocol.messages import MessageType, decode, encode, make

TRAIN = ROOT / "examples" / "matmul_eliza" / "train.py"
DATA = ROOT / "examples" / "matmul_eliza" / "A.csv"


async def rpc(host: str, port: int, msg: Dict[str, Any], timeout: float = 90.0) -> Optional[Dict[str, Any]]:
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


async def find_user(host: str, port: int, token: str, name: str) -> Optional[str]:
    m = await rpc(host, port, make(MessageType.METRICS, token=token), timeout=15)
    for u in ((m or {}).get("topology") or {}).get("users") or []:
        if str(u.get("name")) == name and u.get("user_id"):
            return str(u["user_id"])
    return None


async def submit_once(
    host: str,
    port: int,
    token: str,
    uid: str,
    chunks: int,
    n: int,
    train_src: str,
    data_src: str,
) -> Optional[str]:
    put = await rpc(
        host,
        port,
        make(
            MessageType.PACKAGE_PUT,
            token=token,
            name=f"eliza-stream-{n}",
            files={"A.csv": data_src, "train.py": train_src},
            meta={"dataset": "A.csv", "entrypoint": "train.py", "label_col": "tag", "stream": n},
        ),
        timeout=120,
    )
    if not put or not put.get("ok"):
        print(f"[Eliza] #{n} package failed: {put}", flush=True)
        return None
    package_id = put["package_id"]
    sub = await rpc(
        host,
        port,
        make(
            MessageType.JOB_SUBMIT,
            token=token,
            user_id=uid,
            kernel="userjob",
            policy="campus_only",
            chunks=chunks,
            deadline_sec=300,
            package_id=package_id,
            dataset="A.csv",
            entrypoint="train.py",
            label_col="tag",
            epochs=1,
            lr=0.0,
        ),
        timeout=60,
    )
    if not sub or not sub.get("ok"):
        print(f"[Eliza] #{n} submit failed: {sub}", flush=True)
        return None
    jid = sub.get("job_id") or sub.get("queue_id")
    print(
        f"[Eliza] FIRE #{n} queued={bool(sub.get('queued'))} "
        f"job={sub.get('job_id')} q={sub.get('queue_id')} pkg={package_id}",
        flush=True,
    )
    return str(jid) if jid else None


async def tracker(
    host: str,
    port: int,
    token: str,
    uid_holder: Dict[str, str],
    pending: Set[str],
    stop: asyncio.Event,
) -> None:
    """Poll cluster; log finishes. Never blocks the submit loop."""
    seen_done: Set[str] = set()
    while not stop.is_set():
        try:
            uid = uid_holder.get("uid") or ""
            if uid:
                await rpc(
                    host,
                    port,
                    make(MessageType.USER_HEARTBEAT, token=token, user_id=uid),
                    timeout=10,
                )
            m = await rpc(host, port, make(MessageType.METRICS, token=token), timeout=15)
            topo = (m or {}).get("topology") or {}
            gw = topo.get("gateway") or {}
            jobs = topo.get("jobs") or []
            for j in jobs:
                jid = str(j.get("job_id") or "")
                if not jid or jid in seen_done:
                    continue
                if j.get("finished"):
                    seen_done.add(jid)
                    pending.discard(jid)
                    print(
                        f"[Eliza] DONE {jid} {j.get('done')}/{j.get('total')} "
                        f"checksum={j.get('checksum')}",
                        flush=True,
                    )
            loads = {
                str(w.get("name") or w.get("worker_id")): w.get("load")
                for w in (topo.get("workers") or [])
            }
            print(
                f"[Eliza] live jobs={gw.get('running_jobs')} intake={gw.get('intake_depth')} "
                f"tasks={gw.get('pending_tasks')}/{gw.get('assigned_tasks')} loads={loads}",
                flush=True,
            )
        except Exception as exc:
            print(f"[Eliza] tracker err: {exc}", flush=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.5)
        except asyncio.TimeoutError:
            pass


async def amain() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--master", default="13.217.224.71:9100")
    p.add_argument("--token", default="")
    p.add_argument("--user-name", default="Eliza")
    p.add_argument("--chunks", type=int, default=4)
    p.add_argument(
        "--pause",
        type=float,
        default=0.15,
        help="delay between submits (seconds); keep small for continuous fire",
    )
    args = p.parse_args()
    host, port_s = args.master.split(":")
    port = int(port_s)
    token = (args.token or os.environ.get("HPC_JOIN_TOKEN") or "").strip()

    if not TRAIN.exists() or not DATA.exists():
        print("missing matmul_eliza package files", flush=True)
        return 1

    train_src = TRAIN.read_text(encoding="utf-8")
    data_src = DATA.read_text(encoding="utf-8")

    uid = await find_user(host, port, token, args.user_name)
    if not uid:
        print(
            f"[Eliza] user {args.user_name!r} not online — start keep_users_online first",
            flush=True,
        )
        return 2

    uid_holder = {"uid": uid}
    pending: Set[str] = set()
    stop = asyncio.Event()
    track = asyncio.create_task(tracker(host, port, token, uid_holder, pending, stop))

    print(
        f"[Eliza] CONTINUOUS firehose as {args.user_name} ({uid}) → {host}:{port} "
        f"pause={args.pause}s (no wait-for-done between submits)",
        flush=True,
    )
    n = 0
    try:
        while True:
            n += 1
            try:
                live = await find_user(host, port, token, args.user_name)
                if live:
                    uid_holder["uid"] = live
                    uid = live
                jid = await submit_once(
                    host, port, token, uid, args.chunks, n, train_src, data_src
                )
                if jid:
                    pending.add(jid)
            except Exception as exc:
                print(f"[Eliza] submit err: {exc}", flush=True)
                await asyncio.sleep(1.0)
            await asyncio.sleep(max(0.05, args.pause))
    except asyncio.CancelledError:
        pass
    finally:
        stop.set()
        await track
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(amain()))
    except KeyboardInterrupt:
        print("[Eliza] stream stopped", flush=True)
        raise SystemExit(0)
