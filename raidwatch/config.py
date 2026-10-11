"""Typed, validated configuration for raidwatch."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from raidwatch.storage import StorageError, read_json

STRATEGY_CHANNEL_LOCK = "channel_lock"
STRATEGY_VERIFICATION_GATE = "verification_gate"
STRATEGY_BOTH = "both"
VALID_STRATEGIES = (
    STRATEGY_CHANNEL_LOCK,
    STRATEGY_VERIFICATION_GATE,
    STRATEGY_BOTH,
)

DEFAULT_WINDOW_SECONDS = 15
DEFAULT_JOIN_THRESHOLD = 10
DEFAULT_COOLDOWN_MINUTES = 30
DEFAULT_TRUSTED_ACCOUNT_AGE_DAYS = 7


class ConfigError(Exception):
    """Raised when a raidwatch configuration is invalid or unreadable."""


@dataclass
class RaidWatchConfig:
    """All raidwatch settings.

    ``dry_run`` defaults to True on purpose: a fresh install can only ever
    report what it *would* do until a server admin explicitly opts into
    live lockdowns.
    """

    window_seconds: int = DEFAULT_WINDOW_SECONDS
    join_threshold: int = DEFAULT_JOIN_THRESHOLD
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES
    dry_run: bool = True
    lockdown_strategy: str = STRATEGY_CHANNEL_LOCK
    alert_channel_id: int | None = None
    staff_role_id: int | None = None
    trusted_account_age_days: float = DEFAULT_TRUSTED_ACCOUNT_AGE_DAYS
    auto_unlock_minutes: int = 0  # 0 = stay locked until a moderator unlocks

    def validate(self) -> None:
        """Raise ConfigError if any setting is out of range."""
        if self.window_seconds <= 0:
            raise ConfigError("window_seconds must be positive")
        if self.join_threshold < 2:
            raise ConfigError("join_threshold must be at least 2")
        if self.cooldown_minutes < 0:
            raise ConfigError("cooldown_minutes must not be negative")
        if self.lockdown_strategy not in VALID_STRATEGIES:
            raise ConfigError(
                f"lockdown_strategy must be one of {', '.join(VALID_STRATEGIES)}"
            )
        for name in ("alert_channel_id", "staff_role_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value <= 0):
                raise ConfigError(f"{name} must be a positive Discord snowflake id")
        if self.trusted_account_age_days < 0:
            raise ConfigError("trusted_account_age_days must not be negative")
        if self.auto_unlock_minutes < 0:
            raise ConfigError("auto_unlock_minutes must not be negative")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RaidWatchConfig:
        """Build a config from a plain dict; unknown keys are rejected."""
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown config keys: {', '.join(sorted(unknown))}")
        config = cls(**{k: v for k, v in data.items() if k in known})
        config.validate()
        return config

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (safe for JSON)."""
        return asdict(self)


def load_config(path: str | Path) -> RaidWatchConfig:
    """Load config from a JSON file; return defaults when the file is absent.

    Raises:
        ConfigError: if the file exists but is corrupt or invalid.
    """
    config_path = Path(path)
    if not config_path.exists():
        return RaidWatchConfig()
    try:
        data = read_json(config_path)
    except StorageError as exc:
        raise ConfigError(f"could not read config {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config {config_path} must contain a JSON object")
    try:
        return RaidWatchConfig.from_dict(data)
    except TypeError as exc:
        raise ConfigError(f"invalid config {config_path}: {exc}") from exc
