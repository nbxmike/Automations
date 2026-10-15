#!/usr/bin/env python3
# Virtual MQTT device host used by Alexa routines and automations.
# Historically this file managed only late_arrival_override, but it now hosts
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
# - late_arrival_override: blocks yard midnight shutdown when ON.
# - kitchenSpectral: Alexa-visible kitchen dimmer and manual-intervention marker.
VIRTUAL_DEVICES = {
    "late_arrival_override": {
        "reset_at_sunrise": True,
        "auto_reset_seconds": None,
    },
    "kitchenSpectral": {
        "reset_at_sunrise": False,
        "auto_reset_seconds": None,
    },
}
KITCHEN_SPECTRAL = "kitchenSpectral"
KITCHEN_SPECTRAL_LEVEL_TOPICS = {
    f"cmnd/{KITCHEN_SPECTRAL}/BRIGHTNESS",
    f"cmnd/{KITCHEN_SPECTRAL}/BRIGHTNESS_WITH_ONOFF",
}
KITCHEN_SPECTRAL_MANUAL_TOPIC = f"stat/{KITCHEN_SPECTRAL}/manuallyTriggered"
MANUAL_TRIGGER_CLEAR_SECONDS = 5
BRIGHTNESS_MIN = 1
BRIGHTNESS_MAX = 254

# Logging setup matches the kitchen automation style.
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

device_state: Dict[str, bool] = {name: False for name in VIRTUAL_DEVICES}
device_brightness = {KITCHEN_SPECTRAL: 127}
last_state_change_utc: Dict[str, datetime] = {
    name: datetime.now(timezone.utc) for name in VIRTUAL_DEVICES
}
sunrise_reset_done = False
missing_sun_config_logged = False
manual_trigger_timer: Optional[threading.Timer] = None


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
    if device_name == KITCHEN_SPECTRAL:
        topics.extend(KITCHEN_SPECTRAL_LEVEL_TOPICS)
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

    if device_name == KITCHEN_SPECTRAL:
        client.publish(
            f"stat/{KITCHEN_SPECTRAL}/BRIGHTNESS",
            str(device_brightness[KITCHEN_SPECTRAL]),
            retain=True,
        )

    # Provide a JSON state payload for automation consumers.
    state_payload = json.dumps(
        {
            "device": device_name,
            "state": state_value,
            "time_utc": time_utc,
        }
    )
    client.publish(f"stat/{device_name}/STATE", state_payload, retain=True)


def set_device_state(client, device_name: str, new_state: bool):
    """Set the virtual device state and publish it to all state topics."""
    device_state[device_name] = bool(new_state)
    last_state_change_utc[device_name] = datetime.now(timezone.utc)
    publish_state(client, device_name)


def _clear_manual_trigger(client):
    global manual_trigger_timer
    client.publish(KITCHEN_SPECTRAL_MANUAL_TOPIC, "OFF", retain=True)
    logging.info("Cleared kitchenSpectral manuallyTriggered flag.")
    manual_trigger_timer = None


def _signal_manual_trigger(client):
    global manual_trigger_timer
    if manual_trigger_timer is not None:
        manual_trigger_timer.cancel()

    client.publish(KITCHEN_SPECTRAL_MANUAL_TOPIC, "ON", retain=True)
    manual_trigger_timer = threading.Timer(
        MANUAL_TRIGGER_CLEAR_SECONDS,
        _clear_manual_trigger,
        args=(client,),
    )
    manual_trigger_timer.daemon = True
    manual_trigger_timer.start()


def _handle_brightness_command(client, topic: str, payload: str):
    try:
        brightness = int(float(payload))
    except ValueError:
        logging.warning("Ignored invalid kitchenSpectral brightness: %r", payload)
        return

    brightness = max(BRIGHTNESS_MIN, min(BRIGHTNESS_MAX, brightness))
    device_brightness[KITCHEN_SPECTRAL] = brightness
    if topic.endswith("BRIGHTNESS_WITH_ONOFF"):
        device_state[KITCHEN_SPECTRAL] = True
    last_state_change_utc[KITCHEN_SPECTRAL] = datetime.now(timezone.utc)
    _signal_manual_trigger(client)
    publish_state(client, KITCHEN_SPECTRAL)
    logging.info("Received kitchenSpectral brightness command: %s", brightness)


def on_message(client, userdata, msg):
    """Handle ON/OFF commands for the virtual device."""
    try:
        payload = msg.payload.decode(errors="replace").strip()
        device_name = device_for_command_topic(msg.topic)
        if device_name is None:
            return

        if msg.topic in KITCHEN_SPECTRAL_LEVEL_TOPICS:
            _handle_brightness_command(client, msg.topic, payload)
            return

        value = _normalize_bool(payload)
        if value is None:
            logging.warning(f"Ignored unsupported command on {msg.topic}: {payload!r}")
            return

        logging.info(f"Received command for {device_name} on {msg.topic}: {value}")
        set_device_state(client, device_name, value)
        if device_name == KITCHEN_SPECTRAL:
            _signal_manual_trigger(client)
    except Exception:
        logging.exception("Unhandled error in MQTT message handler.")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("Connected to MQTT broker.")
        for topic in all_power_command_topics():
            client.subscribe(topic)
            logging.info(f"Subscribed to {topic}")

        # Default all hosted virtual devices to OFF on startup.
        for device_name in VIRTUAL_DEVICES:
            set_device_state(client, device_name, False)
        client.publish(KITCHEN_SPECTRAL_MANUAL_TOPIC, "OFF", retain=True)
    else:
        logging.error(f"Failed to connect to MQTT broker. rc={rc}")


def on_disconnect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        logging.warning(f"Unexpected MQTT disconnect (rc={rc}). Reconnecting...")
    else:
        logging.info("Disconnected from MQTT broker.")


def handle_shutdown(signum, frame):
    logging.info("Shutdown signal received. Exiting late_arrival_override service.")
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
        "Virtual device host is running (late_arrival_override + kitchenSpectral)."
    )

    last_quarter_hour = None

    try:
        while True:
            now = datetime.now().astimezone()
            sunrise = _get_today_sunrise()

            if sunrise is not None:
                if now >= sunrise and not sunrise_reset_done:
                    if device_state.get("late_arrival_override", False):
                        logging.info("Sunrise reached. Resetting late_arrival_override to OFF.")
                        set_device_state(client, "late_arrival_override", False)
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
