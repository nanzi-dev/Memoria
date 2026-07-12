"""Player-scoped adjustable world time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memoria.core.config import configs
from memoria.db import repository

UTC = timezone.utc
ALLOWED_TIME_SCALES = frozenset({0, 1, 2, 5, 10})


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


def local_period(local_now: datetime) -> str:
    hour = local_now.hour
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


def format_elapsed(delta: timedelta | None) -> str:
    if delta is None:
        return "此前没有互动记录"
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "不到 1 分钟"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时"
    days = hours // 24
    if days < 7:
        return f"{days} 天"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks} 周"
    months = days // 30
    if months < 12:
        return f"{months} 个月"
    years = days // 365
    return f"{years} 年"


@dataclass(frozen=True)
class WorldClockSnapshot:
    player_id: str
    timezone: str
    time_scale: int
    real_now: datetime
    world_now: datetime

    @property
    def paused(self) -> bool:
        return self.time_scale == 0

    @property
    def local_now(self) -> datetime:
        return self.world_now.astimezone(ZoneInfo(self.timezone))

    @property
    def period(self) -> str:
        return local_period(self.local_now)

    def to_api_dict(self) -> dict:
        return {
            "world_now": self.world_now.isoformat(),
            "real_now": self.real_now.isoformat(),
            "timezone": self.timezone,
            "time_scale": self.time_scale,
            "paused": self.paused,
        }

    def prompt_context(self, last_interaction_world_at: datetime | str | None = None) -> dict:
        elapsed = None
        if last_interaction_world_at:
            elapsed = self.world_now - as_utc(last_interaction_world_at)
        local_now = self.local_now
        weekdays = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
        return {
            **self.to_api_dict(),
            "local_date": local_now.strftime("%Y-%m-%d"),
            "local_time": local_now.strftime("%H:%M:%S"),
            "weekday": weekdays[local_now.weekday()],
            "period": self.period,
            "last_interaction_elapsed": format_elapsed(elapsed),
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
        time_scale=scale,
        real_now=current_real,
        world_now=calculate_world_now(
            row["anchor_real_utc"],
            row["anchor_world_utc"],
            scale,
            current_real,
        ),
    )


def update_clock(
    player_id: str,
    *,
    timezone_name: str | None = None,
    time_scale: int | None = None,
    real_now: datetime | None = None,
) -> WorldClockSnapshot:
    current_real = as_utc(real_now or utc_now())
    current = get_clock_snapshot(player_id, real_now=current_real)
    next_timezone = validate_timezone(timezone_name) if timezone_name is not None else current.timezone
    next_scale = validate_time_scale(time_scale) if time_scale is not None else current.time_scale
    repository.save_player_world_clock(
        player_id=player_id,
        timezone_name=next_timezone,
        anchor_real_utc=current_real.isoformat(),
        anchor_world_utc=current.world_now.isoformat(),
        time_scale=next_scale,
        updated_at=current_real.isoformat(),
    )
    return WorldClockSnapshot(
        player_id=player_id,
        timezone=next_timezone,
        time_scale=next_scale,
        real_now=current_real,
        world_now=current.world_now,
    )


def sync_clock(
    player_id: str,
    *,
    real_now: datetime | None = None,
) -> WorldClockSnapshot:
    current_real = as_utc(real_now or utc_now())
    current = get_clock_snapshot(player_id, real_now=current_real)
    repository.save_player_world_clock(
        player_id=player_id,
        timezone_name=current.timezone,
        anchor_real_utc=current_real.isoformat(),
        anchor_world_utc=current_real.isoformat(),
        time_scale=current.time_scale,
        updated_at=current_real.isoformat(),
    )
    return WorldClockSnapshot(
        player_id=player_id,
        timezone=current.timezone,
        time_scale=current.time_scale,
        real_now=current_real,
        world_now=current_real,
    )
