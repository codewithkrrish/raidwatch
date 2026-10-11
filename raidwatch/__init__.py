"""raidwatch — anti-raid protection for discord.py bots.

Sliding-window join-velocity detection, automatic server lockdown,
staff alerts, and a dry-run mode for safe threshold tuning.
"""

from raidwatch.config import ConfigError, RaidWatchConfig, load_config
from raidwatch.detector import JoinEvent, JoinVelocityDetector, RaidAlert
from raidwatch.lockdown import (
    LockdownAction,
    LockdownError,
    LockdownReport,
    plan_lockdown,
    plan_unlock,
)
from raidwatch.storage import StorageError, read_json, write_json_atomic

__version__ = "0.1.0"

__all__ = [
    "ConfigError",
    "JoinEvent",
    "JoinVelocityDetector",
    "LockdownAction",
    "LockdownError",
    "LockdownReport",
    "RaidAlert",
    "RaidWatchConfig",
    "StorageError",
    "__version__",
    "load_config",
    "plan_lockdown",
    "plan_unlock",
    "read_json",
    "write_json_atomic",
]
