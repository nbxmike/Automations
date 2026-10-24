#!/usr/bin/env python3
"""Poll a diyHue Hue v1 API and append device inventories and changes to text."""

from __future__ import annotations

import argparse
import json
import math
import runpy
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


CREDENTIALS_PATH = Path(__file__).resolve().parents[1] / "automation_credentials.py"


class HueError(Exception):
    """An API request failed or returned an invalid Hue response."""


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def request_json(url: str, timeout: float, insecure: bool, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise HueError(f"HTTP {exc.code}: check the server address and API key") from None
    except (URLError, OSError, ValueError) as exc:
        raise HueError(f"Request failed ({type(exc).__name__}); check connectivity, TLS, and JSON response") from None
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and isinstance(item.get("error"), dict):
                error_type = item["error"].get("type", "unknown")
                hint = {
                    1: "unauthorized: register a valid DIYHUE_API_KEY in automation_credentials.py",
                    101: "link button not pressed: enable linking in diyHue and retry --register",
                }.get(error_type, "check the diyHue server logs")
                raise HueError(f"Hue API error {error_type}: {hint}")
    return result


def redact(value):
    if isinstance(value, dict):
        sensitive = {
            "whitelist", "username", "password", "clientkey", "client_key",
            "apikey", "api_key", "token", "access_token", "refresh_token",
        }
        return {
            key: "[REDACTED]" if key.lower() in sensitive else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def changes(previous, current, path="") -> list[str]:
    differences = []
    if isinstance(previous, dict) and isinstance(current, dict):
        for key in sorted(previous.keys() | current.keys()):
            child_path = f"{path}/{key}"
            if key not in previous:
                differences.append(f"ADDED {child_path}: {json.dumps(current[key], sort_keys=True)}")
            elif key not in current:
                differences.append(f"REMOVED {child_path}: {json.dumps(previous[key], sort_keys=True)}")
            else:
                differences.extend(changes(previous[key], current[key], child_path))
    elif previous != current:
        differences.append(
            f"CHANGED {path}: {json.dumps(previous, sort_keys=True)} -> "
            f"{json.dumps(current, sort_keys=True)}"
        )
    return differences


def write_snapshot(report, snapshot: dict, previous, server: str) -> None:
    report.write(f"\n{'=' * 72}\n{timestamp()} | {server}\n")
    report.write("INITIAL INVENTORY\n" if previous is None else "ATTRIBUTE CHANGES\n")
    if previous is not None:
        for difference in changes(previous, snapshot):
            report.write(difference + "\n")
    report.write("\nRESOURCE INDEX\n")
    for category, resources in sorted(snapshot.items()):
        if not isinstance(resources, dict) or category == "config":
            continue
        report.write(f"{category}: {len(resources)}\n")
        for resource_id, resource in sorted(resources.items()):
            if isinstance(resource, dict):
                report.write(
                    f"  {resource_id}: {resource.get('name', '(unnamed)')}"
                    f" | type={resource.get('type', '(unspecified)')}\n"
                )
    report.write("\nFULL HUE V1 ATTRIBUTES (known credential fields redacted)\n")
    report.write(json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
    report.flush()


def positive_number(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive finite number") from None
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://172.24.32.102", help="diyHue base URL or IP")
    parser.add_argument("--interval", type=positive_number, default=5.0, help="poll interval in seconds (default: 5)")
    parser.add_argument("--timeout", type=positive_number, default=10.0, help="request timeout in seconds (default: 10)")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("diyhue_devices.txt"))
    parser.add_argument("--once", action="store_true", help="write one inventory and exit")
    parser.add_argument("--register", action="store_true", help="register and save a key using diyhue_register.py")
    parser.add_argument("--insecure", action="store_true", help="disable HTTPS certificate verification (trusted LAN only)")
    args = parser.parse_args(argv)
    args.server = normalize_server(args.server, parser)
    return args


def normalize_server(server: str, parser: argparse.ArgumentParser) -> str:
    server = server.strip()
    if "://" not in server:
        server = "http://" + server
    address = urlsplit(server)
    if (
        address.scheme not in {"http", "https"} or not address.hostname
        or address.username is not None or address.password is not None
        or address.path not in {"", "/"} or address.query or address.fragment
    ):
        parser.error("--server must be an HTTP(S) base URL without credentials, path, query, or fragment")
    return server.rstrip("/")


def load_api_key(path: Path = CREDENTIALS_PATH) -> str:
    try:
        credentials = runpy.run_path(str(path))
    except Exception:
        raise HueError("Cannot load automation_credentials.py; check its existence, permissions, and Python syntax") from None
    api_key = credentials.get("DIYHUE_API_KEY")
    if not isinstance(api_key, str) or not api_key.strip():
        raise HueError(
            "No DIYHUE_API_KEY in automation_credentials.py. Enable linking in diyHue, "
            "then run Tools/diyhue_register.py."
        )
    return api_key.strip()


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.register:
        from diyhue_register import main as register_main

        register_args = ["--server", args.server, "--timeout", str(args.timeout)]
        if args.insecure:
            register_args.append("--insecure")
        return register_main(register_args)
    if args.insecure:
        print("Warning: HTTPS certificate verification is disabled.", file=sys.stderr)
    try:
        api_key = load_api_key()
    except HueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    endpoint = args.server + "/api/" + quote(api_key, safe="")
    previous = None
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("a", encoding="utf-8") as report:
            report.write(f"\nMONITOR STARTED {timestamp()} | {args.server}\n")
            report.write("Read-only Hue v1 polling; cannot identify command sender or capture changes between polls.\n")
            report.flush()
            print(f"Monitoring {args.server}; report: {args.output.resolve()}", flush=True)
            while True:
                try:
                    snapshot = request_json(endpoint, args.timeout, args.insecure)
                    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("lights"), dict):
                        raise HueError("Expected a Hue v1 inventory object containing 'lights'")
                    snapshot = redact(snapshot)
                except HueError as exc:
                    message = f"{timestamp()} | ERROR: {exc}"
                    report.write(message + "\n")
                    report.flush()
                    print(message, file=sys.stderr, flush=True)
                    if args.once:
                        return 1
                else:
                    if previous is None or snapshot != previous:
                        write_snapshot(report, snapshot, previous, args.server)
                        print(f"{timestamp()} | Inventory written ({len(snapshot['lights'])} lights)", flush=True)
                        previous = snapshot
                    if args.once:
                        return 0
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
        return 0
    except OSError as exc:
        print(f"Cannot write report: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())