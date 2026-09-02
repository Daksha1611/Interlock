#!/usr/bin/env bash
# Copies committed run artifacts into docs/ for the static demo page.
#
# GitHub Pages serves ONLY the docs/ folder, so the viewer cannot fetch
# ../runs/... at all — the data has to live under docs/. This script is the
# single place that copy happens, so the duplication is explicit and drift
# shows up as a diff rather than silently.
#
# It copies and reshapes. It never recomputes: every number the page shows
# came out of an actual run.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=docs/data
mkdir -p "$OUT"

cp runs/results/holdout_three_way_2026-09-01.json "$OUT/holdout.json"
cp runs/results/redteam_agent_n10_2026-09-02.json "$OUT/redteam.json"

# audit trails: JSONL -> JSON array, verbatim records
jsonl_to_json () {
  python3 -c "
import json,sys
recs=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
json.dump(recs, open(sys.argv[2],'w'), separators=(',',':'))
print(f'{sys.argv[2]}: {len(recs)} decisions')
" "$1" "$2"
}
jsonl_to_json runs/run_agent_llm_7a3279219e/audit.jsonl        "$OUT/decisions_holdout.json"
jsonl_to_json runs/redteam_agent_llm_6271196af9/audit.jsonl    "$OUT/decisions_redteam.json"

du -sh "$OUT"

# Derived comparisons, COMPUTED from the audit trails rather than typed in, so
# the page can never drift from the artifacts it claims to describe.
python3 - <<'PY'
import collections, json

RUNS = {
    "B0": "runs/run_B0_blind_retry_1f2d6ac3f8/audit.jsonl",
    "B1": "runs/run_B1_scheduled_retry_dd6fdfb107/audit.jsonl",
    "agent": "runs/run_agent_llm_7a3279219e/audit.jsonl",
}
EXECUTED = {"ALLOW", "MODIFY"}
# Strictly RETRY for the like-for-like table: SWITCH_RAIL is agent-only, so
# including it would smuggle the wider action space into the comparison whose
# entire purpose is to exclude it.

retry_targeting, by_action = {}, {}
for name, path in RUNS.items():
    recs = [json.loads(l) for l in open(path) if l.strip()]
    executed = 0
    recovered = 0
    counts, value = collections.Counter(), collections.Counter()
    for r in recs:
        fa = r.get("final_action")
        if r["disposition"] not in EXECUTED or not fa:
            continue
        at = fa["action_type"]
        if at == "RETRY":
            executed += 1
            if r.get("money_delta"):
                recovered += 1
        if r.get("money_delta"):
            counts[at] += 1
            value[at] += r["money_delta"]
    retry_targeting[name] = {
        "retries_executed": executed, "recovered": recovered,
        "hit_rate": (recovered / executed) if executed else 0.0,
    }
    by_action[name] = {"counts": dict(counts), "value_paise": dict(value)}

json.dump({"retry_targeting": retry_targeting, "recoveries_by_action": by_action},
          open("docs/data/derived.json", "w"), indent=2)
for k, v in retry_targeting.items():
    print(f"  {k:<6} retries={v['retries_executed']:>3} recovered={v['recovered']:>3} hit={v['hit_rate']:.0%}")
PY

# Cache-bust the page assets. GitHub Pages serves styles.css / app.js with
# cache-control: max-age=600, so a browser that loaded the page in the last
# ten minutes keeps the OLD stylesheet and script against fresh HTML -- the
# tabs then render as native buttons and don't respond. Stamping a content
# hash into the reference makes a changed file a different URL, so the
# browser cannot serve a stale one. Matters most mid-demo.
python3 - <<'PY'
import hashlib, pathlib, re
docs = pathlib.Path("docs")
html = (docs / "index.html").read_text()
for asset in ("styles.css", "app.js"):
    digest = hashlib.sha256((docs / asset).read_bytes()).hexdigest()[:8]
    html = re.sub(rf'({re.escape(asset)})(\?v=[0-9a-f]+)?', rf'\1?v={digest}', html)
(docs / "index.html").write_text(html)
print("  stamped asset versions: " + ", ".join(
    re.findall(r'(?:styles\.css|app\.js)\?v=[0-9a-f]+', html)))
PY
