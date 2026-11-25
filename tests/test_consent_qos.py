from worker.consent import CONSENT_TEXT, prompt_consent
from worker.qos import effective_threads


def test_consent_text_covers_pdf_points():
    lower = CONSENT_TEXT.lower()
    assert "purpose" in lower
    assert "personal file" in lower or "personal files" in lower
    assert "leave" in lower
    assert "cpu" in lower


def test_auto_consent(monkeypatch):
    assert prompt_consent(auto=True) is True


def test_cpu_cap():
    assert effective_threads(8, 2) == 2
    assert effective_threads(8, 0) == 8
    assert effective_threads(2, 8) == 2
