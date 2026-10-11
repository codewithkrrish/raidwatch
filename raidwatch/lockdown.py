"""Lockdown planning: what a raid response does, before it does it.

Planning is pure and works on plain data, so the exact same plan the bot
executes can be previewed in dry-run mode or in the CLI simulator.
Execution against real Discord objects lives in the cog, which stays thin.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable

from raidwatch.config import (
    STRATEGY_BOTH,
    STRATEGY_CHANNEL_LOCK,
    STRATEGY_VERIFICATION_GATE,
    VALID_STRATEGIES,
)


class LockdownError(Exception):
    """Raised when a lockdown plan cannot be built."""


@dataclass(frozen=True)
class ChannelSummary:
    """The minimum channel info needed to plan a lockdown."""

    id: int
    name: str


@dataclass(frozen=True)
class LockdownAction:
    """One reversible step of a lockdown."""

    kind: str  # STRATEGY_CHANNEL_LOCK | STRATEGY_VERIFICATION_GATE
    target_id: int | None  # channel id, or None for server-wide actions
    target_name: str
    detail: str


@dataclass(frozen=True)
class LockdownReport:
    """What happened (or would have happened) during a lockdown."""

    dry_run: bool
    alert_id: str
    actions: tuple[LockdownAction, ...] = field(default_factory=tuple)
    generated_at: float = field(default_factory=time.time)

    @property
    def mode(self) -> str:
        """Human label for how this report was produced."""
        return "DRY RUN" if self.dry_run else "LIVE"


def plan_lockdown(
    channels: Iterable[ChannelSummary], strategy: str
) -> list[LockdownAction]:
    """Build the ordered list of actions that locks a server down.

    Raises:
        LockdownError: on an unknown strategy.
    """
    if strategy not in VALID_STRATEGIES:
        raise LockdownError(
            f"unknown lockdown strategy {strategy!r}; "
            f"expected one of {', '.join(VALID_STRATEGIES)}"
        )
    actions: list[LockdownAction] = []
    if strategy in (STRATEGY_CHANNEL_LOCK, STRATEGY_BOTH):
        for channel in channels:
            actions.append(
                LockdownAction(
                    kind=STRATEGY_CHANNEL_LOCK,
                    target_id=channel.id,
                    target_name=f"#{channel.name}",
                    detail="Deny send_messages for @everyone",
                )
            )
    if strategy in (STRATEGY_VERIFICATION_GATE, STRATEGY_BOTH):
        actions.append(
            LockdownAction(
                kind=STRATEGY_VERIFICATION_GATE,
                target_id=None,
                target_name="server",
                detail="Raise verification level to HIGH",
            )
        )
    return actions


def plan_unlock(actions: Iterable[LockdownAction]) -> list[LockdownAction]:
    """Build the reverse plan that undoes a lockdown, in reverse order."""
    reversed_actions: list[LockdownAction] = []
    for action in reversed(list(actions)):
        if action.kind == STRATEGY_CHANNEL_LOCK:
            detail = "Restore send_messages for @everyone"
        else:
            detail = "Restore previous verification level"
        reversed_actions.append(
            LockdownAction(
                kind=action.kind,
                target_id=action.target_id,
                target_name=action.target_name,
                detail=detail,
            )
        )
    return reversed_actions
