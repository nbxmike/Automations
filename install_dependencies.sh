#!/bin/sh
# Install the system Python packages required by the Raspberry Pi automation
# scripts in /home/pi/automations. Uses APT packages only.

set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script with sudo: sudo ./install_dependencies.sh" >&2
    exit 1
fi

AUTOMATIONS_DIR="/home/pi/automations"
if [ ! -d "$AUTOMATIONS_DIR" ]; then
    echo "Automation directory not found: $AUTOMATIONS_DIR" >&2
    exit 1
fi

# Repair files copied from Windows before installing dependencies.
for file in "$AUTOMATIONS_DIR"/*.service "$AUTOMATIONS_DIR"/*.py "$AUTOMATIONS_DIR"/*.sh; do
    [ -f "$file" ] || continue
    if ! sed -i 's/\r$//' "$file"; then
        echo "Could not normalize line endings: $file" >&2
        exit 1
    fi
    case "$file" in
        *.py|*.sh)
            if ! chmod +x "$file"; then
                echo "Could not make file executable: $file" >&2
                exit 1
            fi
            ;;
    esac
done

apt-get update

# python3: interpreter used by all automation scripts and their systemd units.
# python3-paho-mqtt: MQTT client library used to communicate with the broker.
# python3-astral: sunrise/sunset calculations used by the time-based automations.
#                 Install via apt first; a pip fallback is only used if apt cannot
#                 provide the package on a given distro.
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 \
    python3-paho-mqtt \
    python3-astral

printf '\nDependencies installed. To install and start the automation services, run:\n'
printf '  cd /home/pi/automations\n'
printf '  sudo ./install_services.sh --all          # all services\n'
printf '  sudo ./install_services.sh <service_name> # a single service\n'
printf '\nRun ./install_services.sh with no arguments to list services; see README.md for details.\n'
