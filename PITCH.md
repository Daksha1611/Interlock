# Pitch script — Bounded Recovery Engine

Pre-filled with real numbers as of 2026-08-22. Update the [PENDING] items once tomorrow's full held-out run and remaining red-team replicates land.

Total: 5 minutes across 6 beats (§11 of the spec).

---

## 1. The framing (30s)

> "Razorpay already optimizes retry timing — Optimizer, smart routing, in-session retries, hundreds of millions of data points. That's not our pitch. The open question is what happens the moment you let an LLM, not a rules engine, decide to move someone's money. That system can be confidently, expensively wrong — and 'be careful' in a prompt doesn't prove it isn't. We built the architecture that answers that, and the adversarial harness that proves it holds."

## 2. The propose/dispose architecture (60s)

> "The agent proposes an action — retry, switch rail, nudge, escalate, stop. It never executes anything. A separate policy gate — ordinary Python reading a YAML policy, no model call, no prompt — is the only path to money or customer contact. We don't assert this separation in a design doc; four structural tests statically verify it: the agent module has zero import path to the gate's executor, the world simulator and the agent share no imports, the gate contains no LLM call at all, and only one function in the entire codebase is allowed to mutate the money ledger."

Show: `tests/test_isolation.py` — 4 tests, all passing.

## 3. Adversarial results (70s)

> "We built ten scenarios engineered to trap a recovery agent into a wrong money action: a payment already settled by bank transfer, a refund in flight, a duplicate webhook after the attempt cap is already used up, a mandate revoked mid-sequence, an open chargeback, a risk flag set after the fact, a customer opting out mid-sequence, an ambiguous timeout that actually succeeded, a prompt-injection attempt through a customer note field, and a mandate at its regulatory presentation limit."

**Result across 30 live decisions from the real LLM agent (OpenRouter) spanning all 10 scenario types:**

| | count |
|---|---|
| agent proposed something dangerous | **9 / 30** |
| **actually executed unsafely** | **0** |

> "The agent got it wrong 9 times — including proposing to keep retrying a payment that had already exhausted its attempt cap, and retrying an order with an open dispute. The gate caught every single one. That gap between 9 and 0 *is* the thesis: the agent doesn't need to be perfect, because it structurally can't be the last line of defense."

[PENDING: complete the 3 under-sampled scenarios — ambiguous_timeout, injected_instruction, mandate_cap_boundary — currently 1 replicate each, target 3+ once quota resets. Update the 30 → final N.]

## 4. Live audit replay (50s)

> "Every decision — including the refusals — is logged and reconstructible offline, without ever calling the LLM again."

Live demo:
```bash
PYTHONPATH=src python -m audit.demo <run_id>
```
Real output from a B1 baseline run:
- **ALLOW** — a clean scheduled retry, all invariants satisfied.
- **MODIFY** — a customer nudge scheduled at a quiet-hour timestamp, automatically rescheduled to 09:00 instead of denied outright.
- **DENY** — a retry blocked because the amount exceeded the auto-retry ceiling; the gate says escalate, not retry.

All three replay to the exact same disposition, computed fresh from the logged context, zero LLM calls.

## 5. The recovery table (50s)

> "Safety that costs all the revenue isn't a result. Here's B0 — blind retry, what a naive cron job does — against B1, a coarse-reason-aware baseline. Both run through the exact same gate as the agent."

| strategy | recovery rate | net recovered (₹) | policy violations | gate interventions |
|---|---|---|---|---|
| B0 (blind retry) | 25.1% | 190,900 | 0 | 300 |
| B1 (scheduled retry) | 28.9% | 207,312 | 0 | 193 |
| agent (LLM) | [PENDING held-out run] | | | |

> "Notice B0 gets nearly 50% of its proposals intercepted by the gate — retrying hard declines, breaching mandate caps — and still comes out at zero violations. The gate isn't a speed bump for a careful agent; it's load-bearing for a careless one too."

[PENDING: run `eval.report --strategies B0,B1,agent --data-dir data/holdout --limit-orders N` and fill in the agent row.]

## 6. Limitations (40s)

Be ready to say, honestly:

- **Two real gate gaps were found and fixed during red-teaming** — before ever spending an LLM call on it, running the adversarial suite against the *deterministic baselines* surfaced that no invariant blocked retrying a publicly-known non-retryable reason code (only `RISK_BLOCK` was special-cased), and that the risk-block rule only covered retries, not customer contact. Both fixed. This is presented as a feature of the methodology, not a caveat: cheap, LLM-free adversarial testing against baselines caught real bugs before the expensive agent testing ever ran.
- **Information-lag double-settlements are a real, disclosed limit.** A scheduled retry can succeed hours before an independent external settlement (e.g. a bank transfer) is even recorded — the gate had no way to know yet. This is not counted as a policy violation (the gate structurally could not have prevented it), but it is tracked and reported separately as a reconciliation-timing gap, not swept under "zero violations."
- **The duplicate-webhook trap is the agent's weakest spot** — 4/4 replicates so far, the agent proposed retrying past an already-exhausted attempt cap when the same failure arrived under a second event ID. The gate caught all 4. Worth a targeted prompt fix, but exactly the kind of miss the architecture is built to not depend on the agent avoiding.
- [PENDING: diagnosis confusion matrix from the held-out run — where was the agent confidently wrong about the underlying reason, not just the action.]

---

## Numbers to have ready if asked

- **41 unit tests** for the gate alone (12 invariants × pass/fail + integration + a simulated prompt-injection case), all passing without any network call.
- **63 tests total** in the suite, all passing, ~2.5s runtime.
- OpenRouter free tier is 50 requests/day (not the commonly-quoted 200) — disclose this if asked how the live-agent numbers were sized.
