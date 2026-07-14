"""Small five-field cron helpers shared by clocks and event scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _parse_number(value: str, field_name: str) -> int:
    if not value or not value.isdigit():
        raise ValueError(f"cron {field_name} field contains an invalid value: {value!r}")
    return int(value)


def _validate_field(
    field: str,
    min_value: int,
    max_value: int,
    field_name: str,
) -> None:
    if not field:
        raise ValueError(f"cron {field_name} field must not be empty")
    for part in field.split(","):
        if not part:
            raise ValueError(f"cron {field_name} field contains an empty list item")
        if part == "*":
            continue
        if part.startswith("*/"):
            step = _parse_number(part[2:], field_name)
            if step <= 0:
                raise ValueError(f"cron {field_name} step must be positive")
            continue
        if "-" in part:
            bounds = part.split("-")
            if len(bounds) != 2:
                raise ValueError(f"cron {field_name} range is invalid: {part!r}")
            start = _parse_number(bounds[0], field_name)
            end = _parse_number(bounds[1], field_name)
            if start > end:
                raise ValueError(f"cron {field_name} range must not be reversed")
            values = (start, end)
        else:
            values = (_parse_number(part, field_name),)
        for value in values:
            if value < min_value or value > max_value:
                raise ValueError(
                    f"cron {field_name} value {value} is outside "
                    f"{min_value}..{max_value}"
                )


def validate_cron_schedule(schedule: str) -> None:
    """Validate the supported five-field cron grammar and numeric bounds."""
    parts = str(schedule or "").split()
    if len(parts) != 5:
        raise ValueError(
            "cron expression must have 5 fields: minute hour day month weekday"
        )
    for field, min_value, max_value, name in (
        (parts[0], 0, 59, "minute"),
        (parts[1], 0, 23, "hour"),
        (parts[2], 1, 31, "day"),
        (parts[3], 1, 12, "month"),
        (parts[4], 0, 7, "weekday"),
    ):
        _validate_field(field, min_value, max_value, name)


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
    validate_cron_schedule(schedule)
    parts = schedule.split()
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
