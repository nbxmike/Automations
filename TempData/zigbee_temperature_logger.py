#!/usr/bin/env python3
"""Subscribe to Zigbee2MQTT temperature sensors and log readings to CSV.

This script is designed to run on a headless Raspberry Pi over SSH inside tmux.
It listens for MQTT updates from Zigbee2MQTT sensor devices and writes one row per
reading with the local date, time, device name, and temperature in Celsius.

Example usage:
    tmux new -s tempdata
    cd /home/pi/Automations
    python3 TempData/zigbee_temperature_logger.py

The script will create a CSV file in the same TempData folder that it lives in.
Edit SENSOR_NAMES below to match the actual devices you are using.
"""

from __future__ import annotations

import csv
import json
import logging
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from paho.mqtt import client as mqtt_client
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit(
        "This script requires the paho-mqtt library. Install it with: "
        "python3 -m pip install paho-mqtt"
    ) from exc

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from automation_credentials import MQTT_BROKER, MQTT_PORT, MQTT_PASS, MQTT_USER

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

TOPIC_PREFIX = "zigbee2mqtt"

# Add or remove sensor names here to match your actual Zigbee2MQTT device names.
# The example names listed in the request are included below. If you have a second
# th_dot list, add it to EXTRA_SENSOR_NAMES and it will be merged automatically.
SENSOR_NAMES = [
    *[f"th_disp{i}" for i in range(1, 9)],
    *[f"th_dot{i}" for i in range(1, 9)],
]
EXTRA_SENSOR_NAMES = []
TARGET_SENSORS = list(dict.fromkeys(SENSOR_NAMES + EXTRA_SENSOR_NAMES))

TEMP_DATA_DIR = Path(__file__).resolve().parent
CSV_PATH = TEMP_DATA_DIR / "temperature_log.csv"

CSV_COLUMNS = ["date", "time", "device", "temperature_c", "humidity", "battery", "voltage"]


def make_client_id() -> str:
    return f"{socket.gethostname()}_temp_logger_{int(time.time())}"


def append_row(device: str, temperature: float, payload: dict) -> None:
    now_local = datetime.now().astimezone()
    row = {
        "date": now_local.strftime("%Y-%m-%d"),
        "time": now_local.strftime("%H:%M:%S"),
        "device": device,
        "temperature_c": temperature,
        "humidity": payload.get("humidity"),
        "battery": payload.get("battery"),
        "voltage": payload.get("voltage"),
    }

    file_exists = CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    logging.info(
        "Logged %s = %.2fC at %s %s",
        device,
        temperature,
        row["date"],
        row["time"],
    )


def normalize_topic(topic: str) -> str:
    return topic.strip("/")


def extract_device_name(topic: str) -> str:
    return normalize_topic(topic).split("/")[-1]


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("Connected to MQTT broker %s:%s", MQTT_BROKER, MQTT_PORT)
        client.subscribe(f"{TOPIC_PREFIX}/#")
        logging.info("Subscribed to %s/# for sensors: %s", TOPIC_PREFIX, ", ".join(TARGET_SENSORS))
    else:
        logging.error("MQTT connection failed with result code %s", rc)


def on_message(client, userdata, msg):
    topic = msg.topic
    device_name = extract_device_name(topic)
    if device_name not in TARGET_SENSORS:
        return

    try:
        payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        logging.warning("Ignoring non-JSON payload from %s: %r", topic, msg.payload)
        return

    if not isinstance(payload, dict):
        logging.warning("Ignoring payload from %s because it is not a JSON object: %r", topic, payload)
        return

    temperature = payload.get("temperature")
    if temperature is None:
        return

    try:
        temp_value = float(temperature)
    except (TypeError, ValueError):
        logging.warning("Ignoring invalid temperature for %s: %r", device_name, temperature)
        return

    append_row(device_name, temp_value, payload)


def connect_and_loop():
    try:
        client = mqtt_client.Client(
            callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2,
            client_id=make_client_id(),
        )
    except TypeError:
        client = mqtt_client.Client(client_id=make_client_id())

    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.enable_logger(logging.getLogger("paho.mqtt"))
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    try:
        client.loop_forever(retry_first_connection=True)
    except TypeError:
        client.loop_forever()


def main():
    if not TARGET_SENSORS:
        logging.error("No sensors are configured. Update SENSOR_NAMES in %s", __file__)
        raise SystemExit(1)

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.info("Temperature log path: %s", CSV_PATH)
    logging.info("Monitoring sensor topics: %s", ", ".join(TARGET_SENSORS))
    connect_and_loop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Stopping temperature logger.")
        raise SystemExit(0)
