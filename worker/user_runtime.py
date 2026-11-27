"""Isolated runner for user-uploaded job packages.

Workers never import hardcoded ML trainers. Uploaded entrypoints must define:

    def train_shard(header, rows, params) -> dict

Execution happens in a child process (timeout + crash isolation) so a bad
user script cannot take down the worker agent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional


DRIVER = textwrap.dedent(
    r'''
    import csv, json, sys, traceback
    from pathlib import Path

    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    src = payload["train_source"]
    header = payload["header"]
    rows = payload["rows"]
    params = payload["params"]
    ns = {}
    try:
        exec(compile(src, "<userjob>", "exec"), ns, ns)
        fn = ns.get("train_shard")
        if not callable(fn):
            raise RuntimeError("entrypoint must define train_shard(header, rows, params)")
        out = fn(header, rows, params)
        if not isinstance(out, dict):
            raise RuntimeError("train_shard must return a dict")
        Path(sys.argv[2]).write_text(json.dumps({"ok": True, "result": out}), encoding="utf-8")
    except Exception as exc:
        Path(sys.argv[2]).write_text(
            json.dumps({"ok": False, "error": str(exc), "trace": traceback.format_exc()}),
            encoding="utf-8",
        )
        sys.exit(1)
    '''
).strip()


def run_user_shard(
    train_source: str,
    header: List[str],
    rows: List[str],
    params: Dict[str, Any],
    timeout_sec: float = 120.0,
) -> Dict[str, Any]:
    """Run uploaded code in a subprocess; return the shard result dict."""
    if not (train_source or "").strip():
        raise RuntimeError("userjob missing train_source")
    if not header or not rows:
        raise RuntimeError("userjob missing csv shard")

    with tempfile.TemporaryDirectory(prefix="lattice-userjob-") as td:
        tdir = Path(td)
        req = tdir / "request.json"
        resp = tdir / "response.json"
        driver = tdir / "driver.py"
        req.write_text(
            json.dumps({
                "train_source": train_source,
                "header": header,
                "rows": rows,
                "params": dict(params),
            }),
            encoding="utf-8",
        )
        driver.write_text(DRIVER, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONNOUSERSITE"] = "1"
        try:
            proc = subprocess.run(
                [sys.executable, str(driver), str(req), str(resp)],
                capture_output=True,
                text=True,
                timeout=max(1.0, float(timeout_sec)),
                env=env,
                cwd=str(tdir),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"userjob timed out after {timeout_sec}s") from exc

        if not resp.exists():
            err = (proc.stderr or proc.stdout or "").strip() or f"exit={proc.returncode}"
            raise RuntimeError(f"userjob failed with no result: {err}")

        data = json.loads(resp.read_text(encoding="utf-8"))
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "userjob failed")
        out = data.get("result")
        if not isinstance(out, dict):
            raise RuntimeError("userjob returned non-dict result")
        return out
