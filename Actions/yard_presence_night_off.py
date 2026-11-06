#!/usr/bin/env python3
# Turns off outside lights when everyone is home long enough during the night,
# unless the late-arrival override is active.
#
# Conditions required before shutdown:
# - Local time is between 21:00 and sunrise.
# - arrivalOverride is not ON.
# - phonePresence/everyone is true for 10 continuous minutes.
#
# After shutdown, if wyzeParkingTree and/or BackDoor is turned back ON while
# conditions still match, the 10-minute timer is restarted.
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

LATITUDE: Optional[float] = 42.61281053611971
LONGITUDE: Optional[float] = -70.68931574583688

POWER1_OFF_TOPIC = "cmnd/wyzeParkingTree/POWER1"
BACKDOOR_LIGHT_SET_TOPIC = "zigbee2mqtt/BackDoor/set"

POWER1_STATE_TOPIC = "stat/wyzeParkingTree/POWER1"
POWER2_STATE_TOPIC = "stat/wyzeParkingTree/POWER2"
BACKDOOR_STATE_TOPIC = "zigbee2mqtt/BackDoor"

OVERRIDE_POWER_TOPICS = (
    "stat/arrivalOverride/POWER",
)
OVERRIDE_STATE_TOPICS = (
    "stat/arrivalOverride/STATE",
)
PHONE_EVERYONE_TOPIC = "phonePresence/everyone"

NIGHT_START_HOUR = 21
EVERYONE_HOLD_SECONDS = 600

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# Runtime state
last_override_power_state: Optional[bool] = None
last_override_state_time: Optional[datetime] = None

phone_everyone_home: Optional[bool] = None
phone_everyone_true_since: Optional[datetime] = None

power1_is_on: Optional[bool] = None
power2_is_on: Optional[bool] = None
backdoor_is_on: Optional[bool] = None

countdown_started_at: Optional[datetime] = None
missing_sun_config_logged = False

MQTT_CLIENT_ID_SUFFIX = "d6f33118"


def generate_client_id():
    """Build a descriptive, stable MQTT client ID for this host and script."""
    hostname = socket.gethostname()
    fixed_label = "YardPresenceNightOff"
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


def _extract_backdoor_on(payload: str) -> Optional[bool]:
    """Support BackDoor state payload as either plain text or JSON."""
    value = _normalize_bool(payload)
    if value is not None:
        return value

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    state = data.get("state")
    state_value = _normalize_bool(state)
    if state_value is not None:
        return state_value

    brightness = data.get("brightness")
    if isinstance(brightness, (int, float)):
        return brightness > 0

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
                "Set LATITUDE and LONGITUDE in yard_presence_night_off.py for sunrise checks."
            )
            missing_sun_config_logged = True
        return None

    now = datetime.now().astimezone()
    observer = Observer(latitude=LATITUDE, longitude=LONGITUDE)
    return sun(observer, date=now.date(), tzinfo=now.tzinfo)["sunrise"]


def _is_within_night_window() -> bool:
    """Return True between 21:00 local time and local sunrise."""
    now = datetime.now().astimezone()

    if now.hour >= NIGHT_START_HOUR:
        return True

    sunrise = _get_today_sunrise()
    if sunrise is None:
        return False

    return now < sunrise


def _override_blocks_shutdown() -> bool:
    return last_override_power_state is True


def _outside_lights_on() -> bool:
    # POWER2 can also indicate outside lighting activity even though this script
    # only commands POWER1 OFF to stay aligned with midnight behavior.
    return bool(power1_is_on or power2_is_on or backdoor_is_on)


def _eligible_to_countdown() -> bool:
    if not _is_within_night_window():
        return False
    if _override_blocks_shutdown():
        return False
    if phone_everyone_home is not True:
        return False
    return True


def send_outside_lights_off(client):
    """Turn off the same targets as midnight automation: POWER1 and BackDoor."""
    client.publish(POWER1_OFF_TOPIC, "OFF", retain=False)
    logging.info(f"Sent OFF command to {POWER1_OFF_TOPIC} (first outlet only)")

    backdoor_payload = json.dumps({"state": "OFF"})
    client.publish(BACKDOOR_LIGHT_SET_TOPIC, backdoor_payload, retain=False)
    logging.info(f"Sent OFF command to {BACKDOOR_LIGHT_SET_TOPIC}: {backdoor_payload}")


def _start_or_restart_countdown(reason: str):
    global countdown_started_at

    countdown_started_at = datetime.now(timezone.utc)
    logging.info(
        "Started 10-minute everyone-home countdown (%s).",
        reason,
    )


def _clear_countdown(reason: str):
    global countdown_started_at

    if countdown_started_at is not None:
        logging.info("Cleared everyone-home countdown (%s).", reason)
    countdown_started_at = None


def on_message(client, userdata, msg):
    """Track override, everyone-home signal, and outdoor light state transitions."""
    global last_override_power_state, last_override_state_time
    global phone_everyone_home, phone_everyone_true_since
    global power1_is_on, power2_is_on, backdoor_is_on

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
            if value:
                _clear_countdown(f"{msg.topic} turned ON")
            return

        if msg.topic in OVERRIDE_STATE_TOPICS:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                logging.warning(f"Ignored invalid JSON payload on {msg.topic}: {payload!r}")
                return

            state_value = _normalize_bool(data.get("state"))
            if state_value is not None:
                last_override_power_state = state_value

            time_utc = data.get("time_utc")
            if isinstance(time_utc, str):
                try:
                    last_override_state_time = datetime.fromisoformat(
                        time_utc.replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                except ValueError:
                    last_override_state_time = datetime.now(timezone.utc)
            else:
                last_override_state_time = datetime.now(timezone.utc)

            logging.info(
                f"Updated {msg.topic}: state={last_override_power_state}, "
                f"time_utc={last_override_state_time.isoformat().replace('+00:00', 'Z')}"
            )
            if last_override_power_state is True:
                _clear_countdown(f"{msg.topic} JSON state is ON")
            return

        if msg.topic == PHONE_EVERYONE_TOPIC:
            value = _normalize_bool(payload)
            if value is None:
                logging.warning(f"Ignored unsupported everyone payload: {payload!r}")
                return

            previous = phone_everyone_home
            phone_everyone_home = value
            if value:
                if phone_everyone_true_since is None:
                    phone_everyone_true_since = datetime.now(timezone.utc)
                    logging.info("phonePresence/everyone is TRUE. Started hold tracking.")
                if _eligible_to_countdown() and _outside_lights_on() and countdown_started_at is None:
                    _start_or_restart_countdown("everyone became TRUE")
            else:
                phone_everyone_true_since = None
                _clear_countdown("everyone became FALSE")

            if previous != value:
                logging.info("Updated phone presence everyone -> %s", value)
            return

        if msg.topic == POWER1_STATE_TOPIC:
            value = _normalize_bool(payload)
            if value is None:
                return
            was_on = power1_is_on is True
            power1_is_on = value
            if value and not was_on and _eligible_to_countdown():
                _start_or_restart_countdown("POWER1 turned ON")
            return

        if msg.topic == POWER2_STATE_TOPIC:
            value = _normalize_bool(payload)
            if value is None:
                return
            was_on = power2_is_on is True
            power2_is_on = value
            if value and not was_on and _eligible_to_countdown():
                _start_or_restart_countdown("POWER2 turned ON")
            return

        if msg.topic == BACKDOOR_STATE_TOPIC:
            value = _extract_backdoor_on(payload)
            if value is None:
                return
            was_on = backdoor_is_on is True
            backdoor_is_on = value
            if value and not was_on and _eligible_to_countdown():
                _start_or_restart_countdown("BackDoor turned ON")
            return
    except Exception:
        logging.exception("Unhandled error in MQTT message handler.")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logging.info("Connected to MQTT broker.")
        for topic in (
            *OVERRIDE_POWER_TOPICS,
            *OVERRIDE_STATE_TOPICS,
            PHONE_EVERYONE_TOPIC,
            POWER1_STATE_TOPIC,
            POWER2_STATE_TOPIC,
            BACKDOOR_STATE_TOPIC,
        ):
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
    logging.info("Shutdown signal received. Exiting yard_presence_night_off service.")
    raise SystemExit(0)


async def main():
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

    logging.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}...")
    client.connect(MQTT_BROKER, MQTT_PORT)

    client.loop_start()
    logging.info("Yard night presence off automation running. Press Ctrl+C to exit.")

    try:
        while True:
            if not _eligible_to_countdown():
                _clear_countdown("conditions not eligible")
                await asyncio.sleep(5)
                continue

            if not _outside_lights_on():
                _clear_countdown("outside lights already OFF")
                await asyncio.sleep(5)
                continue

            if phone_everyone_true_since is None:
                await asyncio.sleep(5)
                continue

            if countdown_started_at is None:
                _start_or_restart_countdown("eligible and lights are ON")
                await asyncio.sleep(5)
                continue

            elapsed = datetime.now(timezone.utc) - countdown_started_at
            if elapsed >= timedelta(seconds=EVERYONE_HOLD_SECONDS):
                logging.info(
                    "Everyone has been home for at least %s seconds and conditions match. Turning off outside lights.",
                    EVERYONE_HOLD_SECONDS,
                )
                send_outside_lights_off(client)
                _clear_countdown("shutdown executed")

            await asyncio.sleep(5)
    except SystemExit:
        pass
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
