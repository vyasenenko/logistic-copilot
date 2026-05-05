#!/usr/bin/env python3
"""Emit Makefile assignments from a dotenv file for k8s Docker builds.

Only whitelisted keys are emitted (Make conditional assignment KEY ?= value).
Does not print anything if the env file is missing.

Usage: python3 scripts/k8s_build_env_from_dotenv.py [path/to/.env]
Default path: repo-root/.env (parent of scripts/).
"""
from __future__ import annotations

import pathlib
import sys

# Keys used by Makefile k8s image build / tags (extend as needed).
KEYS = frozenset({
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_TURNSTILE_SITE_KEY",
    "NEXT_PUBLIC_TURNSTILE_THEME",
    "NEXT_PUBLIC_TURNSTILE_LANGUAGE",
    "NEXT_PUBLIC_TURNSTILE_SIZE",
    "TAG",
    "PLATFORM",
    "DOCKER_REGISTRY",
})


def default_env_path() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent / ".env"


def parse_line(raw: str) -> tuple[str, str] | None:
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].strip()
    if "=" not in line:
        return None
    key, _, rest = line.partition("=")
    key = key.strip()
    if not key or not key.replace("_", "").isalnum():
        return None
    val = rest.strip().rstrip("\r")
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        val = val[1:-1]
    return key, val


def parse_dotenv(path: pathlib.Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parsed = parse_line(raw)
        if parsed is None:
            continue
        k, v = parsed
        if k in KEYS:
            out[k] = v
    return out


def make_escape(value: str) -> str:
    return value.replace("$", "$$")


def main() -> int:
    env_path = pathlib.Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else default_env_path()
    env_path = env_path.resolve()
    vals = parse_dotenv(env_path)
    for key in sorted(vals.keys()):
        print(f"{key} ?= {make_escape(vals[key])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
