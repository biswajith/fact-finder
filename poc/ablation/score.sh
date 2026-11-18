#!/usr/bin/env bash
# Recall for every finished run (needs the reference lists), then the summary table.
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT=poc/ablation
for dir in $OUT/*/*/; do
  dir=${dir%/}; tag=$(basename "$dir")
  [ -f "$dir/facts.json" ] || continue
  case $tag in
    ulster) gold="poc/gold/gold_bdgsx.txt poc/gold/gold_c.txt poc/gold/gold_r.txt" ;;
    durham) gold="poc/durham/gold/gold.txt"
            # Until a person has checked the draft and saved it as gold.txt, score against the draft.
            [ -f "$gold" ] || gold="poc/durham/gold/gold_draft.txt" ;;
  esac
  ok=1; for g in $gold; do [ -f "$g" ] || ok=0; done
  [ $ok = 1 ] || { echo "skip recall for $dir: no reference list yet"; continue; }
  # shellcheck disable=SC2086
  # One judge cache per document: the same pair of texts gets the same verdict in every run,
  # so judge noise does not add to the difference between two runs.
  uv run fact-extractor compare $gold --facts "$dir/facts.json" --judge --judge-cache "$OUT/judge.$tag.json" \
    --json "$dir/compare.json" > "$dir/compare.log" 2>&1
done
uv run python poc/ablation/summarize.py
