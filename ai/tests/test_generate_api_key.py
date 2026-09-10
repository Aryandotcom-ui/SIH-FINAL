from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.person_c_generation.generate import call_llm


def _fake_openai_module(captured: dict):
    module = MagicMock()

    class FakeClient:
        def __init__(self, api_key, base_url):
            captured["api_key"] = api_key
            captured["base_url"] = base_url

            self.chat = MagicMock()

            response = MagicMock()
            response.choices = [
                MagicMock(
                    message=MagicMock(
                        content='{"answer_text":"ok","citations":[],"abstained":false}'
                    )
                )
            ]

            self.chat.completions.create.return_value = response

    module.OpenAI.side_effect = FakeClient

    return module


def test_call_llm_uses_explicit_groq_api_key(monkeypatch):
    captured = {}

    monkeypatch.setitem(
        sys.modules,
        "openai",
        _fake_openai_module(captured),
    )

    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    result = call_llm(
        "test prompt",
        api_key="explicit-groq-key",
    )

    assert captured["api_key"] == "explicit-groq-key"
    assert captured["base_url"] == "https://api.groq.com/openai/v1"
    assert "ok" in result


def test_call_llm_falls_back_to_groq_environment_key(monkeypatch):
    captured = {}

    monkeypatch.setitem(
        sys.modules,
        "openai",
        _fake_openai_module(captured),
    )

    monkeypatch.setenv(
        "GROQ_API_KEY",
        "environment-groq-key",
    )

    call_llm("test prompt")

    assert captured["api_key"] == "environment-groq-key"


def test_call_llm_requires_groq_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(
        RuntimeError,
        match="GROQ_API_KEY",
    ):
        call_llm("test prompt")
