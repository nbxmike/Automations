#!/usr/bin/env python3
"""Passively record MQTT messages as rotating, replay-friendly JSON Lines."""

import argparse
import base64
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import runpy
import signal
import socket
import time
from datetime import datetime, timezone
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


class StrictRotatingFileHandler(RotatingFileHandler):
    def handleError(self, record):
        raise


def positive_int(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def topic_filter(value):
    if not value or "\x00" in value or len(value.encode("utf-8")) > 65535:
        raise argparse.ArgumentTypeError("invalid MQTT topic filter")
    levels = value.split("/")
    for index, level in enumerate(levels):
        if ("+" in level and level != "+") or (
            "#" in level and (level != "#" or index != len(levels) - 1)
        ):
            raise argparse.ArgumentTypeError("invalid MQTT wildcard placement")
    if value.startswith("$share/"):
        raise argparse.ArgumentTypeError("shared subscriptions cannot capture every message")
    return value


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", action="append", type=topic_filter,
                        help="repeatable subscription filter (default: #)")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "Tools" / "logs" / "mqtt_activity.jsonl")
    parser.add_argument("--max-bytes", type=positive_int, default=10 * 1024 * 1024)
    parser.add_argument("--backups", type=positive_int, default=10)
    args = parser.parse_args(argv)
    args.topic = list(dict.fromkeys(args.topic or ["#"]))
    return args


class ActivityRecorder:
    def __init__(self, output, max_bytes, backups):
        output.parent.mkdir(parents=True, exist_ok=True)
        self.handler = StrictRotatingFileHandler(
            output, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.session = uuid4().hex
        self.sequence = 0
        self.started_ns = time.monotonic_ns()

    def write(self, event, **fields):
        self.sequence += 1
        now = datetime.now(timezone.utc)
        local = now.astimezone()
        record = {
            "schema_version": 1,
            "timestamp": now.isoformat(timespec="microseconds"),
            "local_time": f"{local:%A %d}/{local.strftime('%b').upper()}/{local:%Y %I:%M:%S%p}",
            "elapsed_ns": time.monotonic_ns() - self.started_ns,
            "session": self.session,
            "sequence": self.sequence,
            "event": event,
            **fields,
        }
        self.handler.handle(logging.LogRecord(
            "mqtt_activity", logging.INFO, __file__, 0,
            json.dumps(record, ensure_ascii=True), (), None
        ))

    def on_message(self, client, userdata, message):
        payload = bytes(message.payload)
        try:
            text = payload.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = base64.b64encode(payload).decode("ascii")
            encoding = "base64"
        self.write(
            "message", topic=message.topic, payload=text, payload_encoding=encoding,
            payload_bytes=len(payload), qos=message.qos, retain=bool(message.retain),
            dup=bool(message.dup), mid=message.mid,
        )

    def close(self):
        self.handler.close()


def load_credentials():
    try:
        config = runpy.run_path(str(ROOT / "automation_credentials.py"))
        return tuple(config[name] for name in (
            "MQTT_BROKER", "MQTT_PORT", "MQTT_USER", "MQTT_PASS"
        ))
    except Exception:
        raise RuntimeError("Cannot load MQTT settings from automation_credentials.py") from None


def stop(signum, frame):
    raise KeyboardInterrupt


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from paho.mqtt import client as mqtt_client

    broker, port, username, password = load_credentials()
    recorder = ActivityRecorder(args.output, args.max_bytes, args.backups)
    client_id = f"{socket.gethostname()}_MQTTActivity_{recorder.session[:8]}"
    options = {"client_id": client_id, "clean_session": True}
    if hasattr(mqtt_client, "CallbackAPIVersion"):
        options["callback_api_version"] = mqtt_client.CallbackAPIVersion.VERSION2
    client = mqtt_client.Client(**options)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        recorder.write("connected" if reason_code == 0 else "connection_rejected",
                       reason=str(reason_code))
        if reason_code != 0:
            logging.error("MQTT connection rejected: %s", reason_code)
            return
        result, mid = client.subscribe([(topic, 1) for topic in args.topic])
        if result != mqtt_client.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT subscribe failed: {result}")
        logging.info("Connected; requested filters: %s", args.topic)

    def on_subscribe(client, userdata, mid, reason_codes, properties=None):
        codes = [getattr(reason, "value", reason) for reason in reason_codes]
        recorder.write("subscribed", mid=mid, filters=args.topic, granted_qos=codes)
        if any(code >= 128 for code in codes):
            raise RuntimeError("Broker rejected a subscription; check MQTT ACLs")

    def on_disconnect(client, userdata, *details):
        reason = details[1] if len(details) == 3 else details[0]
        recorder.write("disconnected", reason=str(reason))
        logging.warning("MQTT disconnected: %s", reason)

    def on_connect_fail(client, userdata):
        recorder.write("connection_failed")
        logging.warning("MQTT connection failed; retrying")

    client.username_pw_set(username, password)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_disconnect = on_disconnect
    client.on_connect_fail = on_connect_fail
    client.on_message = recorder.on_message
    signal.signal(signal.SIGTERM, stop)
    try:
        recorder.write("started", client_id=client_id, filters=args.topic)
        logging.info("Recording to %s", args.output)
        client.connect_async(broker, port, keepalive=60)
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        logging.info("Stopping MQTT activity logger")
    finally:
        try:
            client.disconnect()
            recorder.write("stopped")
        finally:
            recorder.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())