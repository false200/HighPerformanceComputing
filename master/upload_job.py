"""Upload a job package (code + data) to a *live* master, then submit.

This is the user path: no EC2 redeploy, no git pull on the gateway.
"""

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


async def rpc(host: str, port: int, msg: Dict[str, Any], timeout: float = 60.0) -> Optional[Dict[str, Any]]:
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


def _token(args: argparse.Namespace) -> str:
    return (args.token or os.environ.get("HPC_JOIN_TOKEN") or "").strip()


def load_files(mapping: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for dest, src in mapping.items():
        path = Path(src)
        if not path.is_absolute():
            path = ROOT / path
        out[dest] = path.read_text(encoding="utf-8")
    return out


async def upload_and_run(args: argparse.Namespace) -> int:
    host, port_s = args.master.split(":")
    port = int(port_s)
    tok = _token(args)
    files = load_files({
        args.dataset_name: args.dataset,
        args.entrypoint: args.train,
    })
    meta = {
        "dataset": args.dataset_name,
        "entrypoint": args.entrypoint,
        "label_col": args.label_col,
        "epochs": args.epochs,
        "lr": args.lr,
    }
    print(f"[user] uploading package to {host}:{port} files={list(files.keys())}")
    put = await rpc(
        host,
        port,
        make(
            MessageType.PACKAGE_PUT,
            token=tok,
            name=args.name,
            files=files,
            meta=meta,
        ),
    )
    if not put or not put.get("ok"):
        print("package upload failed:", put)
        return 1
    package_id = put["package_id"]
    print(f"[user] stored on platform as {package_id}")

    sub = await rpc(
        host,
        port,
        make(
            MessageType.JOB_SUBMIT,
            token=tok,
            kernel="userjob",
            policy=args.policy,
            chunks=args.chunks,
            deadline_sec=args.deadline,
            package_id=package_id,
            dataset=args.dataset_name,
            entrypoint=args.entrypoint,
            label_col=args.label_col,
            epochs=args.epochs,
            lr=args.lr,
        ),
    )
    if not sub or not sub.get("ok"):
        print("submit failed:", sub)
        return 1
    job_id = sub["job_id"]
    print(f"[user] job {job_id} tasks={sub.get('tasks')} — waiting for cluster…")

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
    p = argparse.ArgumentParser(description="Upload job package to live HPC gateway and run it")
    p.add_argument("--master", default="127.0.0.1:9100")
    p.add_argument("--token", default="")
    p.add_argument("--name", default="logistic-regression")
    p.add_argument("--train", default="examples/logistic_regression/train.py")
    p.add_argument("--dataset", default="examples/logistic_regression/data/exam_pass.csv")
    p.add_argument("--dataset-name", default="data.csv")
    p.add_argument("--entrypoint", default="train.py")
    p.add_argument("--label-col", default="passed")
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--lr", type=float, default=0.08)
    p.add_argument("--chunks", type=int, default=6)
    p.add_argument("--policy", default="campus_only")
    p.add_argument("--deadline", type=float, default=240.0)
    p.add_argument("--timeout", type=float, default=300.0)
    args = p.parse_args()
    raise SystemExit(asyncio.run(upload_and_run(args)))


if __name__ == "__main__":
    main()
