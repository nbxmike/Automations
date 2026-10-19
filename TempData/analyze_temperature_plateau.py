#!/usr/bin/env python3
"""Estimate each Zigbee temperature sensor's offset from a known phase-change plateau.

This script is designed to be run twice for a two-point calibration:

1. Water/ice at 0.0 C to estimate the sensor's offset and drift near the lower end.
2. Lauric acid at about 43.8 C to 44.0 C to estimate the sensor's offset at the
   upper end of the calibration range.

The basic method is the same for either material: detect the time interval where
the sample remains near the known phase-change temperature while latent heat is
absorbed or released. For a correctly calibrated sensor, the plateau should sit at
that physical reference value. The sensor's offset is estimated from the mean
reading over the plateau window.

Usage examples:
    python3 TempData/analyze_temperature_plateau.py --csv TempData/temperature_log.csv --target-temp 0.0
    python3 TempData/analyze_temperature_plateau.py --csv TempData/temperature_log.csv --target-temp 44.0 --tolerance 0.25 --min-seconds 180
"""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass
class PlateauResult:
    device: str
    target_temp_c: float
    plateau_start: datetime
    plateau_end: datetime
    samples: int
    mean_temp_c: float
    min_temp_c: float
    max_temp_c: float
    stdev_c: float
    offset_c: float
    zero_offset_c: float


def parse_timestamp(date_value: str, time_value: str) -> datetime:
    return datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M:%S")


def load_sensor_data(csv_path: Path):
    by_device = defaultdict(list)

    with csv_path.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError(f"CSV file {csv_path} is missing a header row")

        required = {"date", "time", "device", "temperature_c"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV file {csv_path} is missing required columns: {sorted(missing)}")

        for row in reader:
            device = (row.get("device") or "").strip()
            if not device:
                continue
            try:
                temp = float(row.get("temperature_c", "nan"))
            except ValueError:
                continue
            if temp != temp:
                continue
            try:
                timestamp = parse_timestamp(row["date"], row["time"])
            except ValueError:
                continue
            by_device[device].append((timestamp, temp))

    for device, entries in by_device.items():
        entries.sort(key=lambda item: item[0])

    return by_device


def contiguous_segments(values: Iterable[float], tolerance: float, target_temp_c: float = 0.0):
    """Yield contiguous runs near a known phase-change reference temperature."""
    start = None
    previous_index = None
    values_list = list(values)

    for index, value in enumerate(values_list):
        near_target = abs(value - target_temp_c) <= tolerance
        if near_target:
            if start is None:
                start = index
            previous_index = index
        elif start is not None:
            yield start, previous_index + 1
            start = None
            previous_index = None

    if start is not None:
        yield start, previous_index + 1


def find_plateau(device_entries, tolerance_c: float, min_seconds: float, target_temp_c: float = 0.0):
    if not device_entries:
        return None

    times = [stamp for stamp, _ in device_entries]
    temps = [temp for _, temp in device_entries]
    best = None

    for start_idx, end_idx in contiguous_segments(temps, tolerance_c, target_temp_c=target_temp_c):
        segment_times = times[start_idx:end_idx]
        segment_vals = temps[start_idx:end_idx]
        duration_seconds = (segment_times[-1] - segment_times[0]).total_seconds()

        if duration_seconds < min_seconds:
            continue

        mean_temp = statistics.fmean(segment_vals)
        stdev = statistics.pstdev(segment_vals) if len(segment_vals) > 1 else 0.0
        offset_c = mean_temp - target_temp_c
        candidate = {
            "start": segment_times[0],
            "end": segment_times[-1],
            "samples": len(segment_vals),
            "mean_temp": mean_temp,
            "min_temp": min(segment_vals),
            "max_temp": max(segment_vals),
            "stdev": stdev,
            "offset": offset_c,
        }

        if best is None or candidate["samples"] > best["samples"]:
            best = candidate

    if best is None:
        return None

    return PlateauResult(
        device="",
        target_temp_c=target_temp_c,
        plateau_start=best["start"],
        plateau_end=best["end"],
        samples=best["samples"],
        mean_temp_c=best["mean_temp"],
        min_temp_c=best["min_temp"],
        max_temp_c=best["max_temp"],
        stdev_c=best["stdev"],
        offset_c=best["offset"],
        zero_offset_c=best["offset"],
    )


def summarize(device_data, tolerance_c: float, min_seconds: float, target_temp_c: float = 0.0):
    results = []
    for device, entries in sorted(device_data.items()):
        result = find_plateau(
            entries,
            tolerance_c=tolerance_c,
            min_seconds=min_seconds,
            target_temp_c=target_temp_c,
        )
        if result is None:
            print(f"{device}: no plateau near {target_temp_c} C found within tolerance {tolerance_c} C")
            continue
        result.device = device
        results.append(result)
    return results


def print_results(results):
    if not results:
        print("No plateau results found.")
        return

    print(
        "device,target_temp_c,offset_c,plateau_start,plateau_end,samples,"
        "mean_temp_c,min_temp_c,max_temp_c,stdev_c"
    )
    for result in results:
        print(
            f"{result.device},{result.target_temp_c:.4f},{result.offset_c:.4f},"
            f"{result.plateau_start.isoformat(sep=' ')},"
            f"{result.plateau_end.isoformat(sep=' ')},{result.samples},{result.mean_temp_c:.4f},"
            f"{result.min_temp_c:.4f},{result.max_temp_c:.4f},{result.stdev_c:.4f}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Find a known phase-change plateau and estimate each sensor's offset from that reference temperature."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).resolve().parent / "temperature_log.csv",
        help="Path to the sensor CSV file",
    )
    parser.add_argument(
        "--target-temp",
        type=float,
        default=0.0,
        help="Reference phase-change temperature in C (for example 0.0 for water/ice or 44.0 for lauric acid)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.25,
        help="Temperature band around the target phase-change temperature to treat as plateau (default: 0.25 C)",
    )
    parser.add_argument(
        "--min-seconds",
        type=float,
        default=180.0,
        help="Minimum plateau duration to consider valid (default: 180 seconds)",
    )
    args = parser.parse_args()

    csv_path = args.csv.resolve()
    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")

    data = load_sensor_data(csv_path)
    if not data:
        raise SystemExit(f"No sensor data found in {csv_path}")

    results = summarize(data, args.tolerance, args.min_seconds, target_temp_c=args.target_temp)
    print_results(results)


if __name__ == "__main__":
    main()
