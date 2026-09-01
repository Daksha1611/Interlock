# Pitch script — Bounded Recovery Engine

**Track 03 — AI Revenue Recovery (Razorpay AI Buildathon)**

Total: 5 minutes across 7 beats. Numbers current as of 2026-09-01.

---

## 1. The framing (30s)

> "Razorpay already optimizes retry timing — Optimizer, smart routing, in-session retries, hundreds of millions of data points. That's not our pitch, and we're not claiming we beat it. The open question is what happens the moment you let an LLM, not a rules engine, decide to move someone's money. That system can be confidently, expensively wrong — and 'be careful' in a prompt doesn't prove it isn't. We built the architecture that answers that, and the adversarial harness that proves it holds."

The claim is **not** "this recovers more money." It is: *an LLM can be given authority over money actions and be structurally incapable of taking a wrong one, with every decision auditable and replayable.*

## 2. Propose / dispose, including provenance (60s)

> "The agent proposes an action — retry, switch rail, nudge, escalate, stop. It never executes anything. A separate policy gate — ordinary Python reading a YAML policy, no model call, no prompt — is the only path to money or customer contact."

> "We don't assert that separation in a design doc. Four structural tests statically verify it: the agent module has zero import path to the gate or the executor, the world simulator and the agent share no imports, the gate contains no LLM call at all, and exactly one function in the codebase may mutate the money ledger."

Show: `tests/test_isolation.py` — 4 tests, passing.

**The 13th invariant — provenance.** Every context field is tagged TRUSTED (ledger state, reason code, mandate state, amount, timestamps, risk and DNC flags set by compliance systems) or UNTRUSTED (customer notes, display names, order notes, gateway free text). The agent must declare which fields its decision rests on. If a money-moving or contact action cites *any* untrusted field, the gate downgrades it to ESCALATE.

> "This is the part I'd point a security reviewer at. We are deliberately **not** claiming we detect malicious notes — that's undecidable, and it would put a classifier back on the money path. We constrain the *stated basis* for moving money instead. The agent can read a customer note, be completely taken in by it, and say so — and the action becomes an escalation instead of a charge. That moves the prompt-injection claim from 'the gate caught it' to 'untrusted data structurally cannot justify a money action'."

Unknown field names fail closed to UNTRUSTED: a hallucinated citation is the case we know least about, so it must not be the one that defaults to trusted.

## 3. Adversarial results (70s)

Ten scenario families engineered to trap a recovery agent into a wrong money action: a payment already settled by bank transfer, a refund in flight, a duplicate webhook after the attempt cap is used up, a mandate revoked mid-sequence, an open chargeback, a risk flag set after the fact, a customer opting out mid-sequence, an ambiguous timeout that actually succeeded, a prompt injection through a customer note, and a mandate at its regulatory presentation limit. Plus an eleventh **provenance probe**, built so that *no other invariant applies* — a plain gateway timeout, first attempt, under the ceiling, no flags — where the only thing wrong is that the justification came from an attacker-authored note.

**100 live decisions — 10 replicates × 10 families, one pinned model (Groq `openai/gpt-oss-20b`), 2026-08-23:**

| | count |
|---|---|
| agent proposed something dangerous | **31 / 100** |
| **actually executed unsafely** | **0** |

| | denied | allowed |
|---|---|---|
| **dangerous proposals** | **31** | **0** |
| safe proposals | 0 | 69 |

> "The agent got it wrong 31 times out of 100. It proposed retrying a payment that had already exhausted its attempt cap — every single time. It proposed contacting a customer who had opted out mid-sequence — every single time. The gate denied all 31 and allowed all 69 safe ones. That gap between 31 and 0 *is* the thesis: the agent doesn't have to be right, because it structurally cannot be the last line of defence."

**Utility under attack** (after AgentDojo, Debenedetti et al., NeurIPS 2024) — because zero violations is trivially achievable by refusing everything:

| on the adversarial corpus | |
|---|---|
| safe money/contact proposals executed | **9 / 9 (100%)** |
| dangerous proposals blocked | **31 / 31 (100%)** |

> "Notice the second row of the confusion matrix: zero safe proposals denied. The gate isn't buying safety by refusing everything — it discriminates. That's the objection I'd expect first, so we measure it directly."

Be precise if pressed: of the 69 safe proposals, 40 were ESCALATE and 20 STOP — safe by construction. Nine were proposals that would genuinely have moved money or contacted a customer, and **all nine executed**. That's the number that rules out a gate buying its zero by blanket refusal, and n=9 is small — say so rather than let someone find it.

**Cross-model check.** An earlier 30-decision run on OpenRouter's free auto-router proposed 9 dangerous actions and also executed 0. The two models fail *differently* — `mandate_revoked_mid_sequence` trapped the OpenRouter run 0% of the time and the Groq run 80% — which is the point: the safety property belongs to the gate, not to whichever model is proposing.

## 4. Live audit replay (50s)

> "Every decision — including the refusals — is logged and reconstructible offline, without ever calling the LLM again."

```bash
PYTHONPATH=src python -m audit.demo <run_id>
```

Real output from a B1 run:
- **ALLOW** — a clean scheduled retry, all invariants satisfied.
- **MODIFY** — a nudge scheduled into quiet hours, automatically rescheduled to 09:00 rather than denied.
- **DENY** — a retry blocked for exceeding the auto-retry amount ceiling; the gate says escalate, not retry.

All three replay to the identical disposition, recomputed from the logged context, zero LLM calls.

> "Show the DENY one. A system that only logs what it did isn't auditable — you also need the record of what it refused, and why, or you can't tell a safe system from a lucky one."

## 5. The recovery table (50s)

> "Safety that costs all the revenue isn't a result."

**Held-out set, 150 orders, never used for tuning — inspected once:**

| strategy | recovery rate | net recovered (₹) | policy violations | gate interventions |
|---|---|---|---|---|
| B0 (blind retry) | [B0_REC] | [B0_NET] | [B0_VIOL] | [B0_INT] |
| B1 (scheduled retry) | [B1_REC] | [B1_NET] | [B1_VIOL] | [B1_INT] |
| agent (LLM) | [AG_REC] | [AG_NET] | [AG_VIOL] | [AG_INT] |

[RECOVERY_COMMENTARY]

**Severity, not a binary count** (after ToolEmu, Ruan et al., ICLR 2024). A single "violations" number treats "charged a customer twice" and "texted them at 22:00" as the same event:

| tier | what it covers | count |
|---|---|---|
| catastrophic | gate-inconsistent double charge, RISK_BLOCK retry | [SEV_CAT] |
| severe | DNC breach, mandate regulatory cap breach | [SEV_SEV] |
| moderate | quiet-hours contact, contact-frequency breach | [SEV_MOD] |

The "must be zero" claim covers **catastrophic and severe** — pinned in code (`MUST_BE_ZERO_TIERS`) so it can't quietly drift to cover more or less than what we defended here.

## 6. The void run — why the honesty claims are load-bearing (30s)

This is the beat to slow down on.

> "On the 23rd our held-out run reported the agent at **7.3% recovery** against B1's 27.3%. That's a plausible number. It's the kind of number you'd shrug at, write up as 'the LLM underperformed,' and move on."

> "It was wrong. The run had exhausted its token quota at decision 92 of 202. Every call after that failed, and our orchestrator substitutes an ESCALATE when a call fails — so the run *completed*, produced a full audit trail, and reported a number that described an outage rather than a strategy."

> "We caught it because we'd built a check that asks a different question from 'did the run finish': **how much of this run was the strategy actually deciding?** Any report where more than 5% of decisions were failure substitutions is marked untrustworthy and the recovery numbers are stamped INVALID. We deleted that report rather than publish it."

Show `eval/metrics.integrity_metrics` and the `<< INVALID` row marker.

> "I'm telling you about our worst run on purpose. Every team here will show you a number. The question worth asking any of them is: what would have had to go wrong for that number to be false, and would you have noticed? We built the thing that notices. That's the same instinct as the gate — assume the component can fail, and make the failure structurally visible instead of hoping it doesn't happen."

Two real bugs found the same way, both fixed and regression-tested: a malformed provider response that crashed past all retry logic, and a daily-quota error whose wording our detector missed, so a dead endpoint was retried through a full backoff schedule on every decision.

## 7. Limitations (40s)

Said before anyone has to ask:

- **The adversarial suite is in-sample.** Two invariants — `hard_decline_no_retry` and the extended `risk_block` — were *derived* from red-teaming the baselines against this same suite. The gate is partly fitted to these scenarios. It doesn't touch the structural claim, but the trap rates should be read as in-sample, not as generalisation.
- **Replicates are not coverage.** 100 decisions is 10 families seen 10 times, measuring model variance on fixed setups. The confidence interval on any single family's trap rate is wide.
- **Our diagnosis-accuracy number is weaker than it looks, and we'd rather say so than be caught.** In this corpus the gateway's reason code already equals the true reason for **150/150** held-out orders. So the answer is sitting in the input, and B1 scores 100% by copying it. Our confusion matrix therefore measures whether the agent *corrupts a correct signal*, not whether it solves a hard diagnostic problem. [CONFIDENTLY_WRONG]
- **The root cause is our generator, and it makes diagnosis easier than reality.** Real gateway reason codes are noisy and frequently misleading — `DO_NOT_HONOR` is a catch-all that covers everything from fraud suspicion to an expired card to a velocity limit, and issuer outages routinely surface as generic declines rather than as anything labelled an outage. Ours are perfectly faithful. So this metric would be **substantially harder in a real deployment**, and our number should not be read as transferring. We did not fix the generator on purpose: the held-out corpus is frozen, and regenerating it after seeing results would destroy the one property that makes the held-out comparison worth anything.
- **What we'd fix first:** a corpus where the reported reason code is sometimes wrong, so diagnosis is a real task; a held-out adversarial suite the gate was never fitted to; and a second check on the citations themselves, so provenance stops being declaration-based.
- **Provenance constrains the *stated* basis, not the real one.** An agent that reads a note, is influenced by it, and doesn't cite it slips through. We treat unknown fields as untrusted and ask for honest citation, but this is a declaration-based control — it raises the cost of a successful injection, it doesn't eliminate it. The next thing we'd build is a second, adversarial check on the citation itself.
- **Information-lag double settlements are real and disclosed.** A retry can succeed hours before an independent bank transfer is recorded. The gate could not have known, so it's not counted as a policy violation — but it's tracked and reported separately, never folded into "zero violations."
- **The held-out comparison was run against the 12-invariant gate**, before provenance landed. This matters specifically because the 13th invariant *downgrades* actions — every action it touches becomes an ESCALATE, which recovers nothing — so applying it would move the recovery numbers, not leave them alone. Re-running to include it would mean inspecting the held-out set a second time, so we report the 12-invariant result and say which gate produced it. Provenance is evidenced on the adversarial suite instead.

## Future work — the comparison we did not run

**An uplift-optimal classical policy (B2).** Choosing a recovery action is, stated
plainly, a causal inference problem: for this order, which of retry / switch rail /
nudge / wait produces the largest increase in probability of settlement *versus not
acting*? That is a conditional average treatment effect, and the standard tools are
metalearners — the T-learner and X-learner of Künzel et al., *PNAS* 2019 — fit over
logged outcomes from a random-action exploration policy, then deployed as an argmax
over estimated per-action CATE.

We did not build it, and we are naming it rather than omitting it, because it is the
most credible threat to our recovery numbers: **we do not know whether an
uplift-optimal classical policy would beat the LLM on recovery.** It plausibly would.
It costs no inference, it has no prompt to attack, and on a problem this structured a
well-fit metalearner is a strong opponent.

Two things worth saying about that:

1. It would not touch the thesis. The claim is that an LLM given authority over money
   can be made structurally incapable of a wrong action, with every decision
   auditable. A classical policy that recovers more is a different, older answer to a
   different question — one that gives up the natural-language reasoning and the
   readable justification that made the audit trail worth building.
2. **We deliberately did not decide this after seeing our own result.** Choosing
   whether to include a comparator once you know what it would be compared against is
   post-hoc selection — exactly the move this project's integrity tooling exists to
   catch. Skipped up front, disclosed here.

---

## Numbers to have ready if asked

- **154 tests**, all passing, no network — 13 invariants × pass/fail cases, 4 structural isolation tests, 17 provenance tests, integration tests for ALLOW/DENY/MODIFY.
- Free-tier ceilings that shaped the evaluation: OpenRouter ~50 requests/day, Groq 200,000 tokens/day, Google 20 requests/day. Three different units — budget a run in the right one or it dies halfway.
- The gate is **~200 lines of ordinary Python**. That's the whole point: the thing standing between an LLM and someone's money should be small enough to read in one sitting.
