#!/usr/bin/env python3
"""Read-only, path-based shortlist of systemd services for manual review."""

import argparse
import csv
import io
import json
from pathlib import PurePosixPath
import re
import subprocess
import sys


VENDOR_PREFIXES = ("/usr/lib/systemd", "/lib/systemd")
CUSTOM_PREFIXES = (
    "/home", "/root", "/opt", "/srv", "/usr/local", "/mnt", "/media",
)
PROPERTIES = (
    "Id", "LoadState", "ActiveState", "SubState", "UnitFileState",
    "FragmentPath", "SourcePath", "DropInPaths", "WorkingDirectory",
    "ExecStart", "MainPID", "User",
)


def systemctl(arguments, user=False):
    command = ["systemctl"]
    if user:
        command.append("--user")
    result = subprocess.run(
        command + ["--no-pager"] + arguments,
        capture_output=True, text=True, check=True, timeout=30,
    )
    return result.stdout


def under_prefix(path, prefix):
    return PurePosixPath(path).is_relative_to(PurePosixPath(prefix))


def classify(properties, include_vendor=False, exclude_prefixes=()):
    fragment = properties.get("FragmentPath", "")
    if fragment and any(under_prefix(fragment, prefix) for prefix in exclude_prefixes):
        return None

    command = properties.get("ExecStart", "")
    working_directory = properties.get("WorkingDirectory", "").lstrip("-")
    paths = re.findall(r"/[^\s;{}\"']+", command)
    if working_directory.startswith("/"):
        paths.append(working_directory)
    custom_workload = any(
        under_prefix(path, prefix) for path in paths for prefix in CUSTOM_PREFIXES
    )
    vendor = bool(fragment) and any(
        under_prefix(fragment, prefix) for prefix in VENDOR_PREFIXES
    )
    if vendor and not custom_workload and not include_vendor:
        return None

    reasons = []
    if not fragment:
        reasons.append("no unit file path; review")
    elif not vendor:
        reasons.append("non-vendor unit location")
    if custom_workload:
        reasons.append("custom workload path")
    if vendor and include_vendor:
        reasons.append("vendor units requested")

    python_hint = bool(re.search(
        r"(?:^|[/\s=])python(?:\d+(?:\.\d+)*)?(?:\s|;|$)|\.py(?:\s|;|$)",
        command,
    ))
    return {
        "service": properties.get("Id", ""),
        "active": properties.get("ActiveState", ""),
        "substate": properties.get("SubState", ""),
        "enabled": properties.get("UnitFileState", ""),
        "python_hint": "likely" if python_hint else "unknown",
        "pid": properties.get("MainPID", ""),
        "user": properties.get("User", "") or "manager default",
        "unit_path": fragment,
        "source_path": properties.get("SourcePath", ""),
        "drop_ins": properties.get("DropInPaths", ""),
        "working_directory": properties.get("WorkingDirectory", ""),
        "exec_start": command,
        "reason": "; ".join(reasons),
    }


def collect(args):
    installed = json.loads(systemctl(
        ["list-unit-files", "--type=service", "--output=json"], args.user,
    ))
    loaded = json.loads(systemctl(
        ["list-units", "--type=service", "--all", "--output=json"], args.user,
    ))
    names = {row["unit_file"] for row in installed}
    names.update(row["unit"] for row in loaded)
    candidates = []
    errors = 0
    for name in sorted(names):
        if name.endswith("@.service"):
            continue
        try:
            output = systemctl(
                ["show", name, "--property=" + ",".join(PROPERTIES)], args.user,
            )
            properties = dict(
                line.split("=", 1) for line in output.splitlines() if "=" in line
            )
            if properties.get("LoadState") == "not-found":
                print("Warning: unit disappeared: " + name, file=sys.stderr)
                errors += 1
                continue
            if args.running_only and properties.get("SubState") != "running":
                continue
            candidate = classify(properties, args.include_vendor, args.exclude_prefix)
            if candidate is not None:
                candidates.append(candidate)
        except (subprocess.SubprocessError, OSError) as error:
            print("Warning: could not inspect {}: {}".format(name, error), file=sys.stderr)
            errors += 1
    return candidates, errors


def render(candidates, output_format):
    if output_format == "json":
        return json.dumps(candidates, indent=2) + "\n"
    if output_format == "csv":
        stream = io.StringIO(newline="")
        fields = list(classify({}).keys())
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(candidates)
        return stream.getvalue()
    blocks = []
    for candidate in candidates:
        blocks.append("\n".join(
            "{}: {}".format(key, value) for key, value in candidate.items()
        ))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--running-only", action="store_true", help="Only running services")
    parser.add_argument("--user", action="store_true", help="Inspect the current user's manager")
    parser.add_argument("--include-vendor", action="store_true", help="Do not hide distro units")
    parser.add_argument(
        "--exclude-prefix", action="append", default=[], metavar="/PATH",
        help="Exclude units whose unit-file path is under /PATH (repeatable)",
    )
    parser.add_argument("--format", choices=("text", "csv", "json"), default="text")
    args = parser.parse_args()
    if any(not prefix.startswith("/") for prefix in args.exclude_prefix):
        parser.error("--exclude-prefix requires an absolute Linux path")
    try:
        candidates, errors = collect(args)
    except (subprocess.SubprocessError, OSError, ValueError, KeyError) as error:
        print("Unable to list services: {}".format(error), file=sys.stderr)
        return 1
    sys.stdout.write(render(candidates, args.format))
    print("{} candidate services; {} inspection errors.".format(
        len(candidates), errors,
    ), file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())