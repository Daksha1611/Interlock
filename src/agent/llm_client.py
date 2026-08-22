"""Thin OpenRouter client. This is the ONLY place an LLM is called from in
this whole codebase — gate/, world/, baselines/, eval/ never touch it (see
tests/test_isolation.py). Calling this produces a *proposal*; it has no
path to money or customer contact by itself.

Supports rotating across multiple free-tier API keys: each OpenRouter
account's free-model quota is 50 requests/day, so a multi-key setup (one
key per account) raises the effective daily ceiling for this project's
testing without paying. Set OPENROUTER_API_KEYS to a comma-separated list;
OPENROUTER_API_KEY (single key) still works unchanged.
"""

from __future__ import annotations

import json
import os
import re
import time

from dotenv import load_dotenv
from openai import APIError, OpenAI, RateLimitError

load_dotenv()

_DEFAULT_MODEL = "openrouter/free"
_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

_clients: dict[str, OpenAI] = {}
_current_key_idx = [0]  # mutable box: module-level state that survives across calls in one process


def _load_api_keys() -> list[str]:
    keys_csv = os.environ.get("OPENROUTER_API_KEYS")
    if keys_csv:
        keys = [k.strip() for k in keys_csv.split(",") if k.strip()]
    else:
        single = os.environ.get("OPENROUTER_API_KEY")
        keys = [single] if single else []
    if not keys:
        raise RuntimeError(
            "No OpenRouter API key found. Set OPENROUTER_API_KEY (one key) or "
            "OPENROUTER_API_KEYS (comma-separated, rotates to the next key when one "
            "hits its daily free-tier cap) — copy .env.example to .env and fill one in."
        )
    return keys


def _client_for(key: str) -> OpenAI:
    if key not in _clients:
        _clients[key] = OpenAI(api_key=key, base_url=os.environ.get("OPENROUTER_BASE_URL", _DEFAULT_BASE_URL))
    return _clients[key]


def _model() -> str:
    return os.environ.get("OPENROUTER_MODEL", _DEFAULT_MODEL)


def _is_daily_cap_error(e: Exception) -> bool:
    msg = str(e)
    return "free-models-per-day" in msg or "per-day" in msg


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
    """Call the model, expecting a single JSON object back. Retries on
    transient errors with backoff on the SAME key (the free tier is
    20 req/min, so a naive hammering loop would burn the budget); a
    per-day cap error rotates to the next configured key immediately
    instead, since waiting can't help a daily quota."""
    keys = _load_api_keys()
    idx = _current_key_idx[0] % len(keys)
    max_total_attempts = max_retries * len(keys)

    last_err: Exception | None = None
    backoff_step = 0
    for _ in range(max_total_attempts):
        key = keys[idx % len(keys)]
        client = _client_for(key)
        try:
            response = client.chat.completions.create(
                model=_model(),
                max_tokens=max_tokens,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            _current_key_idx[0] = idx  # remember the key that worked for next call
            message = response.choices[0].message
            content = message.content or ""
            try:
                return _extract_json(content)
            except ValueError:
                # Some free-tier reasoning models write the answer into a
                # separate `reasoning` field when they run long — fall back
                # to it before giving up and retrying.
                reasoning = getattr(message, "reasoning", None) or ""
                return _extract_json(reasoning)
        except RateLimitError as e:
            last_err = e
            if _is_daily_cap_error(e) and len(keys) > 1:
                idx += 1  # move to the next key right away, no backoff
            else:
                time.sleep(min(2**backoff_step * 2, 30))
                backoff_step += 1
        except APIError as e:
            last_err = e
            time.sleep(min(2**backoff_step, 10))
            backoff_step += 1
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(1)

    raise RuntimeError(
        f"OpenRouter call failed after {max_total_attempts} attempts across {len(keys)} key(s): {last_err}"
    ) from last_err
