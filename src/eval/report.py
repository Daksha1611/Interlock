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
from eval.metrics import full_report


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
        print(
            f"{r['strategy_name']:<20} "
            f"{rec['recovery_rate']*100:>9.1f}% "
            f"{rec['net_recovered_value_paise']/100:>12,.0f} "
            f"{saf['policy_violations']:>11} "
            f"{saf['agent_trap_rate']*100:>6.1f}% "
            f"{saf['gate_intervention_count']:>9}"
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
    args = parser.parse_args()

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
