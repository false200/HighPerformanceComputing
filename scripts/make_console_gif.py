"""Capture Lattice console activity into docs/images/console-demo.gif."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "docs" / "images" / "gif_frames"
OUT = ROOT / "docs" / "images" / "console-demo.gif"
BACKEND = ROOT / "backend"


def health(host: str) -> dict:
    url = f"http://{host}:9101/health"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())


def main() -> int:
    token = (os.environ.get("HPC_JOIN_TOKEN") or "").strip()
    if not token:
        tok = ROOT / "key" / "join_token.txt"
        if tok.exists():
            token = tok.read_text(encoding="utf-8").strip()
    if not token:
        print("HPC_JOIN_TOKEN required", flush=True)
        return 2

    master = os.environ.get("HPC_MASTER", "13.217.224.71:9100")
    host = master.split(":")[0]
    console = os.environ.get("HPC_CONSOLE", f"http://{host}:8080/")

    h = health(host)
    if int(h.get("workers") or 0) < 2:
        print(f"need >=2 workers online, got {h}", flush=True)
        return 3
    print(f"workers online: {h.get('workers')}", flush=True)

    FRAMES.mkdir(parents=True, exist_ok=True)
    for old in FRAMES.glob("*.png"):
        old.unlink()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND)
    env["HPC_JOIN_TOKEN"] = token

    procs: list[subprocess.Popen] = []
    for _ in range(2):
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "dual_matmul_submit.py"),
                    "--master",
                    master,
                    "--token",
                    token,
                    "--chunks",
                    "8",
                ],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        time.sleep(1.2)

    from playwright.sync_api import sync_playwright
    from PIL import Image

    paths: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(console, wait_until="networkidle", timeout=60000)
        # wait until users show up in the ticker
        for _ in range(20):
            page.wait_for_timeout(500)
            txt = page.locator("#p-users").inner_text()
            if txt.strip() not in ("—", "0", ""):
                break
        page.wait_for_timeout(800)

        for i in range(14):
            path = FRAMES / f"frame_{i:02d}.png"
            page.screenshot(path=str(path), full_page=False)
            paths.append(path)
            print(f"frame {i + 1}/14 users={page.locator('#p-users').inner_text()} "
                  f"peers={page.locator('#p-workers').inner_text()}", flush=True)
            page.wait_for_timeout(1200)
        browser.close()

    for proc in procs:
        if proc.poll() is None:
            proc.terminate()

    frames = []
    for path in paths:
        im = Image.open(path).convert("P", palette=Image.ADAPTIVE, colors=96)
        frames.append(im)

    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=320,
        loop=0,
        optimize=True,
    )
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
