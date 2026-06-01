#!/usr/bin/env python3
"""
Set one environment variable in a dotenv file or Kubernetes ConfigMap/Secret YAML.

Designed for agent-safe updates:
- never prints the value;
- creates a timestamped backup before modifying an existing file;
- updates only the requested key.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

_ENV_LINE = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*)(?P<value>.*)$"
)
_YAML_KEY_LINE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.*)$"
)


def default_backup_dir(path: Path) -> Path:
    return Path.cwd() / ".env-backups"


def backup_path_for(path: Path, backup_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_parent = str(path.resolve().parent).strip("/").replace("/", "__") or "root"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir / f"{safe_parent}__{path.name}.backup-{stamp}"


def validate_key(key: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        raise SystemExit(f"Invalid env key: {key!r}")
    return key


def read_value(args: argparse.Namespace) -> str:
    sources = [
        args.value is not None,
        args.value_env is not None,
        args.value_file is not None,
        args.value_stdin,
    ]
    if sum(sources) != 1:
        raise SystemExit("Pass exactly one of --value, --value-env, --value-file, or --value-stdin.")
    if args.value is not None:
        return args.value
    if args.value_env is not None:
        if args.value_env not in os.environ:
            raise SystemExit(f"Environment variable {args.value_env} is not set.")
        return os.environ[args.value_env]
    if args.value_file is not None:
        return args.value_file.read_text(encoding="utf-8", errors="replace").rstrip("\n")
    return sys.stdin.read().rstrip("\n")


def quote_yaml_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def set_dotenv(path: Path, key: str, value: str, create: bool) -> str:
    if not path.exists():
        if not create:
            raise SystemExit(f"Target file not found: {path}")
        path.write_text("", encoding="utf-8")

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    changed = False
    found = False
    out: list[str] = []

    for line in lines:
        match = _ENV_LINE.match(line)
        if match and match.group("key") == key:
            out.append(match.group("prefix") + value)
            found = True
            changed = True
        else:
            out.append(line)

    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={value}")
        changed = True

    if changed:
        path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return "updated" if found else "added"


def set_k8s_yaml(path: Path, key: str, value: str, section: str) -> str:
    if not path.exists():
        raise SystemExit(f"Target file not found: {path}")

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    in_section = False
    section_indent: int | None = None
    insert_at: int | None = None
    child_indent = "  "
    found = False
    out: list[str] = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if re.match(rf"^{re.escape(section)}:\s*$", stripped):
            in_section = True
            section_indent = indent
            insert_at = len(out) + 1
            child_indent = " " * (indent + 2)
            out.append(line)
            continue

        if in_section and section_indent is not None and stripped and indent <= section_indent:
            in_section = False

        if in_section:
            match = _YAML_KEY_LINE.match(line)
            if match and match.group("key") == key:
                out.append(f"{match.group('indent')}{key}: {quote_yaml_value(value)}")
                found = True
                continue
            if stripped and not stripped.startswith("#"):
                insert_at = len(out) + 1

        out.append(line)

    if section_indent is None:
        out.append(f"{section}:")
        out.append(f"  {key}: {quote_yaml_value(value)}")
        action = "added"
    elif not found:
        target = insert_at if insert_at is not None else len(out)
        out.insert(target, f"{child_indent}{key}: {quote_yaml_value(value)}")
        action = "added"
    else:
        action = "updated"

    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return action


def main() -> int:
    parser = argparse.ArgumentParser(description="Set one env key without printing its value.")
    parser.add_argument("--file", type=Path, required=True, help="Target .env or Kubernetes YAML file.")
    parser.add_argument("--key", required=True, help="Environment variable name.")
    parser.add_argument("--value", default=None, help="Value to write. Not printed back.")
    parser.add_argument("--value-env", default=None, help="Read value from this process environment variable.")
    parser.add_argument("--value-file", type=Path, default=None, help="Read value from a local file.")
    parser.add_argument("--value-stdin", action="store_true", help="Read value from stdin.")
    parser.add_argument("--format", choices=("dotenv", "k8s-yaml"), default="dotenv")
    parser.add_argument("--yaml-section", choices=("data", "stringData"), default="data")
    parser.add_argument("--create", action="store_true", help="Create dotenv target if missing.")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup creation.")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Directory for backups (default: .env-backups in current working directory).",
    )
    args = parser.parse_args()

    key = validate_key(args.key)
    value = read_value(args)
    target: Path = args.file

    backup_path: Path | None = None
    if target.exists() and not args.no_backup:
        backup_dir = args.backup_dir or default_backup_dir(target)
        backup_path = backup_path_for(target, backup_dir)
        shutil.copy2(target, backup_path)

    if args.format == "dotenv":
        action = set_dotenv(target, key, value, create=args.create)
    else:
        action = set_k8s_yaml(target, key, value, section=args.yaml_section)

    print(f"Target: {target}")
    print(f"Key:    {key}")
    print(f"Action: {action}")
    if backup_path:
        print(f"Backup: {backup_path}")
    print("Value:  <redacted>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
