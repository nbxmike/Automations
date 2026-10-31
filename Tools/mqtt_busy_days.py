#!/usr/bin/env python3
"""Keep the busiest MQTT daily log for each weekday; preserve winners on ties."""

import argparse
from datetime import date
import json
import logging
from pathlib import Path
import shutil
import tempfile


DEFAULT_INPUT = Path(__file__).resolve().parent / "logs" / "mqtt_activity.jsonl"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def daily_date(path, base):
    prefix = base.stem + "."
    if not path.name.startswith(prefix):
        return None
    text = path.name[len(prefix):]
    if base.suffix:
        if not text.endswith(base.suffix):
            return None
        text = text[:-len(base.suffix)]
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if text == parsed.isoformat() else None


def message_count(path):
    count = 0
    with path.open(encoding="utf-8") as report:
        for line_number, line in enumerate(report, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                raise ValueError(f"{path}: invalid JSON on line {line_number}") from None
            if not isinstance(record, dict):
                raise ValueError(f"{path}: non-object record on line {line_number}")
            if record.get("event") == "message":
                if not isinstance(record.get("topic"), str) or not record["topic"]:
                    raise ValueError(f"{path}: missing topic on line {line_number}")
                count += 1
    return count


def replace_if_busier(source, target, saved_count):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".busyday-", delete=False) as report:
            temporary = Path(report.name)
        shutil.copyfile(source, temporary)
        copied_count = message_count(temporary)
        if saved_count is not None and copied_count <= saved_count:
            return saved_count
        temporary.replace(target)
        logging.info("Saved %s from %s: %d messages (previous: %s)",
                     target.name, source.name, copied_count, saved_count)
        return copied_count
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def select_busy_days(base, destination):
    if not base.parent.is_dir():
        raise FileNotFoundError(f"Log directory does not exist: {base.parent}")
    if destination.resolve() == base.parent.resolve():
        raise ValueError("Destination must be separate from the daily log directory")
    destination.mkdir(parents=True, exist_ok=True)
    counts = {}
    blocked = set()
    errors = 0
    for weekday in WEEKDAYS:
        target = destination / f"{weekday}.jsonl"
        try:
            counts[weekday] = message_count(target) if target.exists() else None
        except (OSError, ValueError) as exc:
            logging.error("Cannot compare saved %s; leaving it untouched: %s", weekday, exc)
            blocked.add(weekday)
            errors += 1
    for source in sorted(base.parent.iterdir()):
        log_date = daily_date(source, base)
        if not source.is_file() or log_date is None:
            continue
        weekday = WEEKDAYS[log_date.weekday()]
        if weekday in blocked:
            continue
        target = destination / f"{weekday}.jsonl"
        try:
            count = message_count(source)
            saved_count = counts[weekday]
            if saved_count is None or count > saved_count:
                counts[weekday] = replace_if_busier(source, target, saved_count)
            else:
                logging.info("Kept %s: %d messages; %s has %d", target.name,
                             saved_count, source.name, count)
        except (OSError, ValueError) as exc:
            logging.error("Skipped %s: %s", source.name, exc)
            errors += 1
    return 1 if errors else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-base", type=Path, default=DEFAULT_INPUT,
                        help="logger's output base filename (not a dated daily file)")
    parser.add_argument("--output-dir", type=Path,
                        help="destination (default: busydays inside the log directory)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    destination = args.output_dir or args.input_base.parent / "busydays"
    try:
        return select_busy_days(args.input_base, destination)
    except (OSError, ValueError) as exc:
        logging.error("Cannot select busy days: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())