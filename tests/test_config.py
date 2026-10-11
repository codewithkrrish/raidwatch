"""Tests for config validation, loading, and serialization."""

import json

import pytest

from raidwatch.config import ConfigError, RaidWatchConfig, load_config


def test_defaults_are_safe_and_valid():
    config = RaidWatchConfig()
    config.validate()
    assert config.dry_run is True  # safe default: report-only until armed
    assert config.window_seconds == 15
    assert config.join_threshold == 10


@pytest.mark.parametrize(
    "field,value",
    [
        ("window_seconds", 0),
        ("window_seconds", -1),
        ("join_threshold", 1),
        ("cooldown_minutes", -5),
        ("lockdown_strategy", "nuke"),
        ("alert_channel_id", -3),
        ("staff_role_id", "not-an-int"),
        ("trusted_account_age_days", -1.0),
        ("auto_unlock_minutes", -1),
    ],
)
def test_invalid_values_rejected(field, value):
    config = RaidWatchConfig(**{field: value})
    with pytest.raises(ConfigError):
        config.validate()


def test_unknown_keys_rejected():
    with pytest.raises(ConfigError, match="unknown config keys"):
        RaidWatchConfig.from_dict({"window_seconds": 10, "mystery_key": 1})


def test_partial_dict_uses_defaults():
    config = RaidWatchConfig.from_dict({"join_threshold": 25})
    assert config.join_threshold == 25
    assert config.window_seconds == 15  # default kept


def test_roundtrip(tmp_path):
    config = RaidWatchConfig(
        join_threshold=25, dry_run=False, lockdown_strategy="both", auto_unlock_minutes=10
    )
    restored = RaidWatchConfig.from_dict(config.to_dict())
    assert restored.to_dict() == config.to_dict()


def test_load_missing_file_returns_defaults(tmp_path):
    config = load_config(tmp_path / "does-not-exist.json")
    assert config.to_dict() == RaidWatchConfig().to_dict()


def test_load_valid_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"join_threshold": 25, "dry_run": False}))
    config = load_config(path)
    assert config.join_threshold == 25
    assert config.dry_run is False


def test_load_corrupt_file_raises_config_error(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not valid json")
    with pytest.raises(ConfigError):
        load_config(path)


def test_load_non_object_raises_config_error(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps([1, 2, 3]))
    with pytest.raises(ConfigError):
        load_config(path)


def test_load_invalid_values_raises_config_error(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"join_threshold": 0}))
    with pytest.raises(ConfigError):
        load_config(path)
