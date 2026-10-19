# Monitors kitchen presence and light states over MQTT, dimming after vacancy
# and restoring algorithm-dimmed lights after sustained occupancy.
import asyncio
from concurrent.futures import CancelledError as FutureCancelledError
import json
import logging
import socket
from typing import Dict, Optional, Tuple

from automation_credentials import MQTT_BROKER, MQTT_PORT, MQTT_PASS, MQTT_USER
from paho.mqtt import client as mqtt_client

# --- Configuration ---

# Zigbee2MQTT Friendly Names
PRESENCE_SENSOR_TOPIC = "zigbee2mqtt/Kitchen Presence"
STRIP_TOPICS = [
    "zigbee2mqtt/Fridge LED Strip/set",
    "zigbee2mqtt/Sink LED Strip/set",
]
STRIP_STATE_TOPICS = [
    topic[:-4] if topic.endswith("/set") else topic for topic in STRIP_TOPICS
]
DIMMER_SET_TOPIC = "girier01/11/set"
DIMMER_STATE_TOPIC = "girier01/11/get"
MANUAL_POWER_TRIGGER_STATE_TOPIC = "stat/kitchenSpectral/manuallyTriggeredPower"
MANUAL_BRIGHTNESS_TRIGGER_STATE_TOPIC = "stat/kitchenSpectral/manuallyTriggeredBrightness"
LIGHT_STATE_TOPICS = STRIP_STATE_TOPICS + [DIMMER_STATE_TOPIC]
SET_TO_STATE_TOPIC = {
    set_topic: state_topic
    for set_topic, state_topic in zip(STRIP_TOPICS, STRIP_STATE_TOPICS)
}
SET_TO_STATE_TOPIC[DIMMER_SET_TOPIC] = DIMMER_STATE_TOPIC

# Automation Settings
IDLE_TIMEOUT = 300     # Time in seconds (5 minutes) before dimming
DIM_BRIGHTNESS = 38    # Dimmed to 15% brightness level (0-254)
OCCUPIED_BRIGHTEN_DELAY = 90 # brightening after 1.5 minutes of occupancy
BRIGHTEN_BRIGHTNESS = 204  # Approximately 80% of the 0-254 level range
WARM_COLOR_TEMP = 500  # Warmest color temp setting in mireds
TRANSITION_SECONDS = 3  # Smooth brightness ramp duration for supported devices
ASSUME_EMPTY_WHEN_PRESENCE_UNKNOWN = True

# Logging Setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

idle_task = None
presence_task = None
last_presence_state: Optional[bool] = None
strip_power_state: Dict[str, Optional[bool]] = {
    topic: None for topic in LIGHT_STATE_TOPICS
}
light_brightness: Dict[str, Optional[int]] = {
    topic: None for topic in LIGHT_STATE_TOPICS
}
light_change_sources: Dict[str, Optional[str]] = {
    topic: None for topic in LIGHT_STATE_TOPICS
}
auto_command_pending: Dict[str, bool] = {topic: False for topic in LIGHT_STATE_TOPICS}
algorithm_dimmed: Dict[str, bool] = {topic: False for topic in LIGHT_STATE_TOPICS}
manual_dim_cycle_active = False


# Randomly assigned during development; static per implementation for readable,
# consistent logs. Re-randomize at least when using this script as a new-program template.
MQTT_CLIENT_ID_SUFFIX = "debcd190"


def generate_client_id():
    """Build a descriptive, stable MQTT client ID for this host and script."""
    hostname = socket.gethostname()
    fixed_label = "KitchenDim"
    return f"{hostname}_{fixed_label}_{MQTT_CLIENT_ID_SUFFIX}"


def send_dim_command(client):
    """Dim tracked lights that are on, preserving CCT control for the strips."""
    payload = json.dumps(
        {
            "brightness": DIM_BRIGHTNESS,
            "color_temp": WARM_COLOR_TEMP,
            "transition": TRANSITION_SECONDS,
        }
    )
    dim_targets = [
        set_topic
        for set_topic in STRIP_TOPICS
        if _needs_brightness_command(
            SET_TO_STATE_TOPIC[set_topic], DIM_BRIGHTNESS
        )
    ]
    dimmer_needs_command = _needs_brightness_command(
        DIMMER_STATE_TOPIC, DIM_BRIGHTNESS
    )

    if not dim_targets and not dimmer_needs_command:
        logging.info("No tracked lights are on. Skipping dim command.")
        return

    for topic in dim_targets:
        client.publish(topic, payload)
        state_topic = SET_TO_STATE_TOPIC[topic]
        algorithm_dimmed[state_topic] = True
        auto_command_pending[state_topic] = True
        light_change_sources[state_topic] = "auto"
        logging.info(
            f"Sent dim command to {topic}: Brightness={DIM_BRIGHTNESS}, ColorTemp={WARM_COLOR_TEMP}"
        )

    if dimmer_needs_command:
        client.publish(
            DIMMER_SET_TOPIC,
            json.dumps(
                {
                    "brightness": DIM_BRIGHTNESS,
                    "transition": TRANSITION_SECONDS,
                }
            ),
        )
        algorithm_dimmed[DIMMER_STATE_TOPIC] = True
        auto_command_pending[DIMMER_STATE_TOPIC] = True
        light_change_sources[DIMMER_STATE_TOPIC] = "auto"
        logging.info(
            f"Sent dim command to {DIMMER_SET_TOPIC}: Brightness={DIM_BRIGHTNESS}"
        )


def send_brighten_command(client):
    """Raise any tracked on-lights that are below the target brightness."""
    targets = [
        set_topic
        for set_topic in STRIP_TOPICS
        if _needs_brightness_command(
            SET_TO_STATE_TOPIC[set_topic], BRIGHTEN_BRIGHTNESS, brighten=True
        )
    ]

    for topic in targets:
        client.publish(
            topic,
            json.dumps(
                {
                    "brightness": BRIGHTEN_BRIGHTNESS,
                    "transition": TRANSITION_SECONDS,
                }
            ),
        )
        state_topic = SET_TO_STATE_TOPIC[topic]
        algorithm_dimmed[state_topic] = False
        auto_command_pending[state_topic] = True
        light_change_sources[state_topic] = "auto"
        logging.info("Raised kitchen light %s to brightness %s", topic, BRIGHTEN_BRIGHTNESS)

    if _needs_brightness_command(
        DIMMER_STATE_TOPIC, BRIGHTEN_BRIGHTNESS, brighten=True
    ):
        client.publish(
            DIMMER_SET_TOPIC,
            json.dumps(
                {
                    "brightness": BRIGHTEN_BRIGHTNESS,
                    "transition": TRANSITION_SECONDS,
                }
            ),
        )
        algorithm_dimmed[DIMMER_STATE_TOPIC] = False
        auto_command_pending[DIMMER_STATE_TOPIC] = True
        light_change_sources[DIMMER_STATE_TOPIC] = "auto"
        logging.info(
            "Raised kitchen dimmer %s to brightness %s",
            DIMMER_SET_TOPIC,
            BRIGHTEN_BRIGHTNESS,
        )


def _cancel_presence_timer_if_running(reason):
    global presence_task
    if presence_task and not presence_task.done():
        presence_task.cancel()
        logging.info("Presence recovery timer cancelled: %s", reason)


def _start_presence_timer_if_needed(client, loop):
    global presence_task
    if not _any_light_on():
        return
    if manual_dim_cycle_active:
        logging.info(
            "Presence recovery timer suppressed during active manual dim cycle."
        )
        return
    if presence_task is None or presence_task.done():
        presence_task = asyncio.run_coroutine_threadsafe(
            handle_occupied(client), loop
        )
        presence_task.add_done_callback(_log_idle_task_result)
        logging.info("Presence recovery timer started: %ss", OCCUPIED_BRIGHTEN_DELAY)


def _log_idle_task_result(future):
    """Log unexpected idle-task failures so the service never fails silently."""
    try:
        future.result()
    except FutureCancelledError:
        logging.info("Idle timer task cancelled.")
    except Exception as exc:
        logging.exception(f"Idle task failed unexpectedly: {exc}")


def _any_light_on():
    return any(state is True for state in strip_power_state.values())


def _presence_is_empty_for_automation():
    """Return True when automation should treat room as empty."""
    if last_presence_state is False:
        return True
    if last_presence_state is None and ASSUME_EMPTY_WHEN_PRESENCE_UNKNOWN:
        return True
    return False


def _start_idle_timer_if_needed(client, loop, reason, restart_if_active=False):
    """Start the idle timer once for the current empty-room cycle."""
    global idle_task
    if idle_task is not None and not idle_task.done():
        if not restart_if_active:
            logging.info("Idle timer already active; ignoring duplicate start request: %s", reason)
            return
        _cancel_idle_timer_if_running(f"restarting idle timer for: {reason}")
    idle_task = asyncio.run_coroutine_threadsafe(handle_idle(client), loop)
    idle_task.add_done_callback(_log_idle_task_result)
    logging.info("Idle timer started: %s", reason)


def _cancel_idle_timer_if_running(reason):
    global idle_task
    if idle_task and not idle_task.done():
        idle_task.cancel()
        logging.info("Idle timer cancelled: %s", reason)


def _extract_presence(data):
    """Return presence bool when available, otherwise None."""
    presence_value = data.get("presence")
    if presence_value is None:
        presence_value = data.get("occupancy")
    if presence_value is None:
        return None
    return bool(presence_value)


def _needs_brightness_command(state_topic, target, brighten=False):
    """Target unknown devices blindly; otherwise compare only devices that are on."""
    if strip_power_state.get(state_topic) is False:
        return False

    current_brightness = light_brightness.get(state_topic)
    if current_brightness is None:
        return True
    if brighten:
        return current_brightness < target
    return current_brightness > target


def _extract_light_status(data) -> Tuple[Optional[bool], Optional[int]]:
    """Return known power and brightness values independently when available."""
    if isinstance(data, (int, float)):
        brightness = int(data)
        return brightness > 0, brightness

    if not isinstance(data, dict):
        return None, None

    is_on = None
    state = data.get("state")
    if isinstance(state, str):
        state_upper = state.upper()
        if state_upper == "ON":
            is_on = True
        elif state_upper == "OFF":
            is_on = False

    brightness = data.get("brightness")
    if isinstance(brightness, (int, float)):
        brightness = int(brightness)
        if is_on is None:
            is_on = brightness > 0
        return is_on, brightness

    return is_on, None


async def handle_idle(client):
    """Wait for 1 minute, then dim the lights."""
    try:
        logging.info(
            "Idle timer: starting %ss countdown (room empty, lights on).",
            IDLE_TIMEOUT,
        )
        await asyncio.sleep(IDLE_TIMEOUT)
        logging.info("Idle timer expired: dimming kitchen lights.")
        send_dim_command(client)
    except asyncio.CancelledError:
        logging.info("Idle timer cancelled before completion.")


async def handle_occupied(client):
    """Wait for continuous occupancy, then brighten eligible lights."""
    try:
        await asyncio.sleep(OCCUPIED_BRIGHTEN_DELAY)
        if last_presence_state is not True:
            logging.info("Occupancy ended before the brightening timer completed.")
            return
        send_brighten_command(client)
    except asyncio.CancelledError:
        logging.info("Occupied brightening timer cancelled before completion.")


def on_message(client, userdata, msg, loop):
    """Handle incoming MQTT messages from the presence sensor."""
    global idle_task, last_presence_state, manual_dim_cycle_active
    try:
        raw_payload = msg.payload.decode(errors="replace").strip()

        if msg.topic == MANUAL_POWER_TRIGGER_STATE_TOPIC:
            if raw_payload.upper() in {"ON", "TRUE", "1", "YES"}:
                logging.info("Manual kitchenSpectral ON/OFF event observed.")
            return

        if msg.topic == MANUAL_BRIGHTNESS_TRIGGER_STATE_TOPIC:
            if raw_payload.upper() in {"ON", "TRUE", "1", "YES"}:
                manual_dim_cycle_active = True
                for topic in algorithm_dimmed:
                    algorithm_dimmed[topic] = False
                _cancel_presence_timer_if_running("Alexa manual intervention")
                logging.info(
                    "Manual dim cycle enabled via kitchenSpectral; auto-brightening suppressed."
                )
            return

        data = json.loads(raw_payload)

        if msg.topic == PRESENCE_SENSOR_TOPIC:
            is_present = _extract_presence(data)
            if is_present is None:
                return

            # Ignore duplicate state messages to avoid timer churn.
            if last_presence_state is not None and is_present == last_presence_state:
                return

            last_presence_state = is_present

            if is_present:
                _cancel_idle_timer_if_running("presence detected")
                _start_presence_timer_if_needed(client, loop)
            elif _any_light_on():
                if manual_dim_cycle_active:
                    manual_dim_cycle_active = False
                    logging.info(
                        "Manual dim cycle cleared after vacancy; auto-brightening re-enabled."
                    )
                _cancel_presence_timer_if_running("presence cleared")
                _start_idle_timer_if_needed(client, loop, "room empty and light on")
            else:
                if manual_dim_cycle_active:
                    manual_dim_cycle_active = False
                    logging.info(
                        "Manual dim cycle cleared after vacancy; auto-brightening re-enabled."
                    )
                _cancel_presence_timer_if_running("presence cleared")
                logging.info("Room empty, lights are off; idle timer not started.")

        elif msg.topic in LIGHT_STATE_TOPICS:
            light_is_on, brightness = _extract_light_status(data)
            if light_is_on is None and brightness is None:
                logging.info("Ignoring light update without state data on %s", msg.topic)
                return

            previous_state = strip_power_state.get(msg.topic)
            previous_brightness = light_brightness.get(msg.topic)
            if light_is_on is not None:
                strip_power_state[msg.topic] = light_is_on
            if brightness is not None:
                light_brightness[msg.topic] = brightness

            if light_is_on is None:
                light_is_on = strip_power_state.get(msg.topic)
            if (
                previous_state == strip_power_state.get(msg.topic)
                and previous_brightness == light_brightness.get(msg.topic)
            ):
                return

            if auto_command_pending.get(msg.topic, False):
                light_change_sources[msg.topic] = "auto"
                auto_command_pending[msg.topic] = False
            else:
                light_change_sources[msg.topic] = "manual"

            if light_is_on is False:
                algorithm_dimmed[msg.topic] = False
            if previous_state != strip_power_state.get(msg.topic):
                state_label = "ON" if light_is_on else "OFF"
                logging.info("Light state: %s -> %s", msg.topic, state_label)
            if previous_brightness != light_brightness.get(msg.topic):
                logging.info(
                    "Light brightness: %s -> %s",
                    msg.topic,
                    light_brightness[msg.topic],
                )

            if light_is_on and _presence_is_empty_for_automation():
                change_source = light_change_sources.get(msg.topic)
                if change_source == "auto":
                    logging.info(
                        "Light on after automated change; ignoring idle restart for %s",
                        msg.topic,
                    )
                else:
                    reason = "light turned on while room is empty"
                    if last_presence_state is None:
                        reason = "light turned on with unknown presence (treated as empty)"
                    _start_idle_timer_if_needed(client, loop, reason)
            elif not _any_light_on():
                _cancel_idle_timer_if_running("all tracked lights are off")
            elif light_is_on:
                logging.info("Light turned on while occupied; idle timer not started.")

    except json.JSONDecodeError:
        logging.error("Failed to parse JSON payload from MQTT message.")
    except Exception:
        logging.exception("Unhandled error in MQTT message handler.")


def on_connect(client, userdata, flags, rc, properties=None):
    """Subscribe on every (re)connect so the service recovers from broker drops."""
    if rc == 0:
        logging.info("MQTT connected.")
        client.subscribe(PRESENCE_SENSOR_TOPIC)
        logging.info("Subscribed to %s", PRESENCE_SENSOR_TOPIC)
        for topic in LIGHT_STATE_TOPICS:
            client.subscribe(topic)
            logging.info("Subscribed to %s", topic)
        client.subscribe(MANUAL_POWER_TRIGGER_STATE_TOPIC)
        logging.info("Subscribed to %s", MANUAL_POWER_TRIGGER_STATE_TOPIC)
        client.subscribe(MANUAL_BRIGHTNESS_TRIGGER_STATE_TOPIC)
        logging.info("Subscribed to %s", MANUAL_BRIGHTNESS_TRIGGER_STATE_TOPIC)
    else:
        logging.error("MQTT connect failed. rc=%s", rc)


def on_disconnect(client, userdata, flags, rc, properties=None):
    if rc != 0:
        logging.warning("MQTT disconnected unexpectedly (rc=%s). Reconnecting...", rc)
    else:
        logging.info("MQTT disconnected.")


async def main():
    loop = asyncio.get_running_loop()

    client_id = generate_client_id()
    logging.info("Using MQTT client_id: %s", client_id)

    # Initialize MQTT Client
    # If this script is reused for a different automation, adjust the fixed
    # label in generate_client_id() so the client_id remains descriptive.
    client = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION2, client_id=client_id
    )

    # Set Credentials
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    # Attach message handler
    client.on_message = lambda c, u, m: on_message(c, u, m, loop)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    logging.info("Connecting to MQTT broker at %s...", MQTT_BROKER)
    client.connect(MQTT_BROKER, MQTT_PORT)

    # Start non-blocking MQTT loop
    client.loop_start()
    logging.info("Automation script running. Press Ctrl+C to exit.")

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