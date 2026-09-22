"""Fail-closed exchange-session windows from target-owned calendar evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from hypertrade.targets.ports import SessionCalendarEvidence
from hypertrade.targets.schemas import TargetCalendarV1


@dataclass(frozen=True)
class SessionWindow:
    baseline_day: date
    dates: tuple[date, ...]
    timezone: ZoneInfo
    open_time: time
    close_time: time
    source_hash: str

    def bounds(self, day: date) -> tuple[datetime, datetime]:
        def boundary(clock: time) -> datetime:
            local = datetime.combine(day, clock, self.timezone)
            utc = local.astimezone(UTC)
            if (
                utc.astimezone(self.timezone).replace(tzinfo=None) != local.replace(tzinfo=None)
                or local.replace(fold=1).utcoffset() != local.utcoffset()
            ):
                raise ValueError("ambiguous_session_clock")
            return utc

        return boundary(self.open_time), boundary(self.close_time)


def completed_session_window(
    calendar: TargetCalendarV1, evidence: SessionCalendarEvidence, now: datetime
) -> SessionWindow:
    if calendar.mode != "sessions" or not calendar.session_open or not calendar.session_close:
        raise ValueError("session_calendar_incomplete")
    try:
        tz = ZoneInfo(calendar.timezone)
        opening = time.fromisoformat(calendar.session_open)
        closing = time.fromisoformat(calendar.session_close)
        start = date.fromisoformat(evidence.start_date)
        end = date.fromisoformat(evidence.end_date)
        dates = tuple(date.fromisoformat(value) for value in evidence.trading_dates)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("session_calendar_invalid") from exc
    if (
        not evidence.complete
        or not evidence.source_hash
        or evidence.timezone != calendar.timezone
        or start > end
        or not opening < closing
        or dates != tuple(sorted(set(dates)))
        or any(day < start or day > end for day in dates)
        or (
            calendar.trading_days
            and any(day.weekday() not in calendar.trading_days for day in dates)
        )
    ):
        raise ValueError("session_calendar_ambiguous")
    if now.tzinfo is None:
        raise ValueError("timestamp_missing_timezone")
    local_now = now.astimezone(tz)
    if end < local_now.date() - timedelta(days=1) or start > local_now.date() - timedelta(days=90):
        raise ValueError("session_calendar_coverage_missing")
    completed = tuple(day for day in dates if datetime.combine(day, closing, tz) <= local_now)
    if len(completed) < calendar.evidence_window_days + 1:
        raise ValueError("session_baseline_close_missing")
    selected = completed[-calendar.evidence_window_days :]
    if len(selected) % 2:
        raise ValueError("session_window_not_even")
    return SessionWindow(
        completed[-calendar.evidence_window_days - 1],
        selected,
        tz,
        opening,
        closing,
        evidence.source_hash,
    )
