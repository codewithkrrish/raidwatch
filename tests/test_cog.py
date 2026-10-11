"""Tests for the raidwatch discord.py cog (wiring only, with fake Discord objects)."""

from datetime import datetime, timezone

import pytest

discord = pytest.importorskip("discord")

from raidwatch.cog import RaidWatchCog, account_age_days
from raidwatch.config import RaidWatchConfig


class FakeRole:
    pass


class FakeChannel:
    def __init__(self, channel_id: int, name: str) -> None:
        self.id = channel_id
        self.name = name
        self.permission_calls: list[dict] = []

    async def set_permissions(self, role, **kwargs):
        self.permission_calls.append(kwargs)


class FakeGuild:
    def __init__(self) -> None:
        self.default_role = FakeRole()
        self.text_channels = [FakeChannel(1, "general"), FakeChannel(2, "chat")]
        self.verification_level = discord.VerificationLevel.low
        self.edit_calls: list[dict] = []

    def get_channel(self, channel_id):
        for channel in self.text_channels:
            if channel.id == channel_id:
                return channel
        return None

    async def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        if "verification_level" in kwargs:
            self.verification_level = kwargs["verification_level"]


class FakeMember:
    def __init__(self, member_id: int, guild: FakeGuild, age_days: float = 0.0) -> None:
        self.id = member_id
        self.guild = guild
        now = datetime.now(timezone.utc).timestamp()
        self.created_at = datetime.fromtimestamp(
            now - age_days * 86_400.0, tz=timezone.utc
        )


class FakeBot:
    def __init__(self) -> None:
        self.cogs: list = []

    async def add_cog(self, cog):
        self.cogs.append(cog)


def make_cog(**config_kwargs) -> tuple[RaidWatchCog, FakeBot, FakeGuild]:
    config = RaidWatchConfig(join_threshold=5, **config_kwargs)
    bot = FakeBot()
    cog = RaidWatchCog(bot, config)
    return cog, bot, FakeGuild()


async def join_burst(cog: RaidWatchCog, guild: FakeGuild, count: int, start_id: int = 1):
    for i in range(count):
        await cog.on_member_join(FakeMember(start_id + i, guild))


@pytest.mark.asyncio
async def test_dry_run_never_locks():
    cog, _, guild = make_cog(dry_run=True)
    await join_burst(cog, guild, 10)
    assert cog._locked is False
    assert all(ch.permission_calls == [] for ch in guild.text_channels)


@pytest.mark.asyncio
async def test_live_lockdown_locks_channels():
    cog, _, guild = make_cog(dry_run=False)
    await join_burst(cog, guild, 5)
    assert cog._locked is True
    for channel in guild.text_channels:
        assert channel.permission_calls == [
            {"send_messages": False, "reason": "raidwatch: raid detected"}
        ]


@pytest.mark.asyncio
async def test_verification_gate_strategy():
    cog, _, guild = make_cog(dry_run=False, lockdown_strategy="verification_gate")
    await join_burst(cog, guild, 5)
    assert cog._locked is True
    assert guild.edit_calls == [
        {
            "verification_level": discord.VerificationLevel.high,
            "reason": "raidwatch: raid detected",
        }
    ]
    # channels untouched
    assert all(ch.permission_calls == [] for ch in guild.text_channels)


@pytest.mark.asyncio
async def test_no_alert_no_lockdown():
    cog, _, guild = make_cog(dry_run=False)
    await join_burst(cog, guild, 3)  # below threshold of 5
    assert cog._locked is False


@pytest.mark.asyncio
async def test_trusted_joins_ignored_by_cog():
    cog, _, guild = make_cog(dry_run=False)
    for i in range(10):
        await cog.on_member_join(FakeMember(i, guild, age_days=30.0))
    assert cog._locked is False


@pytest.mark.asyncio
async def test_unlock_restores_permissions():
    cog, _, guild = make_cog(dry_run=False)
    await join_burst(cog, guild, 5)
    assert cog._locked is True
    await cog._apply_unlock(guild)
    assert cog._locked is False
    for channel in guild.text_channels:
        assert channel.permission_calls[-1] == {
            "send_messages": None,
            "reason": "raidwatch: raid over",
        }


def test_account_age_days():
    created = datetime(2024, 1, 1, tzinfo=timezone.utc)
    joined = datetime(2024, 1, 11, tzinfo=timezone.utc).timestamp()
    assert account_age_days(created, joined) == pytest.approx(10.0)


def test_account_age_days_future_created_clamped():
    created = datetime(2027, 1, 1, tzinfo=timezone.utc)
    joined = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    assert account_age_days(created, joined) == 0.0
