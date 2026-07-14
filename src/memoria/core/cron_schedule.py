"""Small five-field cron helpers shared by clocks and event scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _field_matches(value: int, field: str, min_value: int, max_value: int) -> bool:
    field = (field or "*").strip()
    if field == "*":
        return True
    allowed: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            return True
        if part.startswith("*/"):
            step = int(part[2:])
            if step <= 0:
                raise ValueError("cron step must be positive")
            allowed.update(range(min_value, max_value + 1, step))
        elif "-" in part:
            start, end = [int(item) for item in part.split("-", 1)]
            allowed.update(range(max(min_value, start), min(max_value, end) + 1))
        else:
            allowed.add(int(part))
    return value in allowed


def _cron_weekday(when: datetime) -> int:
    """Return cron weekday where Sunday is 0 and Saturday is 6."""
    return (when.weekday() + 1) % 7


def _weekday_field_matches(weekday: int, field: str) -> bool:
    field = (field or "*").strip()
    if field == "*":
        return True

    allowed: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            return True
        if part.startswith("*/"):
            step = int(part[2:])
            if step <= 0:
                raise ValueError("cron step must be positive")
            allowed.update(range(0, 7, step))
        elif "-" in part:
            raw_start, raw_end = [int(item) for item in part.split("-", 1)]
            start = 0 if raw_start == 7 else raw_start
            end = 0 if raw_end == 7 else raw_end
            if raw_end == 7 and start > 0:
                allowed.update(range(start, 7))
                allowed.add(0)
            elif start <= end:
                allowed.update(range(max(0, start), min(6, end) + 1))
            else:
                allowed.update(range(start, 7))
                allowed.update(range(0, end + 1))
        else:
            value = int(part)
            allowed.add(0 if value == 7 else value)
    return weekday in allowed


def cron_matches(schedule: str, when: datetime) -> bool:
    """Return whether a five-field cron expression matches the minute."""
    parts = schedule.split()
    if len(parts) != 5:
        raise ValueError("cron expression must have 5 fields: minute hour day month weekday")
    return (
        _field_matches(when.minute, parts[0], 0, 59)
        and _field_matches(when.hour, parts[1], 0, 23)
        and _field_matches(when.day, parts[2], 1, 31)
        and _field_matches(when.month, parts[3], 1, 12)
        and _weekday_field_matches(_cron_weekday(when), parts[4])
    )


def next_cron_run(
    schedule: str,
    after: datetime | None = None,
    max_minutes: int = 366 * 24 * 60,
    timezone_name: str = "UTC",
) -> datetime:
    """Return the next world-UTC instant matching a player's local cron."""
    cursor = after or datetime.now(timezone.utc)
    cursor = cursor.astimezone(timezone.utc).replace(second=0, microsecond=0)
    cursor += timedelta(minutes=1)
    local_timezone = ZoneInfo(timezone_name)
    for _ in range(max_minutes):
        if cron_matches(schedule, cursor.astimezone(local_timezone)):
            return cursor
        cursor += timedelta(minutes=1)
    raise ValueError(f"unable to find next cron run in search window: {schedule}")


def collect_due_cron_runs(
    schedule: str,
    first_due: datetime,
    through: datetime,
    *,
    timezone_name: str,
    replay_limit: int,
) -> tuple[list[datetime], int, datetime]:
    """Collect bounded replay instants, total due count, and the next future run."""
    if replay_limit < 1:
        raise ValueError("replay_limit must be at least 1")

    cursor = first_due.astimezone(timezone.utc)
    through = through.astimezone(timezone.utc)
    replay_runs: list[datetime] = []
    due_count = 0
    while cursor <= through:
        due_count += 1
        if len(replay_runs) < replay_limit:
            replay_runs.append(cursor)
        cursor = next_cron_run(
            schedule,
            cursor,
            timezone_name=timezone_name,
        )
    return replay_runs, due_count, cursor
