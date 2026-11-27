"""Submit Eliza + Bob matmul jobs at the same time; print queue + results."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from protocol.messages import MessageType, decode, encode, make


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


async def run_one(
    host: str,
    port: int,
    token: str,
    user_name: str,
    train: Path,
    dataset: Path,
    chunks: int,
    label: str,
    *,
    reuse_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    t_wall0 = time.time()
    stay = bool(reuse_user_id)
    if reuse_user_id:
        uid = str(reuse_user_id)
        await rpc(host, port, make(MessageType.USER_HEARTBEAT, token=token, user_id=uid))
        print(f"[{label}] using existing session {uid}", flush=True)
    else:
        hello = await rpc(host, port, make(MessageType.USER_HELLO, token=token, name=user_name))
        if not hello or not hello.get("ok"):
            return {"user": user_name, "error": f"hello failed: {hello}"}
        uid = str(hello["user_id"])
        print(f"[{label}] online {uid}", flush=True)

    files = {
        "A.csv": dataset.read_text(encoding="utf-8"),
        "train.py": train.read_text(encoding="utf-8"),
    }
    put = await rpc(
        host,
        port,
        make(
            MessageType.PACKAGE_PUT,
            token=token,
            name=f"matmul-{user_name}",
            files=files,
            meta={"dataset": "A.csv", "entrypoint": "train.py", "label_col": "tag"},
        ),
    )
    if not put or not put.get("ok"):
        if not stay:
            await rpc(host, port, make(MessageType.USER_BYE, token=token, user_id=uid))
        return {"user": user_name, "error": f"package failed: {put}"}
    package_id = put["package_id"]
    print(f"[{label}] package {package_id} ({train.name})", flush=True)

    sub_t0 = time.time()
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
    )
    if not sub or not sub.get("ok"):
        if not stay:
            await rpc(host, port, make(MessageType.USER_BYE, token=token, user_id=uid))
        return {"user": user_name, "error": f"submit failed: {sub}"}

    queued = bool(sub.get("queued"))
    job_id = sub.get("job_id")
    print(
        f"[{label}] submit queued={queued} job_id={job_id} "
        f"queue_id={sub.get('queue_id')} position={sub.get('position')} "
        f"tasks={sub.get('tasks')} (+{time.time()-sub_t0:.2f}s)",
        flush=True,
    )

    result: Dict[str, Any] = {
        "user": user_name,
        "user_id": uid,
        "package_id": package_id,
        "initially_queued": queued,
        "queue_id": sub.get("queue_id"),
        "train": str(train),
    }
    deadline = time.time() + 240
    last_note = ""
    while time.time() < deadline:
        await rpc(host, port, make(MessageType.USER_HEARTBEAT, token=token, user_id=uid))
        st = await rpc(
            host,
            port,
            make(MessageType.JOB_STATUS, token=token, user_id=uid, job_id=job_id),
        )
        if not st:
            await asyncio.sleep(0.4)
            continue
        if st.get("queued") and not st.get("job_id"):
            note = f"intake waiting depth≈{st.get('position')}"
            if note != last_note:
                print(f"[{label}] {note}", flush=True)
                last_note = note
            await asyncio.sleep(0.5)
            continue
        if st.get("job_id"):
            job_id = st["job_id"]
            result["job_id"] = job_id
        note = f"progress {st.get('done')}/{st.get('total')}"
        if note != last_note:
            print(f"[{label}] {note}", flush=True)
            last_note = note
        if st.get("finished"):
            result["status"] = st
            result["wall_sec"] = round(time.time() - t_wall0, 3)
            print(f"[{label}] DONE wall={result['wall_sec']}s checksum={st.get('checksum')}", flush=True)
            break
        await asyncio.sleep(0.35)
    else:
        result["error"] = "timeout"

    if not stay:
        try:
            await rpc(host, port, make(MessageType.USER_BYE, token=token, user_id=uid))
            print(f"[{label}] logout", flush=True)
        except Exception as exc:
            print(f"[{label}] logout failed: {exc}", flush=True)
    else:
        print(f"[{label}] session kept online", flush=True)
    return result


async def snapshot_loop(host: str, port: int, token: str, stop: asyncio.Event, out: list) -> None:
    while not stop.is_set():
        try:
            m = await rpc(host, port, make(MessageType.METRICS, token=token), timeout=10)
            topo = (m or {}).get("topology") or {}
            gw = topo.get("gateway") or {}
            snap = {
                "t": round(time.time(), 2),
                "workers": gw.get("worker_count"),
                "users": gw.get("user_count"),
                "running_jobs": gw.get("running_jobs"),
                "intake_depth": gw.get("intake_depth"),
                "pending": gw.get("pending_tasks"),
                "assigned": gw.get("assigned_tasks"),
                "loads": {
                    w.get("worker_id"): w.get("load")
                    for w in (topo.get("workers") or [])
                },
            }
            out.append(snap)
            print(
                f"[cluster] jobs={snap['running_jobs']} intake={snap['intake_depth']} "
                f"tasks={snap['pending']}/{snap['assigned']} loads={snap['loads']}",
                flush=True,
            )
        except Exception as exc:
            print(f"[cluster] snap err {exc}", flush=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


async def _lookup_users(host: str, port: int, token: str) -> Dict[str, str]:
    m = await rpc(host, port, make(MessageType.METRICS, token=token), timeout=15)
    users = ((m or {}).get("topology") or {}).get("users") or []
    return {str(u.get("name")): str(u.get("user_id")) for u in users if u.get("name") and u.get("user_id")}


async def amain() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--master", default="13.217.224.71:9100")
    p.add_argument("--token", default="")
    p.add_argument("--chunks", type=int, default=6)
    p.add_argument(
        "--reuse-users",
        action="store_true",
        help="Submit as already-connected console users (no new hello/bye)",
    )
    args = p.parse_args()
    host, port_s = args.master.split(":")
    port = int(port_s)
    token = (args.token or os.environ.get("HPC_JOIN_TOKEN") or "").strip()

    reuse: Dict[str, str] = {}
    if args.reuse_users:
        reuse = await _lookup_users(host, port, token)
        for need in ("Eliza", "Bob"):
            if need not in reuse:
                print(f"[dual] missing online user {need}; online={list(reuse)}", flush=True)
                return 2
        print(f"[dual] reusing sessions {reuse}", flush=True)

    stop = asyncio.Event()
    snaps: list = []
    watcher = asyncio.create_task(snapshot_loop(host, port, token, stop, snaps))

    eliza = run_one(
        host,
        port,
        token,
        "Eliza",
        ROOT / "examples" / "matmul_eliza" / "train.py",
        ROOT / "examples" / "matmul_eliza" / "A.csv",
        args.chunks,
        "Eliza",
        reuse_user_id=reuse.get("Eliza"),
    )
    bob = run_one(
        host,
        port,
        token,
        "Bob",
        ROOT / "examples" / "matmul_bob" / "train.py",
        ROOT / "examples" / "matmul_bob" / "A.csv",
        args.chunks,
        "Bob",
        reuse_user_id=reuse.get("Bob"),
    )
    print("[dual] launching Eliza + Bob submits together…", flush=True)
    results = await asyncio.gather(eliza, bob)
    stop.set()
    await watcher

    print("\n=== RESULTS ===", flush=True)
    print(json.dumps({"results": results, "snapshots": snaps[-12:]}, indent=2))
    return 0 if all("error" not in r for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
