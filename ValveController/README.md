# Four-Valve ESP32 Controller

PlatformIO/Arduino firmware for an ESP32 DevKitC with an ESP32-WROOM-32 module
and four BTS7960/IBT-2 full-bridge boards. The structure follows the neighboring
RelayBoard project. Use a classic dual-core ESP32, not an ESP32-C3/S3 or a
WROVER/PSRAM variant that reserves GPIO16/17.

## Pin Selection and Wiring

Each motor needs two independently routed LEDC PWM signals, one enable signal
driving both bridge enables, and two active-low limit-switch inputs: 12 outputs
and 8 inputs overall. All eight PWM signals use hardware LEDC channels 0-7 at
20 kHz and 8-bit resolution. ESP32's GPIO matrix allows LEDC on every chosen
output; no analog output or software PWM is used. Enables are ordinary GPIO.
Each valve is independent; only R_EN and L_EN **on the same board** are tied.

GPIO34/35/36/39 are input-only and have no internal pull-ups, so they are assigned
to switches. Flash GPIO6-11, UART0 GPIO1/3, and boot-sensitive GPIO0/2/5/12 are
left alone. GPIO15 is used only as a switch input. Low at reset suppresses ROM
UART boot messages and changes unused SDIO-slave timing; it does not prevent
normal flash boot or subsequent firmware serial output. JTAG pins are reused.

The output triples are neighboring header positions, grouped by valve. Valves
1/2 use the left header's central/lower GPIO group; valves 3/4 use the right
header's upper/central GPIO group. Switch pairs use the remaining nearby pins.
Follow **GPIO labels**, not physical header pin numbers or cable colors.

| Valve | RPWM | LPWM | R_EN + L_EN | Fully open switch | Fully closed switch |
| --- | --- | --- | --- | --- | --- |
| 1 | GPIO32 | GPIO33 | GPIO25 | GPIO36 (VP) | GPIO39 (VN) |
| 2 | GPIO26 | GPIO27 | GPIO14 | GPIO34 | GPIO35 |
| 3 | GPIO23 | GPIO22 | GPIO21 | GPIO13 | GPIO15 |
| 4 | GPIO19 | GPIO18 | GPIO17 | GPIO16 | GPIO4 |

Configuration lives in [include/valve_config.h](include/valve_config.h). Startup
checks reject duplicate pins and unsupported GPIO assignments before enabling
outputs. Do not change the board variant or map without rechecking its pinout.

### Motor Modules

- Module header: 1=RPWM, 2=LPWM, 3=R_EN, 4=L_EN, 5=R_IS, 6=L_IS, 7=VCC, 8=GND.
- Use one GPIO per enable pair, **not** a permanently connected 5 V enable.
- Feed module VCC from regulated 5 V and join ESP32, module logic, and motor-supply
  grounds. Connect the motor to M+/M- and a suitable fused motor supply to B+/B-.
  Do not power motors from the DevKitC or connect motor supply to a GPIO.
- R_IS/L_IS are unused and must remain disconnected from the ESP32. Their current
  sense/alarm function is not monitored by this firmware.
- The supplied module manual advertises 3.3-5 V control, but the supplied diagrams
  show varying 74HC244/74AHC244 buffers. Their thresholds at 5 V are not all
  guaranteed compatible with ESP32 3.3 V. For a variant-independent installation,
  route all 12 control outputs through two 74AHCT244 buffers powered at 5 V.
  Tie their active-low output enables low, decouple each with 100 nF, and keep
  unused buffer inputs grounded. Use a noninverting, TTL-input 5 V buffer, not
  a bare 5 V 74HC244 or slow bidirectional I2C level-shifter board.
- Add 10 kohm pull-downs on all ESP32-to-buffer control inputs and on each
  module's enable pair. Confirm the enable pairs stay low when the ESP32 resets,
  is unpowered, or is being flashed. Never assume software protects reset time.
- Provide local supply decoupling, suitable fusing, wire gauge, cooling, and
  motor-supply transient suppression. Avoid backfeeding USB through an external
  DevKitC 5 V supply; follow the board's power-selection instructions.

### Limit Switches

Use dry contacts or compatible open-collector signals. Each input needs its own
external 4.7-10 kohm pull-up to **3.3 V**, with the switch between GPIO and GND.
A contact closes only at its corresponding end stop. Never apply 5/12/24 V to an
ESP32 input. All switch pins use INPUT mode and rely on these external pull-ups.
Route sensor wiring away from motor wiring; use appropriate filtering/protection
for long cables. A disconnected wire reads inactive and cannot be distinguished
from an unreached stop, so the timeout is only a fallback, not fault detection.

## Motion and Status

`open`/`on` requests opening; `close`/`off` requests closing. Commands are exact,
lowercase payloads without trailing whitespace. Invalid payloads/topics do nothing.

| Open switch low | Closed switch low | Motion | Report |
| --- | --- | --- | --- |
| Yes | Yes | Any; force disabled | `error` |
| Yes | No | Any | `open` |
| No | Yes | Any | `closed` |
| No | No | Opening | `opening` |
| No | No | Closing | `closing` |
| No | No | Stopped or reversing pause | `unknown` |

Neither switch low is a valid mid-travel state and permits starting. An active
destination switch prevents starting. During travel, that destination switch
immediately cancels motion; both switches low also immediately cancels motion.
An active departure switch permits moving away from its stop. Switch states
take precedence over motion when reporting. No automatic restart follows a
limit hit, contradictory switches, or timeout; a fresh command is required.

Clockwise means RPWM active / LPWM zero; counterclockwise means the reverse.
Opening defaults to clockwise on each valve, closing to counterclockwise.
Actual shaft direction depends on motor wiring. Set a valve's `openDirection`
to `Direction::Counterclockwise` to reverse its opening direction without
changing MQTT command names or switch assignments.

Stopped means both PWM duties zero and both enable pins low (coast/high
impedance, not active braking). A reversal disables the bridge for at least
`kReversalDelayMs` (default 100 ms) before driving the other direction. Repeating
the same command does not reset the travel timer. `kMaxTravelMs` defaults to
120000 ms: expiry stops the motor and, with neither switch active, reports
`unknown`. Set this to a measured, appropriate maximum before installation.
`kMotorDuty` defaults to 255/255; reduce it if the motor/application requires PWM.

A high-priority FreeRTOS task checks all switches once per RTOS tick, independent
of MQTT connection attempts and reporting. Latest commands arrive through a
separate one-element queue per valve. Wi-Fi/MQTT outages do not pause monitoring:
an existing movement continues to its limit or timeout. Boot never restores
movement locally. Switch handling stops on the first active sample without
software debounce or automatic resumption. Allow for task latency and mechanical
coast distance; use independent hardwired interlocks/emergency isolation where
overtravel can cause damage. This firmware is not a safety-rated controller.

## MQTT

[include/mqtt_config.h](include/mqtt_config.h) defines `MQTT_ROOT_TOPIC` and
`MQTT_CLIENT_ID`, both initially `heater-valves`. It imports the existing local
credential header. Credentials are unchanged and excluded from version control.
Required macros are `WIFI_SSID`, `WIFI_PASSWORD`, `MQTT_BROKER_HOST`,
`MQTT_BROKER_PORT`, and `MQTT_AUTH_ENABLED`; when authentication is enabled,
`MQTT_USERNAME` and `MQTT_PASSWORD` are also required. This matches RelayBoard's
plain TCP MQTT transport; TLS is not configured.

| Topic | Direction | Payload |
| --- | --- | --- |
| `heater-valves/valve1` through `heater-valves/valve4` | Command | `open`, `on`, `close`, `off` |
| `heater-valves/valve1/set` through `heater-valves/valve4/set` | Command alias, matching RelayBoard layout | Same |
| `heater-valves/valve1/state` through `heater-valves/valve4/state` | Retained status | Table above |
| `heater-valves/availability` | Retained availability / last will | `online`, `offline` |

Every 60 seconds one retained status is published in round-robin order:
valve1, valve2, valve3, valve4, then repeat. Each valve therefore has a four-minute
periodic refresh. Changes and reconnect snapshots are published additionally.
Failed periodic publications retry without advancing the valve index. The
60-second wait is a timer, **not sleep/deep sleep**: networking and end-stop
monitoring remain active. Set topics are subscribed at QoS 1; status publishes
use PubSubClient's QoS 0. `offline` is the broker's last will, subject to keepalive
and broker detection delay, not an instantaneous hardware-health guarantee.

Send commands **without MQTT retain**. PubSubClient's callback does not expose
the retain flag, so retained commands will replay on reconnect and may move a
valve. Clear any previously retained commands before commissioning.

## Build and Development

Open [ValveController.code-workspace](ValveController.code-workspace) in VS Code
and install the recommended PlatformIO extension. The project pins Espressif32
8.0.0 (Arduino-ESP32 3.3.x), using the Arduino 3.x LEDC API. Dependencies are in
[platformio.ini](platformio.ini). No secrets are stored in the workspace file.

The Windows workspace includes Build, Upload, Serial Monitor, and Host Tests
tasks. PlatformIO tasks use its standard per-user installation. Host Tests need
`g++` on PATH (for example MinGW); no ESP32 or broker is needed for those tests.
Run the default build task, or from a PlatformIO terminal:

```powershell
pio run -e esp32dev
pio run -e esp32dev --target upload
pio device monitor --baud 115200
```

Set `upload_port`/`monitor_port` in the environment if automatic serial-port
selection is ambiguous. Uploading is manual; no upload runs when opening the
workspace. The host test task compiles and runs
[test/test_valve_control.cpp](test/test_valve_control.cpp), covering all limit
combinations, command synonyms, invalid commands, direction reversal dead time,
timeout, time-counter rollover, GPIO uniqueness, and valve independence.

## Commissioning

1. With motor power disconnected, verify every GPIO and pull-up/pull-down,
   inactive boot outputs, and module control levels using a meter/logic analyzer.
2. Verify each switch alone produces `open` or `closed`; both grounded produces
   `error`; neither produces `unknown`. A contradictory pair must not start.
3. Use a current-limited motor supply and decouple the valve if practical. Check
   each motor's physical direction and correct `openDirection` before travel.
4. Test both destination stops, reversals, all four motors together, network
   outages during motion, reset, and travel timeout. Confirm overrun is acceptable.
5. Observe one-valve-per-minute refreshes and retained changes with an MQTT
   client. Do not rely on the broker alone to verify actual motor disable.

Reference material: the supplied BTS7960 module manual (header pin functions),
Infineon BTS7960 datasheet (IN/INH behavior), module circuit diagrams (input
buffers), and Espressif DevKitC/ESP32 documents (GPIO capabilities and straps).
Compilation and host tests do not replace these powered hardware checks.