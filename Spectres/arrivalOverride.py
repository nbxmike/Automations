#!/usr/bin/env python3
import json
import logging
import signal
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from automation_credentials import MQTT_BROKER, MQTT_PASS, MQTT_PORT, MQTT_USER
from paho.mqtt import client as mqtt_client

DEVICE_NAME = "arrivalOverride"
HA_COMMAND_TOPIC = f"lights/{DEVICE_NAME}/set"
HA_STATE_TOPIC = f"lights/{DEVICE_NAME}/state"
HA_DISCOVERY_TOPIC = f"homeassistant/light/{DEVICE_NAME}/light/config"
POWER_TOPIC = f"cmnd/{DEVICE_NAME}/POWER"
SET_TOPIC = f"cmnd/{DEVICE_NAME}/SET"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

device_state = False


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


def _publish_state(client):
    state_value = "ON" if device_state else "OFF"
    client.publish(f"stat/{DEVICE_NAME}/POWER", state_value, retain=True)
    payload = {
        "device": DEVICE_NAME,
        "state": state_value,
        "time_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    client.publish(f"stat/{DEVICE_NAME}/STATE", json.dumps(payload), retain=True)
    client.publish(HA_STATE_TOPIC, json.dumps({"state": state_value}), retain=True)
    logging.info("Published %s state=%s", DEVICE_NAME, state_value)


def _publish_discovery(client):
    discovery_payload = {
        "name": DEVICE_NAME,
        "unique_id": f"virtual_{DEVICE_NAME}_01",
        "command_topic": HA_COMMAND_TOPIC,
        "state_topic": HA_STATE_TOPIC,
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


def _handle_json_command(client, payload):
    global device_state
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logging.warning("Ignored invalid %s JSON command: %r", DEVICE_NAME, payload)
        return

    if not isinstance(data, dict):
        logging.warning("Ignored non-object %s JSON command: %r", DEVICE_NAME, payload)
        return

    if "state" not in data:
        return
    state_value = _normalize_bool(data["state"])
    if state_value is None:
        logging.warning("Ignored invalid %s state in JSON command: %r", DEVICE_NAME, data["state"])
        return
    _set_state(client, state_value)


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode(errors="replace").strip()
        if msg.topic in {POWER_TOPIC, SET_TOPIC}:
            value = _normalize_bool(payload)
            if value is None:
                logging.warning("Ignored unsupported command on %s: %r", msg.topic, payload)
                return
            _set_state(client, value)
            return
        if msg.topic == HA_COMMAND_TOPIC:
            _handle_json_command(client, payload)
            return
    except Exception:
        logging.exception("Unhandled error in MQTT message handler for %s.", DEVICE_NAME)


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("Connected to MQTT broker for %s.", DEVICE_NAME)
        for topic in [POWER_TOPIC, SET_TOPIC, HA_COMMAND_TOPIC]:
            client.subscribe(topic)
            logging.info("Subscribed to %s", topic)
        _publish_discovery(client)
        _set_state(client, False)
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
