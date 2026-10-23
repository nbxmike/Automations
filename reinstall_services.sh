#!/bin/bash
# Reinstall and restart automation services after updating Python scripts or unit files.
# Usage: sudo ./reinstall_services.sh <service_name>[.service] | --all
set -euo pipefail

EXCLUDED_SERVICES=("omada_presence_automation")

is_excluded_service() {
    local candidate="$1"
    for excluded in "${EXCLUDED_SERVICES[@]}"; do
        if [ "$candidate" = "$excluded" ]; then
            return 0
        fi
    done
    return 1
}

if [ "$#" -ne 1 ]; then
    echo "Usage: sudo $0 <service_name>[.service] | --all" >&2
    exit 1
fi

if [ "$1" != "--all" ]; then
    name="${1%.service}"
    if is_excluded_service "$name"; then
        echo "ERROR: Service '$name' is intentionally excluded from scripted install/reinstall." >&2
        echo "Excluded list: ${EXCLUDED_SERVICES[*]}" >&2
        exit 1
    fi
fi

# Remove CRLF endings before validation and installation because Windows edits
# can break systemd unit files and Python scripts on the Pi.
shopt -s nullglob
for file in /home/pi/automations/*.service /home/pi/automations/*.py /home/pi/automations/*.sh /home/pi/automations/Spectres/*.service /home/pi/automations/Spectres/*.py /home/pi/automations/Spectres/*.sh /home/pi/automations/Routers/*.service /home/pi/automations/Routers/*.py /home/pi/automations/Routers/*.sh; do
    [ -e "$file" ] || continue
    sed -i 's/\r$//' "$file"
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/install_services.sh" "$1"
