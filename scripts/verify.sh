#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"

fail() {
  echo "FAIL: $*" >&2
  exit 2
}

command -v python3 >/dev/null || fail "python3 is required"
python3 - "${ROOT}" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from schedule_agent.cron import cron_matches, parse_cron
parse_cron("0 6 * * *")
from datetime import datetime, timezone
assert cron_matches("0 6 * * *", datetime(2026, 9, 16, 6, 0))
print("python package import: ok")
PY

if [[ -x "${HOME}/.local/bin/schedule-agent" ]]; then
  schedule-agent --version
  schedule-agent validate || true
else
  "${ROOT}/bin/schedule-agent" --version
  echo "note: not installed to ~/.local/bin yet. run scripts/install.sh"
fi

if ! command -v agent >/dev/null 2>&1 && [[ ! -x "${HOME}/.local/bin/agent" ]]; then
  echo "WARN: Cursor CLI (agent) not found"
fi

echo "verify finished"
