from datetime import datetime, timezone

from app.services.freight_read import (
    normalize_shipment_date_field,
    normalize_shipment_date_scope,
    normalize_shipment_sort_field,
    shipment_list_window,
)


def test_shipment_list_window_today_starts_at_midnight_utc():
    now = datetime(2026, 4, 25, 15, 30, tzinfo=timezone.utc)

    start, end = shipment_list_window(date_scope="today", now=now)

    assert start == datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc)
    assert end == now


def test_shipment_list_window_last_2_days():
    now = datetime(2026, 4, 25, 15, 30, tzinfo=timezone.utc)

    start, end = shipment_list_window(date_scope="last_2_days", now=now)

    assert start == datetime(2026, 4, 23, 15, 30, tzinfo=timezone.utc)
    assert end == now


def test_shipment_list_window_current_month():
    now = datetime(2026, 4, 25, 15, 30, tzinfo=timezone.utc)

    start, end = shipment_list_window(date_scope="current_month", now=now)

    assert start == datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    assert end == now


def test_shipment_list_window_all_has_no_bounds():
    assert shipment_list_window(date_scope="all") == (None, None)


def test_shipment_list_window_unknown_scope_defaults_to_last_7_days():
    now = datetime(2026, 4, 25, 15, 30, tzinfo=timezone.utc)

    start, end = shipment_list_window(date_scope="surprise", now=now)

    assert start == datetime(2026, 4, 18, 15, 30, tzinfo=timezone.utc)
    assert end == now


def test_shipment_query_normalizers_default_unknown_values():
    assert normalize_shipment_date_scope("weird") == "last_7_days"
    assert normalize_shipment_date_field("weird") == "created_at"
    assert normalize_shipment_sort_field("weird") == "date_field"
    assert normalize_shipment_date_field(" updated_at ") == "updated_at"
