#!/usr/bin/env python3
"""Turn off the yard outlet when every expected phone is seen on the Omada WiFi.

This script is intentionally close to the existing automation style in the project:
- MQTT login and publish use the same broker details as the yard scripts.
- The target turn-off action mirrors the same Tasmota outlet 1 command used by
  yard_midnight_automation.py.
- The Omada controller is polled for client presence, and the outlet is only
  switched off when all configured phones are online on the site.

Required packages:
    pip install requests paho-mqtt
"""

import asyncio
import logging
import socket
import time
from datetime import datetime, timezone
from typing import Iterable, List, Optional

import requests
from automation_credentials import (
    MQTT_BROKER,
    MQTT_PASS,
    MQTT_PORT,
    MQTT_USER,
    OMADA_BASE_URL,
    OMADA_CLIENT_ID,
    OMADA_CLIENT_SECRET,
    OMADA_OMADAC_ID,
    OMADA_PASSWORD,
    OMADA_SITE_ID,
    OMADA_SITE_NAME,
    OMADA_USERNAME,
)
from paho.mqtt import client as mqtt_client

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
# Connection details are loaded from automation_credentials.py so they are not
# checked into git.

# MQTT broker used by the existing yard automations.

# The Tasmota-controlled yard outlet used by the midnnight automation.
POWER1_OFF_TOPIC = "cmnd/wyze_parking_tree/POWER1"

# Omada controller settings.
# This controller requires the OpenAPI client-credentials flow, which matches the
# working curl commands discovered against the live controller.

# Legacy username/password values are kept only for compatibility with older
# controller builds. The active controller uses client credentials instead.

# List of devices that must be present before shutting off the yard outlet.
# Use either a friendly name or a MAC address. MAC matching is more reliable.
EXPECTED_CLIENTS: List[str] = [
    "AlicePhone",
    "BobPhone",
    "aa:bb:cc:dd:ee:ff",
]

# Do not count a phone as home if it has been inactive for longer than this.
ONLINE_STALE_SECONDS = 1800
POLL_SECONDS = 60

# This is intentionally static per script, like the rest of the project.
MQTT_CLIENT_ID_SUFFIX = "2947a1f3"

# -----------------------------------------------------------------------------
# End configuration
# -----------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")


def generate_client_id() -> str:
    hostname = socket.gethostname()
    fixed_label = "YardOmadaPresence" 
    return f"{hostname}_{fixed_label}_{MQTT_CLIENT_ID_SUFFIX}"


def normalize_mac(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = str(value).strip().lower().replace("-", ":")
    if not candidate:
        return None
    pieces = [piece for piece in candidate.split(":") if piece]
    if not pieces:
        return None
    return ":".join(piece.zfill(2) for piece in pieces)


def normalize_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text.lower() if text else None


def parse_timestamp(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _parse_api_response(payload):
    if isinstance(payload, dict):
        for key in ("result", "data", "clients", "list"):
            value = payload.get(key)
            if value is not None:
                return value
        return payload
    if isinstance(payload, list):
        return payload
    return []


def get_api_base_url(session: requests.Session) -> str:
    """Return the Omada API base URL including the controller-specific prefix when available."""
    base = OMADA_BASE_URL.rstrip("/")
    controller_id = (
        getattr(session, "omadac_id", None)
        or getattr(session, "omadacId", None)
        or OMADA_OMADAC_ID
    )
    if controller_id and str(controller_id).strip():
        return f"{base}/{str(controller_id).strip()}"
    return base


def login_to_omada(session: requests.Session):
    """Log in to the Omada controller using the OpenAPI client-credentials flow."""
    token_url = f"{OMADA_BASE_URL.rstrip('/')}/openapi/authorize/token?grant_type=client_credentials"
    payload = {
        "omadacId": OMADA_OMADAC_ID,
        "client_id": OMADA_CLIENT_ID,
        "client_secret": OMADA_CLIENT_SECRET,
    }

    try:
        response = session.post(token_url, json=payload, timeout=15, verify=False)
        raw_text = response.text[:2000]
        logging.info("OpenAPI token request to %s -> status=%s body=%s", token_url, response.status_code, raw_text)
        if response.status_code not in (200, 201, 202, 204):
            raise RuntimeError(f"OpenAPI token request failed: {response.status_code} {raw_text}")

        data = response.json() if response.content else {}
        result = data.get("result", {}) if isinstance(data, dict) else {}
        access_token = result.get("accessToken") or data.get("accessToken")
        if not access_token:
            raise RuntimeError(f"OpenAPI token response did not contain accessToken: {data}")

        session.headers["Authorization"] = f"AccessToken={access_token}"
        session.omadac_id = str(OMADA_OMADAC_ID)
        logging.info("Stored Omada controller ID: %s", session.omadac_id)
        session.headers["Content-Type"] = "application/json"
        logging.info("Logged in to Omada controller with OpenAPI client credentials.")
        return True
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"Unable to authenticate to Omada controller. Last error: {exc}")


def get_site_id(session: requests.Session) -> str:
    """Fetch the site id for the configured site using the Omada OpenAPI site endpoint."""
    api_base = get_api_base_url(session)
    urls = [
        f"{api_base}/openapi/v1/{OMADA_OMADAC_ID}/sites?page=1&pageSize=100",
        f"{api_base}/openapi/v1/{OMADA_OMADAC_ID}/sites",
    ]
    site_id = (OMADA_SITE_ID or "").strip()
    if site_id:
        logging.info("Using OMADA_SITE_ID override: %s", site_id)
        return site_id

    for url in urls:
        try:
            response = session.get(url, timeout=15, verify=False)
            raw_text = response.text[:5000]
            logging.info("GET %s -> status=%s body=%s", url, response.status_code, raw_text)
            try:
                payload = response.json() if response.content else {}
            except ValueError:
                logging.warning("Non-JSON response from %s: %s", url, raw_text)
                payload = {}
            logging.info("Raw site JSON from %s: %s", url, payload)
            entries = _parse_api_response(payload)
            if not isinstance(entries, list):
                logging.warning("Unexpected site response structure from %s: %s", url, payload)
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name") or entry.get("siteName") or entry.get("site_name")
                site_id_candidate = entry.get("siteId") or entry.get("id") or entry.get("site_id")
                if name and normalize_name(name) == normalize_name(OMADA_SITE_NAME):
                    logging.info("Matched site by name: %s -> %s", name, site_id_candidate)
                    return str(site_id_candidate)
                if site_id_candidate and normalize_name(OMADA_SITE_NAME) in {None, "default", ""}:
                    logging.info("Using first site because OMADA_SITE_NAME is empty: %s", site_id_candidate)
                    return str(site_id_candidate)
            if entries:
                first_id = entries[0].get("siteId") or entries[0].get("id") or entries[0].get("site_id")
                if first_id:
                    logging.info("Using first available site id as fallback: %s", first_id)
                    return str(first_id)
        except Exception as exc:  # pragma: no cover
            logging.warning("Site lookup failed for %s: %s", url, exc)

    raise RuntimeError(
        "Could not find the requested Omada site. Check OMADA_SITE_ID / OMADA_SITE_NAME and the controller credentials."
    )


def list_omada_clients(session: requests.Session) -> List[dict]:
    """Return a list of client records from the Omada controller using the OpenAPI endpoint."""
    api_base = get_api_base_url(session)
    site_id = get_site_id(session)
    urls = [
        f"{api_base}/openapi/v1/{OMADA_OMADAC_ID}/sites/{site_id}/clients?page=1&pageSize=100",
        f"{api_base}/openapi/v1/{OMADA_OMADAC_ID}/sites/{site_id}/clients",
    ]

    for url in urls:
        try:
            response = session.get(url, timeout=20, verify=False)
            raw_text = response.text[:5000]
            logging.info("GET %s -> status=%s body=%s", url, response.status_code, raw_text)
            try:
                payload = response.json() if response.content else {}
            except ValueError:
                logging.warning("Non-JSON client response from %s: %s", url, raw_text)
                payload = {}
            logging.info("Raw client JSON from %s: %s", url, payload)
            records = _parse_api_response(payload)
            if isinstance(records, list):
                cleaned = [entry for entry in records if isinstance(entry, dict)]
                if cleaned:
                    sample = cleaned[:3]
                    for index, client in enumerate(sample, start=1):
                        logging.info(
                            "Client sample %s: name=%r, hostname=%r, mac=%r, macAddress=%r, "
                            "online=%r, isOnline=%r, connected=%r, isConnected=%r, status=%r, "
                            "lastSeen=%r, time=%r",
                            client.get("name"),
                            client.get("hostname"),
                            client.get("mac"),
                            client.get("macAddress"),
                            client.get("online"),
                            client.get("isOnline"),
                            client.get("connected"),
                            client.get("isConnected"),
                            client.get("status"),
                            client.get("lastSeen"),
                            client.get("time"),
                        )
                return cleaned
        except Exception as exc:  # pragma: no cover
            logging.warning("Client lookup failed for %s: %s", url, exc)

    raise RuntimeError("Could not retrieve the Omada client list for the configured site.")


def client_is_online(client: dict) -> bool:
    """Determine whether a client is considered online and fresh enough to count as home."""
    if not isinstance(client, dict):
        return False

    online_fields = [
        client.get("online"),
        client.get("isOnline"),
        client.get("connected"),
        client.get("isConnected"),
    ]
    if any(value is True for value in online_fields):
        # Some Omada controllers include a lastSeen timestamp. Only treat the client as
        # present if it has been active within the configured window.
        last_seen = (
            parse_timestamp(client.get("lastSeen"))
            or parse_timestamp(client.get("last_seen"))
            or parse_timestamp(client.get("time"))
            or parse_timestamp(client.get("onlineTime"))
        )
        if last_seen is not None:
            age_seconds = (datetime.now(timezone.utc) - last_seen).total_seconds()
            if age_seconds > ONLINE_STALE_SECONDS:
                logging.info(
                    "Client %s is online but stale (%.0f seconds old); treating it as away.",
                    client.get("name") or client.get("hostname") or client.get("mac") or "unknown",
                    age_seconds,
                )
                return False
        return True

    status = str(client.get("status") or "").lower()
    if status in {"online", "connected", "active"}:
        last_seen = (
            parse_timestamp(client.get("lastSeen"))
            or parse_timestamp(client.get("last_seen"))
            or parse_timestamp(client.get("time"))
        )
        if last_seen is not None:
            age_seconds = (datetime.now(timezone.utc) - last_seen).total_seconds()
            if age_seconds > ONLINE_STALE_SECONDS:
                return False
        return True

    return False


def matching_client_names(clients: Iterable[dict]) -> List[str]:
    seen: List[str] = []
    for client in clients:
        name = normalize_name(client.get("name") or client.get("hostname") or client.get("clientName"))
        if name:
            seen.append(name)
        mac = normalize_mac(client.get("mac") or client.get("macAddress") or client.get("wirelessMac"))
        if mac:
            seen.append(mac)
    return seen


def everyone_is_home(clients: List[dict]) -> bool:
    """Return True only when every configured expected client is online and recognized."""
    names = matching_client_names(client for client in clients if client_is_online(client))

    for expected in EXPECTED_CLIENTS:
        normalized_expected = normalize_name(expected)
        normalized_mac = normalize_mac(expected)
        if normalized_expected is not None and normalized_expected in names:
            continue
        if normalized_mac is not None and normalized_mac in names:
            continue
        logging.info("Expected client not detected as home: %s", expected)
        return False

    return True


def publish_power1_off(client):
    """Allow the script to behave exactly like the midnight automation: just turn off outlet 1."""
    client.publish(POWER1_OFF_TOPIC, "OFF", retain=False)
    logging.info("Sent OFF command to %s (first outlet only)", POWER1_OFF_TOPIC)


async def main():
    client_id = generate_client_id()
    logging.info("Using MQTT client_id: %s", client_id)

    mqtt_client_obj = mqtt_client.Client(
        mqtt_client.CallbackAPIVersion.VERSION2,
        client_id=client_id,
    )
    mqtt_client_obj.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt_client_obj.reconnect_delay_set(min_delay=1, max_delay=30)

    logging.info("Connecting to MQTT broker at %s:%s...", MQTT_BROKER, MQTT_PORT)
    mqtt_client_obj.connect(MQTT_BROKER, MQTT_PORT)
    mqtt_client_obj.loop_start()

    session = requests.Session()
    session.verify = False
    login_to_omada(session)

    try:
        while True:
            try:
                clients = list_omada_clients(session)
                if everyone_is_home(clients):
                    logging.info("All expected phones are home. Turning off the yard outlet 1.")
                    publish_power1_off(mqtt_client_obj)
                    time.sleep(2)
                    # Stay in a safe state until the controller no longer reports everyone home.
                    await asyncio.sleep(POLL_SECONDS)
                    continue
                logging.info("Not all expected phones are home. No action taken.")
            except Exception as exc:  # pragma: no cover - top-level resilience for controller issues.
                logging.exception("Omada presence check failed: %s", exc)
            await asyncio.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        logging.info("Shutting down Omada presence automation.")
    finally:
        mqtt_client_obj.loop_stop()
        mqtt_client_obj.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
