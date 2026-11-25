import hmac

from master.auth import resolve_join_token, token_ok


def test_token_ok_matches():
    assert token_ok("secret", "secret")
    assert not token_ok("nope", "secret")
    assert not token_ok("", "secret")
    assert token_ok("", "")  # open lab
    assert token_ok(None, "")


def test_resolve_prefers_env(monkeypatch):
    monkeypatch.setenv("HPC_JOIN_TOKEN", "from-env")
    assert resolve_join_token({"auth": {"join_token": "from-yaml"}}) == "from-env"
    monkeypatch.delenv("HPC_JOIN_TOKEN", raising=False)
    assert resolve_join_token({"auth": {"join_token": "from-yaml"}}) == "from-yaml"


def test_compare_digest_style():
    a = "abc"
    b = "abc"
    assert hmac.compare_digest(a.encode(), b.encode())
