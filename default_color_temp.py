#!/usr/bin/env python3
# Applies default kitchen brightness/color temperature after manual ON events
# when those values were not explicitly provided by MQTT commands.
import asyncio
import json
import logging
import socket
from concurrent.futures import CancelledError as FutureCancelledError
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

# Kitchen devices controlled by this script (same devices as kitchen_dimming.py).
STRIP_TOPICS = [
    "zigbee2mqtt/Fridge LED Strip/set",
    "zigbee2mqtt/Sink LED Strip/set",
]
DIMMER_SET_TOPIC = "girier01/11/set"

# kitchenSpectral observation topics.
KITCHEN_SPECTRAL_POWER_STATE_TOPIC = "stat/kitchenSpectral/POWER"
MANUAL_POWER_TRIGGER_STATE_TOPIC = "stat/kitchenSpectral/manuallyTriggeredPower"
MANUAL_BRIGHTNESS_TRIGGER_STATE_TOPIC = "stat/kitchenSpectral/manuallyTriggeredBrightness"
MANUAL_COLOR_TEMP_TRIGGER_STATE_TOPIC = "stat/kitchenSpectral/manuallyTriggeredColorTemp"

# Defaults applied after a manual ON event when no explicit value was sent.
POST_ON_DELAY_SECONDS = 5
DEFAULT_BRIGHTNESS = 200
DAYLIGHT_COLOR_TEMP = 300
NIGHT_COLOR_TEMP = 500

# Set your kitchen location for sunrise/sunset calculation.
LATITUDE: Optional[float] = 42.61281053611971
LONGITUDE: Optional[float] = -70.68931574583688

TRANSITION_SECONDS = 3

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

last_kitchen_power_state: Optional[bool] = None
manual_brightness_seen = False
manual_color_temp_seen = False
pending_default_task = None
missing_sun_config_logged = False


# Randomly assigned during development; static per implementation for readable,
# consistent logs. Re-randomize at least when using this script as a new-program template.
MQTT_CLIENT_ID_SUFFIX = "9f5f42b1"


def generate_client_id():
    """Build a descriptive, stable MQTT client ID for this host and script."""
    hostname = socket.gethostname()
    fixed_label = "KitchenDefaults"
    return f"{hostname}_{fixed_label}_{MQTT_CLIENT_ID_SUFFIX}"


def _normalize_bool(value):
    text = value.strip().upper()
    if text in {"ON", "TRUE", "1", "YES"}:
        return True
    if text in {"OFF", "FALSE", "0", "NO"}:
        return False
    return None


def _is_nighttime():
    """Return True between sunset and sunrise in local time."""
    global missing_sun_config_logged

    if Observer is None or sun is None or LATITUDE is None or LONGITUDE is None:
        if not missing_sun_config_logged:
            logging.error(
                "Astral and kitchen coordinates are required for daylight defaults. "
                "Falling back to nighttime color temperature."
            )
            missing_sun_config_logged = True
        return True

    now = datetime.now().astimezone()
    observer = Observer(latitude=LATITUDE, longitude=LONGITUDE)
    solar_events = sun(observer, date=now.date(), tzinfo=now.tzinfo)
    return now >= solar_events["sunset"] or now < solar_events["sunrise"]


def _cancel_pending_default_task(reason):
    global pending_default_task
    if pending_default_task is not None and not pending_default_task.done():
        pending_default_task.cancel()
        logging.info("Cancelled pending default apply timer: %s", reason)


async def _apply_defaults_after_delay(client):
    try:
        await asyncio.sleep(POST_ON_DELAY_SECONDS)
        if last_kitchen_power_state is not True:
            logging.info("KitchenSpectral is no longer ON; skipping default apply.")
            return

        if not manual_brightness_seen:
            payload = json.dumps(
                {
                    "brightness": DEFAULT_BRIGHTNESS,
                    "transition": TRANSITION_SECONDS,
                }
            )
            for topic in STRIP_TOPICS:
                client.publish(topic, payload)
            client.publish(DIMMER_SET_TOPIC, payload)
            logging.info(
                "Applied default brightness=%s to kitchen devices after manual ON.",
                DEFAULT_BRIGHTNESS,
            )
        else:
            logging.info("Skipped default brightness: manual brightness command detected.")

        if not manual_color_temp_seen:
            target_color_temp = NIGHT_COLOR_TEMP if _is_nighttime() else DAYLIGHT_COLOR_TEMP
            color_payload = json.dumps(
                {
                    "color_temp": target_color_temp,
                    "transition": TRANSITION_SECONDS,
                }
            )
            for topic in STRIP_TOPICS:
                client.publish(topic, color_payload)
            logging.info(
                "Applied default color_temp=%s to kitchen strips after manual ON.",
                target_color_temp,
            )
        else:
            logging.info("Skipped default color temp: manual color-temp command detected.")
    except asyncio.CancelledError:
        logging.info("Default apply timer cancelled before completion.")


def _log_task_result(future):
    try:
        future.result()
    except FutureCancelledError:
        logging.info("Default apply task cancelled.")
    except Exception:
        logging.exception("Default apply task failed unexpectedly.")


def _start_default_apply_timer(client, loop):
    global pending_default_task, manual_brightness_seen, manual_color_temp_seen
    manual_brightness_seen = False
    manual_color_temp_seen = False
    _cancel_pending_default_task("starting new manual ON window")
    pending_default_task = asyncio.run_coroutine_threadsafe(
        _apply_defaults_after_delay(client), loop
    )
    pending_default_task.add_done_callback(_log_task_result)
    logging.info(
        "Detected manual kitchenSpectral ON. Waiting %ss before applying defaults.",
        POST_ON_DELAY_SECONDS,
    )


def on_message(client, userdata, msg, loop):
    global last_kitchen_power_state, manual_brightness_seen, manual_color_temp_seen
    payload = msg.payload.decode(errors="replace").strip()
    topic = msg.topic

    if topic == KITCHEN_SPECTRAL_POWER_STATE_TOPIC:
        parsed = _normalize_bool(payload)
        if parsed is None:
            logging.warning("Ignored unsupported kitchenSpectral POWER state: %r", payload)
            return
        last_kitchen_power_state = parsed
        logging.info("Observed kitchenSpectral POWER=%s", "ON" if parsed else "OFF")
        if not parsed:
            _cancel_pending_default_task("kitchenSpectral turned OFF")
        return

    if topic == MANUAL_POWER_TRIGGER_STATE_TOPIC:
        parsed = _normalize_bool(payload)
        if parsed is True:
            if last_kitchen_power_state is True:
                _start_default_apply_timer(client, loop)
            else:
                logging.info(
                    "Manual power trigger observed while kitchenSpectral not ON; skipping."
                )
        return

    if topic == MANUAL_BRIGHTNESS_TRIGGER_STATE_TOPIC:
        parsed = _normalize_bool(payload)
        if parsed is True:
            manual_brightness_seen = True
            logging.info("Manual brightness command detected during ON window.")
        return

    if topic == MANUAL_COLOR_TEMP_TRIGGER_STATE_TOPIC:
        parsed = _normalize_bool(payload)
        if parsed is True:
            manual_color_temp_seen = True
            logging.info("Manual color-temp command detected during ON window.")
        return


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("MQTT connected.")
        for topic in [
            KITCHEN_SPECTRAL_POWER_STATE_TOPIC,
            MANUAL_POWER_TRIGGER_STATE_TOPIC,
            MANUAL_BRIGHTNESS_TRIGGER_STATE_TOPIC,
            MANUAL_COLOR_TEMP_TRIGGER_STATE_TOPIC,
        ]:
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
    loop = asyncio.get_running_loop()

    client_id = generate_client_id()
    logging.info("Using MQTT client_id: %s", client_id)

    client = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION2, client_id=client_id
    )

    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    client.on_message = lambda c, u, m: on_message(c, u, m, loop)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    logging.info("Connecting to MQTT broker at %s...", MQTT_BROKER)
    client.connect(MQTT_BROKER, MQTT_PORT)

    client.loop_start()
    logging.info("Default color-temp automation running. Press Ctrl+C to exit.")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        _cancel_pending_default_task("service shutdown")
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
