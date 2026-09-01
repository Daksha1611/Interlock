"use strict";
// Read-only viewer over committed run artifacts in ./data/. It renders what the
// runs produced and derives nothing on its own beyond formatting — every figure
// here traces to a file in runs/results/ or an audit trail.

const NAMES = { B0_blind_retry: "B0 (blind retry)", B1_scheduled_retry: "B1 (scheduled retry)", agent_llm: "agent (LLM)" };
const KEY = { B0_blind_retry: "B0", B1_scheduled_retry: "B1", agent_llm: "agent" };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (x) => (x === null || x === undefined ? "—" : (x * 100).toFixed(1) + "%");
const rs = (p) => "₹" + (p / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 });

const UNTRUSTED = new Set(["customer_note", "customer.name", "order_notes", "gateway_message"]);
const TRUSTED = new Set(["reason", "rail", "amount", "occurred_at", "attempt_number", "mandate_id", "now",
  "attempts_so_far", "mandate_presentations_so_far", "invoice_already_settled", "refund_in_flight",
  "open_chargeback", "last_contact_at", "amount_ceiling", "customer.do_not_contact", "customer.risk_flagged"]);
// Mirrors domain.provenance.is_untrusted: unknown field names fail closed.
const isUntrusted = (f) => !TRUSTED.has(f);

const table = (head, rows, hiIdx) =>
  `<table><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>` +
  rows.map((r, i) => `<tr class="${i === hiIdx ? "hi" : ""}">${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("") +
  `</tbody></table>`;

let HOLDOUT = null, DERIVED = null, DECISIONS = {}, REDTEAM = null;
let curDataset = "holdout", curFilter = "ALL", curSel = null;

async function boot() {
  [HOLDOUT, DERIVED, REDTEAM] = await Promise.all([
    fetch("data/holdout.json").then((r) => r.json()),
    fetch("data/derived.json").then((r) => r.json()),
    fetch("data/redteam.json").then((r) => r.json()),
  ]);
  renderResults();
  $("tab-results").onclick = () => switchTab(true);
  $("tab-audit").onclick = () => switchTab(false);
  $("dataset").onchange = (e) => { curDataset = e.target.value; curSel = null; loadDecisions(); };
  document.querySelectorAll("[data-disp]").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll("[data-disp]").forEach((x) => x.classList.remove("on"));
      b.classList.add("on"); curFilter = b.dataset.disp; renderList();
    };
  });
}

function switchTab(showResults) {
  $("view-results").hidden = !showResults;
  $("view-audit").hidden = showResults;
  $("tab-results").classList.toggle("on", showResults);
  $("tab-audit").classList.toggle("on", !showResults);
  if (!showResults && !DECISIONS[curDataset]) loadDecisions();
}

/* ---------------- results ---------------- */

function renderResults() {
  const order = ["B0_blind_retry", "B1_scheduled_retry", "agent_llm"];
  const by = Object.fromEntries(HOLDOUT.map((r) => [r.strategy_name, r]));

  const bad = HOLDOUT.filter((r) => !r.integrity.metrics_trustworthy);
  $("integrity").innerHTML = bad.length
    ? `<div class="callout"><b class="bad">INVALID RUN.</b> ${bad.map((r) => NAMES[r.strategy_name]).join(", ")} exceeded the LLM-failure substitution threshold; recovery numbers do not describe the strategy.</div>`
    : `<div class="callout"><b class="ok">Run verified clean.</b> <code>integrity.metrics_trustworthy: true</code> on all three strategies — 0 of the agent's ${by.agent_llm.integrity.total_decisions} decisions were escalate-on-LLM-failure substitutions. An earlier run that failed this check reported 7.3% recovery when the truth was ~27%; it was deleted rather than published.</div>`;

  const rt = DERIVED.retry_targeting;
  $("retry-table").innerHTML = table(
    ["strategy", "retries executed", "recovered", "hit rate"],
    order.map((s) => { const d = rt[KEY[s]]; return [NAMES[s], d.retries_executed, d.recovered, pct(d.hit_rate)]; }), 2);

  $("totals-table").innerHTML = table(
    ["strategy", "recovery rate", "net recovered", "policy violations", "attempts", "₹/attempt", "gate interventions"],
    order.map((s) => { const r = by[s], v = r.recovery, f = r.safety; return [
      NAMES[s], pct(v.recovery_rate), rs(v.net_recovered_value_paise),
      `<span class="${f.policy_violations ? "bad" : "ok"}">${f.policy_violations}</span>`,
      v.attempts, rs(v.attempt_efficiency_paise_per_attempt), f.gate_intervention_count]; }), 2);

  const A = DERIVED.recoveries_by_action.agent, B = DERIVED.recoveries_by_action.B1;
  const tot = Object.values(A.value_paise).reduce((a, b) => a + b, 0) - Object.values(B.value_paise).reduce((a, b) => a + b, 0);
  $("decomp-table").innerHTML = table(
    ["action", "available to", "Δ recoveries", "Δ value", "share of gain"],
    [["RETRY", "both", null, null], ["SWITCH_RAIL", "agent only", null, null], ["NUDGE", "both", null, null]]
      .map(([act, who]) => {
        const dc = (A.counts[act] || 0) - (B.counts[act] || 0);
        const dv = (A.value_paise[act] || 0) - (B.value_paise[act] || 0);
        return [act, who, (dc >= 0 ? "+" : "") + dc,
          `<span class="${dv >= 0 ? "ok" : "bad"}">${dv >= 0 ? "+" : "−"}${rs(Math.abs(dv))}</span>`,
          ((dv / tot) * 100).toFixed(0) + "%"];
      }));

  $("safety-table").innerHTML = table(
    ["strategy", "decisions", "policy violations", "DNC breaches", "RISK_BLOCK retries", "mandate breaches", "denied", "modified"],
    order.map((s) => { const f = by[s].safety; return [NAMES[s], f.total_decisions,
      `<span class="${f.policy_violations ? "bad" : "ok"}">${f.policy_violations}</span>`,
      f.dnc_breaches, f.risk_block_retries, f.mandate_cap_breaches, f.gate_deny_count, f.gate_modify_count]; }), 2);

  $("severity-table").innerHTML = table(
    ["strategy", "catastrophic", "severe", "moderate", "must-be-zero total", "claim holds"],
    order.map((s) => { const v = by[s].severity, t = v.tier_totals; return [NAMES[s],
      `<span class="${t.catastrophic ? "bad" : "ok"}">${t.catastrophic}</span>`,
      `<span class="${t.severe ? "bad" : "ok"}">${t.severe}</span>`, t.moderate, v.must_be_zero_total,
      v.zero_violation_claim_holds ? '<span class="ok">yes</span>' : '<span class="bad">NO</span>']; }), 2);

  const lag = Math.max(...HOLDOUT.map((r) => r.severity.reconciliation_timing_excluded || 0));
  $("caveats").innerHTML = `
    <div class="callout">
      <b>What these numbers do not show.</b>
      ${lag ? `${lag} double settlement is excluded as reconciliation timing — a retry settled before an independent bank transfer was recorded, which the gate could not have known at decision time. It is reported, not folded into the zero.<br><br>` : ""}
      <b>The lift is conditional on a simulated outcome model.</b> Success is decided by curves we wrote in <code>config/taxonomy.yaml</code>, not fitted to production traffic. The agent's retries with no prior nudge succeed at 55%, and <code>peak_prob</code> in that file is 0.55 — a large part of this measures whether an LLM can find the peak of a curve we specified. Not a production lift estimate.<br><br>
      <b>This run used the 12-invariant gate</b>, before the provenance rule landed. The 13th only downgrades actions, so applying it would move these numbers; re-running would mean inspecting the held-out set twice.<br><br>
      <b>Diagnosis accuracy is degenerate here.</b> The gateway reason code equals ground truth for 150/150 orders, so B1 scores 100% by copying the input. The agent's 99.3% means it overrode a correct signal once.
    </div>`;
}

/* ---------------- audit explorer ---------------- */

async function loadDecisions() {
  const file = curDataset === "holdout" ? "data/decisions_holdout.json" : "data/decisions_redteam.json";
  $("list").innerHTML = `<p class="empty">Loading…</p>`;
  if (!DECISIONS[curDataset]) DECISIONS[curDataset] = await fetch(file).then((r) => r.json());
  $("ds-note").textContent = curDataset === "holdout"
    ? "The held-out comparison run. It predates the provenance rule, so these records carry no cited_fields — switch to the red-team suite to see provenance in action."
    : "The adversarial suite, including the provenance probe. Every record here declares cited_fields; the gate downgrades any money action citing untrusted data.";
  renderList();
}

const matches = (r) => curFilter === "ALL" ? true
  : curFilter === "UNTRUSTED" ? (r.proposed_action.cited_fields || []).some(isUntrusted)
  : r.disposition === curFilter;

function renderList() {
  const recs = (DECISIONS[curDataset] || []).filter(matches);
  if (!recs.length) { $("list").innerHTML = `<p class="empty">No decisions match this filter.</p>`; return; }
  $("list").innerHTML = recs.map((r) => {
    const tainted = (r.proposed_action.cited_fields || []).some(isUntrusted);
    return `<div class="row ${r.decision_id === curSel ? "sel" : ""}" data-id="${r.decision_id}">
      <span class="pill ${r.disposition}">${r.disposition}</span>
      <b>${esc(r.proposed_action.action_type)}</b>${tainted ? ' <span class="pill DENY">untrusted</span>' : ""}
      <div class="id">${esc(r.decision_id)} · ${esc(r.order_id)} · step ${r.step}</div></div>`;
  }).join("");
  $("list").querySelectorAll(".row").forEach((el) => { el.onclick = () => { curSel = el.dataset.id; renderList(); renderDetail(); }; });
  if (curSel) renderDetail();
}

function renderDetail() {
  const r = DECISIONS[curDataset].find((x) => x.decision_id === curSel);
  if (!r) return;
  const c = r.context_snapshot, p = r.proposed_action, d = r.diagnosis;
  const cited = p.cited_fields || [];
  const note = (r.event && r.event.metadata && r.event.metadata.customer_note) || null;

  const kv = (o) => `<dl class="kv">` + Object.entries(o).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("") + `</dl>`;
  const bool = (b) => b ? '<span class="bad">true</span>' : "false";

  $("detail").innerHTML = `
    <h3>Decision</h3>
    ${kv({ decision_id: `<code>${esc(r.decision_id)}</code>`, order: esc(r.order_id), step: r.step,
           strategy: esc(r.strategy_name), disposition: `<span class="pill ${r.disposition}">${r.disposition}</span>` })}

    <h3>Input context (what the gate saw)</h3>
    ${kv({ now: esc(c.now), amount: rs(c.amount) + " / ceiling " + (c.amount_ceiling != null ? rs(c.amount_ceiling) : "—"),
           attempts_so_far: c.attempts_so_far, mandate_presentations_so_far: c.mandate_presentations_so_far,
           last_failure_reason: esc(c.last_failure_reason), invoice_already_settled: bool(c.invoice_already_settled),
           refund_in_flight: bool(c.refund_in_flight), open_chargeback: bool(c.open_chargeback),
           "customer.do_not_contact": bool(c.customer.do_not_contact), "customer.risk_flagged": bool(c.customer.risk_flagged),
           last_contact_at: esc(c.last_contact_at || "never") })}
    ${note ? `<h3>customer_note — untrusted, customer-supplied</h3><div class="reason bad">${esc(note)}</div>` : ""}

    <h3>Agent diagnosis</h3>
    ${kv({ diagnosed_reason: esc(d.reason), confidence: d.confidence != null ? d.confidence : "—" })}
    ${d.reasoning ? `<div class="reason">${esc(d.reasoning)}</div>` : ""}

    <h3>cited_fields — what the agent said drove this</h3>
    ${cited.length
      ? `<div class="chips">${cited.map((f) => `<span class="chip ${isUntrusted(f) ? "untrusted" : ""}">${esc(f)}</span>`).join("")}</div>
         ${cited.some(isUntrusted) ? `<p class="note bad">Cites untrusted data → any money or contact action is downgraded to ESCALATE by the 13th invariant.</p>` : ""}`
      : `<p class="note">None recorded — this run predates the provenance rule.</p>`}

    <h3>Proposed action</h3>
    ${kv({ action_type: `<b>${esc(p.action_type)}</b>`, scheduled_at: esc(p.scheduled_at),
           rail: esc(p.rail || "—"), message: p.message ? esc(p.message) : "—" })}

    <h3>Gate invariants — all ${r.rule_results.length} evaluated</h3>
    <table class="rules"><tbody>${r.rule_results.map((x) => `<tr>
      <td>${esc(x.rule)}</td>
      <td style="width:70px"><span class="${x.passed ? "ok" : "bad"}">${x.passed ? "pass" : "FAIL"}</span></td>
      <td style="text-align:left">${esc(x.detail || "")}</td></tr>`).join("")}</tbody></table>

    <h3>Disposition</h3>
    ${kv({ outcome: `<span class="pill ${r.disposition}">${r.disposition}</span>`,
           final_action: r.final_action ? esc(r.final_action.action_type) + " at " + esc(r.final_action.scheduled_at) : "<i>none — denied</i>",
           money_delta: r.money_delta ? `<span class="ok">${rs(r.money_delta)}</span>` : "0",
           model: r.llm_usage ? esc(r.llm_usage.provider + " / " + r.llm_usage.model) : "— (deterministic baseline)" })}
    <div class="reason">${esc(r.disposition_reason)}</div>`;
}

boot();
