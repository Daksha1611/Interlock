"""Thin LLM client. This is the ONLY place an LLM is called from in this
whole codebase — gate/, world/, baselines/, eval/ never touch it (see
tests/test_isolation.py). Calling this produces a *proposal*; it has no
path to money or customer contact by itself.

Every provider used here speaks the OpenAI chat-completions wire format, so
one client library covers all of them and only the base URL, key, and model
name differ. Endpoints are tried in configured order and rotate on rate
limits, which lets a run draw on several free tiers back to back instead of
stopping when the first one is spent. See .env.example for the variables.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import APIError, OpenAI, RateLimitError

load_dotenv()


@dataclass(frozen=True)
class _Endpoint:
    provider: str
    api_key: str
    base_url: str
    model: str


# Order matters: earlier providers are preferred, later ones are the fallback
# once the earlier tiers are spent for the day. Adding a provider is one more
# entry here plus its keys in the environment, as long as it speaks the
# OpenAI chat-completions format.
_PROVIDERS = (
    ("OPENROUTER", "https://openrouter.ai/api/v1", "openrouter/free"),
    ("GROQ", "https://api.groq.com/openai/v1", "openai/gpt-oss-20b"),
)

_clients: dict[tuple[str, str], OpenAI] = {}
_current_endpoint_idx = [0]  # mutable box: survives across calls in one process


def _keys_for(prefix: str) -> list[str]:
    csv = os.environ.get(f"{prefix}_API_KEYS")
    if csv:
        return [k.strip() for k in csv.split(",") if k.strip()]
    single = os.environ.get(f"{prefix}_API_KEY")
    return [single.strip()] if single and single.strip() else []


def _load_endpoints() -> list[_Endpoint]:
    endpoints = []
    for prefix, default_base, default_model in _PROVIDERS:
        base_url = os.environ.get(f"{prefix}_BASE_URL", default_base)
        model = os.environ.get(f"{prefix}_MODEL", default_model)
        for key in _keys_for(prefix):
            endpoints.append(_Endpoint(prefix, key, base_url, model))
    if not endpoints:
        raise RuntimeError(
            "No LLM API key found. Set OPENROUTER_API_KEY(S) and/or "
            "GROQ_API_KEY(S) — copy .env.example to .env and fill one in."
        )
    return endpoints


def _client_for(ep: _Endpoint) -> OpenAI:
    cache_key = (ep.base_url, ep.api_key)
    if cache_key not in _clients:
        _clients[cache_key] = OpenAI(api_key=ep.api_key, base_url=ep.base_url)
    return _clients[cache_key]


_DAILY_CAP_RE = re.compile(
    r"per[-_ ]day"       # OpenRouter says "free-models-per-day"; separators vary by provider
    r"|per[-_ ]diem"
    r"|\b[rt]pd\b"       # Groq spells the daily ceilings RPD / TPD
    r"|daily (?:limit|quota)",
    re.IGNORECASE,
)


def _is_daily_cap_error(e: Exception) -> bool:
    """A per-day quota can't be waited out inside one run, so it means 'move
    to the next endpoint' rather than 'back off'. Each provider words it
    differently."""
    return bool(_DAILY_CAP_RE.search(str(e)))


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(text)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"could not extract JSON from model output: {text[:300]!r}")


def chat_json(system: str, user: str, max_tokens: int = 700, max_retries: int = 4) -> dict:
    """Call the model, expecting a single JSON object back.

    A per-day quota error moves straight to the next endpoint (waiting can't
    refill a daily quota). A per-minute limit also moves on first, since a
    different provider's minute budget is independent; only once every
    endpoint is rate-limited in the same lap does it back off and sleep.
    """
    endpoints = _load_endpoints()
    n = len(endpoints)
    idx = _current_endpoint_idx[0] % n
    max_total_attempts = max_retries * n

    last_err: Exception | None = None
    backoff_step = 0
    rate_limited_streak = 0
    capped: set[int] = set()

    for _ in range(max_total_attempts):
        while idx % n in capped:
            idx += 1
        slot = idx % n
        ep = endpoints[slot]
        try:
            response = _client_for(ep).chat.completions.create(
                model=ep.model,
                max_tokens=max_tokens,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            _current_endpoint_idx[0] = slot  # remember what worked for the next call
            message = response.choices[0].message
            content = message.content or ""
            try:
                return _extract_json(content)
            except ValueError:
                # Some reasoning models write the answer into a separate
                # `reasoning` field when they run long — fall back to it
                # before giving up and retrying.
                reasoning = getattr(message, "reasoning", None) or ""
                return _extract_json(reasoning)
        except RateLimitError as e:
            last_err = e
            if _is_daily_cap_error(e):
                capped.add(slot)
                if len(capped) == n:
                    break  # every endpoint is out of daily quota
            else:
                rate_limited_streak += 1
                if rate_limited_streak >= n - len(capped):
                    time.sleep(min(2**backoff_step * 2, 30))
                    backoff_step += 1
                    rate_limited_streak = 0
            idx += 1
        except APIError as e:
            last_err = e
            time.sleep(min(2**backoff_step, 10))
            backoff_step += 1
            idx += 1
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(1)

    raise RuntimeError(
        f"LLM call failed across {n} endpoint(s) "
        f"({', '.join(sorted({e.provider for e in endpoints}))}): {last_err}"
    ) from last_err
