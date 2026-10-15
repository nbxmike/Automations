#!/bin/bash
# Remove stale renamed services from the Raspberry Pi, plus retired Night Holdoff.
# Usage: sudo ./remove_stale_services.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script with sudo: sudo ./remove_stale_services.sh" >&2
    exit 1
fi

STALE_SERVICES=(
    "wyze_parking_tree_sunset"
    "wyze_parking_tree_sunrise_off"
    "wyze_parking_tree_midnight_off"
    "night_holdoff_matter"
    "kitchen_morning"
)

STALE_GREP_PATTERN="$(printf '%s|' "${STALE_SERVICES[@]}")"
STALE_GREP_PATTERN="${STALE_GREP_PATTERN%|}"

echo "Checking for stale services..."
systemctl list-unit-files --type=service | grep -E "$STALE_GREP_PATTERN" || true

echo
echo "Disabling and removing stale services..."
for service in "${STALE_SERVICES[@]}"; do
    systemctl disable --now "${service}.service" 2>/dev/null || true

    rm -f \
        "/etc/systemd/system/${service}.service" \
        "/etc/systemd/system/multi-user.target.wants/${service}.service"

    echo "  Removed: ${service}.service"
done

echo
systemctl daemon-reload
systemctl reset-failed || true

echo "Done."
echo "Remaining matches (should be empty):"
systemctl list-unit-files --type=service | grep -E "$STALE_GREP_PATTERN" || true
