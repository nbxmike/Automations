#!/bin/bash

# Ensure the script is run with root privileges
if [ "$EUID" -ne 0 ]; then
  echo "[-] Please run this script with sudo or as root." >&2
  exit 1
fi

# Path to your processes file (change if located elsewhere)
PROCESS_FILE="Processes.txt"

if [ ! -f "$PROCESS_FILE" ]; then
  echo "[-] Error: File '$PROCESS_FILE' not found!" >&2
  exit 1
fi

echo "[+] Parsing services from $PROCESS_FILE..."

# Extract lines starting with 'service:' and get the second column (e.g., BackyardSpecter.service)
SERVICES=$(grep '^service:' "$PROCESS_FILE" | awk '{print $2}')

if [ -z "$SERVICES" ]; then
  echo "[-] No services found in the file."
  exit 0
fi

for svc in $SERVICES; do
  echo "--------------------------------------------------"
  echo "[*] Processing service: $svc"

  # 1. Stop the service if it's running
  if systemctl is-active --quiet "$svc"; then
    echo "    -> Stopping $svc..."
    systemctl stop "$svc"
  else
    echo "    -> Service $svc is already stopped."
  fi

  # 2. Disable the service from starting on boot
  if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
    echo "    -> Disabling $svc..."
    systemctl disable "$svc"
  else
    echo "    -> Service $svc is already disabled or has no install state."
  fi

  # 3. Remove the unit file if it exists in /etc/systemd/system/
  UNIT_PATH="/etc/systemd/system/$svc"
  if [ -f "$UNIT_PATH" ]; then
    echo "    -> Removing unit file at $UNIT_PATH..."
    rm -f "$UNIT_PATH"
  else
    echo "    -> Unit file not found at $UNIT_PATH (might already be removed)."
  fi
done

echo "--------------------------------------------------"
echo "[+] Reloading systemd daemon to clear removed units..."
systemctl daemon-reload
systemctl reset-failed

echo "[✔] All services have been successfully stopped, disabled, and removed!"