# Turns off both outlets of a Tasmota-powered Wyze Plug Outdoor at sunrise.
# This is the inverse of yard_sunset_automation.py and uses the same MQTT
# broker configuration, geolocation, and logging style as kitchen_morning.py.
# File renamed from wyze_parking_tree_sunrise_off.py to yard_sunrise_automation.py
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

# Set your location for sunrise calculation.
LATITUDE: Optional[float] = 42.61281053611971
LONGITUDE: Optional[float] = -70.68931574583688

# Tasmota dual-outlet Wyze Plug Outdoor command topics for both relays.
POWER_COMMAND_TOPICS = [
    "cmnd/wyze_parking_tree/POWER1",
    "cmnd/wyze_parking_tree/POWER2",
]
GARDEN_LIGHTS_SET_TOPIC = "zigbee2mqtt/GardenLights/set"
BACKDOOR_LIGHT_SET_TOPIC = "zigbee2mqtt/BackDoor/set"

# Logging setup matches the kitchen automation style.
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

sunrise_triggered = False
missing_sun_config_logged = False


# Randomly assigned during development; static per implementation for readable,
# consistent logs. Re-randomize at least when using this script as a new-program template.
MQTT_CLIENT_ID_SUFFIX = "6bac0cad"


def generate_client_id():
    """Build a descriptive, stable MQTT client ID for this host and script."""
    hostname = socket.gethostname()
    fixed_label = "YardSunriseAutomation"
    return f"{hostname}_{fixed_label}_{MQTT_CLIENT_ID_SUFFIX}"


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
                "Set LATITUDE and LONGITUDE in yard_sunrise_automation.py for sunrise checks."
            )
            missing_sun_config_logged = True
        return None

    now = datetime.now().astimezone()
    observer = Observer(latitude=LATITUDE, longitude=LONGITUDE)
    return sun(observer, date=now.date(), tzinfo=now.tzinfo)["sunrise"]


def send_sunrise_off_command(client):
    """Send OFF commands to both Wyze relays and selected Zigbee lights."""
    for topic in POWER_COMMAND_TOPICS:
        client.publish(topic, "OFF", retain=False)
        logging.info(f"Sent sunrise OFF command to {topic}")

    garden_payload = json.dumps({"state": "OFF"})
    client.publish(GARDEN_LIGHTS_SET_TOPIC, garden_payload, retain=False)
    logging.info(f"Sent sunrise OFF command to {GARDEN_LIGHTS_SET_TOPIC}: {garden_payload}")

    backdoor_payload = json.dumps({"state": "OFF"})
    client.publish(BACKDOOR_LIGHT_SET_TOPIC, backdoor_payload, retain=False)
    logging.info(f"Sent sunrise OFF command to {BACKDOOR_LIGHT_SET_TOPIC}: {backdoor_payload}")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("Connected to MQTT broker.")
    else:
        logging.error(f"Failed to connect to MQTT broker. rc={rc}")


def on_disconnect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        logging.warning(f"Unexpected MQTT disconnect (rc={rc}). Reconnecting...")
    else:
        logging.info("Disconnected from MQTT broker.")


async def main():
    global sunrise_triggered

    client_id = generate_client_id()
    logging.info(f"Using MQTT client_id: {client_id}")

    client = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION2,
        client_id=client_id,
    )

    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    logging.info(f"Connecting to MQTT broker at {MQTT_BROKER}...")
    client.connect(MQTT_BROKER, MQTT_PORT)

    client.loop_start()
    logging.info("Yard sunrise automation script running. Press Ctrl+C to exit.")

    try:
        while True:
            now = datetime.now().astimezone()
            sunrise = _get_today_sunrise()

            if sunrise is not None:
                if now >= sunrise and not sunrise_triggered:
                    logging.info("Sunrise reached. Turning off both outlets.")
                    send_sunrise_off_command(client)
                    sunrise_triggered = True
                elif now < sunrise and sunrise_triggered:
                    sunrise_triggered = False

            await asyncio.sleep(30)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
