"""When the next private report should go out."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def parse_hour_minute(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"Horário inválido: {value!r}. Use HH:MM.")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour > 23 or minute > 59 or len(parts[0]) != 2 or len(parts[1]) != 2:
        raise ValueError(f"Horário inválido: {value!r}. Use HH:MM.")
    return hour, minute


def next_report_at(
    now: datetime,
    hour_minute: str,
    timezone_name: str,
    interval_days: int,
    last_sent_at: datetime | None,
) -> datetime:
    """Return the next send instant.

    The first run of a day sends immediately when the configured hour has already
    passed and no report was sent for this interval. Later runs wait for the
    following slot.
    """

    if now.tzinfo is None:
        raise ValueError("now precisa ter fuso horário.")
    if interval_days < 1:
        raise ValueError("report_interval_days precisa ser pelo menos 1.")

    tz = ZoneInfo(timezone_name)
    local_now = now.astimezone(tz)
    hour, minute = parse_hour_minute(hour_minute)
    slot = time(hour, minute)

    def at(day: date) -> datetime:
        return datetime.combine(day, slot, tzinfo=tz)

    if last_sent_at is None:
        today_slot = at(local_now.date())
        if local_now >= today_slot:
            return local_now
        return today_slot

    last_local = last_sent_at.astimezone(tz)
    due_at = at(last_local.date() + timedelta(days=interval_days))
    if due_at <= local_now:
        return local_now
    return due_at


def seconds_until_next_report(
    now: datetime,
    hour_minute: str,
    timezone_name: str,
    interval_days: int,
    last_sent_at: datetime | None,
) -> float:
    target = next_report_at(now, hour_minute, timezone_name, interval_days, last_sent_at)
    return max(0.0, (target - now).total_seconds())
