# Thermostat Router Firmware

PlatformIO Arduino firmware for the ESP32-WROOM-32 / ESP32 DevKitC V4 installed on the ES32A08 board. PlatformIO's `esp32dev` board definition targets the classic ESP32. The ES32A08 74HC595 output pins and integrated display use the pin assignments from its board support package.

## MQTT

The broker host and port are in `include/mqtt_config.h`; change the host from `mqtt.local` to the address reachable on your network. Keep the existing Wi-Fi credentials in the root-level `wifi_secrets.h`; do not move it to `include/`. The firmware includes that file directly, and the repository ignores any file named `wifi_secrets.h`. Credential values are not copied into the firmware sources. The firmware connects to 2.4 GHz Wi-Fi, as supported by the ESP32.

Optional broker credentials can be placed in the ignored `include/mqtt_secrets.h`:

```cpp
#define MQTT_AUTH_ENABLED 1
#define MQTT_USERNAME "your-user"
#define MQTT_PASSWORD "your-password"
```

For each zone, publish one of `bypass`, `on`, or `off` to:

| Zone | Command topic | Relay pair |
| --- | --- | --- |
| 1 | `thermostat-router/zone1/set` | 1 (odd), 2 (even) |
| 2 | `thermostat-router/zone2/set` | 3 (odd), 4 (even) |
| 3 | `thermostat-router/zone3/set` | 5 (odd), 6 (even) |
| 4 | `thermostat-router/zone4/set` | 7 (odd), 8 (even) |

The retained state is published to the corresponding `.../state` topic. A received valid command updates its zone's state immediately. In addition, the firmware publishes one zone every 120 seconds in round-robin order, completing a full pass every eight minutes. Broker availability is retained at `thermostat-router/availability`.

Relay states follow the requested mapping: `bypass` deenergizes both contacts, `on` energizes both, and `off` energizes only the even-numbered relay. All zones start in `bypass` after reset. The display shows `b`, `1`, or `0` for each zone from left to right, and shows `----` for five seconds every 25 seconds.

## Build and flash

### Build on a second machine

The first build needs internet access to download the Espressif platform and its packages. On a machine where you can install software:

1. Install Visual Studio Code and the `PlatformIO IDE` extension.
2. Copy or clone this project to that machine and open `RelayBoard.code-workspace`.
3. Securely copy the local root-level `wifi_secrets.h` into the project root. It is intentionally ignored by Git and is not included in a clone. Do not commit or publish it.
4. Open the PlatformIO Core CLI from the VS Code Command Palette (`PlatformIO: Open PlatformIO Core CLI`), then run these commands from the project directory:

	```sh
	pio pkg install -e esp32dev
	pio run -e esp32dev
	```

`platformio.ini` declares the `espressif32` platform, the `esp32dev` board, the Arduino framework, and the PubSubClient library. PlatformIO resolves and installs the compatible ESP32 compiler/toolchain, Arduino core, uploader tools, and library during dependency installation/build. These generated packages stay in PlatformIO's package cache; they do not need to be added to this repository. The first install requires network access to the PlatformIO package registry and its download hosts. If that network is blocked, use a machine with authorized access or ask IT to allow those downloads.

After the initial successful build, use the PlatformIO Build and Upload commands in VS Code. The serial monitor baud rate is 115200.

Confirm the physical relay numbering and thermostat/furnace terminal wiring before connecting a heating system. This firmware does not infer or validate external wiring.