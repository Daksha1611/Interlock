"""Unit tests for the multi-key rotation in agent/llm_client.py — no
network. Mocks the OpenAI client's chat.completions.create directly."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from openai import RateLimitError

import agent.llm_client as llm_client


@pytest.fixture(autouse=True)
def reset_module_state(monkeypatch):
    """Module-level client cache / key pointer must not leak between tests."""
    llm_client._clients.clear()
    llm_client._current_key_idx[0] = 0
    yield
    llm_client._clients.clear()
    llm_client._current_key_idx[0] = 0


def _daily_cap_error() -> RateLimitError:
    req = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx2.Response(429, request=req)
    return RateLimitError("Rate limit exceeded: free-models-per-day", response=resp, body=None)


def _make_response(payload: dict) -> MagicMock:
    message = MagicMock()
    message.content = json.dumps(payload)
    message.reasoning = None
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    return response


def test_single_key_success(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-a")
    monkeypatch.delenv("OPENROUTER_API_KEYS", raising=False)

    with patch("agent.llm_client.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = _make_response({"x": 1})
        result = llm_client.chat_json("sys", "user")

    assert result == {"x": 1}
    MockOpenAI.assert_called_once_with(api_key="key-a", base_url=llm_client._DEFAULT_BASE_URL)


def test_rotates_to_next_key_on_daily_cap(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEYS", "key-a,key-b")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    call_log = []

    def fake_openai(api_key, base_url):
        client = MagicMock()

        def create(**kwargs):
            call_log.append(api_key)
            if api_key == "key-a":
                raise _daily_cap_error()
            return _make_response({"ok": True})

        client.chat.completions.create.side_effect = create
        return client

    with patch("agent.llm_client.OpenAI", side_effect=fake_openai):
        result = llm_client.chat_json("sys", "user")

    assert result == {"ok": True}
    assert call_log == ["key-a", "key-b"]


def test_remembers_working_key_across_calls(monkeypatch):
    """After key-a is exhausted once, subsequent calls in the same process
    should start from key-b directly, not re-try the known-bad key first."""
    monkeypatch.setenv("OPENROUTER_API_KEYS", "key-a,key-b")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    call_log = []

    def fake_openai(api_key, base_url):
        client = MagicMock()

        def create(**kwargs):
            call_log.append(api_key)
            if api_key == "key-a":
                raise _daily_cap_error()
            return _make_response({"ok": True})

        client.chat.completions.create.side_effect = create
        return client

    with patch("agent.llm_client.OpenAI", side_effect=fake_openai):
        llm_client.chat_json("sys", "user")
        call_log.clear()
        llm_client.chat_json("sys", "user")

    assert call_log == ["key-b"]


def test_all_keys_exhausted_raises_clear_error(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEYS", "key-a,key-b")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with patch("agent.llm_client.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.side_effect = _daily_cap_error()
        with pytest.raises(RuntimeError, match="2 key"):
            llm_client.chat_json("sys", "user", max_retries=1)


def test_no_keys_configured_raises_helpful_error(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="No OpenRouter API key"):
        llm_client.chat_json("sys", "user")
