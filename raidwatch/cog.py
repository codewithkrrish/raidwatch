"""raidwatch discord.py cog — thin integration layer.

All detection, planning, and config logic lives in the sibling modules;
this cog only wires them to Discord events and slash commands.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import discord
    from discord import app_commands
    from discord.ext import commands

    _DISCORD_AVAILABLE = True
except ImportError:  # pragma: no cover - discord.py is a runtime dependency
    discord = None  # type: ignore[assignment]
    app_commands = None  # type: ignore[assignment]
    commands = None  # type: ignore[assignment]
    _DISCORD_AVAILABLE = False

from raidwatch.config import ConfigError, RaidWatchConfig, load_config
from raidwatch.detector import JoinEvent, JoinVelocityDetector, RaidAlert
from raidwatch.lockdown import (
    STRATEGY_CHANNEL_LOCK,
    STRATEGY_VERIFICATION_GATE,
    ChannelSummary,
    LockdownAction,
    plan_lockdown,
    plan_unlock,
)
from raidwatch.storage import write_json_atomic

BRAND_RED = 0xE11D48
DEFAULT_CONFIG_PATH = "raidwatch_config.json"


def require_discord() -> None:
    """Raise a clear error when discord.py is not installed."""
    if not _DISCORD_AVAILABLE:
        raise RuntimeError(
            "discord.py is required to run the raidwatch cog "
            "(pip install 'raidwatch[bot]' or pip install discord.py)"
        )


def account_age_days(created_at: datetime, joined_at: float) -> float:
    """Age of a Discord account in days at join time."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    joined = datetime.fromtimestamp(joined_at, tz=timezone.utc)
    age = (joined - created_at).total_seconds() / 86_400.0
    return max(age, 0.0)


class RaidWatchCog(commands.Cog if _DISCORD_AVAILABLE else object):  # type: ignore[misc]
    """Anti-raid protection: join-velocity detection + automatic lockdown."""

    def __init__(
        self,
        bot: Any,
        config: RaidWatchConfig,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
    ) -> None:
        require_discord()
        self.bot = bot
        self.config = config
        self.config_path = Path(config_path)
        self.detector = self._build_detector()
        self._locked: bool = False
        self._lockdown_actions: list[LockdownAction] = []
        self._previous_verification_level: Any = None
        self._unlock_task: asyncio.Task[None] | None = None

    def _build_detector(self) -> JoinVelocityDetector:
        return JoinVelocityDetector(
            window_seconds=self.config.window_seconds,
            join_threshold=self.config.join_threshold,
            cooldown_seconds=self.config.cooldown_minutes * 60,
            trusted_account_age_days=self.config.trusted_account_age_days,
        )

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    @commands.Cog.listener()  # type: ignore[misc]
    async def on_member_join(self, member: Any) -> None:
        now = time.time()
        event = JoinEvent(
            timestamp=now,
            user_id=str(member.id),
            account_age_days=account_age_days(member.created_at, now),
        )
        alert = self.detector.record(event)
        if alert is None or self._locked:
            return
        await self._handle_alert(member.guild, alert)

    async def _handle_alert(self, guild: Any, alert: RaidAlert) -> None:
        actions = plan_lockdown(self._channel_summaries(guild), self.config.lockdown_strategy)
        if self.config.dry_run:
            await self._send_alert(guild, alert, actions, dry_run=True)
            return
        await self._apply_lockdown(guild, actions)
        await self._send_alert(guild, alert, actions, dry_run=False)
        if self.config.auto_unlock_minutes > 0:
            self._schedule_auto_unlock(guild)

    def _channel_summaries(self, guild: Any) -> list[ChannelSummary]:
        return [
            ChannelSummary(id=channel.id, name=channel.name)
            for channel in guild.text_channels
        ]

    async def _apply_lockdown(self, guild: Any, actions: list[LockdownAction]) -> None:
        for action in actions:
            if action.kind == STRATEGY_CHANNEL_LOCK and action.target_id is not None:
                channel = guild.get_channel(action.target_id)
                if channel is not None:
                    await channel.set_permissions(
                        guild.default_role,
                        send_messages=False,
                        reason="raidwatch: raid detected",
                    )
            elif action.kind == STRATEGY_VERIFICATION_GATE:
                self._previous_verification_level = guild.verification_level
                await guild.edit(
                    verification_level=discord.VerificationLevel.high,
                    reason="raidwatch: raid detected",
                )
        self._locked = True
        self._lockdown_actions = actions

    async def _apply_unlock(self, guild: Any) -> None:
        for action in plan_unlock(self._lockdown_actions):
            if action.kind == STRATEGY_CHANNEL_LOCK and action.target_id is not None:
                channel = guild.get_channel(action.target_id)
                if channel is not None:
                    await channel.set_permissions(
                        guild.default_role,
                        send_messages=None,
                        reason="raidwatch: raid over",
                    )
            elif action.kind == STRATEGY_VERIFICATION_GATE:
                await guild.edit(
                    verification_level=self._previous_verification_level,
                    reason="raidwatch: raid over",
                )
        self._locked = False
        self._lockdown_actions = []
        self.detector.reset()

    def _schedule_auto_unlock(self, guild: Any) -> None:
        if self._unlock_task is not None and not self._unlock_task.done():
            self._unlock_task.cancel()

        async def _unlock_later() -> None:
            await asyncio.sleep(self.config.auto_unlock_minutes * 60)
            if self._locked:
                await self._apply_unlock(guild)

        self._unlock_task = asyncio.create_task(_unlock_later())

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    async def _send_alert(
        self, guild: Any, alert: RaidAlert, actions: list[LockdownAction], *, dry_run: bool
    ) -> None:
        channel = (
            guild.get_channel(self.config.alert_channel_id)
            if self.config.alert_channel_id
            else None
        )
        if channel is None:
            return
        mode = "DRY RUN — no action taken" if dry_run else "LOCKDOWN APPLIED"
        mention = (
            f"<@&{self.config.staff_role_id}> " if self.config.staff_role_id else ""
        )
        embed = discord.Embed(
            title=f"Raid detected — {mode}",
            description=(
                f"{mention}{alert.joins_in_window} joins inside "
                f"{alert.window_seconds}s "
                f"({alert.joins_per_minute:.0f}/min)"
            ),
            color=BRAND_RED,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="Response plan",
            value="\n".join(f"- {a.target_name}: {a.detail}" for a in actions)
            or "none",
            inline=False,
        )
        if dry_run:
            embed.add_field(
                name="Next step",
                value="Disable dry-run with /raidwatch dryrun off to arm lockdowns.",
                inline=False,
            )
        await channel.send(embed=embed)

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    raidwatch = app_commands.Group(  # type: ignore[assignment]
        name="raidwatch", description="Raid protection controls"
    )

    @raidwatch.command(name="status", description="Show raidwatch status")
    async def status(self, interaction: Any) -> None:
        """Show detector settings and current lock state."""
        embed = discord.Embed(title="raidwatch status", color=BRAND_RED)
        embed.add_field(
            name="Detector",
            value=(
                f"{self.config.join_threshold} joins / {self.config.window_seconds}s, "
                f"{self.config.cooldown_minutes}m cooldown"
            ),
            inline=False,
        )
        embed.add_field(
            name="Mode",
            value="DRY RUN" if self.config.dry_run else "LIVE",
            inline=True,
        )
        embed.add_field(
            name="Lockdown",
            value="ACTIVE" if self._locked else "standby",
            inline=True,
        )
        embed.add_field(
            name="Joins in window",
            value=str(self.detector.pending_count(time.time())),
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @raidwatch.command(name="dryrun", description="Toggle dry-run mode")
    @app_commands.describe(enabled="True = report only, False = arm live lockdowns")
    async def dryrun(self, interaction: Any, enabled: bool) -> None:
        """Toggle dry-run mode and persist the config."""
        self.config.dry_run = enabled
        self._persist_config()
        state = "DRY RUN (report only)" if enabled else "LIVE (lockdowns armed)"
        await interaction.response.send_message(
            f"raidwatch mode: {state}", ephemeral=True
        )

    @raidwatch.command(name="unlock", description="Lift an active lockdown")
    async def unlock(self, interaction: Any) -> None:
        """Manually lift a lockdown."""
        if not self._locked:
            await interaction.response.send_message(
                "No active lockdown.", ephemeral=True
            )
            return
        await self._apply_unlock(interaction.guild)
        await interaction.response.send_message(
            "Lockdown lifted.", ephemeral=True
        )

    @raidwatch.command(name="simulate", description="Simulate a join burst")
    @app_commands.describe(
        joins="Number of joins to simulate", seconds="Over how many seconds"
    )
    async def simulate(self, interaction: Any, joins: int, seconds: int) -> None:
        """Feed synthetic joins through the detector (never locks)."""
        if joins < 1 or joins > 500 or seconds < 1 or seconds > 3600:
            await interaction.response.send_message(
                "Keep it sane: 1-500 joins over 1-3600 seconds.", ephemeral=True
            )
            return
        now = time.time()
        alert: RaidAlert | None = None
        for i in range(joins):
            ts = now - seconds + (seconds * i / max(joins - 1, 1))
            alert = self.detector.record(
                JoinEvent(timestamp=ts, user_id=f"sim-{i}", account_age_days=0.0)
            )
        self.detector.reset()
        if alert is None:
            verdict = "would NOT have triggered"
        else:
            verdict = (
                f"would have triggered on join #{alert.joins_in_window} "
                f"({alert.joins_per_minute:.0f}/min)"
            )
        await interaction.response.send_message(
            f"Simulation: {joins} joins over {seconds}s {verdict}.",
            ephemeral=True,
        )

    def _persist_config(self) -> None:
        write_json_atomic(self.config_path, self.config.to_dict())

    def cog_unload(self) -> None:
        if self._unlock_task is not None and not self._unlock_task.done():
            self._unlock_task.cancel()


async def setup(
    bot: Any,
    config: RaidWatchConfig | None = None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Load the raidwatch cog.

    Usage in your bot::

        from raidwatch.cog import setup as setup_raidwatch
        await setup_raidwatch(bot)
    """
    require_discord()
    cfg = config or load_config(config_path)
    await bot.add_cog(RaidWatchCog(bot, cfg, config_path=config_path))


__all__ = ["RaidWatchCog", "require_discord", "setup"]
