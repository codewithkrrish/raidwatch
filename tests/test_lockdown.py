"""Tests for lockdown planning."""

import pytest

from raidwatch.lockdown import (
    ChannelSummary,
    LockdownError,
    LockdownReport,
    plan_lockdown,
    plan_unlock,
)

CHANNELS = [
    ChannelSummary(id=1, name="general"),
    ChannelSummary(id=2, name="chat"),
]


def test_channel_lock_plan_covers_every_channel():
    actions = plan_lockdown(CHANNELS, "channel_lock")
    assert len(actions) == 2
    assert all(a.kind == "channel_lock" for a in actions)
    assert [a.target_id for a in actions] == [1, 2]
    assert actions[0].target_name == "#general"


def test_verification_gate_plan_is_server_wide():
    actions = plan_lockdown(CHANNELS, "verification_gate")
    assert len(actions) == 1
    assert actions[0].target_id is None
    assert actions[0].target_name == "server"


def test_both_strategy_combines_actions():
    actions = plan_lockdown(CHANNELS, "both")
    assert len(actions) == 3
    kinds = [a.kind for a in actions]
    assert kinds.count("channel_lock") == 2
    assert kinds.count("verification_gate") == 1


def test_unknown_strategy_rejected():
    with pytest.raises(LockdownError, match="unknown lockdown strategy"):
        plan_lockdown(CHANNELS, "ban_everyone")


def test_empty_channel_list_plans_nothing_for_channel_lock():
    assert plan_lockdown([], "channel_lock") == []


def test_unlock_reverses_plan():
    actions = plan_lockdown(CHANNELS, "both")
    undone = plan_unlock(actions)
    assert len(undone) == len(actions)
    # reversed order
    assert undone[0].kind == "verification_gate"
    assert undone[1].target_id == 2
    assert undone[2].target_id == 1
    assert all("Restore" in a.detail for a in undone)


def test_report_mode_label():
    dry = LockdownReport(dry_run=True, alert_id="x")
    live = LockdownReport(dry_run=False, alert_id="x")
    assert dry.mode == "DRY RUN"
    assert live.mode == "LIVE"
