"""CLI: run one or more strategies over a corpus split and print the
comparison table (§6 / §11.5 of the spec). This is where B0/B1 first get
numbers, and later where the agent gets compared against them.
"""

from __future__ import annotations

import argparse
import json

from domain.strategy import Strategy
from eval.harness import run_strategy
from eval.loaders import load_configs, load_split
from eval.metrics import full_report, llm_usage_metrics


def run_all(
    strategies: list[Strategy], data_dir: str, config_dir: str = "config", limit_orders: int | None = None
) -> list[dict]:
    """Runs every strategy passed here over the SAME (possibly subsampled)
    set of orders — apples-to-apples per §6.4's fairness conditions. Pass a
    `limit_orders` when the agent is in the list and you need to stay inside
    a free-tier API budget; B0/B1 alone can always run on the full split."""
    cfg = load_configs(config_dir)
    events, ground_truths, customers = load_split(data_dir, limit_orders=limit_orders, seed=cfg["simulation"]["seed"])
    seed = cfg["simulation"]["seed"]

    reports = []
    for strat in strategies:
        result = run_strategy(
            strat, events, ground_truths, customers, cfg["policy"], cfg["taxonomy"], seed=seed
        )
        reports.append(full_report(result, ground_truths, cfg["policy"], cfg["economics"]))
    return reports


def print_table(reports: list[dict]) -> None:
    header = f"{'strategy':<20} {'recov.rate':>10} {'net(₹)':>12} {'violations':>11} {'trap%':>7} {'gate int.':>9}"
    print(header)
    print("-" * len(header))
    for r in reports:
        rec = r["recovery"]
        saf = r["safety"]
        integ = r.get("integrity", {})
        # Mark the row itself, so a compromised number is never readable as a
        # clean result even if the warning below scrolls off.
        flag = "" if integ.get("metrics_trustworthy", True) else "  << INVALID"
        print(
            f"{r['strategy_name']:<20} "
            f"{rec['recovery_rate']*100:>9.1f}% "
            f"{rec['net_recovered_value_paise']/100:>12,.0f} "
            f"{saf['policy_violations']:>11} "
            f"{saf['agent_trap_rate']*100:>6.1f}% "
            f"{saf['gate_intervention_count']:>9}"
            f"{flag}"
        )

    compromised = [r for r in reports if not r.get("integrity", {}).get("metrics_trustworthy", True)]
    if compromised:
        print()
        print("!" * 78)
        print("INVALID RUN — the recovery numbers above do NOT describe the strategy.")
        for r in compromised:
            i = r["integrity"]
            print(
                f"  {r['strategy_name']}: {i['llm_fallback_decisions']}/{i['total_decisions']} decisions "
                f"({i['llm_fallback_rate']*100:.0f}%) were escalate-on-LLM-failure substitutions "
                f"rather than proposals; only {i['decisions_actually_proposed']} were actually decided."
            )
        print("A failed call escalates, and an escalation recovers nothing, so recovery is")
        print("understated by however much of the run was lost. Re-run with quota available.")
        print("!" * 78)

    if any("severity" in r for r in reports):
        print()
        print("violations by severity (catastrophic/severe must be 0):")
        for r in reports:
            sev = r.get("severity")
            if not sev:
                continue
            t = sev["tier_totals"]
            verdict = "OK" if sev["zero_violation_claim_holds"] else "CLAIM BROKEN"
            print(
                f"  {r['strategy_name']:<20} catastrophic={t['catastrophic']}  severe={t['severe']}  "
                f"moderate={t['moderate']}   [{verdict}]"
            )
        lag = max(r.get("severity", {}).get("reconciliation_timing_excluded", 0) for r in reports)
        if lag:
            print(f"  ({lag} double-settlement(s) excluded as reconciliation timing — not knowable at decision time)")

    llm_reports = [r for r in reports if r.get("llm_usage", {}).get("decisions_with_llm_call")]
    if llm_reports:
        print()
        print("provider/model distribution:")
        for r in llm_reports:
            u = r["llm_usage"]
            print(
                f"  {r['strategy_name']}: {u['decisions_with_llm_call']} LLM-backed decisions, "
                f"providers={u['provider_distribution']}, models={u['model_distribution']}, "
                f"{u['total_tokens']:,} tokens total ({u['mean_tokens_per_decision']:.0f}/decision)"
            )


def dry_run(n: int, data_dir: str, config_dir: str = "config") -> None:
    """Spend a small, known amount of real API quota to measure what a full
    run would cost, and print the projection — never launch a real held-out
    run blind. Prints only; writes no report."""
    from agent.llm_client import configured_endpoints
    from agent.orchestrator import AgentStrategy

    cfg = load_configs(config_dir)
    seed = cfg["simulation"]["seed"]

    _, full_ground_truths, _ = load_split(data_dir, seed=seed)
    total_orders = len({t.order_id for t in full_ground_truths})

    events, ground_truths, customers = load_split(data_dir, limit_orders=n, seed=seed)
    print(f"dry run: spending real quota on {len(ground_truths)} of {total_orders} orders in {data_dir!r}")
    print(f"endpoints configured (in preference order): {configured_endpoints()}")

    result = run_strategy(
        AgentStrategy(), events, ground_truths, customers, cfg["policy"], cfg["taxonomy"], seed=seed
    )
    records = result["audit"].load_all()
    usage = llm_usage_metrics(records)

    n_decisions = result["n_decisions"]
    n_orders_run = result["n_orders"]
    decisions_per_order = (n_decisions / n_orders_run) if n_orders_run else 0.0
    projected_decisions = decisions_per_order * total_orders
    projected_tokens = usage["mean_tokens_per_decision"] * projected_decisions

    print()
    print(f"observed: {n_orders_run} orders -> {n_decisions} decisions "
          f"({usage['decisions_with_llm_call']} carried a real LLM call)")
    print(f"observed tokens/decision: mean {usage['mean_tokens_per_decision']:.0f} "
          f"(prompt {usage['total_prompt_tokens'] / max(usage['decisions_with_llm_call'], 1):.0f} "
          f"+ completion {usage['total_completion_tokens'] / max(usage['decisions_with_llm_call'], 1):.0f})")
    print(f"provider distribution this dry run: {usage['provider_distribution']}")
    print(f"decisions/order observed: {decisions_per_order:.2f}")
    print(
        f"projected for the full corpus ({total_orders} orders, "
        f"~{projected_decisions:.0f} decisions): {projected_tokens:,.0f} tokens total"
    )


_STRATEGY_NAMES = {"B0", "B1", "agent"}


def _build_strategy(name: str) -> Strategy:
    if name == "B0":
        from baselines.b0_blind_retry import BlindRetry

        return BlindRetry()
    if name == "B1":
        from baselines.b1_scheduled_retry import ScheduledRetry

        return ScheduledRetry()
    if name == "agent":
        from agent.orchestrator import AgentStrategy

        return AgentStrategy()
    raise ValueError(f"unknown strategy {name!r}, expected one of {_STRATEGY_NAMES}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/corpus")
    parser.add_argument("--strategies", default="B0,B1", help="comma-separated: B0,B1,agent")
    parser.add_argument("--limit-orders", type=int, default=None, help="subsample N orders (needed for 'agent' on a free API tier)")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--dry-run-n", type=int, default=None,
        help="spend real quota on N orders' worth of agent decisions, print observed/projected token "
             "cost, and exit without writing a report — run this before any real held-out run",
    )
    args = parser.parse_args()

    if args.dry_run_n is not None:
        dry_run(args.dry_run_n, args.data_dir)
        return

    names = [n.strip() for n in args.strategies.split(",")]
    strategies = [_build_strategy(n) for n in names]

    reports = run_all(strategies, args.data_dir, limit_orders=args.limit_orders)
    print_table(reports)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(reports, f, indent=2)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
