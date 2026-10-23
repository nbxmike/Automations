#!/usr/bin/env python3
# Routes backyardGhostly virtual commands to the yard devices.
import json
import logging
import socket
from typing import Dict, Optional

from automation_credentials import MQTT_BROKER, MQTT_PORT, MQTT_PASS, MQTT_USER
from paho.mqtt import client as mqtt_client

# --- Configuration ---
BACKYARD_VIRTUAL_NAMES = ("backyardGhostly",)
POWER1_OFF_TOPIC = "cmnd/wyzeParkingTree/POWER1"
POWER2_ON_TOPIC = "cmnd/wyzeParkingTree/POWER2"
POWER_COMMAND_TOPICS = [
    "cmnd/wyzeParkingTree/POWER1",
    "cmnd/wyzeParkingTree/POWER2",
]
GARDEN_LIGHTS_SET_TOPIC = "zigbee2mqtt/GardenLights/set"
GARDEN_PATH_SET_TOPIC = "zigbee2mqtt/gardenPath/set"
BACKDOOR_LIGHT_SET_TOPIC = "zigbee2mqtt/BackDoor/set"
BRIGHTNESS_MIN = 1
BRIGHTNESS_MAX = 254
COLOR_TEMP_MIN = 153
COLOR_TEMP_MAX = 500
ALEXA_COLOR_TEMP_MAX = 454

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

TOPIC_TO_KIND: Dict[str, str] = {}
for virtual_name in BACKYARD_VIRTUAL_NAMES:
    TOPIC_TO_KIND[f"lights/{virtual_name}/set"] = "ha_set_json"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/POWER"] = "power_text"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/SET"] = "power_text"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/brightness"] = "brightness"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/brightnessWithOnOff"] = "brightness_on"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/colorTemp"] = "color_temp"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/colorTempWithOnOff"] = "color_temp_on"

# Randomly assigned during development; static per implementation for readable,
# consistent logs. Re-randomize at least when using this script as a new-program template.
MQTT_CLIENT_ID_SUFFIX = "8dcb6e31"


def generate_client_id():
    """Build a descriptive, stable MQTT client ID for this host and script."""
    hostname = socket.gethostname()
    fixed_label = "BackyardSpectreRouter"
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


def _clamp_brightness(value):
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, parsed))


def _clamp_color_temp(value):
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    scaled = round(
        COLOR_TEMP_MIN
        + (parsed - COLOR_TEMP_MIN)
        * (COLOR_TEMP_MAX - COLOR_TEMP_MIN)
        / (ALEXA_COLOR_TEMP_MAX - COLOR_TEMP_MIN)
    )
    return max(COLOR_TEMP_MIN, min(COLOR_TEMP_MAX, scaled))


def _publish_lights_payload(client, topic: str, *, state: Optional[bool] = None, brightness: Optional[int] = None, color_temp: Optional[int] = None):
    payload = {}

    # For the yard devices, a direct OFF command should only turn off the first Wyze plug outlet.
    # Garden lights and BackDoor are not switched off here by the virtual device OFF action.
    if state is False:
        client.publish(POWER1_OFF_TOPIC, "OFF")
        logging.info("Forwarded %s -> %s payload=%s", "backyardGhostly off", POWER1_OFF_TOPIC, "OFF")
        return

    if state is not None:
        payload["state"] = "ON" if state else "OFF"

    if brightness is not None:
        payload["brightness"] = brightness

    if color_temp is not None:
        payload["color_temp"] = color_temp

    if not payload:
        return

    if payload.get("state") == "OFF":
        # This case should never reach the Zigbee light topics for the virtual backyard device.
        return

    serialized = json.dumps(payload)
    client.publish(topic, serialized)
    logging.info("Forwarded %s -> %s payload=%s", "backyardGhostly", topic, serialized)


def _publish_to_physical_devices(
    client,
    source_topic: str,
    state: Optional[bool] = None,
    brightness: Optional[int] = None,
    color_temp: Optional[int] = None,
):
    # An OFF command only turns off the first Wyze outlet. The other devices stay as-is.
    if state is False:
        client.publish(POWER1_OFF_TOPIC, "OFF")
        logging.info("Forwarded %s -> %s payload=%s", source_topic, POWER1_OFF_TOPIC, "OFF")
        return

    should_turn_on = state is True or brightness is not None or color_temp is not None
    if should_turn_on:
        for topic in POWER_COMMAND_TOPICS:
            client.publish(topic, "ON")
            logging.info("Forwarded %s -> %s payload=%s", source_topic, topic, "ON")

        light_payload = {"state": "ON"}
        if brightness is not None:
            light_payload["brightness"] = brightness
        if color_temp is not None:
            light_payload["color_temp"] = color_temp

        serialized = json.dumps(light_payload)
        for topic in (GARDEN_LIGHTS_SET_TOPIC, BACKDOOR_LIGHT_SET_TOPIC):
            client.publish(topic, serialized)
            logging.info("Forwarded %s -> %s payload=%s", source_topic, topic, serialized)

        garden_path_payload = json.dumps({"state": "ON"})
        client.publish(GARDEN_PATH_SET_TOPIC, garden_path_payload)
        logging.info(
            "Forwarded %s -> %s payload=%s",
            source_topic,
            GARDEN_PATH_SET_TOPIC,
            garden_path_payload,
        )


def _handle_ha_set_json(client, topic: str, payload: str):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logging.warning("Ignored invalid virtual-light JSON command on %s: %r", topic, payload)
        return

    if not isinstance(data, dict):
        logging.warning("Ignored non-object virtual-light JSON command on %s: %r", topic, payload)
        return

    state = None
    brightness = None
    color_temp = None

    if "state" in data:
        state = _normalize_bool(data["state"])
        if state is None:
            logging.warning("Ignored unsupported state on %s: %r", topic, data["state"])
            return

    if "brightness" in data:
        brightness = _clamp_brightness(data["brightness"])
        if brightness is None:
            logging.warning("Ignored invalid brightness on %s: %r", topic, data["brightness"])
            return

    if "color_temp" in data:
        color_temp = _clamp_color_temp(data["color_temp"])
        if color_temp is None:
            logging.warning("Ignored invalid color_temp on %s: %r", topic, data["color_temp"])
            return
    elif "color" in data and isinstance(data["color"], dict) and "temp" in data["color"]:
        color_temp = _clamp_color_temp(data["color"]["temp"])
        if color_temp is None:
            logging.warning("Ignored invalid color.temp on %s: %r", topic, data["color"]["temp"])
            return

    if state is None and brightness is None and color_temp is None:
        logging.warning("Ignored virtual-light JSON command with no supported fields on %s", topic)
        return

    _publish_to_physical_devices(
        client,
        source_topic=topic,
        state=state,
        brightness=brightness,
        color_temp=color_temp,
    )


def route_backyard_spectre_command(client, topic: str, payload: str):
    """Route a backyardGhostly command to the real yard devices."""
    kind = TOPIC_TO_KIND.get(topic)
    if kind is None:
        return

    if kind == "ha_set_json":
        _handle_ha_set_json(client, topic, payload)
        return

    if kind == "power_text":
        state = _normalize_bool(payload)
        if state is None:
            logging.warning("Ignored unsupported power payload on %s: %r", topic, payload)
            return
        _publish_to_physical_devices(client, source_topic=topic, state=state)
        return

    if kind in {"brightness", "brightness_on"}:
        brightness = _clamp_brightness(payload)
        if brightness is None:
            logging.warning("Ignored invalid brightness payload on %s: %r", topic, payload)
            return
        state = True if kind == "brightness_on" else None
        _publish_to_physical_devices(
            client,
            source_topic=topic,
            state=state,
            brightness=brightness,
        )
        return

    if kind in {"color_temp", "color_temp_on"}:
        color_temp = _clamp_color_temp(payload)
        if color_temp is None:
            logging.warning("Ignored invalid color_temp payload on %s: %r", topic, payload)
            return
        state = True if kind == "color_temp_on" else None
        _publish_to_physical_devices(
            client,
            source_topic=topic,
            state=state,
            color_temp=color_temp,
        )
        return


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode(errors="replace").strip()
        route_backyard_spectre_command(client, msg.topic, payload)
    except Exception:
        logging.exception("Unhandled error in MQTT message handler.")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("Connected to MQTT broker for backyardGhostly router.")
        for topic in sorted(TOPIC_TO_KIND):
            client.subscribe(topic)
            logging.info("Subscribed to %s", topic)
    else:
        logging.error("Failed to connect to MQTT broker. rc=%s", rc)


def on_disconnect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        logging.warning("Unexpected MQTT disconnect (rc=%s). Reconnecting...", rc)
    else:
        logging.info("Disconnected from MQTT broker.")


def main():
    client_id = generate_client_id()
    logging.info("Using MQTT client_id: %s", client_id)

    client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2, client_id=client_id)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.on_message = on_message
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    logging.info("Connecting to MQTT broker at %s...", MQTT_BROKER)
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.loop_start()
    logging.info("Backyard spectre MQTT router running. Press Ctrl+C to exit.")

    try:
        while True:
            pass
    except KeyboardInterrupt:
        logging.info("Shutting down backyard spectre router...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
