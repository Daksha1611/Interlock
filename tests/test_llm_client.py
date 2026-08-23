"""Unit tests for the multi-provider endpoint rotation in agent/llm_client.py
— no network. Mocks the OpenAI client's chat.completions.create directly."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from openai import RateLimitError

from agent import llm_client

ALL_KEY_VARS = [
    "OPENROUTER_API_KEY", "OPENROUTER_API_KEYS",
    "GROQ_API_KEY", "GROQ_API_KEYS",
    "GEMINI_API_KEY", "GEMINI_API_KEYS",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Module-level client cache / endpoint pointer must not leak between
    tests, and a real key in the developer's .env must not leak in either."""
    for var in ALL_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    llm_client._clients.clear()
    llm_client._current_endpoint_idx[0] = 0
    yield
    llm_client._clients.clear()
    llm_client._current_endpoint_idx[0] = 0


def _rate_limit_error(message: str) -> RateLimitError:
    req = httpx2.Request("POST", "https://example.invalid/chat/completions")
    resp = httpx2.Response(429, request=req)
    return RateLimitError(message, response=resp, body=None)


def _daily_cap_error() -> RateLimitError:
    return _rate_limit_error("Rate limit exceeded: free-models-per-day")


def _make_response(payload: dict) -> MagicMock:
    message = MagicMock()
    message.content = json.dumps(payload)
    message.reasoning = None
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    return response


def _fake_openai_factory(call_log: list, failing: dict):
    """Builds an OpenAI() stand-in that logs the key used and raises whatever
    `failing` maps that key to."""
    def fake_openai(api_key, base_url):
        client = MagicMock()

        def create(**kwargs):
            call_log.append((api_key, kwargs["model"]))
            if api_key in failing:
                raise failing[api_key]()
            return _make_response({"ok": True})

        client.chat.completions.create.side_effect = create
        return client

    return fake_openai


def test_single_key_success(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-a")

    with patch("agent.llm_client.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = _make_response({"x": 1})
        result = llm_client.chat_json("sys", "user")

    assert result == {"x": 1}
    MockOpenAI.assert_called_once_with(api_key="key-a", base_url="https://openrouter.ai/api/v1")


def test_rotates_to_next_key_on_daily_cap(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEYS", "key-a,key-b")

    call_log: list = []
    with patch("agent.llm_client.OpenAI", side_effect=_fake_openai_factory(call_log, {"key-a": _daily_cap_error})):
        result = llm_client.chat_json("sys", "user")

    assert result == {"ok": True}
    assert [k for k, _ in call_log] == ["key-a", "key-b"]


def test_falls_through_to_next_provider_when_first_is_capped(monkeypatch):
    """The headline behaviour: OpenRouter's 50/day running out moves the run
    onto Groq rather than stopping it."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")

    call_log: list = []
    with patch("agent.llm_client.OpenAI", side_effect=_fake_openai_factory(call_log, {"or-key": _daily_cap_error})):
        result = llm_client.chat_json("sys", "user")

    assert result == {"ok": True}
    assert call_log == [("or-key", "openrouter/free"), ("groq-key", "openai/gpt-oss-20b")]


def test_provider_order_is_openrouter_then_groq_then_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    endpoints = llm_client._load_endpoints()
    assert [e.provider for e in endpoints] == ["OPENROUTER", "GROQ", "GEMINI"]


def test_per_provider_model_override_is_used(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("GROQ_MODEL", "custom-model")

    call_log: list = []
    with patch("agent.llm_client.OpenAI", side_effect=_fake_openai_factory(call_log, {})):
        llm_client.chat_json("sys", "user")

    assert call_log == [("groq-key", "custom-model")]


def test_remembers_working_endpoint_across_calls(monkeypatch):
    """After key-a is exhausted once, subsequent calls in the same process
    should start from key-b directly, not re-try the known-bad key first."""
    monkeypatch.setenv("OPENROUTER_API_KEYS", "key-a,key-b")

    call_log: list = []
    with patch("agent.llm_client.OpenAI", side_effect=_fake_openai_factory(call_log, {"key-a": _daily_cap_error})):
        llm_client.chat_json("sys", "user")
        call_log.clear()
        llm_client.chat_json("sys", "user")

    assert [k for k, _ in call_log] == ["key-b"]


def test_daily_capped_endpoint_is_not_retried_within_a_call(monkeypatch):
    """A capped endpoint should be skipped for the rest of the call rather
    than consuming attempts that the healthy endpoints could use."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")

    call_log: list = []
    failing = {"or-key": _daily_cap_error, "groq-key": lambda: _rate_limit_error("rate limit, try again")}
    with (
        patch("agent.llm_client.OpenAI", side_effect=_fake_openai_factory(call_log, failing)),
        patch("agent.llm_client.time.sleep"),
        pytest.raises(RuntimeError),
    ):
        llm_client.chat_json("sys", "user", max_retries=3)

    keys_used = [k for k, _ in call_log]
    assert keys_used.count("or-key") == 1  # capped once, then skipped
    assert keys_used.count("groq-key") > 1  # transient limit, so it keeps being retried


def test_all_endpoints_capped_raises_without_sleeping(monkeypatch):
    """Waiting can't refill a daily quota, so an all-capped call must fail
    fast rather than burn the backoff schedule."""
    monkeypatch.setenv("OPENROUTER_API_KEYS", "key-a,key-b")

    with patch("agent.llm_client.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.side_effect = _daily_cap_error()
        with (
            patch("agent.llm_client.time.sleep") as mock_sleep,
            pytest.raises(RuntimeError, match="2 endpoint"),
        ):
            llm_client.chat_json("sys", "user", max_retries=4)

    mock_sleep.assert_not_called()


def test_no_keys_configured_raises_helpful_error():
    with pytest.raises(RuntimeError, match="No LLM API key"):
        llm_client.chat_json("sys", "user")


@pytest.mark.parametrize("message", [
    "Rate limit exceeded: free-models-per-day",
    "Rate limit reached for model on requests per day (RPD)",
    "Rate limit reached for model on tokens per day (TPD)",
    "You exceeded your quota: generate_requests_per_model_per_day",
])
def test_daily_cap_detection_covers_each_provider_wording(message):
    assert llm_client._is_daily_cap_error(_rate_limit_error(message))


def test_transient_rate_limit_is_not_treated_as_daily_cap():
    assert not llm_client._is_daily_cap_error(_rate_limit_error("Rate limit reached, please slow down"))
