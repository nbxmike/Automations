# Tools

## diyHue Monitor

[diyhue_monitor.py](diyhue_monitor.py) reads the Hue v1 API exposed by a diyHue
server and generates a text report of devices, their attributes, and changes.
Use it while issuing Alexa or Google Home commands to compare the bridge's
exposed state before and after a command.

### Requirements

- Python 3.9 or newer. No additional Python packages are needed.
- Network access from the computer running the script to the diyHue server.
- A Hue API username/key authorized on that server. **An API key is required.**

The API key is not your diyHue web-interface username or password. MQTT and
Omada credentials are not needed. The monitor reads `DIYHUE_API_KEY` from
[automation_credentials.py](../automation_credentials.py) in the repository
root. That file is excluded from Git. The registration tool saves the key there;
no terminal environment variable is needed.

Commands below assume your terminal is in the repository's root directory.
On Windows, use `python`; on Linux/Raspberry Pi, use `python3`.
If your terminal is already in the Tools directory, replace
`Tools/diyhue_monitor.py` with `diyhue_monitor.py`, and
`Tools/diyhue_register.py` with `diyhue_register.py`.

### Server Address And Connection

The default server address is `http://172.24.32.102`. No script changes are
needed to use a different IP address: pass `--server` when running the tool.
For example, to use `172.24.32.110`:

```powershell
python Tools/diyhue_monitor.py --server http://172.24.32.110 --once
```

Supply only the server's base URL, not an `/api` path or an API key. A bare
IP address also works and defaults to HTTP. If diyHue uses a nonstandard port,
include it, for example `--server http://172.24.32.110:8080`.
Use the same server address for registration and monitoring: keys belong to
the server on which they were created.

Before registration, open the diyHue web interface in a browser and confirm
that you can reach the server. Ensure firewalls, VLAN rules, or routing do not
block its API port. The script makes its own connection when it runs; no MQTT
connection or separate connection command is necessary.

If your server requires HTTPS, use `--server https://172.24.32.102` for both
registration and monitoring. Prefer a trusted certificate and a hostname that
matches it. For a self-signed certificate on a trusted LAN only, you can add
`--insecure` to either command to disable certificate verification. Plain HTTP
sends the API key and device data without encryption.

### Create An API Key

[diyhue_register.py](diyhue_register.py) creates a Hue API user and saves the key
as `DIYHUE_API_KEY` in the root credentials file. Existing MQTT/Omada settings
are preserved. If the key already has a standalone assignment, it is replaced
rather than duplicated. A missing credentials file is created.

1. Open the diyHue web interface and log in if prompted.
2. Activate its virtual link button or link/pairing mode. The label and location
   depend on your diyHue version.
3. While linking is enabled, run:

```powershell
python Tools/diyhue_register.py --server http://172.24.32.102
```

On Linux/Raspberry Pi:

```sh
python3 Tools/diyhue_register.py --server http://172.24.32.102
```

Successful registration confirms the save without displaying the key. Keep the
credentials file private and do not commit it. Registration creates an API user,
but does not switch or dim any devices. Normal monitoring only reads the API.
If Hue error 101 reports that the link button was not pressed, enable linking
again and immediately retry the command. If saving fails after registration,
an API user may already exist on the server; inspect diyHue's authorized users
before repeatedly retrying. The monitor's original `--register` option remains
available as a shortcut and now also saves the key.

If you already have a valid key, skip registration and add this assignment to
the root credentials file, using your existing key instead of the placeholder:

```python
DIYHUE_API_KEY = "your-hue-api-key"
```

Keys normally persist across sessions, reboots, and months until revoked or the
server configuration is reset. You do not need to register before every run.

### Run The Monitor

After saving a key, run the monitor from any terminal without exporting it.

Windows PowerShell:

```powershell
python Tools/diyhue_monitor.py --server http://172.24.32.102 --once
python Tools/diyhue_monitor.py --server http://172.24.32.102
```

Linux/Raspberry Pi:

```sh
python3 Tools/diyhue_monitor.py --server http://172.24.32.102 --once
python3 Tools/diyhue_monitor.py --server http://172.24.32.102
```

The first invocation checks the connection and writes one inventory before
exiting. The second monitors continuously, polling every five seconds.
Stop it with Ctrl+C. The monitor loads the root credentials file each time it
starts, regardless of the terminal's working directory. It does not use the
`DIYHUE_API_KEY` environment variable. If you change the saved key, restart the
monitor. Avoid sharing the credentials file or screenshots containing it.

### Report And Options

The default report is `diyhue_devices.txt` beside the script in the Tools
directory, regardless of your terminal's working directory. Each run appends
an initial inventory. Subsequent polls append attribute changes and a full
snapshot only when API data differs. Existing report contents are preserved.

The report includes resources returned by the Hue v1 root endpoint, such as
lights, sensors, groups, scenes, rules, schedules, and bridge configuration.
Device attributes include names, IDs, models, manufacturers, states,
reachability, and capabilities when the bridge exposes those fields.

```sh
python3 Tools/diyhue_monitor.py --interval 1 --timeout 15 --output diyhue_debug.txt
python3 Tools/diyhue_monitor.py --help
```

`--interval` changes the delay between polls in seconds; `--timeout` changes
the network request timeout in seconds. Both must be positive, finite numbers.
`--output` selects another report location; relative paths are relative to the
terminal's working directory. The script creates missing parent directories.

### Troubleshooting And Limits

- **Missing key or Hue error 1:** check `DIYHUE_API_KEY` in the root credentials file,
  check that it belongs to the selected server, or register a new key.
- **Connection failure or HTTP error:** verify IP address, scheme, port,
  network access, certificate trust, and that the server exposes the Hue v1 API.
  Check diyHue's own logs for details.
- **Cannot write report:** choose a writable location with `--output`.
- **Continuous errors:** monitoring logs failures and retries. Use `--once`
  to test a connection and exit with a nonzero status if the request fails.

Issue an assistant command while monitoring, then inspect the timestamped
changes to the relevant device. Polling cannot identify the command sender,
capture requests or changes between polls, or show Alexa/Google-side caches.
The report describes what the bridge exposes, not proof of what an assistant
received. This tool does not query Hue v2 resources.

Known credential fields, including the API-user whitelist, are redacted.
Device names, IP addresses, and other private metadata remain: review reports
before sharing them. Reports grow without automatic rotation; stop monitoring
and archive or remove the report when debugging is complete.