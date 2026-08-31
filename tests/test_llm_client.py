"""Unit tests for the multi-provider endpoint rotation in agent/llm_client.py
— no network. Mocks the OpenAI client's chat.completions.create directly."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from openai import APIError, RateLimitError

from agent import llm_client

ALL_KEY_VARS = [
    "OPENROUTER_API_KEY", "OPENROUTER_API_KEYS",
    "GROQ_API_KEY", "GROQ_API_KEYS",
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


def _rate_limit_error_with_headers(message: str, headers: dict) -> RateLimitError:
    req = httpx2.Request("POST", "https://example.invalid/chat/completions")
    resp = httpx2.Response(429, request=req, headers=headers)
    return RateLimitError(message, response=resp, body=None)


def _make_response(payload: dict, prompt_tokens: int = 42, completion_tokens: int = 7) -> MagicMock:
    message = MagicMock()
    message.content = json.dumps(payload)
    message.reasoning = None
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    response.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
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
        result, meta = llm_client.chat_json("sys", "user")

    assert result == {"x": 1}
    assert meta == {"provider": "OPENROUTER", "model": "openrouter/free", "prompt_tokens": 42, "completion_tokens": 7}
    MockOpenAI.assert_called_once_with(api_key="key-a", base_url="https://openrouter.ai/api/v1")


def test_rotates_to_next_key_on_daily_cap(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEYS", "key-a,key-b")

    call_log: list = []
    with patch("agent.llm_client.OpenAI", side_effect=_fake_openai_factory(call_log, {"key-a": _daily_cap_error})):
        result, meta = llm_client.chat_json("sys", "user")

    assert result == {"ok": True}
    assert meta["provider"] == "OPENROUTER"
    assert [k for k, _ in call_log] == ["key-a", "key-b"]


def test_falls_through_to_next_provider_when_first_is_capped(monkeypatch):
    """The headline behaviour: OpenRouter's 50/day running out moves the run
    onto Groq rather than stopping it."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")

    call_log: list = []
    with patch("agent.llm_client.OpenAI", side_effect=_fake_openai_factory(call_log, {"or-key": _daily_cap_error})):
        result, meta = llm_client.chat_json("sys", "user")

    assert result == {"ok": True}
    assert meta["provider"] == "GROQ"
    assert call_log == [("or-key", "openrouter/free"), ("groq-key", "openai/gpt-oss-20b")]


def test_provider_order_is_openrouter_then_groq(monkeypatch):
    """Order is fixed by _PROVIDERS, not by which key happens to be set first
    in the environment — OpenRouter is preferred, Groq is the backup."""
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    endpoints = llm_client._load_endpoints()
    assert [e.provider for e in endpoints] == ["OPENROUTER", "GROQ"]


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
    "Rate limit exceeded: free-models-per-day",              # OpenRouter
    "Rate limit reached for model on requests per day (RPD)",  # Groq
    "Rate limit reached for model on tokens per day (TPD)",    # Groq
    "You exceeded your quota: generate_requests_per_model_per_day",  # underscore form
])
def test_daily_cap_detection_covers_each_provider_wording(message):
    assert llm_client._is_daily_cap_error(_rate_limit_error(message))


def test_transient_rate_limit_is_not_treated_as_daily_cap():
    assert not llm_client._is_daily_cap_error(_rate_limit_error("Rate limit reached, please slow down"))


# --- rotation semantics: the three failure shapes 1c distinguishes ---------


def test_quota_exhausted_rotates_away_permanently(monkeypatch):
    """Daily cap: the endpoint is dropped for the rest of this call, not
    retried, since no amount of waiting inside one call refills it."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")

    call_log: list = []
    with patch("agent.llm_client.OpenAI", side_effect=_fake_openai_factory(call_log, {"or-key": _daily_cap_error})):
        result, meta = llm_client.chat_json("sys", "user")

    assert result == {"ok": True}
    assert meta["provider"] == "GROQ"
    assert [k for k, _ in call_log] == ["or-key", "groq-key"]  # or-key tried exactly once, never again


def test_rate_limited_backs_off_and_retries_same_provider(monkeypatch):
    """A transient 429 (not a daily cap) must retry the SAME endpoint after
    backing off, using the provider's Retry-After header when it sends one
    — rotating away would abandon an endpoint that works again in seconds."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")  # present but must be untouched

    transient = _rate_limit_error_with_headers("Rate limit reached, please slow down", {"retry-after": "0"})

    call_log: list = []
    calls = {"n": 0}

    def fake_openai(api_key, base_url):
        client = MagicMock()

        def create(**kwargs):
            call_log.append((api_key, kwargs["model"]))
            calls["n"] += 1
            if calls["n"] == 1:
                raise transient
            return _make_response({"ok": True})

        client.chat.completions.create.side_effect = create
        return client

    with patch("agent.llm_client.OpenAI", side_effect=fake_openai), patch("agent.llm_client.time.sleep") as mock_sleep:
        result, meta = llm_client.chat_json("sys", "user")

    assert result == {"ok": True}
    assert meta["provider"] == "OPENROUTER"
    assert [k for k, _ in call_log] == ["or-key", "or-key"]  # retried the SAME provider, never touched groq-key
    mock_sleep.assert_called_once_with(0.0)  # honored Retry-After rather than guessing a backoff


def test_hard_error_rotates_to_next_endpoint(monkeypatch):
    """A hard API error (not a rate limit) rotates to the next endpoint
    rather than retrying the one that just failed."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")

    def hard_error():
        return APIError("internal server error", request=httpx2.Request("POST", "https://example.invalid"), body=None)

    call_log: list = []
    with (
        patch("agent.llm_client.OpenAI", side_effect=_fake_openai_factory(call_log, {"or-key": hard_error})),
        patch("agent.llm_client.time.sleep"),
    ):
        result, meta = llm_client.chat_json("sys", "user")

    assert result == {"ok": True}
    assert meta["provider"] == "GROQ"
    assert [k for k, _ in call_log] == ["or-key", "groq-key"]
