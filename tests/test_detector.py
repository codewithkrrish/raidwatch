"""Tests for the sliding-window join-velocity detector."""

import pytest

from raidwatch.detector import JoinEvent, JoinVelocityDetector


def make_detector(**kwargs) -> JoinVelocityDetector:
    defaults = {
        "window_seconds": 15,
        "join_threshold": 5,
        "cooldown_seconds": 60,
        "trusted_account_age_days": 7.0,
    }
    defaults.update(kwargs)
    return JoinVelocityDetector(**defaults)


def join(ts: float, user: str = "u", age: float = 0.0) -> JoinEvent:
    return JoinEvent(timestamp=ts, user_id=user, account_age_days=age)


def test_burst_triggers_alert():
    detector = make_detector()
    alert = None
    for i in range(5):
        alert = detector.record(join(1000.0 + i, user=f"user-{i}"))
    assert alert is not None
    assert alert.joins_in_window == 5
    assert alert.window_seconds == 15
    assert alert.suspects == tuple(f"user-{i}" for i in range(5))
    assert alert.joins_per_minute == pytest.approx(5 * 60 / 15)


def test_below_threshold_no_alert():
    detector = make_detector()
    for i in range(4):
        assert detector.record(join(1000.0 + i, user=f"user-{i}")) is None


def test_window_slides_old_joins_expire():
    detector = make_detector()
    for i in range(4):  # 4 joins at t=1000
        detector.record(join(1000.0, user=f"early-{i}"))
    # 30s later the early joins are outside the 15s window
    for i in range(4):
        assert detector.record(join(1030.0 + i, user=f"late-{i}")) is None
    assert detector.pending_count(1033.0) == 4


def test_cooldown_suppresses_repeat_alerts():
    detector = make_detector()
    for i in range(5):
        detector.record(join(1000.0 + i, user=f"first-{i}"))
    # second burst inside the 60s cooldown: recorded but no alert
    for i in range(5):
        assert detector.record(join(1010.0 + i, user=f"second-{i}")) is None
    # after the cooldown a new burst alerts again
    alert = None
    for i in range(5):
        alert = detector.record(join(2000.0 + i, user=f"third-{i}"))
    assert alert is not None
    assert alert.joins_in_window == 5


def test_trusted_accounts_not_counted():
    detector = make_detector()
    # 20 joins from 30-day-old accounts: trusted, never counted
    for i in range(20):
        assert detector.record(join(1000.0 + i, user=f"old-{i}", age=30.0)) is None
    assert detector.pending_count(1019.0) == 0
    # brand-new accounts still count
    alert = None
    for i in range(5):
        alert = detector.record(join(2000.0 + i, user=f"new-{i}", age=0.0))
    assert alert is not None


def test_trust_filter_disabled_at_zero():
    detector = make_detector(trusted_account_age_days=0.0)
    for i in range(20):
        detector.record(join(1000.0, user=f"old-{i}", age=365.0))
    assert detector.pending_count(1000.0) == 20


def test_reset_clears_window_and_cooldown():
    detector = make_detector()
    for i in range(5):
        detector.record(join(1000.0 + i, user=f"a-{i}"))
    detector.reset()
    assert detector.pending_count(1005.0) == 0
    # immediate re-burst alerts again (cooldown was cleared)
    alert = None
    for i in range(5):
        alert = detector.record(join(1006.0 + i, user=f"b-{i}"))
    assert alert is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"window_seconds": 0},
        {"window_seconds": -5},
        {"join_threshold": 1},
        {"join_threshold": 0},
        {"cooldown_seconds": -1},
        {"trusted_account_age_days": -1.0},
    ],
)
def test_invalid_parameters_rejected(kwargs):
    with pytest.raises(ValueError):
        make_detector(**kwargs)
