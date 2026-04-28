#!/usr/bin/env bash
# post_session.sh — Hermes session-end hook for postmortem-evolve.
#
# Runs after a Hermes session ends. Extracts failure candidates from the
# session transcript, surfaces them to the user, and promotes any recurring
# patterns into MEMORY.md.
#
# Install: copy or symlink to ~/.hermes/hooks/ and register via
#          `hermes hooks add post_session ~/.hermes/hooks/post_session.sh`
#          (verify exact CLI flag with `hermes hooks --help` — Hermes' hook
#          spec evolves; this script targets the documented Stop/SessionEnd
#          event, but flag names may need adjustment.)
#
# Inputs (env vars Hermes typically sets — see `hermes hooks --help`):
#   HERMES_SESSION_ID         — session id of the session that just ended
#   HERMES_SESSION_TRANSCRIPT — path to the session transcript JSON
#
# Stdlib bash only. Python is invoked via the user's Python (3.9+ supported).

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
SKILL_DIR="$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)"
DETECT="$SKILL_DIR/scripts/detect.py"
PROMOTE="$SKILL_DIR/scripts/promote.py"

# Pick a python — prefer hermes' bundled venv if available, else system.
if [[ -x "/usr/local/lib/hermes-agent/venv/bin/python" ]]; then
    PYTHON="/usr/local/lib/hermes-agent/venv/bin/python"
elif command -v python3 &> /dev/null; then
    PYTHON="$(command -v python3)"
else
    echo "[postmortem-evolve] no python3 found, skipping" >&2
    exit 0
fi

TRANSCRIPT="${HERMES_SESSION_TRANSCRIPT:-}"

# Step 1: detect candidates from the just-ended session (if transcript provided)
if [[ -n "$TRANSCRIPT" && -f "$TRANSCRIPT" ]]; then
    echo "[postmortem-evolve] scanning $TRANSCRIPT for failure signals..."
    CANDIDATES_JSON="$("$PYTHON" "$DETECT" --input "$TRANSCRIPT" --strict --format json)"
    CANDIDATE_COUNT="$(echo "$CANDIDATES_JSON" | "$PYTHON" -c 'import json,sys; print(len(json.load(sys.stdin).get("candidates",[])))')"
    if [[ "$CANDIDATE_COUNT" -gt 0 ]]; then
        echo "[postmortem-evolve] $CANDIDATE_COUNT candidate(s) — review and consider writing entries:"
        echo "$CANDIDATES_JSON"
    else
        echo "[postmortem-evolve] no failure signals detected in this session"
    fi
else
    echo "[postmortem-evolve] no transcript path in env, skipping detection step"
fi

# Step 2: run promotion (always — picks up entries written by the agent during the session)
echo "[postmortem-evolve] running promotion against ~/.hermes/memories/..."
"$PYTHON" "$PROMOTE" --prune
