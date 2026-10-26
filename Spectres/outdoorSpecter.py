#!/usr/bin/env python3
import json
import logging
import signal
import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from automation_credentials import MQTT_BROKER, MQTT_PASS, MQTT_PORT, MQTT_USER
from paho.mqtt import client as mqtt_client

DEVICE_NAME = "outdoorGhostly"
HA_COMMAND_TOPIC = f"lights/{DEVICE_NAME}/set"
HA_STATE_TOPIC = f"lights/{DEVICE_NAME}/state"
HA_DISCOVERY_TOPIC = f"homeassistant/light/{DEVICE_NAME}/light/config"
POWER_TOPIC = f"cmnd/{DEVICE_NAME}/POWER"
SET_TOPIC = f"cmnd/{DEVICE_NAME}/SET"
BRIGHTNESS_TOPIC = f"cmnd/{DEVICE_NAME}/brightness"
BRIGHTNESS_WITH_ONOFF_TOPIC = f"cmnd/{DEVICE_NAME}/brightnessWithOnOff"
COLOR_TEMP_TOPIC = f"cmnd/{DEVICE_NAME}/colorTemp"
COLOR_TEMP_WITH_ONOFF_TOPIC = f"cmnd/{DEVICE_NAME}/colorTempWithOnOff"
POWER_MANUAL_TOPIC = f"stat/{DEVICE_NAME}/manuallyTriggeredPower"
BRIGHTNESS_MANUAL_TOPIC = f"stat/{DEVICE_NAME}/manuallyTriggeredBrightness"
COLOR_TEMP_MANUAL_TOPIC = f"stat/{DEVICE_NAME}/manuallyTriggeredColorTemp"
MANUAL_TRIGGER_CLEAR_SECONDS = 5
BRIGHTNESS_MIN = 1
BRIGHTNESS_MAX = 254
COLOR_TEMP_MIN = 153
COLOR_TEMP_MAX = 454

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

device_state = False
device_brightness = 127
device_color_temp = COLOR_TEMP_MAX
manual_trigger_timers = {}


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


def _get_state():
    state_value = "ON" if device_state else "OFF"
    return {
        "device": DEVICE_NAME,
        "state": state_value,
        "brightness": device_brightness,
        "color_temp": device_color_temp,
        "color_mode": "ct",
        "time_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _publish_state(client):
    state = _get_state()
    state_value = state["state"]
    client.publish(f"stat/{DEVICE_NAME}/POWER", state_value, retain=True)
    client.publish(f"stat/{DEVICE_NAME}/brightness", str(device_brightness), retain=True)
    client.publish(f"stat/{DEVICE_NAME}/colorTemp", str(device_color_temp), retain=True)

    client.publish(HA_STATE_TOPIC, json.dumps(state), retain=True)
    logging.info("Published %s state=%s brightness=%s color_temp=%s", DEVICE_NAME, state_value, device_brightness, device_color_temp)
    return state


def _publish_discovery(client):
    discovery_payload = {
        "name": DEVICE_NAME,
        "unique_id": f"virtual_{DEVICE_NAME}_01",
        "command_topic": HA_COMMAND_TOPIC,
        "state_topic": HA_STATE_TOPIC,
        "brightness": True,
        "color_temp": True,
        "min_mireds": COLOR_TEMP_MIN,
        "max_mireds": COLOR_TEMP_MAX,
        "device": {
            "identifiers": [f"{DEVICE_NAME}_id"],
            "name": DEVICE_NAME,
            "model": "LTW001",
            "manufacturer": "Custom",
        },
    }
    client.publish(HA_DISCOVERY_TOPIC, json.dumps(discovery_payload), retain=True)
    logging.info("Published discovery for %s to %s", DEVICE_NAME, HA_DISCOVERY_TOPIC)


def _set_state(client, new_state):
    global device_state
    device_state = bool(new_state)
    _publish_state(client)


def _clear_manual_trigger(client, topic):
    timer = manual_trigger_timers.pop(topic, None)
    if timer is not None:
        timer.cancel()
    client.publish(topic, "OFF", retain=True)
    logging.info("Cleared %s manual flag: %s", DEVICE_NAME, topic)


def _signal_manual_trigger(client, topic):
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


def _handle_brightness_command(client, payload):
    global device_brightness
    try:
        brightness = int(float(payload))
    except ValueError:
        logging.warning("Ignored invalid %s brightness: %r", DEVICE_NAME, payload)
        return
    device_brightness = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, brightness))
    _signal_manual_trigger(client, BRIGHTNESS_MANUAL_TOPIC)
    _publish_state(client)
    logging.info("Received %s brightness command: %s", DEVICE_NAME, device_brightness)


def _handle_color_temp_command(client, payload):
    global device_color_temp
    try:
        color_temp = int(float(payload))
    except ValueError:
        logging.warning("Ignored invalid %s color_temp: %r", DEVICE_NAME, payload)
        return
    device_color_temp = max(COLOR_TEMP_MIN, min(COLOR_TEMP_MAX, color_temp))
    _signal_manual_trigger(client, COLOR_TEMP_MANUAL_TOPIC)
    _publish_state(client)
    logging.info("Received %s color_temp command: %s", DEVICE_NAME, device_color_temp)


def _handle_json_command(client, payload):
    global device_state, device_brightness, device_color_temp
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logging.warning("Ignored invalid %s JSON command: %r", DEVICE_NAME, payload)
        return

    if not isinstance(data, dict):
        logging.warning("Ignored non-object %s JSON command: %r", DEVICE_NAME, payload)
        return

    state_updated = False

    if "state" in data:
        state_value = _normalize_bool(data["state"])
        if state_value is None:
            logging.warning("Ignored invalid %s state in JSON command: %r", DEVICE_NAME, data["state"])
            return
        device_state = state_value
        _signal_manual_trigger(client, POWER_MANUAL_TOPIC)
        state_updated = True

    if "brightness" in data:
        try:
            device_brightness = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, int(float(data["brightness"]))))
        except (TypeError, ValueError):
            logging.warning("Ignored invalid %s brightness in JSON command: %r", DEVICE_NAME, data["brightness"])
            return
        _signal_manual_trigger(client, BRIGHTNESS_MANUAL_TOPIC)
        state_updated = True

    color_temp_input = None
    if "color_temp" in data:
        color_temp_input = data["color_temp"]
    elif "color" in data and isinstance(data["color"], dict) and "temp" in data["color"]:
        color_temp_input = data["color"]["temp"]

    if color_temp_input is not None:
        try:
            device_color_temp = max(COLOR_TEMP_MIN, min(COLOR_TEMP_MAX, int(float(color_temp_input))))
        except (TypeError, ValueError):
            logging.warning("Ignored invalid %s color_temp in JSON command: %r", DEVICE_NAME, color_temp_input)
            return
        _signal_manual_trigger(client, COLOR_TEMP_MANUAL_TOPIC)
        state_updated = True

    if not state_updated:
        logging.warning("Ignored %s JSON command with no supported fields: %r", DEVICE_NAME, payload)
        return

    _publish_state(client)


def on_message(client, userdata, msg):
    global device_state
    try:
        payload = msg.payload.decode(errors="replace").strip()
        if msg.topic in {POWER_TOPIC, SET_TOPIC}:
            value = _normalize_bool(payload)
            if value is None:
                logging.warning("Ignored unsupported command on %s: %r", msg.topic, payload)
                return
            _set_state(client, value)
            _signal_manual_trigger(client, POWER_MANUAL_TOPIC)
            return
        if msg.topic in {BRIGHTNESS_TOPIC, BRIGHTNESS_WITH_ONOFF_TOPIC}:
            if msg.topic == BRIGHTNESS_WITH_ONOFF_TOPIC:
                device_state = True
            _handle_brightness_command(client, payload)
            return
        if msg.topic in {COLOR_TEMP_TOPIC, COLOR_TEMP_WITH_ONOFF_TOPIC}:
            if msg.topic == COLOR_TEMP_WITH_ONOFF_TOPIC:
                device_state = True
            _handle_color_temp_command(client, payload)
            return
        if msg.topic == HA_COMMAND_TOPIC:
            _handle_json_command(client, payload)
            return
    except Exception:
        logging.exception("Unhandled error in MQTT message handler for %s.", DEVICE_NAME)


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("Connected to MQTT broker for %s.", DEVICE_NAME)
        for topic in [
            POWER_TOPIC,
            SET_TOPIC,
            BRIGHTNESS_TOPIC,
            BRIGHTNESS_WITH_ONOFF_TOPIC,
            COLOR_TEMP_TOPIC,
            COLOR_TEMP_WITH_ONOFF_TOPIC,
            HA_COMMAND_TOPIC,
        ]:
            client.subscribe(topic)
            logging.info("Subscribed to %s", topic)
        _publish_discovery(client)
        _set_state(client, False)
        client.publish(POWER_MANUAL_TOPIC, "OFF", retain=True)
        client.publish(BRIGHTNESS_MANUAL_TOPIC, "OFF", retain=True)
        client.publish(COLOR_TEMP_MANUAL_TOPIC, "OFF", retain=True)
    else:
        logging.error("Failed to connect to MQTT broker for %s. rc=%s", DEVICE_NAME, rc)


def on_disconnect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        logging.warning("Unexpected MQTT disconnect for %s (rc=%s). Reconnecting...", DEVICE_NAME, rc)
    else:
        logging.info("Disconnected from MQTT broker for %s.", DEVICE_NAME)


def handle_shutdown(signum, frame):
    logging.info("Shutdown signal received for %s. Exiting.", DEVICE_NAME)
    raise SystemExit(0)


def main():
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    hostname = socket.gethostname()
    client_id = f"{hostname}_{DEVICE_NAME}"
    logging.info("Using MQTT client_id: %s", client_id)

    client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2, client_id=client_id)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.on_message = on_message
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    logging.info("Connecting to MQTT broker at %s...", MQTT_BROKER)
    client.connect(MQTT_BROKER, MQTT_PORT)
    logging.info("Virtual device service running for %s.", DEVICE_NAME)

    try:
        client.loop_forever()
    except SystemExit:
        pass
    except KeyboardInterrupt:
        logging.info("Shutting down %s...", DEVICE_NAME)
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
