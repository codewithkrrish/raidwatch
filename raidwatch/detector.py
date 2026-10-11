"""Join-velocity raid detection using a sliding time window.

Pure logic with no discord.py dependency, so it is trivially unit-testable
and reusable in the bundled CLI simulator.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

SECONDS_PER_DAY = 86_400.0


@dataclass(frozen=True)
class JoinEvent:
    """A single member-join observation."""

    timestamp: float  # epoch seconds; events must arrive in chronological order
    user_id: str
    account_age_days: float = 0.0


@dataclass(frozen=True)
class RaidAlert:
    """Raised when a join-velocity spike is detected."""

    detected_at: float
    joins_in_window: int
    window_seconds: int
    suspects: tuple[str, ...]

    @property
    def joins_per_minute(self) -> float:
        """Extrapolated joins-per-minute rate for this burst."""
        if self.window_seconds <= 0:
            return 0.0
        return self.joins_in_window * 60.0 / self.window_seconds


class JoinVelocityDetector:
    """Detects join-velocity spikes with a sliding time window.

    Joins from accounts older than ``trusted_account_age_days`` are not
    counted toward the window. This cuts false positives from legitimate
    traffic bursts (giveaways, announcements, partner pings) where the
    joining accounts are usually established.
    """

    def __init__(
        self,
        *,
        window_seconds: int,
        join_threshold: int,
        cooldown_seconds: int,
        trusted_account_age_days: float = 0.0,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if join_threshold < 2:
            raise ValueError("join_threshold must be at least 2")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must not be negative")
        if trusted_account_age_days < 0:
            raise ValueError("trusted_account_age_days must not be negative")
        self._window_seconds = window_seconds
        self._join_threshold = join_threshold
        self._cooldown_seconds = cooldown_seconds
        self._trusted_account_age_days = trusted_account_age_days
        self._window: deque[tuple[float, str]] = deque()
        self._last_alert_at: float | None = None

    def record(self, event: JoinEvent) -> RaidAlert | None:
        """Record a join; return a RaidAlert if this join trips the threshold."""
        if self._is_trusted(event):
            return None
        self._purge(event.timestamp)
        self._window.append((event.timestamp, event.user_id))
        if len(self._window) < self._join_threshold:
            return None
        if self._in_cooldown(event.timestamp):
            return None
        self._last_alert_at = event.timestamp
        suspects = tuple(user_id for _, user_id in self._window)
        return RaidAlert(
            detected_at=event.timestamp,
            joins_in_window=len(self._window),
            window_seconds=self._window_seconds,
            suspects=suspects,
        )

    def pending_count(self, now: float) -> int:
        """Number of untrusted joins currently inside the window."""
        self._purge(now)
        return len(self._window)

    def reset(self) -> None:
        """Clear the window and the alert cooldown (e.g. after an unlock)."""
        self._window.clear()
        self._last_alert_at = None

    def _is_trusted(self, event: JoinEvent) -> bool:
        return (
            self._trusted_account_age_days > 0
            and event.account_age_days >= self._trusted_account_age_days
        )

    def _in_cooldown(self, now: float) -> bool:
        return (
            self._last_alert_at is not None
            and now - self._last_alert_at < self._cooldown_seconds
        )

    def _purge(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._window and self._window[0][0] <= cutoff:
            self._window.popleft()
