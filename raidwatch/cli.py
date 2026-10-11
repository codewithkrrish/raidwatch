"""raidwatch-sim: offline raid simulator for tuning detection thresholds.

Reads a JSONL file of join events, runs the same detector the Discord cog
uses, and prints what the bot would have done — including the lockdown
plan. Use this to tune ``window_seconds`` / ``join_threshold`` against
real server join logs before going live.

Event file format (one JSON object per line):
    {"ts": 1728566400.0, "user_id": "123456789", "account_created": "2024-01-02T15:04:05"}

``account_created`` may be null or omitted (treated as a brand-new account).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raidwatch.config import ConfigError, RaidWatchConfig, load_config
from raidwatch.detector import JoinEvent, JoinVelocityDetector, RaidAlert
from raidwatch.lockdown import (
    ChannelSummary,
    LockdownReport,
    plan_lockdown,
)

EXIT_OK = 0
EXIT_USAGE_ERROR = 2

SECONDS_PER_DAY = 86_400.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="raidwatch-sim",
        description="Simulate raidwatch raid detection against a join-event log.",
    )
    parser.add_argument("events", help="JSONL file of join events")
    parser.add_argument(
        "--config",
        default=None,
        help="JSON config file (defaults are used when omitted)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="report actions as LIVE instead of DRY RUN (still a simulation)",
    )
    parser.add_argument(
        "--channels",
        default="general,chat,memes",
        help="comma-separated channel names for the lockdown plan preview",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON instead of human-readable text",
    )
    return parser.parse_args(argv)


def account_age_days(account_created: str | None, event_ts: float) -> float:
    """Age of an account in days at the moment of the join event."""
    if not account_created:
        return 0.0
    try:
        created = datetime.fromisoformat(account_created)
    except ValueError:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = (datetime.fromtimestamp(event_ts, tz=timezone.utc) - created).total_seconds()
    return max(age, 0.0) / SECONDS_PER_DAY


def read_events(path: Path) -> tuple[list[JoinEvent], int]:
    """Read join events; return (events, bad_line_count)."""
    events: list[JoinEvent] = []
    bad_lines = 0
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw: Any = json.loads(line)
                ts = float(raw["ts"])
                user_id = str(raw["user_id"])
                age = account_age_days(raw.get("account_created"), ts)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                bad_lines += 1
                print(f"warning: skipping line {lineno}: {exc}", file=sys.stderr)
                continue
            events.append(
                JoinEvent(timestamp=ts, user_id=user_id, account_age_days=age)
            )
    events.sort(key=lambda e: e.timestamp)
    return events, bad_lines


def run_simulation(
    events: list[JoinEvent],
    config: RaidWatchConfig,
    dry_run: bool,
    channel_names: list[str],
) -> dict[str, Any]:
    """Run the detector over the events and build a report dict."""
    detector = JoinVelocityDetector(
        window_seconds=config.window_seconds,
        join_threshold=config.join_threshold,
        cooldown_seconds=config.cooldown_minutes * 60,
        trusted_account_age_days=config.trusted_account_age_days,
    )
    alerts: list[RaidAlert] = []
    counted = 0
    for event in events:
        alert = detector.record(event)
        trusted = (
            config.trusted_account_age_days > 0
            and event.account_age_days >= config.trusted_account_age_days
        )
        if not trusted:
            counted += 1
        if alert is not None:
            alerts.append(alert)

    lockdown_actions: list[dict[str, Any]] = []
    if alerts:
        first = alerts[0]
        channels = [
            ChannelSummary(id=index + 1, name=name)
            for index, name in enumerate(channel_names)
        ]
        actions = plan_lockdown(channels, config.lockdown_strategy)
        lockdown_actions = [
            {"kind": a.kind, "target": a.target_name, "detail": a.detail}
            for a in actions
        ]
        _ = LockdownReport(
            dry_run=dry_run,
            alert_id=f"sim-{int(first.detected_at)}",
            actions=tuple(actions),
        )

    return {
        "events_total": len(events),
        "events_counted": counted,
        "alerts": [
            {
                "detected_at": a.detected_at,
                "joins_in_window": a.joins_in_window,
                "window_seconds": a.window_seconds,
                "joins_per_minute": round(a.joins_per_minute, 1),
                "suspects": list(a.suspects),
            }
            for a in alerts
        ],
        "dry_run": dry_run,
        "strategy": config.lockdown_strategy,
        "lockdown_actions": lockdown_actions,
    }


def print_text_report(report: dict[str, Any], config: RaidWatchConfig) -> None:
    """Print a human-readable simulation report."""
    mode = "DRY RUN" if report["dry_run"] else "LIVE"
    print("raidwatch simulation report")
    print(f"  mode:            {mode}")
    print(
        f"  detector:        {config.join_threshold} joins / "
        f"{config.window_seconds}s window, "
        f"{config.cooldown_minutes}m cooldown, "
        f"trust accounts older than {config.trusted_account_age_days:g}d"
    )
    print(
        f"  events:          {report['events_total']} total, "
        f"{report['events_counted']} counted toward detection"
    )
    alerts = report["alerts"]
    if not alerts:
        print("  result:          no raid detected")
        return
    print(f"  result:          RAID DETECTED x{len(alerts)}")
    for i, alert in enumerate(alerts, start=1):
        ts = datetime.fromtimestamp(alert["detected_at"], tz=timezone.utc)
        print(
            f"  alert {i}:         {alert['joins_in_window']} joins in "
            f"{alert['window_seconds']}s "
            f"({alert['joins_per_minute']}/min) at {ts:%Y-%m-%d %H:%M:%S} UTC"
        )
    print(f"  lockdown plan ({report['strategy']}, {mode}):")
    for action in report["lockdown_actions"]:
        print(f"    - [{action['kind']}] {action['target']}: {action['detail']}")
    if report["dry_run"]:
        print("  note:            dry run — nothing was actually locked")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)

    events_path = Path(args.events)
    if not events_path.exists():
        print(f"error: events file not found: {events_path}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    try:
        config = load_config(args.config) if args.config else RaidWatchConfig()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    dry_run = not args.live and config.dry_run
    if args.live:
        dry_run = False

    channel_names = [c.strip() for c in args.channels.split(",") if c.strip()]
    if not channel_names:
        print("error: --channels must list at least one channel", file=sys.stderr)
        return EXIT_USAGE_ERROR

    events, bad_lines = read_events(events_path)
    if not events:
        print("no events to simulate (file is empty or all lines were skipped)")
        return EXIT_OK

    report = run_simulation(events, config, dry_run, channel_names)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_text_report(report, config)
    if bad_lines:
        print(f"({bad_lines} malformed lines skipped)", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
