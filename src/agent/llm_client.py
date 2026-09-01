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
    # Verified reachable via Google's OpenAI-compatibility endpoint (single
    # live call, 2026-08-31): gemini-2.5-flash is retired for new callers,
    # gemini-3.6-flash responds 200 with a normal usage block. Not wired
    # into .env — see .env.example for why.
    ("GOOGLE", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.6-flash"),
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


def configured_endpoints() -> list[dict]:
    """Which provider/model the agent would actually use, in preference
    order. Recorded into evaluation reports so a result can be tied back to
    the model that produced it — trap rates are not comparable across
    models, so a report without this is not reproducible evidence."""
    return [{"provider": e.provider, "model": e.model} for e in _load_endpoints()]


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


def _retry_after_seconds(e: RateLimitError) -> float | None:
    """Prefer the provider's own Retry-After header over a guessed backoff —
    it's a direct answer to "how long until this endpoint works again"
    rather than an approximation of it."""
    response = getattr(e, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        return None


def _usage_meta(ep: _Endpoint, response) -> dict:
    usage = getattr(response, "usage", None)
    return {
        "provider": ep.provider,
        "model": ep.model,
        "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage is not None else None,
        "completion_tokens": getattr(usage, "completion_tokens", None) if usage is not None else None,
    }


def chat_json(system: str, user: str, max_tokens: int = 700, max_retries: int = 4) -> tuple[dict, dict]:
    """Call the model, expecting a single JSON object back. Returns
    `(parsed_json, usage_meta)` — the second element records which
    provider/model actually answered and how many tokens it cost, so a
    caller can attribute spend instead of it disappearing into the call.

    Three failure shapes, handled differently:
    - daily quota exhausted: no amount of waiting inside this call refills
      it, so the endpoint is dropped for the rest of the call (permanent
      rotation).
    - transient rate limit (a per-minute ceiling): the SAME endpoint is
      retried after backing off — rotating away would abandon an endpoint
      that will work again in seconds, wasting a healthy one's budget for
      nothing gained.
    - a hard error (network, 5xx, malformed output): rotate to the next
      endpoint, since retrying the same one is unlikely to fare better.
    """
    endpoints = _load_endpoints()
    n = len(endpoints)
    idx = _current_endpoint_idx[0] % n
    max_total_attempts = max_retries * n

    last_err: Exception | None = None
    backoff_step = 0
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
            meta = _usage_meta(ep, response)
            choices = getattr(response, "choices", None)
            if not choices:
                # Observed live on OpenRouter's free auto-router: an
                # otherwise-200 response with choices=None. Left unguarded
                # this raises an unhandled TypeError that skips every
                # rotation branch below and kills the whole call outright —
                # exactly the kind of malformed-output case a hard error
                # should be, not a crash.
                raise ValueError(f"{ep.provider} returned a response with no choices")
            message = choices[0].message
            content = message.content or ""
            try:
                return _extract_json(content), meta
            except ValueError:
                # Some reasoning models write the answer into a separate
                # `reasoning` field when they run long — fall back to it
                # before giving up and retrying.
                reasoning = getattr(message, "reasoning", None) or ""
                return _extract_json(reasoning), meta
        except RateLimitError as e:
            last_err = e
            if _is_daily_cap_error(e):
                capped.add(slot)
                if len(capped) == n:
                    break  # every endpoint is out of daily quota
                idx += 1
            else:
                # transient: back off and retry this SAME slot, not the next
                wait = _retry_after_seconds(e)
                if wait is None:
                    wait = min(2**backoff_step * 2, 30)
                time.sleep(wait)
                backoff_step += 1
        except (APIError, ValueError, json.JSONDecodeError) as e:
            # Hard error: network/5xx, a malformed response, or output that
            # never parsed as JSON even from the reasoning fallback. Retrying
            # the same endpoint is unlikely to fare better, so rotate.
            last_err = e
            time.sleep(min(2**backoff_step, 10))
            backoff_step += 1
            idx += 1

    raise RuntimeError(
        f"LLM call failed across {n} endpoint(s) "
        f"({', '.join(sorted({e.provider for e in endpoints}))}): {last_err}"
    ) from last_err
