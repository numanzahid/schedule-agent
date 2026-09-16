#!/usr/bin/env bash
set -euo pipefail

BIN="${HOME}/.local/bin/schedule-agent"
LIB="${HOME}/.local/lib/schedule-agent"
SKILL="${HOME}/.cursor/skills/schedule-agent"
UNIT_DIR="${HOME}/.config/systemd/user"
PURGE=0

if [[ "${1:-}" == "--purge" ]]; then
  PURGE=1
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now cursor-schedule.timer >/dev/null 2>&1 || true
fi

rm -f "${UNIT_DIR}/cursor-schedule.service" "${UNIT_DIR}/cursor-schedule.timer"
rm -f "${BIN}"
rm -rf "${LIB}" "${SKILL}"

if [[ "${PURGE}" -eq 1 ]]; then
  rm -rf "${HOME}/.config/schedule-agent" "${HOME}/.local/state/schedule-agent"
  echo "removed jobs and logs"
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

echo "uninstalled schedule-agent"
