#!/usr/bin/env bash
# Trimming tests: run each configuration on both RFPs, then score recall and precision.
# Usage: poc/ablation/run.sh [config ...]   (no args = all). Re-running a config overwrites it.
# Spends tokens: each run is ~30-90 model calls; grading adds ~1 call per 20 new facts.
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT=poc/ablation

declare -A CONFIGS=(
  # base = the defaults before 2026-11-16 (2 passes, repair on); repair has since been removed,
  # so rerunning base now measures 2 passes without repair.
  [base]="--passes 2"
  [base_rerun]="--passes 2"                         # same again: run-to-run noise
  [p1]="--passes 1"
  [p1_nosweep]="--passes 1 --no-sweep"
  [p1_narrow]="--passes 1 --narrow-sweep"
  [p1_cap8k]="--passes 1 --max-output-tokens 8000"
)
ORDER=(base base_rerun p1 p1_nosweep p1_narrow p1_cap8k)
DOCS=(
  "ulster|RFP-UC26-039 ACTUARIAL SERVICES FOR ULSTER COUNTY SELF INSURANCE PLAN.pdf|rfp-uc26-039|poc/gold/gold_bdgsx.txt poc/gold/gold_c.txt poc/gold/gold_r.txt"
  "durham|RFP24 0031 for Oracle ERP Implementation Partner - Addendum 1.pdf|durham-rfp24-0031|poc/durham/gold/gold.txt"
)
[ $# -gt 0 ] && ORDER=("$@")

for name in "${ORDER[@]}"; do
  for d in "${DOCS[@]}"; do
    IFS='|' read -r tag pdf doc_id gold <<<"$d"
    dir=$OUT/$name/$tag; mkdir -p "$dir"
    echo "== $name / $tag"
    # shellcheck disable=SC2086
    uv run fact-extractor extract "$pdf" --doc-id "$doc_id" --deal-id "$tag" ${CONFIGS[$name]} \
      --out "$dir/facts.json" --report "$dir/report.json" 2> "$dir/extract.log" || { echo "extract failed"; continue; }
    tail -1 "$dir/extract.log" >/dev/null
    head -1 "$dir/extract.log"
    uv run fact-extractor precision "$dir/facts.json" --grade --json "$dir/precision.json" > "$dir/precision.log" 2>&1
  done
done
