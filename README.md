# Home Automation Scripts

This repository contains Python automations and systemd service files for a Raspberry Pi-based home automation setup. The scripts connect to an MQTT broker and coordinate indoor and outdoor lights with a few inputs from other sources.

The author tried Home Assistant, OpenHAB and Node-RED because of their "ease" of use and found that all of them sucked in one way or another.  While each in turn did what the original development team wanted; all were afflicted to some extent by inane abstractions, models, rules and constraints that made the simple automations tedious and non-functional.  For example I ran into problems with abstraction models that did not address light controllers that only had white temperature adjustment but no RGB topics, or, my outdoor dual smart plug was fine until I faced the reality that it shared a single voltage reading for the two outlets and that was beyond the framework to understand, or, that I want an automation to do one thing if the last setting was performed by an automation and something else if the last was from a manual operation.  Also, while integration with a commercial voice assistant for manual control was allegedly integrated in every system they were either behind a paywall, required web access or the alignment between Alexa’s (my existing voice) abstractions and the automation systems’ abstractions was unworkable.

So, python was eventually selected to just grab MQTT topics, some time-of-day data information, data from my LAN’s client list via an API, and, a virtual device which adds some data from my Alexa system.

I do not think that anyone will want to use my automations as is.  I am publishing this just so people have an idea what can be accomplished without the need to learn someone else’s vocabulary and constraint concepts.  Use these scripts as templates and concepts for what can be done.

## What It Does

- **Kitchen lighting:** turns lights on during the early morning, dims them after the room is vacant, and can restore brightness after occupancy returns. Virtual MQTT kitchen devices let Alexa interactions suppress automatic brightening, and a router service can mirror virtual `kitchenSpectre` set commands to the physical kitchen lights.
- **Outdoor lighting and outlets:** controls the outdoor plug and back-door light around sunset, midnight, and sunrise, with a late-arrival override.
- **Phone presence:** polls the Omada controller for configured phones and publishes retained per-person and household presence topics over MQTT. Other automations can use that state to control outdoor devices.

The `.service` files run the automations under systemd. The shell scripts install dependencies, validate Python syntax, install or reinstall services, and remove stale service units.

Zigbee2MQTT, Tasmota, , and phone-presence state across a Mosquitto broker and an Omada network controller.
## Integrations

- Raspberry Pi running Linux and systemd
- MQTT broker
- Zigbee2MQTT and Tasmota devices
- Omada Controller OpenAPI for phone-presence checks
- Alexa integration through the MQTT virtual devices

These automations are tailored to a specific home environment. Device topics, network details, phone identifiers, coordinates, and schedules may need adjustment before use.

## Configuration And Setup

Runtime credentials are supplied through a local `automation_credentials.py` module. It is intentionally excluded from Git; create it on the host and configure the MQTT and Omada values required by the scripts. Do not commit real passwords, API secrets, or other credentials.

For installation prerequisites, the configuration template, service commands, Android Wi-Fi MAC guidance, and maintenance procedures, see [AUTOMATION_INSTRUCTIONS.md](AUTOMATION_INSTRUCTIONS.md). Omada-specific setup and permissions are also documented in [OMADA_SETUP.md](OMADA_SETUP.md) and [OMADA_PERMISSION_CHECKLIST.md](OMADA_PERMISSION_CHECKLIST.md).

The dependency installer uses the host's APT packages for Python, Paho MQTT, and Astral. Install dependencies before enabling services. The detailed instructions describe the expected `/home/pi/automations` deployment path and the service installation workflow.

## diyHue Device Monitor

[Tools/diyhue_monitor.py](Tools/diyhue_monitor.py) polls the Hue v1 API at
`http://172.24.32.102` every five seconds. It uses only the Python standard
library and does not change device states. No MQTT credentials are needed.

Use an existing Hue API username/key, or enable the link/pairing button in the
diyHue web interface and immediately run:

```sh
python3 Tools/diyhue_register.py
```

Registration creates an API user and saves its key as `DIYHUE_API_KEY` in the
git-ignored [automation_credentials.py](automation_credentials.py), preserving
existing credentials without displaying the key. The monitor reads that file;
no environment-variable setup is needed. If you already have a valid key, add
`DIYHUE_API_KEY = "your-hue-api-key"` to that file instead of registering again.
The monitor's `--register` shortcut also saves the key using the new tool.

Windows PowerShell, from the repository directory:

```powershell
python Tools/diyhue_monitor.py
```

Linux/Raspberry Pi:

```sh
python3 Tools/diyhue_monitor.py
```

The default report is `Tools/diyhue_devices.txt`. Each run appends an initial
inventory, followed by timestamped attribute changes and a complete snapshot
whenever the API data changes. It includes every resource returned by the Hue
v1 root endpoint: lights, sensors, groups, scenes, rules, schedules, bridge
configuration, and other available resources. Device records retain names,
IDs, models, manufacturers, state, capabilities, and other exposed attributes.
Unavailable resource types are not invented or fetched through the Hue v2 API.

For a single inventory or a faster debugging session:

```sh
python3 Tools/diyhue_monitor.py --once
python3 Tools/diyhue_monitor.py --interval 1 --output diyhue_debug.txt
```

Use `--server https://172.24.32.102` if your server requires HTTPS. Prefer a
trusted certificate; `--insecure` explicitly permits a self-signed certificate
on a trusted LAN. HTTP sends the API key and device data without encryption.
`--timeout` controls the request timeout in seconds. Stop monitoring with Ctrl+C.
Network/API failures are written to the report and retried; `--once` exits with
a nonzero status on failure.

While monitoring, issue an Alexa or Google Home command and compare the
timestamped changes, especially light state, reachability, type, model, and
capabilities. Polling cannot identify the command sender, capture HTTP request
traffic, show assistant-side caches, or guarantee capture of changes between
polls. This is the bridge's exposed view, not proof of what an assistant received.
Known credential fields (including the API-user whitelist) are redacted, but
device names, network addresses, and other private metadata remain. Review a
report before sharing it. The report is append-only and can grow quickly when
attributes change frequently; stop, archive, or remove it when debugging ends.
