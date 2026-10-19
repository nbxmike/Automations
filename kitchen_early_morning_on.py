# Turns on the kitchen LED strips, Girier dimmer, and first Wyze plug outlet when
# presence is detected between 05:00 local time and sunrise. The lights are set
# to 350 mireds and brightness 200, matching the desired warm early-morning scene.
import asyncio
import json
import logging
import socket
from datetime import datetime, time
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

PRESENCE_SENSOR_TOPIC = "zigbee2mqtt/Kitchen Presence"
STRIP_SET_TOPICS = [
    "zigbee2mqtt/Fridge LED Strip/set",
    "zigbee2mqtt/Sink LED Strip/set",
]
STRIP_STATE_TOPICS = [
    topic[:-4] if topic.endswith("/set") else topic for topic in STRIP_SET_TOPICS
]
STRIP_GET_TOPICS = [f"{topic}/get" for topic in STRIP_STATE_TOPICS]
DIMMER_SET_TOPIC = "girier01/11/set"
DIMMER_STATE_TOPIC = "girier01/11/get"
GARDEN_LIGHTS_SET_TOPIC = "zigbee2mqtt/GardenLights/set"
GARDEN_LIGHTS_STATE_TOPIC = "zigbee2mqtt/GardenLights"
BACKDOOR_LIGHT_SET_TOPIC = "zigbee2mqtt/BackDoor/set"
BACKDOOR_LIGHT_STATE_TOPIC = "zigbee2mqtt/BackDoor"
POWER1_ON_TOPIC = "cmnd/wyzeParkingTree/POWER1"
POWER1_STATE_TOPIC = "stat/wyzeParkingTree/POWER1"
DEVICE_STATE_TOPICS = (
    STRIP_STATE_TOPICS
    + [
        DIMMER_STATE_TOPIC,
        GARDEN_LIGHTS_STATE_TOPIC,
        BACKDOOR_LIGHT_STATE_TOPIC,
        POWER1_STATE_TOPIC,
    ]
)

EARLIEST_TIME = time(5, 0)
MORNING_BRIGHTNESS = 127
MORNING_COLOR_TEMP = 500

# Set your kitchen location for sunrise calculation.
LATITUDE: Optional[float] = 42.61281053611971
LONGITUDE: Optional[float] = -70.68931574583688

# Logging Setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

last_presence_state: Optional[bool] = None
device_state: Dict[str, Optional[bool]] = {topic: None for topic in DEVICE_STATE_TOPICS}
missing_sun_config_logged = False


# Randomly assigned during development; static per implementation for readable,
# consistent logs. Re-randomize at least when using this script as a new-program template.
MQTT_CLIENT_ID_SUFFIX = "01e3644e"


def generate_client_id():
    """Build a descriptive, stable MQTT client ID for this host and script."""
    hostname = socket.gethostname()
    fixed_label = "KitchenEarlyMorningOn"
    return f"{hostname}_{fixed_label}_{MQTT_CLIENT_ID_SUFFIX}"


def _extract_presence(data):
    """Return presence bool when available, otherwise None."""
    presence_value = data.get("presence")
    if presence_value is None:
        presence_value = data.get("occupancy")
    if presence_value is None:
        return None
    return bool(presence_value)


def _extract_power_state(data):
    """Return power bool when available, otherwise None."""
    if isinstance(data, (int, float)):
        return data > 0

    if not isinstance(data, dict):
        return None

    state = data.get("state")
    if isinstance(state, str):
        state_upper = state.upper()
        if state_upper == "ON":
            return True
        if state_upper == "OFF":
            return False

    brightness = data.get("brightness")
    if isinstance(brightness, (int, float)):
        return brightness > 0

    return None


def _is_before_sunrise_after_five_am():
    """Return True when local time is between 05:00 and sunrise."""
    global missing_sun_config_logged

    if Observer is None or sun is None:
        if not missing_sun_config_logged:
            logging.error("astral is not installed. Install with: apt install python3-astral")
            missing_sun_config_logged = True
        return False

    if LATITUDE is None or LONGITUDE is None:
        if not missing_sun_config_logged:
            logging.error(
                "Set LATITUDE and LONGITUDE in kitchen_early_morning_on.py for sunrise checks."
            )
            missing_sun_config_logged = True
        return False

    now = datetime.now().astimezone()
    observer = Observer(latitude=LATITUDE, longitude=LONGITUDE)
    sunrise = sun(observer, date=now.date(), tzinfo=now.tzinfo)["sunrise"]

    return now.time() >= EARLIEST_TIME and now < sunrise


def send_early_morning_on_command(client):
    """Turn on devices only when they're OFF or their state is unknown."""
    payload = json.dumps(
        {
            "state": "ON",
            "brightness": MORNING_BRIGHTNESS,
            "color_temp": MORNING_COLOR_TEMP,
        }
    )

    for topic in STRIP_SET_TOPICS:
        state_topic = topic[:-4] if topic.endswith("/set") else topic
        if device_state.get(state_topic) is True:
            logging.info(f"Leaving strip already ON: {state_topic}")
            continue

        client.publish(topic, payload)
        logging.info(
            f"Sent early-morning ON command to {topic}: "
            f"Brightness={MORNING_BRIGHTNESS}, ColorTemp={MORNING_COLOR_TEMP}"
        )

    if device_state.get(DIMMER_STATE_TOPIC) is not True:
        client.publish(DIMMER_SET_TOPIC, str(MORNING_BRIGHTNESS))
        logging.info(
            f"Sent early-morning brightness command to {DIMMER_SET_TOPIC}: "
            f"Brightness={MORNING_BRIGHTNESS}"
        )
    else:
        logging.info(f"Leaving dimmer already ON: {DIMMER_STATE_TOPIC}")

    if device_state.get(GARDEN_LIGHTS_STATE_TOPIC) is not True:
        garden_payload = json.dumps({"state": "ON"})
        client.publish(GARDEN_LIGHTS_SET_TOPIC, garden_payload, retain=False)
        logging.info(
            f"Sent early-morning ON command to {GARDEN_LIGHTS_SET_TOPIC}: {garden_payload}"
        )
    else:
        logging.info(f"Leaving GardenLights already ON: {GARDEN_LIGHTS_STATE_TOPIC}")

    if device_state.get(BACKDOOR_LIGHT_STATE_TOPIC) is not True:
        backdoor_payload = json.dumps({"state": "ON", "brightness": 50})
        client.publish(BACKDOOR_LIGHT_SET_TOPIC, backdoor_payload, retain=False)
        logging.info(
            f"Sent early-morning ON command to {BACKDOOR_LIGHT_SET_TOPIC}: {backdoor_payload}"
        )
    else:
        logging.info(f"Leaving BackDoor light already ON: {BACKDOOR_LIGHT_STATE_TOPIC}")

    if device_state.get(POWER1_STATE_TOPIC) is not True:
        client.publish(POWER1_ON_TOPIC, "ON", retain=False)
        logging.info(f"Sent early-morning ON command to {POWER1_ON_TOPIC}")
    else:
        logging.info(f"Leaving first Wyze plug outlet already ON: {POWER1_STATE_TOPIC}")


def on_message(client, userdata, msg):
    """Handle incoming presence messages and trigger early morning lights."""
    global last_presence_state

    try:
        raw_payload = msg.payload.decode(errors="replace")
        data = json.loads(raw_payload)

        if msg.topic == PRESENCE_SENSOR_TOPIC:
            is_present = _extract_presence(data)
            if is_present is None:
                return

            if last_presence_state is not None and is_present == last_presence_state:
                return

            last_presence_state = is_present

            if is_present and _is_before_sunrise_after_five_am():
                logging.info(
                    "Morning presence trigger matched. Turning kitchen lights and supported outlets on only when off or unknown."
                )
                send_early_morning_on_command(client)
            return

        if msg.topic in DEVICE_STATE_TOPICS:
            power_state = _extract_power_state(data)
            if power_state is None:
                return

            previous_state = device_state.get(msg.topic)
            device_state[msg.topic] = power_state

            if previous_state != power_state:
                logging.info(
                    f"Device state changed: {msg.topic} -> {'ON' if power_state else 'OFF'}"
                )
            return

    except json.JSONDecodeError:
        if msg.topic in DEVICE_STATE_TOPICS:
            logging.debug(f"Non-JSON state payload ignored for {msg.topic}: {raw_payload}")
        else:
            logging.error("Failed to parse JSON payload from MQTT message.")
    except Exception:
        logging.exception("Unhandled error in MQTT message handler.")


def _request_light_states(client):
    """Request current state from the devices that support a GET topic."""
    for topic in STRIP_GET_TOPICS:
        client.publish(topic, json.dumps({"state": ""}))
        logging.info(f"Requested state from {topic}")

    client.publish(DIMMER_STATE_TOPIC, json.dumps({"state": ""}))
    logging.info(f"Requested state from {DIMMER_STATE_TOPIC}")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("Connected to MQTT broker.")
        client.subscribe(PRESENCE_SENSOR_TOPIC)
        logging.info(f"Subscribed to {PRESENCE_SENSOR_TOPIC}")

        for topic in DEVICE_STATE_TOPICS:
            client.subscribe(topic)
            logging.info(f"Subscribed to {topic}")

        _request_light_states(client)
    else:
        logging.error(f"Failed to connect to MQTT broker. rc={rc}")


def on_disconnect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        logging.warning(f"Unexpected MQTT disconnect (rc={rc}). Reconnecting...")
    else:
        logging.info("Disconnected from MQTT broker.")


async def main():
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
    logging.info("Early morning automation script running. Press Ctrl+C to exit.")

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
