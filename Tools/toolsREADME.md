# Tools

## MQTT Activity Logger

[mqtt_activity_logger.py](mqtt_activity_logger.py) passively records messages on
the broker configured in the root credentials file. It never publishes commands.
Requires Python 3.7+ and `paho-mqtt` (1.6+ or 2.x), available through the existing
`install_dependencies.sh` installer. No changes to the automations are needed.

The default subscription is `#`: this covers all application topics, including
topics constructed dynamically by scripts and topics added in the future. It
also includes unrelated broker traffic. Broker ACLs must permit subscriptions
and delivery for the topics you want to capture. MQTT excludes `$`-prefixed
topics from `#`; add `--topic '#' --topic '$SYS/#'` to include broker statistics.
Use repeatable `--topic` options to restrict capture instead:

```sh
python3 Tools/mqtt_activity_logger.py
python3 Tools/mqtt_activity_logger.py --topic 'zigbee2mqtt/#' --topic 'cmnd/#'
python3 Tools/mqtt_activity_logger.py --help
```

### Install On The Pi

The supplied service assumes `/home/pi/automations` and user `pi`, matching the
other units. The existing service installer does not discover units in Tools;
install this optional diagnostic service explicitly:

```sh
cd /home/pi/automations
sudo ./install_dependencies.sh
sed -i 's/\r$//' Tools/mqtt_activity_logger.py Tools/mqtt_activity_logger.service
python3 -m py_compile Tools/mqtt_activity_logger.py
sudo cp Tools/mqtt_activity_logger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mqtt_activity_logger.service
systemctl status mqtt_activity_logger.service
journalctl -u mqtt_activity_logger.service -f
```

The `pi` user needs read access to the root credentials file and write access to
`Tools/logs` (created automatically and excluded from Git). Restart with
`sudo systemctl restart mqtt_activity_logger.service` after updating the script. After editing the unit,
copy it again and run `daemon-reload` before restarting. Stop capture with
`sudo systemctl stop mqtt_activity_logger.service`.

### Log Format And Retention

Default output: `Tools/logs/mqtt_activity.YYYY-MM-DD.jsonl`, using the Pi's local
date, for example `mqtt_activity.2026-10-31.jsonl`. Each line is a separate JSON
object. UTF-8 payloads remain text, including JSON payloads stored as strings;
non-UTF-8 payloads are base64. Newlines in payloads are escaped, and empty
payloads are preserved. Decode according to `payload_encoding` to recover the
original bytes without parsing and reserializing device JSON.

```json
{"schema_version": 1, "timestamp": "2026-10-30T12:00:00.123456+00:00", "local_time": "Friday 30/OCT/2026 08:00:00AM", "elapsed_ns": 1000000000, "session": "example", "sequence": 3, "event": "message", "topic": "cmnd/kitchenGhostly/POWER", "payload": "ON", "payload_encoding": "utf-8", "payload_bytes": 2, "qos": 0, "retain": false, "dup": false, "mid": 0}
```

Records include UTC reception time, a human-readable `local_time` using the
host's configured timezone (the example uses UTC-04:00), monotonic nanoseconds
since process start, a session ID, and a per-session sequence number.
Weekday/month names and AM/PM follow the process locale, with the month uppercase.
Non-message events record
startup, connection attempts, subscription acknowledgements, disconnects, and
clean shutdown. These help identify gaps; an unclean shutdown may have no stop
event. Lifecycle events are not replayable messages.

Each local calendar day has its own file, created on that day's first record.
Restarts append to the same day's file. Retention is 28 calendar days including
today and the previous 27 days, not the last 28 files. On the first record after
startup and each date change, older dated files with the same base name and
extension are deleted automatically. No empty files are created for idle days;
cleanup waits until the next record if the logger is stopped or idle.
Archive files before expiry if you need a longer history.

Configure with `--output /path/capture.jsonl --retention-days 28`; this produces
`/path/capture.YYYY-MM-DD.jsonl`. Relative paths are relative to the working
directory. The old `--max-bytes` and `--backups` options are no longer used;
remove them from any customized service command. Daily files have no size cap,
so disk usage depends on traffic. Old unsuffixed logs and numbered size-rotation
backups are left untouched; archive or remove them separately.
Do not run two writers with the same output base or apply external log rotation.
Each record is flushed to the OS, not
fsynced: sudden power loss can lose recent records or leave a partial last line.
Write failures terminate the service so systemd can report and restart it.

Follow today's log with
`tail -f "Tools/logs/mqtt_activity.$(date +%F).jsonl"`; rerun after midnight to
follow the new day's file. Logs contain
unredacted payloads, occupancy patterns, and potentially sensitive discovery or
device data. The service creates owner-only files; protect any exported copies.

### Capture And Future Replay Limits

- This is a broker-side subscriber, not a packet sniffer. It cannot identify
  publishers or prove a device acted on a command. Timestamps are reception
  times, and QoS/retain/dup/mid describe delivery to this subscriber, not the
  original publisher's packet. Subscription QoS is 1, not a guarantee of QoS 1
  for messages originally published at QoS 0.
- Initial connection and reconnects deliver retained snapshots marked with
  `retain: true`; these are not necessarily new activity. A live retained publish
  can arrive with `retain: false` under MQTT 3.1.1. The original retain setting
  therefore cannot reliably be reconstructed.
- Capture only runs while connected, uses a clean session, and does not recover
  offline messages. Reconnects back off automatically from 1 to 30 seconds.
  Overlapping custom filters and QoS retransmissions may produce duplicates;
  messages are deliberately not deduplicated.
- A future replay tool should allowlist intended light command topics, skip
  retained snapshots and lifecycle records, and use relative timing within each
  session. Do not blindly replay the entire log: presence, discovery, state,
  overrides, and commands can trigger automations or produce feedback loops.
  No replay functionality is implemented here.

## Busiest Weekday Logs

[mqtt_busy_days.py](mqtt_busy_days.py) scans the logger's daily JSON Lines files
and keeps the busiest log for each weekday in `Tools/logs/busydays`, named
`monday.jsonl` through `sunday.jsonl`. Requires Python 3.8+ and no additional
packages or broker connection. Run from the repository root:

```sh
python3 Tools/mqtt_busy_days.py
```

Each `event: "message"` record counts once, including repeated topics, retained
snapshots, and duplicate deliveries. Lifecycle events and blank lines do not
count. This measures observed MQTT messages, not unique topic names or confirmed
original publications. Weekdays come from the local date in the daily filename.

The script compares candidates against the saved file's message count and
replaces it only for a strictly higher count. Ties leave the saved file untouched.
On the first run, equal candidates are considered in date order, oldest first.
The complete log is copied, preserving payloads, timestamps, source dates, and
lifecycle records. Source logs are not changed. Copies are installed atomically
and created with owner-only permissions; run only one selector at a time.
Missing weekdays remain absent. Saved winners persist across future runs and
are not deleted by the daily logger's 28-day cleanup.

For a customized logger output base or destination:

```sh
python3 Tools/mqtt_busy_days.py --input-base /path/capture.jsonl --output-dir /path/busydays
```

The current day's log is eligible and can replace its saved weekday again as
activity increases. Each replacement counts the copied snapshot before installing
it. Invalid JSON (including a partial last line) or unreadable files are reported
and skipped; a damaged saved winner is left untouched and blocks replacements
for that weekday. Other weekdays still process, but any error gives exit status 1.
Rerun after a partial active-log write has completed. Run regularly, for example
daily, so potential winners are considered before the logger deletes old logs.
This tool is a one-shot command; no service or schedule is installed automatically.

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

The default server address is `http://172.24.34.112`. No script changes are
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
python Tools/diyhue_register.py --server http://172.24.34.112
```

On Linux/Raspberry Pi:

```sh
python3 Tools/diyhue_register.py --server http://172.24.34.112
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
python Tools/diyhue_monitor.py --server http://172.24.34.112 --once
python Tools/diyhue_monitor.py --server http://172.24.34.112
```

Linux/Raspberry Pi:

```sh
python3 Tools/diyhue_monitor.py --server http://172.24.34.112 --once
python3 Tools/diyhue_monitor.py --server http://172.24.34.112
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