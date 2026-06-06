#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LAUNCH_DIR="${HOME}/Library/LaunchAgents"

agents=(
  "ai.trading-agent.precompute.plist:ai.trading-agent.precompute"
  "ai.trading-agent.health.plist:ai.trading-agent.health"
  "ai.trading-agent.stats.plist:ai.trading-agent.stats"
)

mkdir -p "${LAUNCH_DIR}" "${ROOT}/data"

render_agent() {
  local plist_name="$1"
  sed "s#__HOME__#${HOME}#g" "${ROOT}/deploy/${plist_name}" \
    > "${LAUNCH_DIR}/${plist_name}"
}

load_agent() {
  local plist_name="$1"
  local label="$2"
  local target="${LAUNCH_DIR}/${plist_name}"

  if launchctl list | grep -q "[[:space:]]${label}$"; then
    launchctl unload "${target}" >/dev/null 2>&1 || true
  fi
  launchctl load "${target}"
}

for item in "${agents[@]}"; do
  plist_name="${item%%:*}"
  label="${item##*:}"
  render_agent "${plist_name}"
  load_agent "${plist_name}" "${label}"
  echo "loaded ${label}"
done

launchctl list | grep "ai.trading-agent" || true
