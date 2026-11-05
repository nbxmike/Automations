# ES32A08 purpose and connections

## Relay routing

| Pin\Port | CN1   | CN3   | CN5   | CN7   |
|----------|-------|-------|-------|-------|
| 1        | 24VAC | 24VAC | 24VAC | 24VAC |
| 2        | CN2,1 | CN4,1 | CN6,1 | CN8,1 |
| 3        | -     | -     | -     | -     |

| Pin\Port | CN2   | CN4   | CN6   | CN8   |
|----------|-------|-------|-------|-------|
| 1        | CN1,2 | CN3,2 | CN5,2 | CN7,2 |
| 2        | FZ1   | FZ2   | FZ3   | FZ4   |
| 3        | TZ1   | TZ2   | TZ3   | TZ3   |

Where:

- FZx is the furnace's control input for each zone; e.g. FZ1 is furnace zone 1 control.
- TZx is the thermostat output for each zone; e.g. TZ3 is the thermostat for zone 3.