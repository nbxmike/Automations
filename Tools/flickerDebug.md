# Kitchen Flicker Debugging

Use these instructions on the Raspberry Pi running the kitchen services to
retrieve logs after an intermittent flicker or unexpected ON/OFF sequence.
You do not need to leave a live log viewer running before the incident.

## Record The Incident

Record the following as soon as possible:

- The approximate date and time, using the Pi's local time.
- The exact Alexa command or other action that preceded the flicker.
- Which lights were affected: fridge strip, sink strip, dimmer, or all three.
- The delay before the flicker, its duration, and whether the lights recovered.

Check the Pi's date, time, and timezone with:

```sh
date
timedatectl
```

If you noted the time on another device, account for any timezone or clock
difference before selecting the log window.

## Retrieve Historical Logs

Start about one minute before the incident and include several minutes after
it. For an incident around 12:05 on October 24, 2026:

```sh
journalctl \
  -u kitchenSpecter.service \
  -u kitchen_spectre_router.service \
  -u default_color_temp.service \
  -u kitchen_dimming.service \
  --since "2026-10-24 12:04:00" \
  --until "2026-10-24 12:08:00" \
  -o short-iso --no-pager
```

Replace the example dates and times with your incident window. These timestamp
arguments use the Pi's local timezone. The output includes timezone offsets.
The selected services are merged into one chronological view.
Unlike live viewing, this command does not use `-f`: it prints the saved window
and exits.

If access is denied or journal entries are hidden because of permissions, run
the command yourself with `sudo journalctl` in place of `journalctl`.

## Save A Report

This example saves the same window to a file in your home directory:

```sh
journalctl \
  -u kitchenSpecter.service \
  -u kitchen_spectre_router.service \
  -u default_color_temp.service \
  -u kitchen_dimming.service \
  --since "2026-10-24 12:04:00" \
  --until "2026-10-24 12:08:00" \
  -o short-iso --no-pager \
  > ~/kitchen-incident-2026-10-24-1205.txt
```

Use a different filename for each incident. `>` overwrites a file if it already
exists. Review the report with:

```sh
less ~/kitchen-incident-2026-10-24-1205.txt
```

Share the report together with your observations and the incident time. Review
it for private device names, addresses, or other sensitive details first.

## Watch A Reproduction Live

To watch the same services while issuing an Alexa command:

```sh
journalctl -f -o short-iso \
  -u kitchenSpecter.service \
  -u kitchen_spectre_router.service \
  -u default_color_temp.service \
  -u kitchen_dimming.service
```

Press Ctrl+C to stop viewing. This does not stop the services or their logging.

## What To Look For

- Router `Forwarded` entries show commands sent from the virtual kitchen
  device to the strips and dimmer. Look for `"state": "OFF"` between ON commands.
- `Published kitchenGhostly state=...` entries describe the virtual device,
  not a confirmed physical-light state. Note unexpected reconnects nearby.
- `Applied default brightness` and `Applied default color_temp` entries show
  adjustments normally made five seconds after a manual virtual-device ON.
- `Idle timer expired` and `Sent dim command` entries identify vacancy dimming,
  normally after 300 seconds. `Raised kitchen light` or `Raised kitchen dimmer`
  entries identify occupancy brightening after a 90-second recovery timer.
- `Light turned on while occupied` can accompany a brightness update. It does
  not, by itself, prove that a new ON command was sent.

No OFF entry does not rule out a visible blackout. Controller behavior,
overlapping transitions, commands from other publishers, or hardware issues
may not appear as an explicit OFF command in these service logs. Preserve the
full time window rather than filtering out surrounding messages.

## Retention And Missing Logs

Retrieve logs promptly: journal size limits and rotation can remove older
entries. Logs can also be lost after reboot if journaling is not persistent.
Check which boots are still represented in the journal with:

```sh
journalctl --list-boots
```

The historical commands above search available logs across boots unless you
add a boot filter. Listing older boots indicates retained history, but does not
guarantee that every entry from those boots remains available.

If the window is empty, verify the date, timezone, service names, and access
permissions, then try a wider window. A service that was not running could
not produce logs. Journal retrieval cannot recover entries already deleted
or messages that the services never logged.