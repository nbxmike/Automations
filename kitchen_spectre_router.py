#!/usr/bin/env python3
# Routes virtual kitchenSpectre commands to physical kitchen light controllers.
import asyncio
import json
import logging
import socket
from typing import Dict, Optional

from automation_credentials import MQTT_BROKER, MQTT_PORT, MQTT_PASS, MQTT_USER
from paho.mqtt import client as mqtt_client

# --- Configuration ---
KITCHEN_VIRTUAL_NAMES = ("kitchenSpectre",)
STRIP_TOPICS = [
    "zigbee2mqtt/Fridge LED Strip/set",
    "zigbee2mqtt/Sink LED Strip/set",
]
DIMMER_SET_TOPIC = "girier01/11/set"
TRANSITION_SECONDS = 3
BRIGHTNESS_MIN = 1
BRIGHTNESS_MAX = 254
COLOR_TEMP_MIN = 153
COLOR_TEMP_MAX = 500

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

TOPIC_TO_KIND: Dict[str, str] = {}
for virtual_name in KITCHEN_VIRTUAL_NAMES:
    TOPIC_TO_KIND[f"lights/{virtual_name}/set"] = "ha_set_json"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/POWER"] = "power_text"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/SET"] = "power_text"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/brightness"] = "brightness"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/brightnessWithOnOff"] = "brightness_on"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/colorTemp"] = "color_temp"
    TOPIC_TO_KIND[f"cmnd/{virtual_name}/colorTempWithOnOff"] = "color_temp_on"


# Randomly assigned during development; static per implementation for readable,
# consistent logs. Re-randomize at least when using this script as a new-program template.
MQTT_CLIENT_ID_SUFFIX = "2f5b6a97"


def generate_client_id():
    """Build a descriptive, stable MQTT client ID for this host and script."""
    hostname = socket.gethostname()
    fixed_label = "KitchenSpectreRouter"
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
    return max(COLOR_TEMP_MIN, min(COLOR_TEMP_MAX, parsed))


def _publish_to_physical_devices(
    client,
    source_topic: str,
    state: Optional[bool] = None,
    brightness: Optional[int] = None,
    color_temp: Optional[int] = None,
):
    strip_payload = {}
    dimmer_payload = {}

    if state is not None:
        state_text = "ON" if state else "OFF"
        strip_payload["state"] = state_text
        dimmer_payload["state"] = state_text

    if brightness is not None:
        strip_payload["brightness"] = brightness
        dimmer_payload["brightness"] = brightness

    if color_temp is not None:
        strip_payload["color_temp"] = color_temp

    if strip_payload:
        strip_payload["transition"] = TRANSITION_SECONDS
        strip_json = json.dumps(strip_payload)
        for topic in STRIP_TOPICS:
            client.publish(topic, strip_json)
            logging.info("Forwarded %s -> %s payload=%s", source_topic, topic, strip_json)

    if dimmer_payload:
        dimmer_payload["transition"] = TRANSITION_SECONDS
        dimmer_json = json.dumps(dimmer_payload)
        client.publish(DIMMER_SET_TOPIC, dimmer_json)
        logging.info(
            "Forwarded %s -> %s payload=%s",
            source_topic,
            DIMMER_SET_TOPIC,
            dimmer_json,
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


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode(errors="replace").strip()
        kind = TOPIC_TO_KIND.get(msg.topic)
        if kind is None:
            return

        if kind == "ha_set_json":
            _handle_ha_set_json(client, msg.topic, payload)
            return

        if kind == "power_text":
            state = _normalize_bool(payload)
            if state is None:
                logging.warning("Ignored unsupported power payload on %s: %r", msg.topic, payload)
                return
            _publish_to_physical_devices(client, source_topic=msg.topic, state=state)
            return

        if kind in {"brightness", "brightness_on"}:
            brightness = _clamp_brightness(payload)
            if brightness is None:
                logging.warning("Ignored invalid brightness payload on %s: %r", msg.topic, payload)
                return
            state = True if kind == "brightness_on" else None
            _publish_to_physical_devices(
                client,
                source_topic=msg.topic,
                state=state,
                brightness=brightness,
            )
            return

        if kind in {"color_temp", "color_temp_on"}:
            color_temp = _clamp_color_temp(payload)
            if color_temp is None:
                logging.warning("Ignored invalid color_temp payload on %s: %r", msg.topic, payload)
                return
            state = True if kind == "color_temp_on" else None
            _publish_to_physical_devices(
                client,
                source_topic=msg.topic,
                state=state,
                color_temp=color_temp,
            )
            return
    except Exception:
        logging.exception("Unhandled error in MQTT message handler.")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("MQTT connected.")
        for topic in sorted(TOPIC_TO_KIND.keys()):
            client.subscribe(topic)
            logging.info("Subscribed to %s", topic)
    else:
        logging.error("MQTT connect failed. rc=%s", rc)


def on_disconnect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        logging.warning("MQTT disconnected unexpectedly (rc=%s). Reconnecting...", rc)
    else:
        logging.info("MQTT disconnected.")


async def main():
    client_id = generate_client_id()
    logging.info("Using MQTT client_id: %s", client_id)

    client = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION2, client_id=client_id
    )

    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    client.on_message = on_message
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    logging.info("Connecting to MQTT broker at %s...", MQTT_BROKER)
    client.connect(MQTT_BROKER, MQTT_PORT)

    client.loop_start()
    logging.info("Kitchen spectre router running. Press Ctrl+C to exit.")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
