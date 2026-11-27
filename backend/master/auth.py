from __future__ import annotations

import hmac
import os
from typing import Any, Dict, Optional


def resolve_join_token(cfg: Dict[str, Any]) -> str:
    """Prefer env so secrets never need to sit in git-tracked YAML."""
    env = (os.environ.get("HPC_JOIN_TOKEN") or "").strip()
    if env:
        return env
    auth = cfg.get("auth") or {}
    return str(auth.get("join_token") or "").strip()


def token_ok(provided: Optional[str], expected: str) -> bool:
    if not expected:
        # Dev/local mode: open pool when no token configured
        return True
    got = (provided or "").strip()
    if not got:
        return False
    return hmac.compare_digest(got.encode("utf-8"), expected.encode("utf-8"))


def require_enterprise_token(cfg: Dict[str, Any]) -> bool:
    auth = cfg.get("auth") or {}
    return bool(auth.get("require_token", False)) or bool(resolve_join_token(cfg))
