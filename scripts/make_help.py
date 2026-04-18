#!/usr/bin/env python3
"""Render grouped, colored `make help` for CopilotRunner (reads Makefile)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

# --- ANSI --------------------------------------------------------------------
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
WHITE = "\033[37m"

# Section title, list of target names (order preserved)
SECTIONS: list[tuple[str, list[str]]] = [
    (
        "Окружение",
        ["doctor", "env-check"],
    ),
    (
        "Зависимости на хосте (без Docker)",
        ["install", "install-backend", "install-frontend", "install-mobile"],
    ),
    (
        "Docker — образы",
        ["build", "build-nc", "pull"],
    ),
    (
        "Docker — запуск, остановка, перезапуск",
        ["up", "up-d", "down", "stop", "restart", "restart-%", "rebuild", "destroy"],
    ),
    (
        "Логи и проверки здоровья",
        ["ps", "status", "logs", "logs-json", "logs-%", "curl-health"],
    ),
    (
        "Контейнеры: shell и БД",
        ["shell-backend", "shell-frontend", "psql"],
    ),
    (
        "Тесты, линт, формат",
        ["test", "test-backend", "lint", "lint-backend", "lint-frontend", "lint-mobile", "format", "format-backend", "ci"],
    ),
    (
        "Очистка",
        ["clean", "clean-docker"],
    ),
    (
        "Справка",
        ["help"],
    ),
]


def parse_makefile(makefile: Path) -> dict[str, str]:
    """Map target name -> description from `target: ... ## text` lines."""
    text = makefile.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    line_re = re.compile(r"^([a-zA-Z0-9_.%-]+):\s*.*?##\s*(.+)$")
    for line in text.splitlines():
        m = line_re.match(line.strip())
        if m:
            name, desc = m.group(1), m.group(2).strip()
            out.setdefault(name, desc)
    return out


def print_header() -> None:
    title = "CopilotRunner"
    subtitle = "make <цель>   ·   подсказка: make help   ·   подробные команды: V=1 make up"
    bar = "═" * 62
    print()
    print(f"  {DIM}{bar}{RESET}")
    print(f"  {BOLD}{CYAN}{title}{RESET}")
    print(f"  {DIM}{subtitle}{RESET}")
    print(f"  {DIM}{bar}{RESET}")
    print()


def print_section(title: str, rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    print(f"  {BOLD}{WHITE}{title}{RESET}")
    print(f"  {DIM}{'─' * (len(title) + 2)}{RESET}")
    colw = 22
    for name, desc in rows:
        pad = max(0, colw - len(name))
        line = f"    {GREEN}{name}{RESET}{' ' * pad} {desc}"
        print(line)
    print()


def print_footer() -> None:
    print(f"  {DIM}Переменные make:{RESET}")
    print(f"    {CYAN}LOG_TAIL{RESET}      сколько строк в хвосте для {DIM}logs{RESET} / {DIM}logs-*{RESET} (по умолчанию 200)")
    print(f"    {CYAN}CONFIRM=YES{RESET}  без вопроса для {DIM}destroy{RESET} (удаление volumes)")
    print(f"    {CYAN}ARGS='-v'{RESET}    доп. аргументы pytest в {DIM}test-backend{RESET}")
    print(f"    {CYAN}PYTHON=…{RESET}    интерпретатор (если есть — {DIM}backend/.venv/bin/python{RESET})")
    print(f"    {CYAN}COMPOSE=…{RESET}    команда compose, если не {DIM}docker compose{RESET}")
    print(f"    {CYAN}V=1{RESET}          показывать команды shell в рецептах")
    print()


def main() -> int:
    makefile = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "Makefile"
    if not makefile.is_file():
        print(f"Makefile not found: {makefile}", file=sys.stderr)
        return 1

    desc = parse_makefile(makefile)
    print_header()

    used: set[str] = set()
    for section_title, names in SECTIONS:
        rows: list[tuple[str, str]] = []
        for n in names:
            if n not in desc:
                continue
            rows.append((n, desc[n]))
            used.add(n)
        print_section(section_title, rows)

    # Any target with ## not placed in SECTIONS
    rest = sorted(set(desc) - used)
    if rest:
        rows = [(n, desc[n]) for n in rest]
        print_section("Прочее", rows)

    print_footer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
