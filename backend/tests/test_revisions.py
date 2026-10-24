from datetime import date, datetime, timezone

from app.revisions import deserialize_field, deserialize_snapshot


def test_deserialize_field_parses_date_strings_to_date_objects():
    """asyncpg (unlike SQLite) rejects a plain string for a Date column —
    this must return a real `date`, not just something that looks right."""
    value = deserialize_field("target_date", "2026-08-12")
    assert value == date(2026, 8, 12)
    assert isinstance(value, date)


def test_deserialize_field_parses_datetime_strings():
    value = deserialize_field("created_at", "2026-08-12T10:00:00+00:00")
    assert isinstance(value, datetime)


def test_deserialize_field_passes_through_non_date_fields():
    assert deserialize_field("category", "Work") == "Work"
    assert deserialize_field("importance", 3) == 3


def test_deserialize_field_passes_through_none():
    assert deserialize_field("target_date", None) is None


def test_deserialize_field_is_idempotent_on_already_parsed_values():
    d = date(2026, 8, 12)
    assert deserialize_field("target_date", d) is d


def test_deserialize_snapshot_round_trips_dates():
    restored = deserialize_snapshot({"title": "T", "target_date": "2026-08-12", "created_at": None})
    assert restored["target_date"] == date(2026, 8, 12)
    assert restored["title"] == "T"
    assert restored["created_at"] is None
