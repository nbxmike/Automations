# Turns on both outlets of a Tasmota-powered Wyze Plug Outdoor at sunset.
# This follows the same MQTT broker setup, geolocation logic, and logging style
# used in kitchen_morning.py.
# File renamed from wyzeParkingTree_sunset.py to yard_sunset_automation.py
# to better describe the yard automation while preserving the original MQTT topics
# and outlet behavior.
import asyncio
import json
import logging
import socket
from datetime import datetime
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

# Set your location for sunset calculation.
# Example: LATITUDE = 51.4778, LONGITUDE = 0.0
LATITUDE: Optional[float] = 42.61281053611971
LONGITUDE: Optional[float] = -70.68931574583688

# Tasmota dual-outlet Wyze Plug Outdoor command/state topics.
# MQTT Full Topic in the device info screen is "cmnd/wyzeParkingTree/",
# and the state topics are reported under "stat/wyzeParkingTree/".
POWER_COMMAND_TOPICS = [
    "cmnd/wyzeParkingTree/POWER1",
    "cmnd/wyzeParkingTree/POWER2",
]
GARDEN_LIGHTS_SET_TOPIC = "zigbee2mqtt/GardenLights/set"
BACKDOOR_LIGHT_SET_TOPIC = "zigbee2mqtt/BackDoor/set"
POWER_STATE_TOPICS = [
    "stat/wyzeParkingTree/POWER1",
    "stat/wyzeParkingTree/POWER2",
]

# Logging setup matches the kitchen script style.
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

last_power_state = {topic: None for topic in POWER_STATE_TOPICS}
sunset_triggered = False
missing_sun_config_logged = False


# Randomly assigned during development; static per implementation for readable,
# consistent logs. Re-randomize at least when using this script as a new-program template.
MQTT_CLIENT_ID_SUFFIX = "2b114b78"


def generate_client_id():
    """Build a descriptive, stable MQTT client ID for this host and script."""
    hostname = socket.gethostname()
    fixed_label = "YardSunsetAutomation"
    return f"{hostname}_{fixed_label}_{MQTT_CLIENT_ID_SUFFIX}"


def _get_sunset_time():
    """Return today's sunset time in local timezone, or None when config is missing."""
    global missing_sun_config_logged

    if Observer is None or sun is None:
        if not missing_sun_config_logged:
            logging.error("astral is not installed. Install with: pip install astral")
            missing_sun_config_logged = True
        return None

    if LATITUDE is None or LONGITUDE is None:
        if not missing_sun_config_logged:
            logging.error(
                "Set LATITUDE and LONGITUDE in yard_sunset_automation.py for sunset checks."
            )
            missing_sun_config_logged = True
        return None

    now = datetime.now().astimezone()
    observer = Observer(latitude=LATITUDE, longitude=LONGITUDE)
    return sun(observer, date=now.date(), tzinfo=now.tzinfo)["sunset"]


def send_sunset_on_command(client):
    """Send ON commands to both Wyze relays and selected Zigbee lights."""
    for topic in POWER_COMMAND_TOPICS:
        client.publish(topic, "ON", retain=False)
        logging.info(f"Sent sunset ON command to {topic}")

    garden_payload = json.dumps({"state": "ON"})
    client.publish(GARDEN_LIGHTS_SET_TOPIC, garden_payload, retain=False)
    logging.info(f"Sent sunset ON command to {GARDEN_LIGHTS_SET_TOPIC}: {garden_payload}")

    backdoor_payload = json.dumps({"state": "ON", "brightness": 50})
    client.publish(BACKDOOR_LIGHT_SET_TOPIC, backdoor_payload, retain=False)
    logging.info(f"Sent sunset ON command to {BACKDOOR_LIGHT_SET_TOPIC}: {backdoor_payload}")


def on_message(client, userdata, msg):
    """Log state changes reported by the Tasmota plug."""
    payload = msg.payload.decode(errors="replace").strip()

    if msg.topic in POWER_STATE_TOPICS:
        state = payload.upper()
        if state not in {"ON", "OFF"}:
            return

        previous_state = last_power_state.get(msg.topic)
        last_power_state[msg.topic] = state

        if previous_state != state:
            logging.info(f"Outlet state changed: {msg.topic} -> {state}")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("Connected to MQTT broker.")
        for topic in POWER_STATE_TOPICS:
            client.subscribe(topic)
            logging.info(f"Subscribed to {topic}")
    else:
        logging.error(f"Failed to connect to MQTT broker. rc={rc}")


def on_disconnect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        logging.warning(f"Unexpected MQTT disconnect (rc={rc}). Reconnecting...")
    else:
        logging.info("Disconnected from MQTT broker.")


async def main():
    global sunset_triggered

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
    logging.info("Yard sunset automation script running. Press Ctrl+C to exit.")

    try:
        while True:
            now = datetime.now().astimezone()
            sunset = _get_sunset_time()

            if sunset is not None:
                if now >= sunset and not sunset_triggered:
                    logging.info("Sunset reached. Turning on both outlets.")
                    send_sunset_on_command(client)
                    sunset_triggered = True
                elif now < sunset and sunset_triggered:
                    sunset_triggered = False

            await asyncio.sleep(30)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
