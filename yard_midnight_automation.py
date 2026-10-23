#!/usr/bin/env python3
# Turns off only the first outlet of the dual-outlet Wyze WLPPO1 (Tasmota
# reprogrammed) at midnight, unless a late-arrival override is active.
# This follows the MQTT and logging style used in kitchen_morning.py.
# File renamed from wyzeParkingTree_midnight_off.py to yard_midnight_automation.py
# to better reflect its yard/outdoor midnight automation role while preserving the
# original MQTT topics and operational behavior.
import asyncio
import json
import logging
import signal
import socket
from datetime import datetime, timedelta, timezone
from typing import Optional

from automation_credentials import MQTT_BROKER, MQTT_PORT, MQTT_PASS, MQTT_USER
from paho.mqtt import client as mqtt_client

try:
    from astral import Observer
    from astral.sun import sun
except ImportError:
    Observer = None
    sun = None

# --- Configuration ---

# Set your location for sunrise calculation.
LATITUDE: Optional[float] = 42.61281053611971
LONGITUDE: Optional[float] = -70.68931574583688

# Tasmota dual-outlet command topics. Only POWER1 is toggled off.
POWER1_OFF_TOPIC = "cmnd/wyzeParkingTree/POWER1"
BACKDOOR_LIGHT_SET_TOPIC = "zigbee2mqtt/BackDoor/set"
OVERRIDE_POWER_TOPICS = (
    "stat/arrivalOverride/POWER",
)
OVERRIDE_STATE_TOPICS = (
    "stat/arrivalOverride/STATE",
)

# Logging setup matches the kitchen automation style.
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

last_override_power_state: Optional[bool] = None
last_override_state_time: Optional[datetime] = None
missing_sun_config_logged = False


# Randomly assigned during development; static per implementation for readable,
# consistent logs. Re-randomize at least when using this script as a new-program template.
MQTT_CLIENT_ID_SUFFIX = "d5e37dff"


def generate_client_id():
    """Build a descriptive, stable MQTT client ID for this host and script."""
    hostname = socket.gethostname()
    fixed_label = "YardMidnightAutomation"
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
            logging.error("astral is not installed. Install with: apt install python3-astral")
            missing_sun_config_logged = True
        return None

    if LATITUDE is None or LONGITUDE is None:
        if not missing_sun_config_logged:
            logging.error(
                "Set LATITUDE and LONGITUDE in yard_midnight_automation.py for sunrise checks."
            )
            missing_sun_config_logged = True
        return None

    now = datetime.now().astimezone()
    observer = Observer(latitude=LATITUDE, longitude=LONGITUDE)
    return sun(observer, date=now.date(), tzinfo=now.tzinfo)["sunrise"]


def should_skip_light_off():
    """Return True when the late-arrival override is active and fresh enough to block shutdown."""
    global last_override_power_state, last_override_state_time

    if last_override_power_state is True:
        if last_override_state_time is None:
            logging.info(
                "Late-arrival override state is ON but no timestamp was seen. "
                "Treating override as fresh enough to block shutdown."
            )
            return True

        age = datetime.now(timezone.utc) - last_override_state_time
        if age <= timedelta(hours=6):
            logging.info(
                f"Late-arrival override is ON and fresh ({age.total_seconds() / 3600:.2f} hours old); "
                "skipping midnight turnoff for outlet 1."
            )
            return True

        logging.info(
            "Late-arrival override ON state is older than 6 hours; treating it as stale and turning off outlet 1."
        )

    return False


def send_power1_off(client):
    """Turn off the first outlet and BackDoor Zigbee light."""
    client.publish(POWER1_OFF_TOPIC, "OFF", retain=False)
    logging.info(f"Sent OFF command to {POWER1_OFF_TOPIC} (first outlet only)")

    backdoor_payload = json.dumps({"state": "OFF"})
    client.publish(BACKDOOR_LIGHT_SET_TOPIC, backdoor_payload, retain=False)
    logging.info(f"Sent OFF command to {BACKDOOR_LIGHT_SET_TOPIC}: {backdoor_payload}")


def on_message(client, userdata, msg):
    """Track the late-arrival override status and JSON state payload."""
    global last_override_power_state, last_override_state_time

    try:
        payload = msg.payload.decode(errors="replace").strip()

        if msg.topic in OVERRIDE_POWER_TOPICS:
            value = _normalize_bool(payload)
            if value is None:
                logging.warning(f"Ignored unsupported override POWER payload on {msg.topic}: {payload!r}")
                return

            last_override_power_state = value
            last_override_state_time = datetime.now(timezone.utc)
            logging.info(f"Updated {msg.topic} -> {value}")
            return

        if msg.topic in OVERRIDE_STATE_TOPICS:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                logging.warning(f"Ignored invalid JSON payload on {msg.topic}: {payload!r}")
                return

            state_value = data.get("state")
            if isinstance(state_value, str):
                parsed_state = _normalize_bool(state_value)
                if parsed_state is not None:
                    last_override_power_state = parsed_state

            time_utc = data.get("time_utc")
            if isinstance(time_utc, str):
                try:
                    last_override_state_time = datetime.fromisoformat(
                        time_utc.replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                except ValueError:
                    logging.warning(f"Bad time_utc value in {msg.topic}: {time_utc!r}")
                    last_override_state_time = datetime.now(timezone.utc)
            else:
                last_override_state_time = datetime.now(timezone.utc)

            logging.info(
                f"Updated {msg.topic}: state={last_override_power_state}, "
                f"time_utc={last_override_state_time.isoformat().replace('+00:00', 'Z')}"
            )
    except Exception:
        logging.exception("Unhandled error in MQTT message handler.")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("Connected to MQTT broker.")
        for topic in OVERRIDE_POWER_TOPICS + OVERRIDE_STATE_TOPICS:
            client.subscribe(topic)
            logging.info(f"Subscribed to {topic}")
    else:
        logging.error(f"Failed to connect to MQTT broker. rc={rc}")


def on_disconnect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        logging.warning(f"Unexpected MQTT disconnect (rc={rc}). Reconnecting...")
    else:
        logging.info("Disconnected from MQTT broker.")


def handle_shutdown(signum, frame):
    logging.info("Shutdown signal received. Exiting yard_midnight_automation service.")
    raise SystemExit(0)


async def main():
    global last_override_power_state, last_override_state_time

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
    logging.info("Midnight outlet-off automation script running. Press Ctrl+C to exit.")

    try:
        while True:
            now = datetime.now().astimezone()

            # To avoid duplicate actions, trigger only in the first 15 seconds of midnight.
            if now.hour == 0 and now.minute == 0 and now.second <= 15:
                if should_skip_light_off():
                    logging.info("Late-arrival override is active; leaving first outlet unchanged.")
                else:
                    logging.info("Midnight reached. Turning off first outlet only.")
                    send_power1_off(client)

            # Keep a quiet heartbeat, primarily for service health and debug visibility.
            await asyncio.sleep(15)
    except SystemExit:
        pass
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
