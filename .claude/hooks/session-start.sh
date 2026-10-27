#!/bin/bash
# Claude Code on the web: dependencies for tests and the build, and gstack (the AI team's
# skills, CLAUDE.md → "gstack"). Idempotent; the container is cached after the first run.
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

# backend (FastAPI, pytest)
python3 -m pip install -q -r backend/requirements.txt pytest 2>&1 | grep -v "Running pip as the 'root' user" || true

# frontend (type check + build)
(cd frontend && npm install --no-audit --no-fund --loglevel=error)

# gstack — global install, team mode; outside reviews by a second model and telemetry stay off
GS="$HOME/.claude/skills/gstack"
if [ ! -d "$GS/.git" ]; then
  mkdir -p "$HOME/.claude/skills"
  git clone -q --single-branch --depth 1 https://github.com/garrytan/gstack.git "$GS" || { echo "gstack: clone failed, skipping"; exit 0; }
fi
if command -v bun >/dev/null 2>&1; then
  # gstack is tested on Bun 1.4.2 and refuses < 1.3.3; an older Bun only prints a warning
  (cd "$GS" && ./setup --team --quiet) || echo "gstack: setup failed — run 'cd ~/.claude/skills/gstack && ./setup --team' by hand"
  "$GS/bin/gstack-config" set codex_reviews disabled >/dev/null 2>&1 || true
  "$GS/bin/gstack-config" set telemetry off >/dev/null 2>&1 || true
else
  echo "gstack: bun not found — install bun (https://bun.sh) and run ./setup --team in $GS"
fi
