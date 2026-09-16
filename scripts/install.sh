#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
LIB_DIR="${HOME}/.local/lib/schedule-agent"
SKILL_DIR="${HOME}/.cursor/skills/schedule-agent"

mkdir -p "${BIN_DIR}" "${LIB_DIR}" "${SKILL_DIR}"

rm -rf "${LIB_DIR}/schedule_agent"
cp -a "${ROOT}/schedule_agent" "${LIB_DIR}/schedule_agent"
install -m 0755 "${ROOT}/bin/schedule-agent" "${BIN_DIR}/schedule-agent"
install -m 0644 "${ROOT}/skill/SKILL.md" "${SKILL_DIR}/SKILL.md"

if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
  echo "note: ${BIN_DIR} is not on PATH. Add it before using schedule-agent."
fi

echo "installed ${BIN_DIR}/schedule-agent"
echo "installed skill ${SKILL_DIR}/SKILL.md"
echo "installing systemd user timer..."
"${BIN_DIR}/schedule-agent" setup
echo "done. next: schedule-agent validate"
