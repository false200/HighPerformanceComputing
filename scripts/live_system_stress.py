"""Live system / stress test against the real Lattice gateway.

Runs permutation + stress scenarios as a test engineer would:
  - connectivity / topology invariants
  - user session lifecycle
  - single + dual concurrent submits (Eliza/Bob packages)
  - chunk-size permutations
  - burst firehose (intake / load balance)
  - fair multi-user concurrency under load
  - worker utilization checks

Usage:
  py -3 scripts/live_system_stress.py --master 13.217.224.71:9100 --token $env:HPC_JOIN_TOKEN
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from protocol.messages import MessageType, decode, encode, make

ELIZA_TRAIN = ROOT / "examples" / "matmul_eliza" / "train.py"
ELIZA_DATA = ROOT / "examples" / "matmul_eliza" / "A.csv"
BOB_TRAIN = ROOT / "examples" / "matmul_bob" / "train.py"
BOB_DATA = ROOT / "examples" / "matmul_bob" / "A.csv"


@dataclass
class CaseResult:
    name: str
    ok: bool
    detail: str = ""
    elapsed_sec: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SuiteReport:
    cases: List[CaseResult] = field(default_factory=list)

    def add(self, c: CaseResult) -> None:
        self.cases.append(c)
        flag = "PASS" if c.ok else "FAIL"
        print(f"[{flag}] {c.name} ({c.elapsed_sec:.2f}s) {c.detail}", flush=True)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.ok)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.cases if not c.ok)


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


async def metrics(host: str, port: int, token: str) -> Dict[str, Any]:
    m = await rpc(host, port, make(MessageType.METRICS, token=token), timeout=20)
    return m or {}


def topo(m: Dict[str, Any]) -> Dict[str, Any]:
    return (m or {}).get("topology") or {}


async def ensure_user(host: str, port: int, token: str, name: str) -> str:
    m = await metrics(host, port, token)
    for u in topo(m).get("users") or []:
        if str(u.get("name")) == name and u.get("user_id"):
            uid = str(u["user_id"])
            await rpc(host, port, make(MessageType.USER_HEARTBEAT, token=token, user_id=uid))
            return uid
    hello = await rpc(host, port, make(MessageType.USER_HELLO, token=token, name=name))
    if not hello or not hello.get("ok"):
        raise RuntimeError(f"USER_HELLO failed for {name}: {hello}")
    return str(hello["user_id"])


async def submit_package_job(
    host: str,
    port: int,
    token: str,
    uid: str,
    train: Path,
    data: Path,
    chunks: int,
    label: str,
) -> Dict[str, Any]:
    put = await rpc(
        host,
        port,
        make(
            MessageType.PACKAGE_PUT,
            token=token,
            name=f"stress-{label}-{int(time.time()*1000)%100000}",
            files={
                "A.csv": data.read_text(encoding="utf-8"),
                "train.py": train.read_text(encoding="utf-8"),
            },
            meta={"dataset": "A.csv", "entrypoint": "train.py", "label_col": "tag"},
        ),
        timeout=120,
    )
    if not put or not put.get("ok"):
        raise RuntimeError(f"PACKAGE_PUT failed: {put}")
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
            package_id=put["package_id"],
            dataset="A.csv",
            entrypoint="train.py",
            label_col="tag",
            epochs=1,
            lr=0.0,
        ),
        timeout=60,
    )
    if not sub or not sub.get("ok"):
        raise RuntimeError(f"JOB_SUBMIT failed: {sub}")
    return sub


async def wait_user_job(
    host: str,
    port: int,
    token: str,
    uid: str,
    job_id: Optional[str],
    timeout: float = 180.0,
) -> Dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        await rpc(host, port, make(MessageType.USER_HEARTBEAT, token=token, user_id=uid), timeout=10)
        st = await rpc(
            host,
            port,
            make(MessageType.JOB_STATUS, token=token, user_id=uid, job_id=job_id),
            timeout=30,
        )
        if st and st.get("job_id"):
            job_id = st["job_id"]
        if st and st.get("finished"):
            return st
        await asyncio.sleep(0.35)
    raise TimeoutError(f"job {job_id} not finished in {timeout}s")


async def case(report: SuiteReport, name: str, fn) -> None:
    t0 = time.time()
    try:
        detail, metrics_out = await fn()
        report.add(CaseResult(name=name, ok=True, detail=detail, elapsed_sec=time.time() - t0, metrics=metrics_out or {}))
    except Exception as exc:
        report.add(
            CaseResult(
                name=name,
                ok=False,
                detail=f"{exc}",
                elapsed_sec=time.time() - t0,
                metrics={"trace": traceback.format_exc()[-800:]},
            )
        )


async def run_suite(host: str, port: int, token: str) -> SuiteReport:
    report = SuiteReport()

    # --- A. Connectivity / topology ---
    async def a_health():
        m = await metrics(host, port, token)
        t = topo(m)
        g = t.get("gateway") or {}
        assert g or m.get("running") is True or m.get("type") == "METRICS" or "workers" in m
        # health fields may be nested
        workers = t.get("workers") or m.get("workers") or []
        assert len(workers) >= 2, f"need >=2 workers, got {len(workers)}"
        names = {w.get("name") or w.get("worker_id") for w in workers}
        assert "Aejaz" in names and "Divyesh" in names, f"missing named workers: {names}"
        qb = (t.get("gateway") or {}).get("queue_backend") or (t.get("intake") or {}).get("backend")
        assert qb == "rabbitmq", f"queue_backend={qb}"
        return f"workers={sorted(names)} queue={qb}", {"workers": len(workers)}

    await case(report, "A1_topology_workers_rabbitmq", a_health)

    async def a_auth_reject():
        bad = await rpc(host, port, make(MessageType.JOB_SUBMIT, token="WRONG", kernel="batch", chunks=2))
        assert bad and bad.get("type") == MessageType.ERROR.value
        return "unauthorized rejected", {}

    await case(report, "A2_auth_rejects_bad_token", a_auth_reject)

    # --- B. User lifecycle ---
    async def b_user_lifecycle():
        name = f"QA-{int(time.time()) % 10000}"
        hello = await rpc(host, port, make(MessageType.USER_HELLO, token=token, name=name))
        assert hello and hello.get("ok")
        uid = hello["user_id"]
        hb = await rpc(host, port, make(MessageType.USER_HEARTBEAT, token=token, user_id=uid))
        assert hb and hb.get("ok")
        m = await metrics(host, port, token)
        assert any(u.get("user_id") == uid for u in topo(m).get("users") or [])
        bye = await rpc(host, port, make(MessageType.USER_BYE, token=token, user_id=uid))
        assert bye and bye.get("ok")
        await asyncio.sleep(0.5)
        m2 = await metrics(host, port, token)
        assert not any(u.get("user_id") == uid for u in topo(m2).get("users") or [])
        return f"session {uid} hello/hb/bye ok", {}

    await case(report, "B1_user_hello_heartbeat_bye", b_user_lifecycle)

    eliza = await ensure_user(host, port, token, "Eliza")
    bob = await ensure_user(host, port, token, "Bob")

    # --- C. Single-job permutations (chunks) ---
    for chunks in (2, 4, 6):
        async def c_single(ch=chunks):
            sub = await submit_package_job(
                host, port, token, eliza, ELIZA_TRAIN, ELIZA_DATA, ch, f"eliza-c{ch}"
            )
            st = await wait_user_job(host, port, token, eliza, sub.get("job_id"))
            assert st.get("failed", 0) == 0
            assert st.get("done") == st.get("total")
            assert int(st.get("total") or 0) == ch or int(st.get("total") or 0) <= ch
            return f"job={st.get('job_id')} {st.get('done')}/{st.get('total')}", {"chunks": ch}

        await case(report, f"C1_eliza_chunks_{chunks}", c_single)

    async def c_bob_single():
        sub = await submit_package_job(host, port, token, bob, BOB_TRAIN, BOB_DATA, 4, "bob-single")
        st = await wait_user_job(host, port, token, bob, sub.get("job_id"))
        assert st.get("finished") and st.get("failed", 0) == 0
        return f"job={st.get('job_id')} checksum={st.get('checksum')}", {}

    await case(report, "C2_bob_blocked_matmul", c_bob_single)

    # --- D. Concurrent dual-user ---
    async def d_dual():
        t0 = time.time()
        sub_e, sub_b = await asyncio.gather(
            submit_package_job(host, port, token, eliza, ELIZA_TRAIN, ELIZA_DATA, 4, "dual-e"),
            submit_package_job(host, port, token, bob, BOB_TRAIN, BOB_DATA, 4, "dual-b"),
        )
        st_e, st_b = await asyncio.gather(
            wait_user_job(host, port, token, eliza, sub_e.get("job_id")),
            wait_user_job(host, port, token, bob, sub_b.get("job_id")),
        )
        assert st_e.get("finished") and st_b.get("finished")
        assert st_e.get("failed", 0) == 0 and st_b.get("failed", 0) == 0
        # sample mid loads via quick metrics after submit (best-effort)
        return (
            f"Eliza {st_e.get('job_id')} + Bob {st_b.get('job_id')} wall={time.time()-t0:.1f}s",
            {"eliza_ck": st_e.get("checksum"), "bob_ck": st_b.get("checksum")},
        )

    await case(report, "D1_concurrent_eliza_bob", d_dual)

    # --- E. Burst / stress firehose ---
    async def e_burst():
        n = 12
        t0 = time.time()
        # fire without waiting
        subs = []
        for i in range(n):
            uid = eliza if i % 2 == 0 else bob
            train, data = (ELIZA_TRAIN, ELIZA_DATA) if uid == eliza else (BOB_TRAIN, BOB_DATA)
            subs.append(await submit_package_job(host, port, token, uid, train, data, 4, f"burst-{i}"))
            await asyncio.sleep(0.05)
        # observe utilization
        samples = []
        for _ in range(8):
            m = await metrics(host, port, token)
            g = topo(m).get("gateway") or {}
            loads = [int(w.get("load") or 0) for w in topo(m).get("workers") or []]
            samples.append({
                "running": g.get("running_jobs"),
                "pending": g.get("pending_tasks"),
                "assigned": g.get("assigned_tasks"),
                "intake": g.get("intake_depth"),
                "loads": loads,
                "sum_load": sum(loads),
            })
            await asyncio.sleep(0.4)
        # wait all
        waits = []
        for i, sub in enumerate(subs):
            uid = eliza if i % 2 == 0 else bob
            waits.append(wait_user_job(host, port, token, uid, sub.get("job_id"), timeout=240))
        results = await asyncio.gather(*waits, return_exceptions=True)
        fails = [r for r in results if isinstance(r, Exception) or (isinstance(r, dict) and r.get("failed"))]
        max_load = max((s["sum_load"] for s in samples), default=0)
        assert len(fails) == 0, f"burst failures: {fails[:2]}"
        assert max_load >= 1, "workers never showed load during burst"
        return (
            f"burst n={n} wall={time.time()-t0:.1f}s max_sum_load={max_load} samples={samples[-1]}",
            {"max_sum_load": max_load, "n": n},
        )

    await case(report, "E1_burst_12_alternating_users", e_burst)

    # --- F. Load balance / both workers used ---
    async def f_balance():
        # submit several jobs and check both workers accumulate done
        m0 = await metrics(host, port, token)
        done0 = {w.get("name"): int(w.get("tasks_done") or 0) for w in topo(m0).get("workers") or []}
        jobs = []
        for i in range(6):
            jobs.append(await submit_package_job(host, port, token, eliza, ELIZA_TRAIN, ELIZA_DATA, 4, f"bal-{i}"))
        await asyncio.gather(*[wait_user_job(host, port, token, eliza, s.get("job_id")) for s in jobs])
        m1 = await metrics(host, port, token)
        done1 = {w.get("name"): int(w.get("tasks_done") or 0) for w in topo(m1).get("workers") or []}
        dA = done1.get("Aejaz", 0) - done0.get("Aejaz", 0)
        dD = done1.get("Divyesh", 0) - done0.get("Divyesh", 0)
        assert dA > 0 and dD > 0, f"imbalanced or idle: delta Aejaz={dA} Divyesh={dD}"
        return f"delta tasks Aejaz={dA} Divyesh={dD}", {"delta_Aejaz": dA, "delta_Divyesh": dD}

    await case(report, "F1_both_workers_get_tasks", f_balance)

    # --- G. Rapid dual fire (stress overlap) ---
    async def g_overlap():
        async def spam(uid, train, data, n):
            outs = []
            for i in range(n):
                sub = await submit_package_job(host, port, token, uid, train, data, 2, f"ov-{uid[-4:]}-{i}")
                outs.append(sub)
            return outs

        se, sb = await asyncio.gather(
            spam(eliza, ELIZA_TRAIN, ELIZA_DATA, 5),
            spam(bob, BOB_TRAIN, BOB_DATA, 5),
        )
        # wait a subset / all
        await asyncio.gather(
            *[wait_user_job(host, port, token, eliza, s.get("job_id"), timeout=240) for s in se],
            *[wait_user_job(host, port, token, bob, s.get("job_id"), timeout=240) for s in sb],
        )
        return f"overlap 5+5 jobs completed", {"eliza": 5, "bob": 5}

    await case(report, "G1_overlap_5x5_dual_spam", g_overlap)

    # --- H. Final invariants ---
    async def h_final():
        m = await metrics(host, port, token)
        t = topo(m)
        workers = t.get("workers") or []
        assert len(workers) >= 2
        for w in workers:
            assert float(w.get("heartbeat_age_sec") or 0) < 15, f"stale worker {w}"
        lost = ((m.get("gcs") or {}).get("lost_objects"))
        if lost is None:
            lost = (t.get("gcs") or {}).get("lost_objects", 0)
        assert int(lost or 0) == 0
        return f"workers healthy lost_objects={lost}", {"workers": len(workers)}

    await case(report, "H1_final_invariants", h_final)

    return report


async def amain() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--master", default="13.217.224.71:9100")
    p.add_argument("--token", default="")
    p.add_argument("--out", default=str(ROOT / "data" / "logs" / "live_stress_report.json"))
    args = p.parse_args()
    host, port_s = args.master.split(":")
    port = int(port_s)
    token = (args.token or os.environ.get("HPC_JOIN_TOKEN") or "").strip()
    if not token:
        print("HPC_JOIN_TOKEN / --token required", flush=True)
        return 2
    for path in (ELIZA_TRAIN, ELIZA_DATA, BOB_TRAIN, BOB_DATA):
        if not path.exists():
            print(f"missing {path}", flush=True)
            return 2

    print(f"=== LIVE SYSTEM STRESS → {host}:{port} ===", flush=True)
    t0 = time.time()
    report = await run_suite(host, port, token)
    wall = time.time() - t0
    payload = {
        "master": f"{host}:{port}",
        "wall_sec": round(wall, 2),
        "passed": report.passed,
        "failed": report.failed,
        "total": len(report.cases),
        "cases": [
            {
                "name": c.name,
                "ok": c.ok,
                "detail": c.detail,
                "elapsed_sec": round(c.elapsed_sec, 3),
                "metrics": c.metrics,
            }
            for c in report.cases
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"\n=== SUMMARY {report.passed}/{len(report.cases)} passed, "
        f"{report.failed} failed, wall={wall:.1f}s ===",
        flush=True,
    )
    print(f"report: {out}", flush=True)
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
