"""Upload a job package (code + data) to a *live* master, then submit.

User path: register on the console (visible like a worker), heartbeat while
waiting, logout on exit — no EC2 redeploy, no git pull on the gateway.
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

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = BACKEND_ROOT.parent  # project root (config/, key/, examples/)
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

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


async def _heartbeat_loop(host: str, port: int, tok: str, user_id: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await rpc(
                host,
                port,
                make(MessageType.USER_HEARTBEAT, token=tok, user_id=user_id),
                timeout=10.0,
            )
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pass


async def upload_and_run(args: argparse.Namespace) -> int:
    host, port_s = args.master.split(":")
    port = int(port_s)
    tok = _token(args)
    user_id: Optional[str] = None
    stop_hb = asyncio.Event()
    hb_task: Optional[asyncio.Task] = None

    try:
        hello = await rpc(
            host,
            port,
            make(MessageType.USER_HELLO, token=tok, name=args.user_name),
        )
        if not hello or not hello.get("ok"):
            print("user hello failed:", hello)
            return 1
        user_id = str(hello["user_id"])
        print(f"[user] online as {user_id} ({hello.get('name')}) — visible on Lattice")
        hb_task = asyncio.create_task(_heartbeat_loop(host, port, tok, user_id, stop_hb))

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
                user_id=user_id,
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
            err = (sub or {}).get("error") or "submit failed"
            if "no workers" in str(err).lower():
                print("\n*** no workers connected ***", flush=True)
                print("Ask a friend to run Worker.bat, then submit again.\n", flush=True)
            else:
                print(f"submit failed: {err}", flush=True)
                if sub:
                    print(sub, flush=True)
            return 3

        job_id = sub.get("job_id")
        if sub.get("queued") and not job_id:
            print(
                f"[user] intake queued {sub.get('queue_id')} position={sub.get('position')} "
                f"— waiting for capacity…",
                flush=True,
            )
        else:
            print(f"[user] job {job_id} tasks={sub.get('tasks')} — waiting for cluster…")

        t0 = time.time()
        while time.time() - t0 < args.timeout:
            st = await rpc(
                host,
                port,
                make(
                    MessageType.JOB_STATUS,
                    token=tok,
                    user_id=user_id,
                    job_id=job_id,
                ),
            )
            if not st:
                await asyncio.sleep(0.5)
                continue
            if st.get("type") == MessageType.ERROR.value and not job_id:
                await asyncio.sleep(0.5)
                continue
            if st.get("queued") and not st.get("job_id"):
                print(f"queued depth≈{st.get('position')}…", flush=True)
                await asyncio.sleep(0.8)
                continue
            if st.get("job_id"):
                job_id = st.get("job_id")
            print(f"progress {st.get('done')}/{st.get('total')}", flush=True)
            if st.get("finished"):
                print(json.dumps(st, indent=2))
                return 0
            await asyncio.sleep(0.5)
        print("timeout waiting for job")
        return 2
    finally:
        stop_hb.set()
        if hb_task:
            try:
                await asyncio.wait_for(hb_task, timeout=2.0)
            except Exception:
                hb_task.cancel()
        if user_id:
            try:
                await rpc(
                    host,
                    port,
                    make(MessageType.USER_BYE, token=tok, user_id=user_id),
                    timeout=10.0,
                )
                print(f"[user] logout {user_id}")
            except Exception as exc:
                print(f"[user] logout failed: {exc}")


def main() -> None:
    p = argparse.ArgumentParser(description="Upload job package to live HPC gateway and run it")
    p.add_argument("--master", default="127.0.0.1:9100")
    p.add_argument("--token", default="")
    p.add_argument("--user-name", default="submitter")
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
