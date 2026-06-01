#!/usr/bin/env python3
"""Validate a Logistic Copilot env file against an annotated template."""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)\s*$")
YAML_LINE_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.*)\s*$")
META_RE = re.compile(r"^@\s*(?P<key>[a-zA-Z_][a-zA-Z0-9_-]*)\s*:?\s*(?P<value>.*)$")
PRIORITY_RE = re.compile(r"\bP(?P<level>[0-3])\b")

PLACEHOLDER_VALUES = {
    "",
    "changeme",
    "change-me",
    "replace-me",
    "replace_me",
    "changeme_in_production",
    "changeme_generate_a_random_key",
    "sk-...",
    "sk-ant-...",
    "your-key",
    "your-secret",
    "your-token",
}


class Palette:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.reset = "\033[0m" if enabled else ""
        self.bold = "\033[1m" if enabled else ""
        self.dim = "\033[2m" if enabled else ""
        self.red = "\033[31m" if enabled else ""
        self.green = "\033[32m" if enabled else ""
        self.yellow = "\033[33m" if enabled else ""
        self.blue = "\033[34m" if enabled else ""
        self.magenta = "\033[35m" if enabled else ""
        self.cyan = "\033[36m" if enabled else ""

    def paint(self, text: str, *styles: str) -> str:
        if not self.enabled:
            return text
        return "".join(styles) + text + self.reset


@dataclass
class EnvSpec:
    key: str
    default: str = ""
    comments: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    priority: str | None = None

    @property
    def required(self) -> bool:
        return boolish(self.metadata.get("required")) or boolish(self.metadata.get("prod_required"))

    @property
    def allowed_empty(self) -> bool:
        return boolish(self.metadata.get("allowed_empty")) and not boolish(self.metadata.get("required"))

    @property
    def secret(self) -> bool:
        return boolish(self.metadata.get("secret"))

    @property
    def prod_required(self) -> bool:
        return boolish(self.metadata.get("prod_required"))


def boolish(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on", "required"}


def should_use_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never" or os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def strip_value(value: str) -> str:
    value = value.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value


def clean_comment(raw: str) -> str:
    comment = raw.strip()
    if not comment.startswith("#"):
        return ""
    comment = comment[1:].strip()
    if not comment or set(comment) <= {"=", "-", " "}:
        return ""
    return comment


def metadata_from_comment(raw: str) -> tuple[str, str] | None:
    comment = clean_comment(raw)
    if not comment:
        return None
    match = META_RE.match(comment)
    if not match:
        return None
    return match.group("key").strip().lower(), match.group("value").strip() or "true"


def priority_from_comment(raw: str) -> str | None:
    comment = clean_comment(raw)
    if not comment:
        return None
    match = PRIORITY_RE.search(comment)
    return f"P{match.group('level')}" if match else None


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = ENV_LINE_RE.match(raw)
        if match:
            values[match.group("key")] = strip_value(match.group("value"))
    return values


def parse_k8s_yaml(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    in_data = False
    data_indent: int | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        if re.match(r"^(data|stringData):\s*$", stripped):
            in_data = True
            data_indent = indent
            continue
        if in_data and data_indent is not None and stripped and indent <= data_indent:
            in_data = False
        if not in_data:
            continue
        match = YAML_LINE_RE.match(raw)
        if match:
            values[match.group("key")] = strip_value(match.group("value"))
    return values


def parse_values(path: Path) -> dict[str, str]:
    return parse_k8s_yaml(path) if path.suffix.lower() in {".yaml", ".yml"} else parse_dotenv(path)


def parse_template(path: Path) -> dict[str, EnvSpec]:
    specs: dict[str, EnvSpec] = {}
    pending_comments: list[str] = []
    pending_meta: dict[str, str] = {}
    current_priority: str | None = None

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if not stripped:
            pending_comments = []
            pending_meta = {}
            continue
        if stripped.startswith("#"):
            priority = priority_from_comment(raw)
            if priority:
                current_priority = priority
            meta = metadata_from_comment(raw)
            if meta:
                pending_meta[meta[0]] = meta[1]
                continue
            comment = clean_comment(raw)
            if comment:
                pending_comments.append(comment)
            continue
        match = ENV_LINE_RE.match(raw)
        if match:
            key = match.group("key")
            specs[key] = EnvSpec(
                key=key,
                default=strip_value(match.group("value")),
                comments=pending_comments[:],
                metadata=pending_meta.copy(),
                priority=current_priority,
            )
            pending_comments = []
            pending_meta = {}
            continue
        pending_comments = []
        pending_meta = {}
    return specs


def parse_backend_defaults(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        module = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return {}
    settings_class = next((node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Settings"), None)
    if settings_class is None:
        return {}
    defaults: dict[str, str] = {}
    for node in settings_class.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            try:
                defaults[node.target.id.upper()] = ast.unparse(node.value)
            except Exception:
                pass
    return defaults


def is_placeholder(value: str, spec: EnvSpec) -> bool:
    normalized = value.strip().lower()
    if normalized in PLACEHOLDER_VALUES:
        return True
    if spec.prod_required and spec.default and value.strip() == spec.default.strip():
        return True
    return False


def active_provider_keys(values: dict[str, str]) -> list[str]:
    providers = [part.strip().lower() for part in values.get("LLM_PROVIDER_ORDER", "").split(",") if part.strip()]
    provider_key_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    active: list[str] = []
    for provider in providers or list(provider_key_map):
        key = provider_key_map.get(provider)
        if key and values.get(key, "").strip() and not values.get(key, "").strip().lower() in PLACEHOLDER_VALUES:
            active.append(key)
    return active


def custom_policy_errors(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if not active_provider_keys(values):
        errors.append("Set at least one LLM provider key from LLM_PROVIDER_ORDER: DEEPSEEK_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY.")
    if boolish(values.get("AUTH_REQUIRE_TURNSTILE")):
        if not values.get("TURNSTILE_SECRET_KEY", "").strip():
            errors.append("AUTH_REQUIRE_TURNSTILE=true requires TURNSTILE_SECRET_KEY.")
        if not values.get("NEXT_PUBLIC_TURNSTILE_SITE_KEY", "").strip():
            errors.append("AUTH_REQUIRE_TURNSTILE=true requires NEXT_PUBLIC_TURNSTILE_SITE_KEY in the frontend build.")
    if values.get("TMS_BASE_URL", "").strip() and not values.get("TMS_API_KEY", "").strip():
        errors.append("TMS_BASE_URL is set, but TMS_API_KEY is empty.")
    if values.get("RESEND_API_KEY", "").strip() and not values.get("RESEND_FROM_EMAIL", "").strip():
        errors.append("RESEND_API_KEY is set, but RESEND_FROM_EMAIL is empty.")
    return errors


def priority_label(spec: EnvSpec) -> str:
    if spec.priority == "P0":
        return "P0 production critical"
    if spec.priority == "P1":
        return "P1 core workflow"
    if spec.priority == "P2":
        return "P2 feature/integration"
    if spec.priority == "P3":
        return "P3 tuning/local"
    return "unprioritized"


def print_item(title: str, keys: list[str], specs: dict[str, EnvSpec], values: dict[str, str], defaults: dict[str, str], color: str, p: Palette) -> None:
    if not keys:
        return
    print(p.paint(title, color, p.bold))
    for key in keys:
        spec = specs.get(key, EnvSpec(key=key))
        print(f"  {p.paint('-', color)} {p.paint(key, color, p.bold)} {p.paint('[' + priority_label(spec) + ']', p.dim)}")
        badges: list[str] = []
        if spec.required:
            badges.append("required")
        if spec.allowed_empty:
            badges.append("optional")
        if spec.secret:
            badges.append("secret")
        if spec.prod_required:
            badges.append("prod_required")
        if badges:
            print(f"    {p.paint('meta:', p.dim)} {', '.join(badges)}")
        if spec.metadata.get("example"):
            print(f"    {p.paint('example:', p.dim)} {spec.metadata['example']}")
        if key in defaults:
            print(f"    {p.paint('code default:', p.dim)} {defaults[key]}")
        if key in values and values[key].strip() and not spec.secret:
            print(f"    {p.paint('current:', p.dim)} {values[key]}")
        for line in spec.comments[:3]:
            if line.startswith("@") or "====" in line:
                continue
            print(f"    {p.paint(line, p.dim)}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check .env against .env.example.")
    parser.add_argument("--example", type=Path, default=ROOT / ".env.example", help="Template file.")
    parser.add_argument("--env", type=Path, default=ROOT / ".env", help="Target env-like file.")
    parser.add_argument("--show-extra", action="store_true", help="Show keys present in target but not in template.")
    parser.add_argument("--fail-on-extra", action="store_true", help="Fail if target contains keys outside the template.")
    parser.add_argument("--strict", action="store_true", help="Treat optional empty values as warnings but not errors.")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    args = parser.parse_args()

    p = Palette(should_use_color(args.color))
    if not args.example.is_file():
        print(p.paint(f"Template not found: {args.example}", p.red, p.bold), file=sys.stderr)
        return 2
    if not args.env.is_file():
        print(p.paint(f"Target env file not found: {args.env}", p.red, p.bold), file=sys.stderr)
        print(f"Create it with: {p.paint('make env-init', p.cyan, p.bold)}")
        return 2

    specs = parse_template(args.example)
    values = parse_values(args.env)
    defaults = parse_backend_defaults(ROOT / "backend" / "app" / "config.py")

    missing_required = [key for key, spec in specs.items() if key not in values and spec.required]
    missing_optional = [key for key, spec in specs.items() if key not in values and not spec.required]
    required_empty = [
        key
        for key, spec in specs.items()
        if key in values and not values[key].strip() and spec.required and not spec.allowed_empty
    ]
    optional_empty = [
        key
        for key, spec in specs.items()
        if key in values and not values[key].strip() and not (spec.required and not spec.allowed_empty)
    ]
    placeholders = [
        key
        for key, spec in specs.items()
        if key in values and values[key].strip() and spec.required and is_placeholder(values[key], spec)
    ]
    policy_errors = custom_policy_errors(values)
    extra = [key for key in values if key not in specs]

    hard_fail = bool(missing_required or required_empty or placeholders or policy_errors or (args.fail_on_extra and extra))
    status = "READY" if not hard_fail else "NEEDS ATTENTION"
    status_color = p.green if not hard_fail else p.red

    print(p.paint("Logistic Copilot Environment Check", p.cyan, p.bold))
    print(p.paint("-" * 72, p.dim))
    print(f"{p.paint('Status:   ', p.bold)}{p.paint(status, status_color, p.bold)}")
    print(f"{p.paint('Template: ', p.bold)}{args.example}")
    print(f"{p.paint('Target:   ', p.bold)}{args.env}")
    print(
        f"{p.paint('Summary:  ', p.bold)}"
        f"{p.paint(str(len(specs) - len(missing_required) - len(required_empty) - len(placeholders)), p.green, p.bold)}/{len(specs)} ready"
        f"  {p.paint(str(len(missing_required)), p.red, p.bold)} missing required"
        f"  {p.paint(str(len(required_empty)), p.yellow, p.bold)} required empty"
        f"  {p.paint(str(len(placeholders)), p.red, p.bold)} placeholder"
        f"  {p.paint(str(len(policy_errors)), p.red, p.bold)} policy"
        f"  {p.paint(str(len(missing_optional)), p.blue, p.bold)} missing optional"
        f"  {p.paint(str(len(optional_empty)), p.blue, p.bold)} optional empty"
        f"  {p.paint(str(len(extra)), p.magenta, p.bold)} extra"
    )
    print(p.paint("-" * 72, p.dim))

    print_item("Missing required keys", missing_required, specs, values, defaults, p.red, p)
    print_item("Required keys with empty values", required_empty, specs, values, defaults, p.yellow, p)
    print_item("Required keys still using placeholder/default values", placeholders, specs, values, defaults, p.red, p)

    if policy_errors:
        print(p.paint("Policy checks", p.red, p.bold))
        for error in policy_errors:
            print(f"  {p.paint('-', p.red)} {error}")
        print()

    if missing_optional:
        shown = missing_optional[:12]
        print(p.paint("Missing optional keys", p.blue, p.bold))
        print("  " + ", ".join(shown) + (" ..." if len(missing_optional) > len(shown) else ""))
        print()

    if optional_empty:
        shown = optional_empty[:12]
        print(p.paint("Optional empty keys", p.blue, p.bold))
        print("  " + ", ".join(shown) + (" ..." if len(optional_empty) > len(shown) else ""))
        print()

    if extra and (args.show_extra or args.fail_on_extra):
        print(p.paint("Extra keys not present in template", p.magenta if not args.fail_on_extra else p.red, p.bold))
        for key in extra:
            print(f"  - {key}")
        print()

    if hard_fail:
        print(p.paint("Next steps:", p.blue, p.bold))
        print(f"  1. Create/update the file with {p.paint('make env-init', p.cyan, p.bold)} if needed.")
        print(f"  2. Set values safely with {p.paint('make env-set KEY=NAME VALUE=...', p.cyan, p.bold)}.")
        print(f"  3. Re-run {p.paint('make env-check', p.cyan, p.bold)}.")
        return 1

    print(p.paint("Environment looks usable for the configured template.", p.green, p.bold))
    if optional_empty:
        print("Optional empty values are acceptable, but some integrations will stay disabled until configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
