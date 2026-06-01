#!/usr/bin/env python3
"""Render grouped, readable `make help` output for Logistic Copilot."""

from __future__ import annotations

import re
import sys
from pathlib import Path

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
WHITE = "\033[37m"

SECTIONS: list[tuple[str, list[str]]] = [
    ("Environment", ["doctor", "env-init", "env-check", "env-set"]),
    ("Install", ["install", "install-backend", "install-frontend"]),
    ("Docker Build", ["build", "build-nc", "pull"]),
    ("Docker Lifecycle", ["up", "up-d", "down", "stop", "restart", "restart-%", "rebuild", "destroy"]),
    ("Observability", ["ps", "status", "logs", "logs-json", "logs-%", "curl-health"]),
    ("Shells And Database", ["shell-backend", "shell-frontend", "psql"]),
    (
        "Quality",
        ["test", "test-backend", "lint", "lint-backend", "lint-frontend", "format", "format-backend", "ci"],
    ),
    ("Cleanup", ["clean", "clean-docker"]),
    (
        "Kubernetes",
        [
            "k8s-vars",
            "k8s-context",
            "k8s-buildx-backend",
            "k8s-buildx-frontend",
            "k8s-buildx-all",
            "k8s-release",
            "k8s-apply-namespace",
            "k8s-apply-secrets",
            "k8s-apply-config",
            "k8s-apply-databases",
            "k8s-apply-app",
            "k8s-apply-ingress",
            "k8s-apply-letsencrypt-issuer",
            "k8s-apply-base",
            "k8s-apply-full",
            "k8s-apply-dry-run",
            "k8s-secret-from-env",
            "k8s-rollout-restart",
            "k8s-rollout-restart-backend",
            "k8s-rollout-restart-frontend",
            "k8s-status",
            "k8s-get",
            "k8s-logs-backend",
            "k8s-logs-frontend",
            "k8s-describe-backend",
            "k8s-events",
            "k8s-certificates",
            "k8s-port-forward-backend",
            "k8s-do-kubeconfig",
            "k8s-helm-cert-manager",
            "k8s-helm-ingress-nginx",
            "k8s-bootstrap-infra",
            "k8s-ship-images",
            "k8s-deploy",
            "k8s-deploy-base",
        ],
    ),
    ("Help", ["help"]),
]


def parse_makefile(makefile: Path) -> dict[str, str]:
    text = makefile.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    line_re = re.compile(r"^([a-zA-Z0-9_.%+-]+):\s*.*?##\s*(.+)$")
    for line in text.splitlines():
        match = line_re.match(line.strip())
        if match:
            out.setdefault(match.group(1), match.group(2).strip())
    return out


def print_header() -> None:
    bar = "═" * 72
    print()
    print(f"  {DIM}{bar}{RESET}")
    print(f"  {BOLD}{CYAN}Logistic Copilot Developer Console{RESET}")
    print(f"  {DIM}make <target>  |  V=1 make <target> to show shell commands{RESET}")
    print(f"  {DIM}{bar}{RESET}")
    print()
    print(f"  {BOLD}{YELLOW}Recommended handoff flow{RESET}")
    print(f"    {GREEN}make env-init{RESET}       create .env from the documented template")
    print(f"    {GREEN}make env-check{RESET}      validate required, optional, secret, and placeholder values")
    print(f"    {GREEN}make env-set{RESET}        safely set one value without printing it back")
    print(f"    {GREEN}make up-d{RESET}           start the local stack")
    print()


def print_section(title: str, rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    print(f"  {BOLD}{WHITE}{title}{RESET}")
    print(f"  {DIM}{'─' * (len(title) + 2)}{RESET}")
    width = max(22, max(len(name) for name, _ in rows) + 2)
    for name, desc in rows:
        print(f"    {GREEN}{name}{RESET}{' ' * max(1, width - len(name))}{desc}")
    print()


def print_footer() -> None:
    print(f"  {BOLD}{WHITE}Useful variables{RESET}")
    print(f"    {CYAN}KEY=... VALUE=...{RESET}    for {DIM}make env-set{RESET}")
    print(f"    {CYAN}LOG_TAIL=500{RESET}         number of log lines for {DIM}logs{RESET} / {DIM}logs-*{RESET}")
    print(f"    {CYAN}ARGS='-v -k name'{RESET}    extra pytest arguments for {DIM}test-backend{RESET}")
    print(f"    {CYAN}CONFIRM=YES{RESET}          skip confirmation for {DIM}destroy{RESET}")
    print(f"    {CYAN}PYTHON=...{RESET}           Python interpreter override")
    print(f"    {CYAN}COMPOSE=...{RESET}          Docker Compose command override")
    print(f"    {CYAN}TAG / PLATFORM / K8S_NS{RESET} see {DIM}make k8s-vars{RESET}")
    print()


def main() -> int:
    makefile = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "Makefile"
    if not makefile.is_file():
        print(f"Makefile not found: {makefile}", file=sys.stderr)
        return 1

    descriptions = parse_makefile(makefile)
    print_header()

    used: set[str] = set()
    for section_title, names in SECTIONS:
        rows = [(name, descriptions[name]) for name in names if name in descriptions]
        used.update(name for name, _ in rows)
        print_section(section_title, rows)

    rest = sorted(set(descriptions) - used)
    if rest:
        print_section("Other", [(name, descriptions[name]) for name in rest])

    print_footer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
