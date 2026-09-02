"use strict";
/* Read-only viewer over committed run artifacts in ./data/ (copies of
   runs/results/ and the audit trails — GitHub Pages serves only docs/, so the
   artifacts are mirrored there by scripts/build_demo_data.sh, which copies and
   never recomputes). Every figure on this page traces to one of those files. */

const NAME = { B0_blind_retry: "B0 — blind retry", B1_scheduled_retry: "B1 — scheduled retry", agent_llm: "agent — LLM" };
const KEY = { B0_blind_retry: "B0", B1_scheduled_retry: "B1", agent_llm: "agent" };
const ORDER = ["B0_blind_retry", "B1_scheduled_retry", "agent_llm"];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (x) => (x == null ? "—" : (x * 100).toFixed(1) + "%");
const pct0 = (x) => (x == null ? "—" : Math.round(x * 100) + "%");
const rs = (p) => "₹" + Math.round(p / 100).toLocaleString("en-IN");

// mirrors domain.provenance: unknown field names fail closed to untrusted
const TRUSTED = new Set(["reason", "rail", "amount", "occurred_at", "attempt_number", "mandate_id", "now",
  "attempts_so_far", "mandate_presentations_so_far", "invoice_already_settled", "refund_in_flight",
  "open_chargeback", "last_contact_at", "amount_ceiling", "customer.do_not_contact", "customer.risk_flagged"]);
const isUntrusted = (f) => !TRUSTED.has(f);

function table(caption, head, rows, leadIdx) {
  // width class follows column count — see styles.css
  const w = head.length <= 4 ? "w-s" : head.length <= 6 ? "w-m" : "w-l";
  const th = head.map((h) => `<th class="${h.num ? "num" : ""}">${esc(h.label ?? h)}</th>`).join("");
  const tb = rows.map((r, i) =>
    `<tr class="${i === leadIdx ? "lead" : ""}">` +
    r.map((c, j) => `<td class="${j === 0 ? "" : "num"} ${c && c.cls ? c.cls : ""}">${c && c.html !== undefined ? c.html : esc(c)}</td>`).join("") +
    `</tr>`).join("");
  return `<table class="${w}">${caption ? `<caption>${esc(caption)}</caption>` : ""}<thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table>`;
}

let HOLDOUT, DERIVED, DECISIONS = {}, curSet = "holdout", curFilter = "ALL", curSel = null;

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`);
  return r.json();
}

function showError(err, what) {
  $("error-slot").innerHTML =
    `<div class="err"><strong>Could not load ${esc(what)}.</strong><br>${esc(err.message || String(err))}<br><br>
     This page reads committed JSON from <code>docs/data/</code>. If you opened the file directly from disk,
     the browser blocks those reads — serve the folder over HTTP instead
     (<code>python3 -m http.server</code> from <code>docs/</code>).</div>`;
}

async function boot() {
  try {
    [HOLDOUT, DERIVED] = await Promise.all([getJSON("data/holdout.json"), getJSON("data/derived.json")]);
  } catch (e) {
    $("status").textContent = "Run artifacts unavailable.";
    showError(e, "the run results");
    return;
  }
  renderStatus(); renderResults(); initTabs();
  $("dataset").onchange = (e) => { curSet = e.target.value; curSel = null; loadDecisions(); };
  $("filters").querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      $("filters").querySelectorAll("button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on"); curFilter = b.dataset.d; renderList();
    };
  });
  loadDecisions();
}

/* ---------------- tabs ---------------- */

function showTab(which, push) {
  const isResults = which !== "audit";
  $("panel-results").hidden = !isResults;
  $("panel-audit").hidden = isResults;
  $("tab-results").setAttribute("aria-selected", String(isResults));
  $("tab-audit").setAttribute("aria-selected", String(!isResults));
  if (push && location.hash !== (isResults ? "#results" : "#audit")) {
    history.replaceState(null, "", isResults ? "#results" : "#audit");
  }
  window.scrollTo(0, 0);
}

function initTabs() {
  $("tab-results").onclick = () => showTab("results", true);
  $("tab-audit").onclick = () => showTab("audit", true);
  showTab(location.hash === "#audit" ? "audit" : "results", false);
  window.addEventListener("hashchange", () => showTab(location.hash === "#audit" ? "audit" : "results", false));
}

/* ---------------- header status ---------------- */

function renderStatus() {
  const agent = HOLDOUT.find((r) => r.strategy_name === "agent_llm");
  const bad = HOLDOUT.filter((r) => !r.integrity.metrics_trustworthy);
  const i = agent.integrity, u = agent.llm_usage || {};
  $("status").innerHTML = bad.length
    ? `<span class="fail">RUN INVALID</span> — ${bad.map((r) => esc(NAME[r.strategy_name])).join(", ")} exceeded the substitution threshold; the recovery figures do not describe the strategy.`
    : `held-out run · 150 orders · inspected once<br>
       <b>integrity.metrics_trustworthy = true</b> — ${i.llm_fallback_decisions}/${i.total_decisions} decisions were LLM-failure substitutions<br>
       ${u.total_tokens ? `${u.decisions_with_llm_call} model-backed decisions · ${u.total_tokens.toLocaleString()} tokens · ${Object.keys(u.provider_distribution || {}).join(", ").toLowerCase()}` : ""}`;
}

/* ---------------- results ---------------- */

function renderResults() {
  const by = Object.fromEntries(HOLDOUT.map((r) => [r.strategy_name, r]));
  const rt = DERIVED.retry_targeting;

  $("retry-table").innerHTML = table(null,
    ["strategy", "retries executed", "recovered", "hit rate"],
    ORDER.map((s) => { const d = rt[KEY[s]]; return [NAME[s], d.retries_executed, d.recovered, pct0(d.hit_rate)]; }), 2);

  $("totals-table").innerHTML = table(null,
    ["strategy", "recovery rate", "net recovered", "violations", "attempts", "per attempt", "gate interventions"],
    ORDER.map((s) => { const r = by[s], v = r.recovery, f = r.safety; return [
      NAME[s], pct(v.recovery_rate), rs(v.net_recovered_value_paise),
      { html: f.policy_violations, cls: f.policy_violations ? "deny" : "zero" },
      v.attempts, rs(v.attempt_efficiency_paise_per_attempt), f.gate_intervention_count]; }), 2);

  const A = DERIVED.recoveries_by_action.agent, B = DERIVED.recoveries_by_action.B1;
  const sum = (o) => Object.values(o).reduce((a, b) => a + b, 0);
  const tot = sum(A.value_paise) - sum(B.value_paise);
  $("decomp-table").innerHTML = table(null,
    ["action", "available to", "recoveries", "value", "share of gain"],
    [["RETRY", "both"], ["SWITCH_RAIL", "agent only"], ["NUDGE", "both"]].map(([act, who]) => {
      const dc = (A.counts[act] || 0) - (B.counts[act] || 0);
      const dv = (A.value_paise[act] || 0) - (B.value_paise[act] || 0);
      return [act, { html: esc(who) }, (dc >= 0 ? "+" : "−") + Math.abs(dc),
        { html: (dv >= 0 ? "+" : "−") + rs(Math.abs(dv)), cls: dv >= 0 ? "allow" : "deny" },
        Math.round((dv / tot) * 100) + "%"];
    }));

  $("safety-table").innerHTML = table(null,
    ["strategy", "decisions", "violations", "DNC breaches", "RISK_BLOCK retries", "mandate breaches", "denied", "modified"],
    ORDER.map((s) => { const f = by[s].safety; return [NAME[s], f.total_decisions,
      { html: f.policy_violations, cls: f.policy_violations ? "deny" : "zero" },
      { html: f.dnc_breaches, cls: f.dnc_breaches ? "deny" : "zero" },
      { html: f.risk_block_retries, cls: f.risk_block_retries ? "deny" : "zero" },
      { html: f.mandate_cap_breaches, cls: f.mandate_cap_breaches ? "deny" : "zero" },
      f.gate_deny_count, f.gate_modify_count]; }), 2);

  $("severity-table").innerHTML = table(null,
    ["strategy", "catastrophic", "severe", "moderate", "must-be-zero total"],
    ORDER.map((s) => { const t = by[s].severity.tier_totals, v = by[s].severity; return [NAME[s],
      { html: t.catastrophic, cls: t.catastrophic ? "deny" : "zero" },
      { html: t.severe, cls: t.severe ? "deny" : "zero" },
      { html: t.moderate, cls: t.moderate ? "modify" : "zero" },
      { html: v.must_be_zero_total, cls: v.must_be_zero_total ? "deny" : "zero" }]; }), 2);

  const lag = Math.max(...HOLDOUT.map((r) => r.severity.reconciliation_timing_excluded || 0));
  $("lag-note").textContent = lag
    ? `${lag} double settlement is excluded from every tier as reconciliation timing: a retry settled before an independent bank transfer was recorded, which the gate could not have known at decision time. It is reported separately rather than folded into the zero.`
    : "";
}

/* ---------------- audit explorer ---------------- */

async function loadDecisions() {
  const file = curSet === "holdout" ? "data/decisions_holdout.json" : "data/decisions_redteam.json";
  $("ds-note").textContent = curSet === "holdout"
    ? "The held-out comparison run. It predates the provenance rule, so these records carry no cited fields — switch to the adversarial suite to see provenance."
    : "The adversarial suite, including the provenance probe. Every record here declares its cited fields; the gate downgrades any money action citing untrusted data.";
  if (!DECISIONS[curSet]) {
    $("list").innerHTML = `<div class="row">loading…</div>`;
    try { DECISIONS[curSet] = await getJSON(file); }
    catch (e) { $("list").innerHTML = ""; showError(e, "the decision records"); return; }
  }
  renderList();
}

const tainted = (r) => (r.proposed_action.cited_fields || []).some(isUntrusted);
const match = (r) => curFilter === "ALL" ? true : curFilter === "UNTRUSTED" ? tainted(r) : r.disposition === curFilter;

function renderList() {
  const recs = (DECISIONS[curSet] || []).filter(match);
  if (!recs.length) { $("list").innerHTML = `<div class="row" style="color:#848075">No decisions match this filter.</div>`; return; }
  $("list").innerHTML = recs.map((r) => `
    <div class="row" role="option" aria-selected="${r.decision_id === curSel}" data-id="${esc(r.decision_id)}">
      <div class="top">
        <span class="disp ${r.disposition.toLowerCase()}">${esc(r.disposition)}</span>
        <span class="act">${esc(r.proposed_action.action_type)}</span>
        ${tainted(r) ? '<span class="taint">untrusted</span>' : ""}
      </div>
      <div class="meta">${esc(r.decision_id)} · ${esc(r.order_id)} · step ${r.step}</div>
    </div>`).join("");
  $("list").querySelectorAll(".row[data-id]").forEach((el) => {
    el.onclick = () => { curSel = el.dataset.id; renderList(); renderDetail(); };
  });
  if (curSel) renderDetail();
}

const kv = (o) => `<dl class="kv">` + Object.entries(o)
  .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join("") + `</dl>`;
const flag = (b) => b ? `<span class="deny">true</span>` : "false";

function renderDetail() {
  const r = (DECISIONS[curSet] || []).find((x) => x.decision_id === curSel);
  if (!r) return;
  const c = r.context_snapshot, p = r.proposed_action, d = r.diagnosis;
  const cited = p.cited_fields || [];
  const note = r.event && r.event.metadata && r.event.metadata.customer_note;

  $("detail").innerHTML = `
    <div class="dh">Decision</div>
    ${kv({ decision_id: esc(r.decision_id), order: esc(r.order_id), step: r.step,
           strategy: esc(r.strategy_name),
           disposition: `<span class="${r.disposition.toLowerCase()}"><b>${esc(r.disposition)}</b></span>` })}

    <div class="dh">Context the gate saw</div>
    ${kv({ now: esc(c.now), amount: rs(c.amount) + (c.amount_ceiling != null ? "  (ceiling " + rs(c.amount_ceiling) + ")" : ""),
           attempts_so_far: c.attempts_so_far, mandate_presentations_so_far: c.mandate_presentations_so_far,
           last_failure_reason: esc(c.last_failure_reason ?? "—"),
           invoice_already_settled: flag(c.invoice_already_settled), refund_in_flight: flag(c.refund_in_flight),
           open_chargeback: flag(c.open_chargeback), "customer.do_not_contact": flag(c.customer.do_not_contact),
           "customer.risk_flagged": flag(c.customer.risk_flagged), last_contact_at: esc(c.last_contact_at || "never") })}
    ${note ? `<div class="dh">customer_note — untrusted, customer-supplied</div>
              <blockquote class="quote untrusted">${esc(note)}</blockquote>` : ""}

    <div class="dh">Diagnosis</div>
    ${kv({ diagnosed_reason: esc(d.reason ?? "—"), confidence: d.confidence != null ? d.confidence : "—" })}
    ${d.reasoning ? `<blockquote class="quote">${esc(d.reasoning)}</blockquote>` : ""}

    <div class="dh">Cited fields — what the agent said drove this</div>
    ${cited.length
      ? `<div class="chips">${cited.map((f) => `<span class="chip ${isUntrusted(f) ? "u" : ""}">${esc(f)}</span>`).join("")}</div>
         ${cited.some(isUntrusted) ? `<p class="note" style="color:var(--deny)">Cites untrusted data, so any money or contact action is downgraded to ESCALATE by the thirteenth invariant.</p>` : ""}`
      : `<p class="note">None recorded — this run predates the provenance rule.</p>`}

    <div class="dh">Proposed action</div>
    ${kv({ action_type: `<b>${esc(p.action_type)}</b>`, scheduled_at: esc(p.scheduled_at),
           rail: esc(p.rail || "—"), message: p.message ? esc(p.message) : "—" })}

    <div class="dh">Gate invariants — all ${r.rule_results.length} evaluated</div>
    <div class="rules">${r.rule_results.map((x) => `
      <div class="r"><span class="nm">${esc(x.rule)}</span><span class="dots"></span>
        <span class="vd ${x.passed ? "pass" : "fail"}">${x.passed ? "pass" : "FAIL"}</span></div>
      ${x.detail ? `<div class="dt">${esc(x.detail)}</div>` : ""}`).join("")}</div>

    <div class="dh">Disposition</div>
    ${kv({ outcome: `<span class="${r.disposition.toLowerCase()}"><b>${esc(r.disposition)}</b></span>`,
           final_action: r.final_action ? esc(r.final_action.action_type) + " at " + esc(r.final_action.scheduled_at) : "none — denied",
           money_delta: r.money_delta ? `<span class="allow">${rs(r.money_delta)}</span>` : "0",
           model: r.llm_usage ? esc(r.llm_usage.provider.toLowerCase() + " / " + r.llm_usage.model) : "— deterministic baseline" })}
    <blockquote class="quote">${esc(r.disposition_reason)}</blockquote>`;
}

boot();
