"""Player-scoped adjustable world time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memoria.core.config import configs
from memoria.core.cron_schedule import next_cron_run
from memoria.db import repository

UTC = timezone.utc
ALLOWED_TIME_SCALES = frozenset({0, 1, 2, 5, 10})
ALLOWED_TIMEZONE_MODES = frozenset({"fixed", "device"})


class ClockRevisionConflict(ValueError):
    pass


class ClockScheduleBusy(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def validate_timezone(timezone_name: str) -> str:
    name = (timezone_name or "").strip()
    if not name:
        raise ValueError("timezone is required")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"invalid IANA timezone: {name}") from exc
    return name


def validate_time_scale(time_scale: float | int) -> int:
    if isinstance(time_scale, bool) or time_scale not in ALLOWED_TIME_SCALES:
        raise ValueError(f"time_scale must be one of {sorted(ALLOWED_TIME_SCALES)}")
    return int(time_scale)


def validate_timezone_mode(timezone_mode: str) -> str:
    mode = (timezone_mode or "").strip().lower()
    if mode not in ALLOWED_TIMEZONE_MODES:
        raise ValueError(
            f"timezone_mode must be one of {sorted(ALLOWED_TIMEZONE_MODES)}"
        )
    return mode


def calculate_world_now(
    anchor_real_utc: datetime | str,
    anchor_world_utc: datetime | str,
    time_scale: float | int,
    real_now: datetime | str,
) -> datetime:
    real_anchor = as_utc(anchor_real_utc)
    world_anchor = as_utc(anchor_world_utc)
    current_real = as_utc(real_now)
    return world_anchor + (current_real - real_anchor) * float(time_scale)


def local_period(local_now: datetime, locale: str = "zh-CN") -> str:
    hour = local_now.hour
    if not locale.lower().startswith("zh"):
        if 5 <= hour < 8:
            return "early morning"
        if 8 <= hour < 12:
            return "morning"
        if 12 <= hour < 14:
            return "noon"
        if 14 <= hour < 18:
            return "afternoon"
        if 18 <= hour < 22:
            return "evening"
        return "late night"
    if 5 <= hour < 8:
        return "清晨"
    if 8 <= hour < 12:
        return "上午"
    if 12 <= hour < 14:
        return "中午"
    if 14 <= hour < 18:
        return "下午"
    if 18 <= hour < 22:
        return "傍晚"
    return "深夜"


def format_elapsed(delta: timedelta | None, locale: str = "zh-CN") -> str:
    english = not locale.lower().startswith("zh")
    if delta is None:
        return "No previous interaction" if english else "此前没有互动记录"
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return (
            "The recorded interaction is later than the current world time"
            if english
            else "互动记录晚于当前世界时间"
        )
    if seconds < 60:
        return "less than 1 minute" if english else "不到 1 分钟"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}" if english else f"{minutes} 分钟"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''}" if english else f"{hours} 小时"
    days = hours // 24
    if days < 7:
        return f"{days} day{'s' if days != 1 else ''}" if english else f"{days} 天"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks} week{'s' if weeks != 1 else ''}" if english else f"{weeks} 周"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''}" if english else f"{months} 个月"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''}" if english else f"{years} 年"


def world_due_to_real(
    world_due: datetime | str,
    world_now: datetime | str,
    real_now: datetime | str,
    time_scale: int,
) -> datetime | None:
    scale = validate_time_scale(time_scale)
    if scale == 0:
        return None
    due = as_utc(world_due)
    current_world = as_utc(world_now)
    current_real = as_utc(real_now)
    if due <= current_world:
        return current_real
    return current_real + (due - current_world) / scale


def parse_world_time(value: datetime | str, timezone_name: str) -> datetime:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class WorldClockSnapshot:
    player_id: str
    timezone: str
    time_scale: int
    real_now: datetime
    world_now: datetime
    timezone_mode: str = "fixed"
    clock_revision: int = 1

    @property
    def paused(self) -> bool:
        return self.time_scale == 0

    @property
    def local_now(self) -> datetime:
        return self.world_now.astimezone(ZoneInfo(self.timezone))

    @property
    def period(self) -> str:
        return local_period(self.local_now)

    @property
    def real_offset_seconds(self) -> int:
        return int((self.world_now - self.real_now).total_seconds())

    def to_api_dict(self) -> dict:
        return {
            "world_now": self.world_now.isoformat(),
            "real_now": self.real_now.isoformat(),
            "timezone": self.timezone,
            "timezone_mode": self.timezone_mode,
            "time_scale": self.time_scale,
            "paused": self.paused,
            "clock_revision": self.clock_revision,
            "real_offset_seconds": self.real_offset_seconds,
        }

    def prompt_context(
        self,
        last_interaction_world_at: datetime | str | None = None,
        *,
        locale: str = "zh-CN",
    ) -> dict:
        elapsed = None
        if last_interaction_world_at:
            elapsed = self.world_now - as_utc(last_interaction_world_at)
        local_now = self.local_now
        if locale.lower().startswith("zh"):
            weekdays = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
        else:
            weekdays = (
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            )
        return {
            **self.to_api_dict(),
            "local_date": local_now.strftime("%Y-%m-%d"),
            "local_time": local_now.strftime("%H:%M:%S"),
            "weekday": weekdays[local_now.weekday()],
            "period": local_period(local_now, locale),
            "last_interaction_elapsed": format_elapsed(elapsed, locale),
        }


def get_clock_snapshot(
    player_id: str,
    *,
    real_now: datetime | None = None,
    reported_timezone: str | None = None,
) -> WorldClockSnapshot:
    current_real = as_utc(real_now or utc_now())
    default_timezone = validate_timezone(
        reported_timezone or configs.world_clock_default_timezone
    )
    row = repository.get_or_create_player_world_clock(
        player_id=player_id,
        timezone_name=default_timezone,
        real_now_iso=current_real.isoformat(),
    )
    scale = validate_time_scale(row["time_scale"])
    return WorldClockSnapshot(
        player_id=player_id,
        timezone=validate_timezone(row["timezone"]),
        timezone_mode=validate_timezone_mode(row.get("timezone_mode", "fixed")),
        time_scale=scale,
        clock_revision=int(row.get("clock_revision", 1)),
        real_now=current_real,
        world_now=calculate_world_now(
            row["anchor_real_utc"],
            row["anchor_world_utc"],
            scale,
            current_real,
        ),
    )


def _apply_clock_change(
    player_id: str,
    *,
    timezone_name: str | None = None,
    timezone_mode: str | None = None,
    time_scale: int | None = None,
    world_now: datetime | str | None = None,
    expected_revision: int | None = None,
    real_now: datetime | None = None,
) -> WorldClockSnapshot:
    current_real = as_utc(real_now or utc_now())
    current = get_clock_snapshot(player_id, real_now=current_real)
    next_timezone = (
        validate_timezone(timezone_name)
        if timezone_name is not None
        else current.timezone
    )
    next_timezone_mode = (
        validate_timezone_mode(timezone_mode)
        if timezone_mode is not None
        else current.timezone_mode
    )
    next_scale = (
        validate_time_scale(time_scale)
        if time_scale is not None
        else current.time_scale
    )
    next_world = (
        parse_world_time(world_now, next_timezone)
        if world_now is not None
        else current.world_now
    )
    revision = current.clock_revision if expected_revision is None else expected_revision
    timezone_changed = next_timezone != current.timezone
    moved_backward = next_world < current.world_now

    def resolve_schedule(schedule_state: dict) -> tuple[str | None, str | None]:
        previous_run_at = schedule_state.get("next_run_at")
        if not previous_run_at:
            return None, None
        previous_due = as_utc(previous_run_at)
        if timezone_changed or moved_backward:
            next_due = next_cron_run(
                schedule_state["schedule"],
                next_world,
                timezone_name=next_timezone,
            )
        elif previous_due <= next_world:
            next_due = previous_due
        elif previous_due <= current.world_now:
            next_due = next_cron_run(
                schedule_state["schedule"],
                next_world,
                timezone_name=next_timezone,
            )
        else:
            next_due = previous_due
        due_real = world_due_to_real(
            next_due,
            next_world,
            current_real,
            next_scale,
        )
        return next_due.isoformat(), due_real.isoformat() if due_real else None

    try:
        row = repository.update_player_world_clock_and_schedules(
            player_id=player_id,
            expected_revision=revision,
            timezone_name=next_timezone,
            timezone_mode=next_timezone_mode,
            anchor_real_utc=current_real.isoformat(),
            anchor_world_utc=next_world.isoformat(),
            time_scale=next_scale,
            updated_at=current_real.isoformat(),
            resolve_schedule=resolve_schedule,
        )
    except repository.ClockRevisionConflictError as exc:
        raise ClockRevisionConflict(str(exc)) from exc
    except repository.ClockScheduleBusyError as exc:
        raise ClockScheduleBusy(str(exc)) from exc

    return WorldClockSnapshot(
        player_id=player_id,
        timezone=next_timezone,
        timezone_mode=next_timezone_mode,
        time_scale=next_scale,
        clock_revision=int(row["clock_revision"]),
        real_now=current_real,
        world_now=next_world,
    )


def update_clock(
    player_id: str,
    *,
    timezone_name: str | None = None,
    timezone_mode: str | None = None,
    time_scale: int | None = None,
    expected_revision: int | None = None,
    real_now: datetime | None = None,
) -> WorldClockSnapshot:
    return _apply_clock_change(
        player_id,
        timezone_name=timezone_name,
        timezone_mode=timezone_mode,
        time_scale=time_scale,
        expected_revision=expected_revision,
        real_now=real_now,
    )


def set_clock(
    player_id: str,
    world_now: datetime | str,
    *,
    expected_revision: int | None = None,
    real_now: datetime | None = None,
) -> WorldClockSnapshot:
    return _apply_clock_change(
        player_id,
        world_now=world_now,
        expected_revision=expected_revision,
        real_now=real_now,
    )


def advance_clock(
    player_id: str,
    delta: timedelta,
    *,
    expected_revision: int | None = None,
    real_now: datetime | None = None,
) -> WorldClockSnapshot:
    if delta.total_seconds() <= 0:
        raise ValueError("clock advance must be positive")
    current_real = as_utc(real_now or utc_now())
    current = get_clock_snapshot(player_id, real_now=current_real)
    return _apply_clock_change(
        player_id,
        world_now=current.world_now + delta,
        expected_revision=(
            current.clock_revision if expected_revision is None else expected_revision
        ),
        real_now=current_real,
    )


def sync_clock(
    player_id: str,
    *,
    expected_revision: int | None = None,
    real_now: datetime | None = None,
) -> WorldClockSnapshot:
    current_real = as_utc(real_now or utc_now())
    return _apply_clock_change(
        player_id,
        world_now=current_real,
        expected_revision=expected_revision,
        real_now=current_real,
    )
