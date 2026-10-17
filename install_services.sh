#!/bin/bash
# Install, enable and start automation systemd services from /home/pi/automations.
# Usage: sudo ./install_services.sh <service_name>[.service] | --all
set -euo pipefail

AUTOMATIONS_DIR="/home/pi/automations"
SYSTEMD_DIR="/etc/systemd/system"
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

usage() {
    echo "Usage: sudo $0 <service_name>[.service] | --all"
    echo
    echo "Available services in $AUTOMATIONS_DIR:"
    for f in "$AUTOMATIONS_DIR"/*.service; do
        [ -e "$f" ] || continue
        name="$(basename "$f" .service)"
        is_excluded_service "$name" && continue
        echo "  $name"
    done
    echo
    echo "Excluded from this installer: ${EXCLUDED_SERVICES[*]}"
    exit 1
}

fail() {
    echo
    echo "ERROR: $1" >&2
    shift
    for line in "$@"; do
        echo "  $line" >&2
    done
    echo >&2
    echo "Installation halted. No further changes were made." >&2
    exit 1
}

if [ "$#" -ne 1 ]; then
    usage
fi

if [ "$(id -u)" -ne 0 ]; then
    fail "This script must be run as root." "Re-run with: sudo $0 $1"
fi

# Strip CRLF from all automation files before validation. This avoids systemd
# and Python parsing errors when scripts have been edited on a Windows system.
sed -i 's/\r$//' /home/pi/automations/*.service /home/pi/automations/*.py /home/pi/automations/*.sh

if [ ! -d "$AUTOMATIONS_DIR" ]; then
    fail "Automation directory not found: $AUTOMATIONS_DIR" \
        "Copy the automation scripts and service files to $AUTOMATIONS_DIR," \
        "or update AUTOMATIONS_DIR here and the paths in every .service file."
fi

syntax_check="$AUTOMATIONS_DIR/check_python_syntax.sh"
if [ ! -f "$syntax_check" ]; then
    fail "Python syntax checker not found: $syntax_check" \
        "Copy check_python_syntax.sh into $AUTOMATIONS_DIR before installing services."
fi

required_files=(
    "$AUTOMATIONS_DIR/default_color_temp.py"
    "$AUTOMATIONS_DIR/default_color_temp.service"
)
for required_file in "${required_files[@]}"; do
    if [ ! -f "$required_file" ]; then
        fail "Required automation file not found: $required_file" \
            "Copy the missing file into $AUTOMATIONS_DIR before installing services."
    fi
done

echo "Running Python syntax checks..."
if ! bash "$syntax_check"; then
    fail "Python syntax check failed." \
        "Resolve the reported missing files or syntax errors, then re-run the installer."
fi

# Build the list of services to install.
services=()
if [ "$1" = "--all" ]; then
    for f in "$AUTOMATIONS_DIR"/*.service; do
        [ -e "$f" ] || continue
        name="$(basename "$f" .service)"
        is_excluded_service "$name" && continue
        services+=("$name")
    done
    [ "${#services[@]}" -gt 0 ] || fail "No installable .service files found in $AUTOMATIONS_DIR." \
        "All discovered services may be excluded: ${EXCLUDED_SERVICES[*]}"
else
    name="${1%.service}"
    if [[ ! "$name" =~ ^[A-Za-z0-9_]+$ ]]; then
        fail "Invalid service name: '$1'" \
            "Service names may only contain letters, digits and underscores (no hyphens)." \
            "Run '$0' with no arguments to list available services."
    fi
    if is_excluded_service "$name"; then
        fail "Service '$name' is intentionally excluded from scripted install/reinstall." \
            "Use a different service name, or remove it from EXCLUDED_SERVICES in $0 if needed."
    fi
    services=("$name")
fi

# Validate every selected service before touching the system.
echo "Validating ${#services[@]} service(s)..."
for name in "${services[@]}"; do
    unit="$AUTOMATIONS_DIR/$name.service"

    if [[ ! "$name" =~ ^[A-Za-z0-9_]+$ ]]; then
        fail "Service file name '$name.service' contains unsupported characters." \
            "Rename it to use only letters, digits and underscores, then re-run."
    fi

    if [ ! -f "$unit" ]; then
        fail "Service file not found: $unit" \
            "Copy $name.service into $AUTOMATIONS_DIR, or check the spelling." \
            "Run '$0' with no arguments to list available services."
    fi

    if grep -q $'\r' "$unit"; then
        fail "$unit has Windows (CRLF) line endings, which systemd cannot parse reliably." \
            "Fix with: sed -i 's/\\r\$//' $AUTOMATIONS_DIR/*.service $AUTOMATIONS_DIR/*.py $AUTOMATIONS_DIR/*.sh"
    fi

    exec_line="$(grep -m1 '^ExecStart=' "$unit" || true)"
    if [ -z "$exec_line" ]; then
        fail "$unit has no ExecStart= line." \
            "Edit the service file so ExecStart points to its python script."
    fi

    script_path="$(echo "$exec_line" | grep -oE '[^[:space:]=]+\.py' | tail -n1 || true)"
    if [ -z "$script_path" ]; then
        fail "Could not find a .py script in $unit:" \
            "$exec_line" \
            "Edit ExecStart to: /usr/bin/python3 $AUTOMATIONS_DIR/<script>.py"
    fi

    if [ "$(dirname "$script_path")" != "$AUTOMATIONS_DIR" ]; then
        fail "$name.service runs a script outside $AUTOMATIONS_DIR:" \
            "$script_path" \
            "Move the script to $AUTOMATIONS_DIR and update ExecStart/WorkingDirectory in $unit."
    fi

    if [ ! -f "$script_path" ]; then
        fail "Python script for $name.service is missing: $script_path" \
            "Copy $(basename "$script_path") into $AUTOMATIONS_DIR," \
            "or modify ExecStart in $unit to point to the correct script location."
    fi

    if ! python3 -m py_compile "$script_path" 2>/dev/null; then
        fail "Syntax error in $script_path" \
            "Run: python3 -m py_compile $script_path   to see the details."
    fi

    echo "  OK: $name.service -> $script_path"
done

# Copy unit files.
echo
echo "Copying service files to $SYSTEMD_DIR..."
for name in "${services[@]}"; do
    install -o root -g root -m 0644 "$AUTOMATIONS_DIR/$name.service" "$SYSTEMD_DIR/$name.service" \
        || fail "Could not copy $name.service to $SYSTEMD_DIR."
    echo "  Copied $name.service"
done

systemctl daemon-reload \
    || fail "systemctl daemon-reload failed." \
        "Check the unit files with: systemd-analyze verify $SYSTEMD_DIR/<name>.service"

# Enable and (re)start each service, confirming it stays up.
echo
echo "Enabling and starting services..."
for name in "${services[@]}"; do
    if ! systemctl enable "$name.service" >/dev/null 2>&1; then
        fail "Could not enable $name.service." \
            "Check the [Install] section of $SYSTEMD_DIR/$name.service." \
            "Details: systemctl status $name.service"
    fi

    if ! systemctl restart "$name.service"; then
        fail "$name.service failed to start." \
            "View logs: journalctl -u $name.service -n 50 --no-pager" \
            "Status:    systemctl status $name.service"
    fi

    sleep 2
    if ! systemctl is-active --quiet "$name.service"; then
        fail "$name.service started but is no longer running." \
            "View logs: journalctl -u $name.service -n 50 --no-pager" \
            "Common causes: missing python packages (run sudo ./install_dependencies.sh)," \
            "wrong User= in the service file, or MQTT broker unreachable."
    fi

    echo "  Running: $name.service"
done

echo
echo "All selected services installed and running."
echo "Follow logs with: journalctl -u <service_name>.service -f"
