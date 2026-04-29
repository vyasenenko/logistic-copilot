"""Tests for magic-fill datetime parsing helpers."""

from datetime import datetime

from app.api.freight import _parse_magic_local_datetime


def test_parse_magic_local_datetime_strips_quotes():
    assert _parse_magic_local_datetime('"2026-04-28T08:00:00"') == datetime(2026, 4, 28, 8, 0, 0)


def test_parse_magic_local_datetime_strips_fenced_block():
    assert _parse_magic_local_datetime("```\n2026-04-28T08:00:00\n```") == datetime(2026, 4, 28, 8, 0, 0)
