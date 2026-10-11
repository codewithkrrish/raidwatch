# raidwatch

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-65%20passing-brightgreen.svg)](#testing)

Anti-raid protection for discord.py bots. Detects join-velocity spikes with a
sliding time window, locks the server down automatically, and alerts staff —
with a dry-run mode so you can tune thresholds safely before going live.

Raids are bursts: 40 brand-new accounts joining in 30 seconds is never
organic. raidwatch watches the join rate, ignores established accounts (so
giveaways and announcement pings don't false-positive), and reacts in
seconds: channel lockdowns, a verification gate, or both.

## Quick demo

The bundled `raidwatch-sim` runs the exact same detector against a join log,
no Discord server needed:

```
$ raidwatch-sim joins.jsonl --channels general,chat,memes,announcements
raidwatch simulation report
  mode:            DRY RUN
  detector:        10 joins / 15s window, 30m cooldown, trust accounts older than 7d
  events:          20 total, 14 counted toward detection
  result:          RAID DETECTED x1
  alert 1:         10 joins in 15s (40.0/min) at 2026-10-11 11:00:09 UTC
  lockdown plan (channel_lock, DRY RUN):
    - [channel_lock] #general: Deny send_messages for @everyone
    - [channel_lock] #chat: Deny send_messages for @everyone
    - [channel_lock] #memes: Deny send_messages for @everyone
    - [channel_lock] #announcements: Deny send_messages for @everyone
  note:            dry run — nothing was actually locked
```

The 6 quiet joins from old accounts were ignored; the 14-account burst in
14 seconds tripped the threshold.

## Install

```bash
pip install raidwatch
```

Requires Python 3.10+ and discord.py 2.3+.

## Usage

### In your bot

```python
import discord
from discord.ext import commands
from raidwatch.cog import setup as setup_raidwatch

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

async def main():
    await setup_raidwatch(bot)  # reads raidwatch_config.json, dry-run by default
    await bot.start("YOUR_TOKEN")
```

The cog needs the **Server Members** privileged intent (`members=True`).

Then in Discord:

- `/raidwatch status` — detector settings, mode, current window count
- `/raidwatch dryrun <true|false>` — toggle report-only vs live lockdowns
- `/raidwatch unlock` — lift an active lockdown manually
- `/raidwatch simulate <joins> <seconds>` — test the detector with synthetic joins

### Tune thresholds offline

```bash
# JSONL of joins: {"ts": 1728566400.0, "user_id": "123", "account_created": "2024-01-02T15:04:05"}
raidwatch-sim joins.jsonl --config myconfig.json
raidwatch-sim joins.jsonl --json   # machine-readable report
```

### Configuration

Copy `examples/config.example.json` to `raidwatch_config.json`:

| Key | Default | What it does |
| --- | --- | --- |
| `window_seconds` | 15 | Sliding window for join counting |
| `join_threshold` | 10 | Joins inside the window that trip an alert |
| `cooldown_minutes` | 30 | Quiet period after an alert before it can fire again |
| `dry_run` | `true` | Report what *would* happen; never lock (safe default) |
| `lockdown_strategy` | `"channel_lock"` | `"channel_lock"`, `"verification_gate"`, or `"both"` |
| `alert_channel_id` | `null` | Where staff alerts go |
| `staff_role_id` | `null` | Role pinged on alerts |
| `trusted_account_age_days` | 7 | Accounts older than this don't count toward the window |
| `auto_unlock_minutes` | 0 | Auto-lift after N minutes (`0` = manual only) |

## How it works

1. `on_member_join` records each join with the account's age.
2. `JoinVelocityDetector` keeps a sliding window of recent untrusted joins;
   hitting the threshold raises an alert (then a cooldown starts).
3. `plan_lockdown` builds the exact action list for the strategy —
   the same plan is shown in dry-run mode, so what you preview is what runs.
4. The cog applies it: `@everyone` loses `send_messages` per text channel
   and/or the verification level is raised to HIGH; a staff embed goes out.
5. `/raidwatch unlock` (or the auto-unlock timer) reverses every action.

## Project structure

```
raidwatch/
  raidwatch/
    __init__.py    public API + version
    detector.py    sliding-window join-velocity detector (pure logic)
    config.py      typed, validated configuration
    lockdown.py    lockdown planning: what a response does, before it does it
    storage.py     crash-safe atomic JSON persistence
    cli.py         raidwatch-sim: offline detector simulator
    cog.py         discord.py cog — thin integration layer
  tests/           pytest suite (detector, config, storage, lockdown, cli, cog)
  examples/        config.example.json
```

## Testing

```bash
pip install "raidwatch[dev]"
pytest
```

65 tests covering the happy path and the edges: slow joins, cooldown
suppression, trusted-account filtering, corrupt/empty inputs, bad flags,
lockdown planning and reversal, and the cog's wiring against fake
Discord objects.

## License

MIT — see [LICENSE](LICENSE).

Author: [Krrish](https://github.com/codewithkrrish)
