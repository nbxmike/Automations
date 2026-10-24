#!/usr/bin/env python3
"""Register a diyHue API user and save its key in automation_credentials.py."""

from __future__ import annotations

import argparse
import ast
import os
import stat
import sys
import tempfile
from pathlib import Path

from diyhue_monitor import CREDENTIALS_PATH, HueError, normalize_server, positive_number, request_json


def save_api_key(api_key: str, path: Path = CREDENTIALS_PATH) -> None:
    source = path.read_text(encoding="utf-8") if path.exists() else ""
    tree = ast.parse(source)
    assignments = []
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == "DIYHUE_API_KEY" for target in targets):
            if len(targets) != 1 or any(
                other is not node and other.lineno <= node.end_lineno and other.end_lineno >= node.lineno
                for other in tree.body
            ):
                raise ValueError("DIYHUE_API_KEY must be a standalone assignment")
            assignments.append(node)
    if len(assignments) > 1:
        raise ValueError("Multiple DIYHUE_API_KEY assignments; keep only one before registering")
    assignment = f"DIYHUE_API_KEY = {api_key!r}\n"
    if assignments:
        node = assignments[0]
        lines = source.splitlines(keepends=True)
        lines[node.lineno - 1:node.end_lineno] = [assignment]
        updated = "".join(lines)
    else:
        updated = source + ("\n" if source and not source.endswith("\n") else "") + "\n" + assignment
    ast.parse(updated)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(updated)
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://172.24.32.102", help="diyHue base URL or IP")
    parser.add_argument("--timeout", type=positive_number, default=10.0, help="request timeout in seconds")
    parser.add_argument("--insecure", action="store_true", help="disable HTTPS certificate verification (trusted LAN only)")
    args = parser.parse_args(argv)
    args.server = normalize_server(args.server, parser)
    if args.insecure:
        print("Warning: HTTPS certificate verification is disabled.", file=sys.stderr)
    try:
        result = request_json(
            args.server + "/api", args.timeout, args.insecure,
            {"devicetype": "automation_debug#diyhue_monitor"},
        )
        if not isinstance(result, list) or not result or not isinstance(result[0], dict):
            raise HueError("Unexpected registration response")
        success = result[0].get("success")
        api_key = success.get("username") if isinstance(success, dict) else None
        if not isinstance(api_key, str) or not api_key.strip():
            raise HueError("Registration returned no API key")
        save_api_key(api_key.strip())
    except HueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, SyntaxError):
        print(
            "Registration or credential save failed. Check linking, network/TLS, "
            "and automation_credentials.py syntax and write permissions. "
            "An API user may have been created on the server even if saving failed.",
            file=sys.stderr,
        )
        return 1
    print(f"API key saved in {CREDENTIALS_PATH}. Existing credentials preserved; key not displayed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())