"""Tests for the raidwatch-sim CLI."""

import json
from datetime import datetime, timezone

import pytest

from raidwatch.cli import main, read_events

BASE_TS = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc).timestamp()


def write_events_file(path, events):
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    return path


def raid_burst(start_ts, count, gap=1.0):
    return [
        {"ts": start_ts + i * gap, "user_id": f"raider-{i}", "account_created": None}
        for i in range(count)
    ]


def test_quiet_server_no_alert(tmp_path, capsys):
    events = [
        {"ts": BASE_TS + i * 3600, "user_id": f"u-{i}", "account_created": "2024-01-01T00:00:00"}
        for i in range(5)
    ]
    path = write_events_file(tmp_path / "events.jsonl", events)
    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "no raid detected" in out


def test_raid_burst_detected(tmp_path, capsys):
    path = write_events_file(tmp_path / "events.jsonl", raid_burst(BASE_TS, 12))
    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "RAID DETECTED" in out
    assert "DRY RUN" in out
    assert "[channel_lock] #general" in out


def test_live_flag_changes_mode(tmp_path, capsys):
    path = write_events_file(tmp_path / "events.jsonl", raid_burst(BASE_TS, 12))
    assert main([str(path), "--live"]) == 0
    assert "LIVE" in capsys.readouterr().out


def test_json_output_is_parseable(tmp_path, capsys):
    path = write_events_file(tmp_path / "events.jsonl", raid_burst(BASE_TS, 12))
    assert main([str(path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["alerts"]) == 1
    # threshold (10) trips on the 10th join; cooldown suppresses the rest
    assert report["alerts"][0]["joins_in_window"] == 10
    assert report["dry_run"] is True


def test_custom_config_applied(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"join_threshold": 50, "lockdown_strategy": "verification_gate"})
    )
    path = write_events_file(tmp_path / "events.jsonl", raid_burst(BASE_TS, 12))
    assert main([str(path), "--config", str(config_path)]) == 0
    assert "no raid detected" in capsys.readouterr().out  # threshold 50 not hit


def test_missing_events_file_exit_2(tmp_path, capsys):
    assert main([str(tmp_path / "nope.jsonl")]) == 2
    assert "not found" in capsys.readouterr().err


def test_missing_config_file_uses_defaults(tmp_path, capsys):
    path = write_events_file(tmp_path / "events.jsonl", raid_burst(BASE_TS, 12))
    # no --config at all: defaults apply, burst still detected
    assert main([str(path)]) == 0
    assert "RAID DETECTED" in capsys.readouterr().out


def test_corrupt_config_exit_2(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken")
    path = write_events_file(tmp_path / "events.jsonl", raid_burst(BASE_TS, 12))
    assert main([str(path), "--config", str(config_path)]) == 2
    assert "error" in capsys.readouterr().err


def test_malformed_lines_skipped_with_warning(tmp_path, capsys):
    path = tmp_path / "events.jsonl"
    path.write_text(
        f'{{"ts": {BASE_TS}, "user_id": "good-1"}}\n'
        "this is not json\n"
        '{"ts": "abc", "user_id": "bad"}\n'
        f'{{"ts": {BASE_TS + 1}, "user_id": "good-2"}}\n'
    )
    events, bad = read_events(path)
    assert bad == 2
    assert [e.user_id for e in events] == ["good-1", "good-2"]


def test_empty_file_reports_gracefully(tmp_path, capsys):
    path = tmp_path / "events.jsonl"
    path.write_text("")
    assert main([str(path)]) == 0
    assert "no events to simulate" in capsys.readouterr().out


def test_old_accounts_ignored_in_sim(tmp_path, capsys):
    # 30 joins, all from 2-year-old accounts: trusted, no alert
    events = [
        {
            "ts": BASE_TS + i,
            "user_id": f"veteran-{i}",
            "account_created": "2024-01-01T00:00:00",
        }
        for i in range(30)
    ]
    path = write_events_file(tmp_path / "events.jsonl", events)
    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "no raid detected" in out
    assert "0 counted" in out


def test_events_sorted_regardless_of_file_order(tmp_path):
    events = list(reversed(raid_burst(BASE_TS, 3, gap=1.0)))
    path = write_events_file(tmp_path / "events.jsonl", events)
    parsed, _ = read_events(path)
    assert [e.timestamp for e in parsed] == sorted(e.timestamp for e in parsed)
