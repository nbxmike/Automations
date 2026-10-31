# Home Automations

**Run `sudo ./install_dependencies.sh` before you install any services.** The services won't start until the Python packages and system tools it installs are present.

These scripts run on a Raspberry Pi as systemd services from `/home/pi/automations`. They talk to the MQTT broker (Zigbee2MQTT and Tasmota) to automate the kitchen lights, the Wyze outdoor plug (`wyze_parking_tree`), and the late-arrival override.

## Quick start

Run these on the Pi:

```sh
# 1. Put all files in /home/pi/automations, then fix line endings and permissions
#    (needed when the files were edited on Windows). No sudo needed; you own these files.
cd /home/pi/automations
sed -i 's/\r$//' /home/pi/automations/*.service /home/pi/automations/*.py /home/pi/automations/*.sh
chmod +x *.sh *.py

# 2. Install dependencies. REQUIRED FIRST. Needs sudo.
sudo ./install_dependencies.sh

# 3. Optional: check the syntax of every script. No sudo needed.
./check_python_syntax.sh

# 4. Install, enable and start the services. Needs sudo.
sudo ./install_services.sh --all
```

## Local credentials

Each automation script now reads its broker and controller credentials from a local file named `automation_credentials.py`. That file is git-ignored, so the real username/password values are kept off the remote repository.

Create `automation_credentials.py` beside the scripts and fill in your local values before running anything:

```python
MQTT_BROKER = "www.xxx.yyy.zzz"
MQTT_PORT = 1883
MQTT_USER = "your_mqtt_user"
MQTT_PASS = "your_mqtt_password"

OMADA_BASE_URL = "https://your-omada-host:8043"
OMADA_CLIENT_ID = "your_omada_client_id"
OMADA_CLIENT_SECRET = "your_omada_client_secret"
OMADA_SITE_ID = "your_site_id"
OMADA_USERNAME = "your_omada_user"
OMADA_PASSWORD = "your_omada_password"
```

## Automations

| Python script | Service file | What it does |
|---|---|---|
| `kitchen_morning.py` | `kitchen_morning.service` | When kitchen presence is detected between 05:00 and sunrise, and all lights are off, turns on the kitchen LED strips and the Girier dimmer. |
| `kitchen_early_morning_on.py` | `kitchen_early_morning_on.service` | When presence is detected between 05:00 and sunrise, turns on the kitchen LED strips (warm white), outlet 1 of the Wyze plug, GardenLights, gardenPath, and the BackDoor Zigbee light at 20% brightness. |
| `kitchen_dimming.py` | `kitchen_dimming.service` | Dims kitchen lights after 10 minutes of vacancy. If the service dimmed lights, it restores them to about 80% after 3 continuous minutes of occupancy between sunset and sunrise, unless Alexa manually intervenes. |
| `kitchen_spectre_router.py` | `kitchen_spectre_router.service` | Listens for `kitchenGhostly` virtual-device set commands and forwards equivalent power/brightness/color-temp commands to the physical kitchen strips and dimmer topics used by `kitchen_dimming.py`. |
| `backyard_spectre_router.py` | `backyard_spectre_router.service` | Listens for `backyardGhost` virtual-device set commands and forwards ON/brightness/color-temp commands to the Wyze outdoor plug, GardenLights, gardenPath, and BackDoor. OFF only applies to `wyzeParkingTree/POWER1`. |
| `basement_spectre_router.py` | `basement_spectre_router.service` | Listens for `basementGhostly` virtual-device commands and forwards state, brightness, and color temperature to the `Basement_Oil_Tank_Light` Zigbee2MQTT light. |
| `yard_sunset_automation.py` | `yard_sunset_automation.service` | Turns on both outlets of the Tasmota Wyze Plug Outdoor, GardenLights, and gardenPath at sunset. BackDoor uses 50% brightness at or below 60 F, otherwise 25%. |
| `yard_midnight_automation.py` | `yard_midnight_automation.service` | Turns off outlet 1 of the Wyze plug and turns off the BackDoor Zigbee light at midnight, unless the late-arrival override is ON. An override older than 6 hours is treated as stale and ignored. |
| `yard_sunrise_automation.py` | `yard_sunrise_automation.service` | Turns off both outlets of the Wyze plug at sunrise and turns off GardenLights, gardenPath, and the BackDoor Zigbee light. |
| `yard_presence_night_off.py` | `yard_presence_night_off.service` | Between 21:00 and sunrise, when `phonePresence/everyone` has stayed true for 10 minutes and the arrival override is OFF, turns off outside lights. If Wyze/BackDoor turns back ON, the timer restarts. |
| `presence_check_v2.py` | `presence_check_v2.service` | Polls the Omada OpenAPI client list and publishes retained boolean MQTT topics under `phonePresence/` for each tracked person plus `phonePresence/everyone` (logical AND). |
| `omada_presence_automation.py` | `omada_presence_automation.service` | Checks the Omada controller client list and, when every expected phone is home, turns off the yard outlet 1 using the same MQTT command as the midnight automation. |

### Sunset BackDoor Temperature Rule

`yard_sunset_automation.py` requests approximate current outdoor air temperature
from [Open-Meteo](https://open-meteo.com/en/docs) using its existing latitude and
longitude. This is weather-model data, not a sensor measurement at the house.
The free endpoint needs no API key for personal/non-commercial use. The Pi needs
outbound HTTPS access, valid CA certificates, and an accurate system clock.
Coordinates are sent to the weather provider. No additional Python packages are
required.

When the sunset action runs, a temperature at or below 60 F sets BackDoor to
brightness `127` (50% of Zigbee2MQTT's 254 maximum); warmer weather uses `64`
(approximately 25%). The lookup has a 10-second socket timeout. Missing, invalid,
or more than one-hour-old readings fall back to 25%, with a warning in the
service journal. Other lights retain their existing behavior. Temperature is
checked only for the sunset action, not continuously throughout the night.

### Android Wi-Fi MAC setting for `Hornburg`

Android can use a randomized MAC address for each Wi-Fi network. To use the phone's device MAC only on the home network `Hornburg`:

1. Open **Settings** and go to **Network & internet** > **Internet** (on some phones, **Connections** > **Wi-Fi**).
2. Tap the settings/gear icon next to `Hornburg` to open that network's details.
3. Open **Privacy** or **MAC address type** and select **Use device MAC** or **Phone MAC** instead of **Randomized MAC**.
4. Reconnect to `Hornburg` if prompted.
5. Check the connected phone's MAC address in Omada. `presence_check_v2.py` matches phones using the addresses in `TARGET_MACS`; if the address there differs, update that phone's entry to the address Omada reports.

Menu names vary between Android versions and manufacturers. This setting is per Wi-Fi network; changing it for `Hornburg` does not disable randomized MAC addresses on other networks. Using the device MAC makes it consistently identifiable on this network, but also exposes that hardware address to the network.

### Virtual devices in active use

The current virtual devices are split into dedicated scripts:

- `arrivalOverride`: override switch used by `yard_midnight_automation.py` and `yard_presence_night_off.py`.
- `kitchenGhostly`: Alexa-visible kitchen dimmable light with manual-trigger markers for kitchen automations.
- `backyardGhost`: Alexa-visible backyard dimmable light with matching manual-trigger markers.
- `basementGhost`: Alexa-visible basement dimmable light with the same topic/discovery and manual-trigger behavior pattern as `backyardGhost`.
- `livingRoomGhost`: Alexa-visible living-room dimmable light with the same topic/discovery and manual-trigger behavior pattern as `backyardGhost`.
- `outdoorGhost`: Alexa-visible outdoor dimmable light with the same topic/discovery and manual-trigger behavior pattern as `backyardGhost`.

Example Alexa routine behavior:

Use `kitchenGhostly` as the Alexa kitchen light. Commands such as turning it on/off or setting its brightness update the virtual dimmer and publish `ON` briefly to `stat/kitchenGhostly/manuallyTriggeredBrightness` or `stat/kitchenGhostly/manuallyTriggeredPower`; the flag then clears automatically. `kitchen_dimming.py` consumes that flag to suppress algorithmic auto-brightening after Alexa intervention.

MQTT topics for `kitchenGhostly`:

- Power command/state: `cmnd/kitchenGhostly/POWER` and `stat/kitchenGhostly/POWER`
- Brightness commands: `cmnd/kitchenGhostly/brightness` and `cmnd/kitchenGhostly/brightnessWithOnOff`
- Current brightness: `stat/kitchenGhostly/brightness`
- Manual-intervention flags: `stat/kitchenGhostly/manuallyTriggeredPower`, `stat/kitchenGhostly/manuallyTriggeredBrightness`, `stat/kitchenGhostly/manuallyTriggeredColorTemp`

## Support scripts

### `install_dependencies.sh` (sudo required)

```sh
sudo ./install_dependencies.sh
```

Installs everything the automations need. It uses APT packages (`python3`, `python3-paho-mqtt`, `python3-astral`) and is safe to run again. It exits with an error if it isn't run with `sudo`.

### `install_services.sh` (sudo required)

```sh
sed -i 's/\r$//' /home/pi/automations/*.service /home/pi/automations/*.py /home/pi/automations/*.sh

sudo ./install_services.sh --all                  # every *.service in /home/pi/automations
sudo ./install_services.sh presence_check_v2      # one service (".service" suffix optional)
sudo ./install_services.sh                        # list available services
```

Checks every selected service before changing anything. It stops with instructions if any of these is true:
- A service file or its Python script is missing.
- A script is outside `/home/pi/automations`.
- A file has Windows line endings, or a script has a syntax error.

When the checks pass, it copies the unit files to `/etc/systemd/system`, reloads systemd, then enables and starts each service. It also confirms each one is still running. If a service fails to start, it prints the `journalctl` command to use.

### `reinstall_services.sh` (sudo required)

Use this after editing Python scripts or service files in `/home/pi/automations`. It accepts the same service name or `--all` options, then runs the installer to validate the scripts, install updated unit files, and restart the selected services.

```sh
sed -i 's/\r$//' /home/pi/automations/*.service /home/pi/automations/*.py /home/pi/automations/*.sh

sudo ./reinstall_services.sh presence_check_v2
sudo ./reinstall_services.sh --all
```

### `check_python_syntax.sh` (no sudo)

```sh
./check_python_syntax.sh
```

Byte-compiles every automation script in `/home/pi/automations` and reports any that are missing or have syntax errors. It only reads the scripts, so it doesn't need root.

### `fix_services.txt`

Step-by-step instructions for removing the old hyphenated or templated (`@`) services and reinstalling under the current underscore names. Follow it once if you installed services with an older version of these scripts.

## Uninstall retired services from the Pi

If you are retiring services from this automation set (currently `night_holdoff_matter` and `omada_presence_automation`), remove them from systemd and from `/home/pi/automations`:

```sh
cd /home/pi/automations

for s in night_holdoff_matter omada_presence_automation; do
    sudo systemctl disable --now "$s.service" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/$s.service"
    sudo rm -f "/etc/systemd/system/multi-user.target.wants/$s.service"
done

sudo systemctl daemon-reload
sudo systemctl reset-failed

rm -f /home/pi/automations/night_holdoff_matter.py \
            /home/pi/automations/night_holdoff_matter.service \
            /home/pi/automations/omada_presence_automation.py \
            /home/pi/automations/omada_presence_automation.service
```

Verify they are gone:

```sh
systemctl list-unit-files --type=service | grep -E 'night_holdoff_matter|omada_presence_automation' || true
ls -1 /home/pi/automations | grep -E 'night_holdoff_matter|omada_presence_automation' || true
```

## Removing stale renamed services from the Pi

When you move from the old filenames to the new yard automation names, the old systemd unit files can remain enabled and continue to run even after you copy the new scripts onto the Pi. Remove them explicitly so only the new names remain active.

Check for old service names first:

```sh
sudo systemctl list-unit-files --type=service | grep 'wyze_parking_tree_'
```

If you still see the old units, disable and remove them:

```sh
sudo systemctl disable --now wyze_parking_tree_sunset.service
sudo systemctl disable --now wyze_parking_tree_sunrise_off.service
sudo systemctl disable --now wyze_parking_tree_midnight_off.service

sudo rm -f /etc/systemd/system/wyze_parking_tree_sunset.service \
           /etc/systemd/system/wyze_parking_tree_sunrise_off.service \
           /etc/systemd/system/wyze_parking_tree_midnight_off.service

sudo rm -f /etc/systemd/system/multi-user.target.wants/wyze_parking_tree_sunset.service \
           /etc/systemd/system/multi-user.target.wants/wyze_parking_tree_sunrise_off.service \
           /etc/systemd/system/multi-user.target.wants/wyze_parking_tree_midnight_off.service

sudo systemctl daemon-reload
```

Then install the new services:

```sh
sudo ./install_services.sh --all
```

This installs the renamed units such as `yard_sunset_automation.service`, `yard_sunrise_automation.service`, and `yard_midnight_automation.service`, while leaving the underlying MQTT topics and device behavior unchanged.

## Day-to-day commands

| Task | Command | sudo? |
|---|---|---|
| Check one service's status | `systemctl status <name>.service` | No |
| Follow a service's logs | `journalctl -u <name>.service -f` | No (yes if your user isn't in the `adm`/`systemd-journal` group) |
| Restart a service after editing its script | `sudo systemctl restart <name>.service` | Yes |
| Reinstall a service after editing its `.service` file | `sudo ./install_services.sh <name>` | Yes |
| Stop and disable a service | `sudo systemctl disable --now <name>.service` | Yes |

## Configuration notes

- MQTT broker settings and latitude/longitude are set at the top of each Python script.
- Each service file runs as `User=pi` from `/home/pi/automations`. If you use a different user or folder, edit `User=`, `WorkingDirectory=` and `ExecStart=` in every `.service` file, and `AUTOMATIONS_DIR` in `install_services.sh` and `SCRIPT_DIR` in `check_python_syntax.sh`.
