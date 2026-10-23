#!/bin/bash
set -u

SCRIPT_DIR="/home/pi/automations"

if [ ! -d "$SCRIPT_DIR" ]; then
    echo "Script directory not found: $SCRIPT_DIR"
    exit 1
fi

# Repair files copied from Windows before checking or running them.
for file in "$SCRIPT_DIR"/*.service "$SCRIPT_DIR"/*.py "$SCRIPT_DIR"/*.sh "$SCRIPT_DIR"/Routers/*.service "$SCRIPT_DIR"/Routers/*.py "$SCRIPT_DIR"/Routers/*.sh; do
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

cd "$SCRIPT_DIR" || exit 1

python_files=(
    "Routers/backyard_spectre_router.py"
    "Routers/basement_spectre_router.py"
    "default_color_temp.py"
    "kitchen_dimming.py"
    "kitchen_early_morning_on.py"
    "Routers/kitchen_spectre_router.py"
    "presence_check_v2.py"
    "yard_midnight_automation.py"
    "yard_presence_night_off.py"
    "yard_sunrise_automation.py"
    "yard_sunset_automation.py"
    "Spectres/arrivalOverride.py"
    "Spectres/backGardenSpectre.py"
    "Spectres/BackyardSpecter.py"
    "Spectres/basementSpectre.py"
    "Spectres/diningRoomSpectre.py"
    "Spectres/kitchenSpecter.py"
    "Spectres/livingRoomSpectre.py"
    "Spectres/masterBedroomSpecter.py"
    "Spectres/outdoorSpecter.py"
)

# Keep this list aligned with install/reinstall script exclusions.
# omada_presence_automation.py is intentionally omitted from automated checks.

had_error=0

for file in "${python_files[@]}"; do
    if [ ! -f "$file" ]; then
        echo "Missing file: $file"
        had_error=1
        continue
    fi

    echo "Checking syntax: $file"
    if python3 -m py_compile "$file"; then
        echo "OK: $file"
    else
        echo "ERROR: $file"
        had_error=1
    fi
    echo "---"
done

if [ "$had_error" -ne 0 ]; then
    echo "One or more Python scripts failed syntax validation."
    exit 1
fi

echo "All Python scripts passed syntax validation."
exit 0
