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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from protocol.messages import MessageType, decode, encode, make


async def rpc(host: str, port: int, msg: Dict[str, Any], timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(encode(msg))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        return decode(line)
    finally:
        writer.close()
        await writer.wait_closed()


def _token(args: argparse.Namespace) -> str:
    return (args.token or os.environ.get("HPC_JOIN_TOKEN") or "").strip()


async def submit_and_wait(args: argparse.Namespace) -> int:
    host, port_s = args.master.split(":")
    port = int(port_s)
    tok = _token(args)
    payload = {
        "kernel": args.kernel,
        "policy": args.policy,
        "chunks": args.chunks,
        "deadline_sec": args.deadline,
        "token": tok,
    }
    for key in ("dataset", "label_col", "epochs", "lr", "n_rows", "n_samples", "n_features"):
        val = getattr(args, key, None)
        if val is None or val == "":
            continue
        payload[key] = val
    sub = await rpc(host, port, make(MessageType.JOB_SUBMIT, **payload))
    if not sub or not sub.get("ok"):
        print("submit failed:", sub)
        return 1
    job_id = sub["job_id"]
    print(f"submitted job {job_id} tasks={sub.get('tasks')}")
    if args.force_burst:
        await rpc(host, port, make(MessageType.FORCE_BURST, enabled=True, token=tok))
        print("force-burst enabled")

    t0 = time.time()
    while time.time() - t0 < args.timeout:
        st = await rpc(host, port, make(MessageType.JOB_STATUS, job_id=job_id, token=tok))
        if not st:
            await asyncio.sleep(0.5)
            continue
        print(f"progress {st.get('done')}/{st.get('total')}", flush=True)
        if st.get("finished"):
            print(json.dumps(st, indent=2))
            return 0
        await asyncio.sleep(0.5)
    print("timeout waiting for job")
    return 2


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--master", default="127.0.0.1:9100")
    p.add_argument(
        "--kernel",
        default="heat2d",
        choices=["heat2d", "batch", "irregular", "logreg", "linreg"],
    )
    p.add_argument("--policy", default="hybrid", choices=["hybrid", "campus_only", "cloud_only"])
    p.add_argument("--chunks", type=int, default=8)
    p.add_argument("--deadline", type=float, default=120.0)
    p.add_argument("--timeout", type=float, default=180.0)
    p.add_argument("--force-burst", action="store_true")
    p.add_argument("--token", default="", help="Operator/join token (or HPC_JOIN_TOKEN)")
    p.add_argument("--dataset", default="", help="CSV path relative to repo (logreg/linreg)")
    p.add_argument("--label-col", dest="label_col", default="", help="Label column name")
    p.add_argument("--epochs", type=int, default=None)
    p.add_argument("--lr", type=float, default=None)
    p.add_argument("--n-rows", dest="n_rows", type=int, default=None)
    p.add_argument("--n-samples", dest="n_samples", type=int, default=None)
    p.add_argument("--n-features", dest="n_features", type=int, default=None)
    args = p.parse_args()
    raise SystemExit(asyncio.run(submit_and_wait(args)))


if __name__ == "__main__":
    main()
