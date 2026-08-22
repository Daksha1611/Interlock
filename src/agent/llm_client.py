"""Thin OpenRouter client. This is the ONLY place an LLM is called from in
this whole codebase — gate/, world/, baselines/, eval/ never touch it (see
tests/test_isolation.py). Calling this produces a *proposal*; it has no
path to money or customer contact by itself.
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

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Copy .env.example to .env and fill in your key, "
                "or export it in your shell."
            )
        _client = OpenAI(
            api_key=api_key,
            base_url=os.environ.get("OPENROUTER_BASE_URL", _DEFAULT_BASE_URL),
        )
    return _client


def _model() -> str:
    return os.environ.get("OPENROUTER_MODEL", _DEFAULT_MODEL)


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
    rate-limit / transient errors with backoff — the free tier is
    20 req/min, so a naive hammering loop would burn the budget."""
    client = get_client()
    last_err: Exception | None = None
    for attempt in range(max_retries):
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
            time.sleep(min(2 ** attempt * 2, 30))
        except APIError as e:
            last_err = e
            time.sleep(min(2**attempt, 10))
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(1)
    raise RuntimeError(f"OpenRouter call failed after {max_retries} attempts: {last_err}") from last_err
