#!/usr/bin/env python3
# Virtual MQTT device host used by Alexa routines and automations.
# Historically this file managed only lateArrivalOverride, but it now hosts
# multiple virtual devices while keeping the original script/service name.
import asyncio
import json
import logging
import signal
import socket
import threading
from datetime import datetime, timezone
from typing import Dict, Optional

from automation_credentials import MQTT_BROKER, MQTT_PORT, MQTT_PASS, MQTT_USER
from paho.mqtt import client as mqtt_client

try:
    from astral import Observer
    from astral.sun import sun
except ImportError:
    Observer = None
    sun = None

# --- Configuration ---

# Set your kitchen location for sunrise calculation.
LATITUDE: Optional[float] = 42.61281053611971
LONGITUDE: Optional[float] = -70.68931574583688

# Virtual device definitions hosted by this script.
# - lateArrivalOverride: blocks yard midnight shutdown when ON.
# - kitchenSpectral: Alexa-visible kitchen dimmer and manual-change markers.
# - backyardSpectral: Alexa-visible backyard dimmer and manual-change markers.
LATE_ARRIVAL_OVERRIDE = "lateArrivalOverride"
KITCHEN_SPECTRAL = "kitchenSpectral"
BACKYARD_SPECTRAL = "backyardSpectral"
VIRTUAL_DEVICES = {
    LATE_ARRIVAL_OVERRIDE: {
        "reset_at_sunrise": True,
        "auto_reset_seconds": None,
    },
    KITCHEN_SPECTRAL: {
        "reset_at_sunrise": False,
        "auto_reset_seconds": None,
    },
    BACKYARD_SPECTRAL: {
        "reset_at_sunrise": False,
        "auto_reset_seconds": None,
    },
}
KITCHEN_SPECTRAL_LEVEL_TOPICS = {
    f"cmnd/{KITCHEN_SPECTRAL}/brightness",
    f"cmnd/{KITCHEN_SPECTRAL}/brightnessWithOnOff",
}
KITCHEN_SPECTRAL_COLOR_TEMP_TOPICS = {
    f"cmnd/{KITCHEN_SPECTRAL}/colorTemp",
    f"cmnd/{KITCHEN_SPECTRAL}/colorTempWithOnOff",
}
BACKYARD_SPECTRAL_LEVEL_TOPICS = {
    f"cmnd/{BACKYARD_SPECTRAL}/brightness",
    f"cmnd/{BACKYARD_SPECTRAL}/brightnessWithOnOff",
}
BACKYARD_SPECTRAL_COLOR_TEMP_TOPICS = {
    f"cmnd/{BACKYARD_SPECTRAL}/colorTemp",
    f"cmnd/{BACKYARD_SPECTRAL}/colorTempWithOnOff",
}
KITCHEN_SPECTRAL_MANUAL_POWER_TOPIC = (
    f"stat/{KITCHEN_SPECTRAL}/manuallyTriggeredPower"
)
KITCHEN_SPECTRAL_MANUAL_BRIGHTNESS_TOPIC = (
    f"stat/{KITCHEN_SPECTRAL}/manuallyTriggeredBrightness"
)
KITCHEN_SPECTRAL_MANUAL_COLOR_TEMP_TOPIC = (
    f"stat/{KITCHEN_SPECTRAL}/manuallyTriggeredColorTemp"
)
BACKYARD_SPECTRAL_MANUAL_POWER_TOPIC = (
    f"stat/{BACKYARD_SPECTRAL}/manuallyTriggeredPower"
)
BACKYARD_SPECTRAL_MANUAL_BRIGHTNESS_TOPIC = (
    f"stat/{BACKYARD_SPECTRAL}/manuallyTriggeredBrightness"
)
BACKYARD_SPECTRAL_MANUAL_COLOR_TEMP_TOPIC = (
    f"stat/{BACKYARD_SPECTRAL}/manuallyTriggeredColorTemp"
)
MANUAL_TRIGGER_CLEAR_SECONDS = 5
BRIGHTNESS_MIN = 1
BRIGHTNESS_MAX = 254
COLOR_TEMP_MIN = 153
COLOR_TEMP_MAX = 500
LATE_ARRIVAL_OVERRIDE_HA_COMMAND_TOPIC = f"lights/{LATE_ARRIVAL_OVERRIDE}/set"
LATE_ARRIVAL_OVERRIDE_HA_STATE_TOPIC = f"lights/{LATE_ARRIVAL_OVERRIDE}/state"
LATE_ARRIVAL_OVERRIDE_HA_DISCOVERY_TOPIC = (
    f"homeassistant/light/{LATE_ARRIVAL_OVERRIDE}/light/config"
)
KITCHEN_SPECTRAL_HA_COMMAND_TOPIC = f"lights/{KITCHEN_SPECTRAL}/set"
KITCHEN_SPECTRAL_HA_STATE_TOPIC = f"lights/{KITCHEN_SPECTRAL}/state"
KITCHEN_SPECTRAL_HA_DISCOVERY_TOPIC = (
    f"homeassistant/light/{KITCHEN_SPECTRAL}/light/config"
)
BACKYARD_SPECTRAL_HA_COMMAND_TOPIC = f"lights/{BACKYARD_SPECTRAL}/set"
BACKYARD_SPECTRAL_HA_STATE_TOPIC = f"lights/{BACKYARD_SPECTRAL}/state"
BACKYARD_SPECTRAL_HA_DISCOVERY_TOPIC = (
    f"homeassistant/light/{BACKYARD_SPECTRAL}/light/config"
)

# Logging setup matches the kitchen automation style.
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

device_state: Dict[str, bool] = {name: False for name in VIRTUAL_DEVICES}
device_brightness = {KITCHEN_SPECTRAL: 127, BACKYARD_SPECTRAL: 127}
device_color_temp = {KITCHEN_SPECTRAL: 500, BACKYARD_SPECTRAL: 500}
last_state_change_utc: Dict[str, datetime] = {
    name: datetime.now(timezone.utc) for name in VIRTUAL_DEVICES
}
sunrise_reset_done = False
missing_sun_config_logged = False
manual_trigger_timers: Dict[str, threading.Timer] = {}


# Randomly assigned during development; static per implementation for readable,
# consistent logs. Re-randomize at least when using this script as a new-program template.
MQTT_CLIENT_ID_SUFFIX = "c1c85e1f"


def generate_client_id():
    """Build a descriptive, stable MQTT client ID for this host and script."""
    hostname = socket.gethostname()
    fixed_label = "LateArrivalOverride"
    return f"{hostname}_{fixed_label}_{MQTT_CLIENT_ID_SUFFIX}"


def _normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().upper()
        if text in {"ON", "TRUE", "1", "YES"}:
            return True
        if text in {"OFF", "FALSE", "0", "NO"}:
            return False
    return None


def _get_today_sunrise():
    """Return today's sunrise time in local timezone, or None when config is missing."""
    global missing_sun_config_logged

    if Observer is None or sun is None:
        if not missing_sun_config_logged:
            logging.error("astral is not installed. Install with: pip install astral")
            missing_sun_config_logged = True
        return None

    if LATITUDE is None or LONGITUDE is None:
        if not missing_sun_config_logged:
            logging.error(
                "Set LATITUDE and LONGITUDE in late_arrival_override.py for sunrise checks."
            )
            missing_sun_config_logged = True
        return None

    now = datetime.now().astimezone()
    observer = Observer(latitude=LATITUDE, longitude=LONGITUDE)
    return sun(observer, date=now.date(), tzinfo=now.tzinfo)["sunrise"]


def power_command_topics(device_name: str):
    return [
        f"cmnd/{device_name}/POWER",
        f"cmnd/{device_name}/SET",
    ]


def command_topics(device_name: str):
    topics = power_command_topics(device_name)
    if device_name == LATE_ARRIVAL_OVERRIDE:
        topics.append(LATE_ARRIVAL_OVERRIDE_HA_COMMAND_TOPIC)
    if device_name == KITCHEN_SPECTRAL:
        topics.extend(KITCHEN_SPECTRAL_LEVEL_TOPICS)
        topics.extend(KITCHEN_SPECTRAL_COLOR_TEMP_TOPICS)
        topics.append(KITCHEN_SPECTRAL_HA_COMMAND_TOPIC)
    if device_name == BACKYARD_SPECTRAL:
        topics.extend(BACKYARD_SPECTRAL_LEVEL_TOPICS)
        topics.extend(BACKYARD_SPECTRAL_COLOR_TEMP_TOPICS)
        topics.append(BACKYARD_SPECTRAL_HA_COMMAND_TOPIC)
    return topics


def all_power_command_topics():
    topics = []
    for device_name in VIRTUAL_DEVICES:
        topics.extend(command_topics(device_name))
    return topics


def device_for_command_topic(topic: str) -> Optional[str]:
    for device_name in VIRTUAL_DEVICES:
        if topic in command_topics(device_name):
            return device_name
    return None


def publish_state(client, device_name: str):
    """Publish the current state to the virtual device topics."""
    state_value = "ON" if device_state.get(device_name, False) else "OFF"
    time_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Tasmota-style MQTT power state is often read by MatterBridge and scripts.
    client.publish(f"stat/{device_name}/POWER", state_value, retain=True)
    logging.info(f"Published {device_name} POWER={state_value}")

    if device_name in {KITCHEN_SPECTRAL, BACKYARD_SPECTRAL}:
        client.publish(
            f"stat/{device_name}/brightness",
            str(device_brightness[device_name]),
            retain=True,
        )
        client.publish(
            f"stat/{device_name}/colorTemp",
            str(device_color_temp[device_name]),
            retain=True,
        )

    # Provide a JSON state payload for automation consumers.
    state_payload_data = {
        "device": device_name,
        "state": state_value,
        "time_utc": time_utc,
    }
    if device_name in {KITCHEN_SPECTRAL, BACKYARD_SPECTRAL}:
        state_payload_data["brightness"] = device_brightness[device_name]
        state_payload_data["color_temp"] = device_color_temp[device_name]
    state_payload = json.dumps(state_payload_data)
    client.publish(f"stat/{device_name}/STATE", state_payload, retain=True)
    if device_name == LATE_ARRIVAL_OVERRIDE:
        home_assistant_state = {
            "state": state_value,
        }
        client.publish(
            LATE_ARRIVAL_OVERRIDE_HA_STATE_TOPIC,
            json.dumps(home_assistant_state),
            retain=True,
        )
    if device_name == KITCHEN_SPECTRAL:
        home_assistant_state = {
            "state": state_value,
            "brightness": device_brightness[KITCHEN_SPECTRAL],
            "color_temp": device_color_temp[KITCHEN_SPECTRAL],
            "color_mode": "ct",
        }
        client.publish(
            KITCHEN_SPECTRAL_HA_STATE_TOPIC,
            json.dumps(home_assistant_state),
            retain=True,
        )
    if device_name == BACKYARD_SPECTRAL:
        home_assistant_state = {
            "state": state_value,
            "brightness": device_brightness[BACKYARD_SPECTRAL],
            "color_temp": device_color_temp[BACKYARD_SPECTRAL],
            "color_mode": "ct",
        }
        client.publish(
            BACKYARD_SPECTRAL_HA_STATE_TOPIC,
            json.dumps(home_assistant_state),
            retain=True,
        )


def publish_discovery(client):
    late_arrival_override_discovery_payload = {
        "name": LATE_ARRIVAL_OVERRIDE,
        "unique_id": "virtualLateArrivalOverride01",
        "command_topic": LATE_ARRIVAL_OVERRIDE_HA_COMMAND_TOPIC,
        "state_topic": LATE_ARRIVAL_OVERRIDE_HA_STATE_TOPIC,
        "device": {
            "identifiers": ["lateArrivalOverride_id"],
            "name": LATE_ARRIVAL_OVERRIDE,
            "model": "LTW001",
            "manufacturer": "Custom",
        },
    }
    client.publish(
        LATE_ARRIVAL_OVERRIDE_HA_DISCOVERY_TOPIC,
        json.dumps(late_arrival_override_discovery_payload),
        retain=True,
    )
    logging.info(
        "Published discovery for %s to %s",
        LATE_ARRIVAL_OVERRIDE,
        LATE_ARRIVAL_OVERRIDE_HA_DISCOVERY_TOPIC,
    )

    kitchen_spectral_discovery_payload = {
        "name": KITCHEN_SPECTRAL,
        "unique_id": "virtualKitchenSpectral01",
        "command_topic": KITCHEN_SPECTRAL_HA_COMMAND_TOPIC,
        "state_topic": KITCHEN_SPECTRAL_HA_STATE_TOPIC,
        "brightness": True,
        "color_temp": True,
        "color_mode": True,
        "supported_color_modes": ["ct"],
        "min_mireds": COLOR_TEMP_MIN,
        "max_mireds": COLOR_TEMP_MAX,
        "device": {
            "identifiers": ["kitchenSpectral_id"],
            "name": KITCHEN_SPECTRAL,
            "model": "LTW001",
            "manufacturer": "Custom",
        },
    }
    client.publish(
        KITCHEN_SPECTRAL_HA_DISCOVERY_TOPIC,
        json.dumps(kitchen_spectral_discovery_payload),
        retain=True,
    )
    logging.info("Published discovery for kitchenSpectral to %s", KITCHEN_SPECTRAL_HA_DISCOVERY_TOPIC)

    backyard_spectral_discovery_payload = {
        "name": BACKYARD_SPECTRAL,
        "unique_id": "virtualBackyardSpectral01",
        "command_topic": BACKYARD_SPECTRAL_HA_COMMAND_TOPIC,
        "state_topic": BACKYARD_SPECTRAL_HA_STATE_TOPIC,
        "brightness": True,
        "color_temp": True,
        "color_mode": True,
        "supported_color_modes": ["ct"],
        "min_mireds": COLOR_TEMP_MIN,
        "max_mireds": COLOR_TEMP_MAX,
        "device": {
            "identifiers": ["backyardSpectral_id"],
            "name": BACKYARD_SPECTRAL,
            "model": "LTW001",
            "manufacturer": "Custom",
        },
    }
    client.publish(
        BACKYARD_SPECTRAL_HA_DISCOVERY_TOPIC,
        json.dumps(backyard_spectral_discovery_payload),
        retain=True,
    )
    logging.info("Published discovery for backyardSpectral to %s", BACKYARD_SPECTRAL_HA_DISCOVERY_TOPIC)


def set_device_state(client, device_name: str, new_state: bool):
    """Set the virtual device state and publish it to all state topics."""
    device_state[device_name] = bool(new_state)
    last_state_change_utc[device_name] = datetime.now(timezone.utc)
    publish_state(client, device_name)


def _clear_manual_trigger(client, topic: str):
    timer = manual_trigger_timers.pop(topic, None)
    if timer is not None:
        timer.cancel()
    client.publish(topic, "OFF", retain=True)
    logging.info("Cleared kitchenSpectral manual flag: %s", topic)


def _signal_manual_trigger(client, topic: str):
    existing_timer = manual_trigger_timers.get(topic)
    if existing_timer is not None:
        existing_timer.cancel()

    client.publish(topic, "ON", retain=True)
    manual_trigger_timers[topic] = threading.Timer(
        MANUAL_TRIGGER_CLEAR_SECONDS,
        _clear_manual_trigger,
        args=(client, topic),
    )
    manual_trigger_timers[topic].daemon = True
    manual_trigger_timers[topic].start()


def _handle_brightness_command(client, topic: str, payload: str, device_name: str):
    try:
        brightness = int(float(payload))
    except ValueError:
        logging.warning("Ignored invalid %s brightness: %r", device_name, payload)
        return

    brightness = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, brightness))
    device_brightness[device_name] = brightness
    if topic.endswith("brightnessWithOnOff"):
        device_state[device_name] = True
    last_state_change_utc[device_name] = datetime.now(timezone.utc)
    if device_name == KITCHEN_SPECTRAL:
        _signal_manual_trigger(client, KITCHEN_SPECTRAL_MANUAL_BRIGHTNESS_TOPIC)
    elif device_name == BACKYARD_SPECTRAL:
        _signal_manual_trigger(client, BACKYARD_SPECTRAL_MANUAL_BRIGHTNESS_TOPIC)
    publish_state(client, device_name)
    logging.info("Received %s brightness command: %s", device_name, brightness)


def _handle_color_temp_command(client, topic: str, payload: str, device_name: str):
    try:
        color_temp = int(float(payload))
    except ValueError:
        logging.warning("Ignored invalid %s color_temp: %r", device_name, payload)
        return

    color_temp = max(COLOR_TEMP_MIN, min(COLOR_TEMP_MAX, color_temp))
    device_color_temp[device_name] = color_temp
    if topic.endswith("colorTempWithOnOff"):
        device_state[device_name] = True
    last_state_change_utc[device_name] = datetime.now(timezone.utc)
    if device_name == KITCHEN_SPECTRAL:
        _signal_manual_trigger(client, KITCHEN_SPECTRAL_MANUAL_COLOR_TEMP_TOPIC)
    elif device_name == BACKYARD_SPECTRAL:
        _signal_manual_trigger(client, BACKYARD_SPECTRAL_MANUAL_COLOR_TEMP_TOPIC)
    publish_state(client, device_name)
    logging.info("Received %s color_temp command: %s", device_name, color_temp)


def _handle_spectral_json_command(client, payload: str, device_name: str):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logging.warning("Ignored invalid %s JSON command: %r", device_name, payload)
        return

    if not isinstance(data, dict):
        logging.warning("Ignored non-object %s JSON command: %r", device_name, payload)
        return

    state_updated = False

    if "state" in data:
        state_value = _normalize_bool(data["state"])
        if state_value is None:
            logging.warning("Ignored invalid %s state in JSON command: %r", device_name, data["state"])
            return
        device_state[device_name] = state_value
        if device_name == KITCHEN_SPECTRAL:
            _signal_manual_trigger(client, KITCHEN_SPECTRAL_MANUAL_POWER_TOPIC)
        elif device_name == BACKYARD_SPECTRAL:
            _signal_manual_trigger(client, BACKYARD_SPECTRAL_MANUAL_POWER_TOPIC)
        state_updated = True

    if "brightness" in data:
        try:
            brightness = int(float(data["brightness"]))
        except (TypeError, ValueError):
            logging.warning(
                "Ignored invalid %s brightness in JSON command: %r",
                device_name,
                data["brightness"],
            )
            return
        device_brightness[device_name] = max(
            BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, brightness)
        )
        if device_name == KITCHEN_SPECTRAL:
            _signal_manual_trigger(client, KITCHEN_SPECTRAL_MANUAL_BRIGHTNESS_TOPIC)
        elif device_name == BACKYARD_SPECTRAL:
            _signal_manual_trigger(client, BACKYARD_SPECTRAL_MANUAL_BRIGHTNESS_TOPIC)
        state_updated = True

    color_temp_input = None
    if "color_temp" in data:
        color_temp_input = data["color_temp"]
    elif "color" in data and isinstance(data["color"], dict) and "temp" in data["color"]:
        color_temp_input = data["color"]["temp"]

    if color_temp_input is not None:
        try:
            color_temp = int(float(color_temp_input))
        except (TypeError, ValueError):
            logging.warning(
                "Ignored invalid %s color_temp in JSON command: %r",
                device_name,
                color_temp_input,
            )
            return
        device_color_temp[device_name] = max(
            COLOR_TEMP_MIN, min(COLOR_TEMP_MAX, color_temp)
        )
        if device_name == KITCHEN_SPECTRAL:
            _signal_manual_trigger(client, KITCHEN_SPECTRAL_MANUAL_COLOR_TEMP_TOPIC)
        elif device_name == BACKYARD_SPECTRAL:
            _signal_manual_trigger(client, BACKYARD_SPECTRAL_MANUAL_COLOR_TEMP_TOPIC)
        state_updated = True

    if not state_updated:
        logging.warning("Ignored %s JSON command with no supported fields: %r", device_name, payload)
        return

    last_state_change_utc[device_name] = datetime.now(timezone.utc)
    publish_state(client, device_name)
    logging.info("Processed %s JSON command on %s", device_name, f"lights/{device_name}/set")


def _handle_on_off_json_command(client, device_name: str, payload: str, topic: str):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logging.warning("Ignored invalid %s JSON command: %r", device_name, payload)
        return

    if not isinstance(data, dict):
        logging.warning("Ignored non-object %s JSON command: %r", device_name, payload)
        return

    if "state" not in data:
        logging.warning("Ignored %s JSON command with no state field: %r", device_name, payload)
        return

    value = _normalize_bool(data["state"])
    if value is None:
        logging.warning("Ignored invalid %s state in JSON command: %r", device_name, data["state"])
        return

    set_device_state(client, device_name, value)
    logging.info("Processed %s JSON command on %s: %s", device_name, topic, value)


def on_message(client, userdata, msg):
    """Handle ON/OFF commands for the virtual device."""
    try:
        payload = msg.payload.decode(errors="replace").strip()
        device_name = device_for_command_topic(msg.topic)
        if device_name is None:
            return

        if msg.topic in KITCHEN_SPECTRAL_LEVEL_TOPICS:
            _handle_brightness_command(client, msg.topic, payload, KITCHEN_SPECTRAL)
            return
        if msg.topic in KITCHEN_SPECTRAL_COLOR_TEMP_TOPICS:
            _handle_color_temp_command(client, msg.topic, payload, KITCHEN_SPECTRAL)
            return
        if msg.topic in BACKYARD_SPECTRAL_LEVEL_TOPICS:
            _handle_brightness_command(client, msg.topic, payload, BACKYARD_SPECTRAL)
            return
        if msg.topic in BACKYARD_SPECTRAL_COLOR_TEMP_TOPICS:
            _handle_color_temp_command(client, msg.topic, payload, BACKYARD_SPECTRAL)
            return
        if msg.topic == LATE_ARRIVAL_OVERRIDE_HA_COMMAND_TOPIC:
            _handle_on_off_json_command(
                client,
                LATE_ARRIVAL_OVERRIDE,
                payload,
                LATE_ARRIVAL_OVERRIDE_HA_COMMAND_TOPIC,
            )
            return
        if msg.topic == KITCHEN_SPECTRAL_HA_COMMAND_TOPIC:
            _handle_spectral_json_command(client, payload, KITCHEN_SPECTRAL)
            return
        if msg.topic == BACKYARD_SPECTRAL_HA_COMMAND_TOPIC:
            _handle_spectral_json_command(client, payload, BACKYARD_SPECTRAL)
            return

        value = _normalize_bool(payload)
        if value is None:
            logging.warning(f"Ignored unsupported command on {msg.topic}: {payload!r}")
            return

        logging.info(f"Received command for {device_name} on {msg.topic}: {value}")
        set_device_state(client, device_name, value)
        if device_name == KITCHEN_SPECTRAL:
            _signal_manual_trigger(client, KITCHEN_SPECTRAL_MANUAL_POWER_TOPIC)
    except Exception:
        logging.exception("Unhandled error in MQTT message handler.")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("Connected to MQTT broker.")
        for topic in all_power_command_topics():
            client.subscribe(topic)
            logging.info(f"Subscribed to {topic}")
        publish_discovery(client)

        # Default all hosted virtual devices to OFF on startup.
        for device_name in VIRTUAL_DEVICES:
            set_device_state(client, device_name, False)
        client.publish(KITCHEN_SPECTRAL_MANUAL_POWER_TOPIC, "OFF", retain=True)
        client.publish(KITCHEN_SPECTRAL_MANUAL_BRIGHTNESS_TOPIC, "OFF", retain=True)
        client.publish(KITCHEN_SPECTRAL_MANUAL_COLOR_TEMP_TOPIC, "OFF", retain=True)
        client.publish(BACKYARD_SPECTRAL_MANUAL_POWER_TOPIC, "OFF", retain=True)
        client.publish(BACKYARD_SPECTRAL_MANUAL_BRIGHTNESS_TOPIC, "OFF", retain=True)
        client.publish(BACKYARD_SPECTRAL_MANUAL_COLOR_TEMP_TOPIC, "OFF", retain=True)
    else:
        logging.error(f"Failed to connect to MQTT broker. rc={rc}")


def on_disconnect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        logging.warning(f"Unexpected MQTT disconnect (rc={rc}). Reconnecting...")
    else:
        logging.info("Disconnected from MQTT broker.")


def handle_shutdown(signum, frame):
    logging.info("Shutdown signal received. Exiting lateArrivalOverride service.")
    raise SystemExit(0)


async def main():
    global sunrise_reset_done

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    client_id = generate_client_id()
    logging.info(f"Using MQTT client_id: {client_id}")

    client = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION2,
        client_id=client_id,
    )

    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    client.on_message = on_message
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    logging.info(f"Connecting to MQTT broker at {MQTT_BROKER}...")
    client.connect(MQTT_BROKER, MQTT_PORT)

    client.loop_start()
    logging.info(
        "Virtual device host is running (lateArrivalOverride + kitchenSpectral + backyardSpectral)."
    )

    last_quarter_hour = None

    try:
        while True:
            now = datetime.now().astimezone()
            sunrise = _get_today_sunrise()

            if sunrise is not None:
                if now >= sunrise and not sunrise_reset_done:
                    if device_state.get(LATE_ARRIVAL_OVERRIDE, False):
                        logging.info("Sunrise reached. Resetting lateArrivalOverride to OFF.")
                        set_device_state(client, LATE_ARRIVAL_OVERRIDE, False)
                    sunrise_reset_done = True
                elif now < sunrise:
                    sunrise_reset_done = False

            # Auto-reset virtual marker devices that are configured as momentary.
            now_utc = datetime.now(timezone.utc)
            for device_name, config in VIRTUAL_DEVICES.items():
                auto_reset_seconds = config.get("auto_reset_seconds")
                if auto_reset_seconds is None:
                    continue
                if not device_state.get(device_name, False):
                    continue
                changed_at = last_state_change_utc.get(device_name)
                if changed_at is None:
                    continue
                age_seconds = (now_utc - changed_at).total_seconds()
                if age_seconds >= float(auto_reset_seconds):
                    logging.info(
                        "Auto-resetting %s to OFF after %.0f seconds.",
                        device_name,
                        age_seconds,
                    )
                    set_device_state(client, device_name, False)

            # Publish every hosted virtual device state on a regular heartbeat.
            current_quarter_hour = now.minute // 15
            if now.second < 35 and current_quarter_hour in {0, 1, 2, 3}:
                quarter_key = (now.hour, now.minute // 15)
                if last_quarter_hour != quarter_key:
                    logging.info("Quarter-hour heartbeat reached. Publishing virtual device status.")
                    for device_name in VIRTUAL_DEVICES:
                        publish_state(client, device_name)
                    last_quarter_hour = quarter_key

            await asyncio.sleep(30)
    except SystemExit:
        pass
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
