#!/usr/bin/env bash
# One command to set up and start the fact-extractor chat workspace.
#
#   ./start.sh                 # set up what is missing, then serve on port 8765
#   ./start.sh --port 9000     # any extra arguments go to `fact-extractor web`
#   ./start.sh --dev           # development: code changes show without a restart or a rebuild.
#                              # Open http://localhost:5173 (the page reloads itself when web/src changes;
#                              # the server on port 8765 restarts itself when the Python code changes).
#
# Every step is skipped when it is already done, so running it again is cheap.
set -euo pipefail

dev=0
args=()
for a in "$@"; do
  if [[ $a == --dev ]]; then dev=1; else args+=("$a"); fi
done
set -- "${args[@]+"${args[@]}"}"

cd "$(dirname "$0")"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v uv >/dev/null || die "uv is not installed: https://docs.astral.sh/uv/"
# npm is not always linked next to node (e.g. a node symlink in ~/.local/bin);
# look in the folder of the real node binary before giving up.
if ! command -v npm >/dev/null && command -v node >/dev/null; then
  PATH="$(dirname "$(readlink -f "$(command -v node)")"):$PATH"
fi
command -v npm >/dev/null || die "npm is not installed (Node.js is needed to build the web UI)"

say "Python dependencies (uv sync)"
uv sync --quiet

if [[ ! -f .env ]]; then
  say "Creating .env from .env.example"
  cp .env.example .env
fi
if ! grep -Eq '^OPENAI_API_KEY=.+' .env && [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "note: OPENAI_API_KEY is not set in .env; chat, summaries and new runs will not work until it is."
fi

if [[ ! -d web/node_modules || web/package-lock.json -nt web/node_modules ]]; then
  say "Web dependencies (npm install)"
  npm --prefix web install --no-audit --no-fund
  touch web/node_modules
fi

if [[ $dev == 1 ]]; then
  say "Development mode: open http://localhost:5173"
  npm --prefix web run dev -- --clearScreen false &
  vite=$!
  trap 'kill "$vite" 2>/dev/null || true' EXIT INT TERM
  uv run fact-extractor web --runs runs --reload "$@"
  exit $?
fi

static=src/fact_extractor/web/static
if [[ ! -f $static/index.html ]] \
   || [[ -n "$(find web/src web/index.html web/vite.config.ts web/package.json -newer "$static/index.html" -print -quit)" ]]; then
  say "Building the web UI"
  npm --prefix web run build
fi

say "Starting the workspace"
exec uv run fact-extractor web --runs runs "$@"
