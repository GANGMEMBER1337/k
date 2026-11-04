import datetime as dt
import re
from typing import Optional

import discord
from discord.ext import commands

DURATION_RE = re.compile(r"^(\d+)([smhdw])$")
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
MAX_TIMEOUT = dt.timedelta(days=28)


def parse_duration(text: str) -> Optional[dt.timedelta]:
    match = DURATION_RE.match(text.strip().lower())
    if not match:
        return None
    return dt.timedelta(seconds=int(match[1]) * UNITS[match[2]])


class Moderation(commands.Cog):
    """Moderation commands."""

    def __init__(self, bot):
        self.bot = bot

    # ---------- helpers ----------

    @staticmethod
    def hierarchy_error(ctx, target: discord.Member) -> Optional[str]:
        if target.id == ctx.author.id:
            return "You can't do that to yourself."
        if target.id == ctx.guild.owner_id:
            return "You can't do that to the server owner."
        if target.id == ctx.guild.me.id:
            return "Nice try."
        if ctx.author.id != ctx.guild.owner_id and target.top_role >= ctx.author.top_role:
            return "That member's top role is equal to or higher than yours."
        if target.top_role >= ctx.guild.me.top_role:
            return "That member's top role is higher than mine."
        return None

    async def log(self, guild, action, target, moderator, reason, color=0xE74C3C):
        chan_id = await self.bot.db.get_setting(guild.id, "modlog_channel")
        if not chan_id:
            return
        channel = guild.get_channel(int(chan_id))
        if not channel:
            return
        embed = discord.Embed(title=action, color=color, timestamp=discord.utils.utcnow())
        embed.add_field(name="User", value=f"{target} ({target.id})")
        embed.add_field(name="Moderator", value=f"{moderator} ({moderator.id})")
        embed.add_field(name="Reason", value=reason or "No reason given", inline=False)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @staticmethod
    def audit_reason(ctx, reason):
        return f"{ctx.author} ({ctx.author.id}): {reason or 'No reason given'}"[:512]

    # ---------- ban / kick ----------

    @commands.hybrid_command(description="Ban a user (works on users not in the server too)")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, user: discord.User, *, reason: Optional[str] = None):
        if user.id == ctx.author.id:
            return await ctx.send("You can't ban yourself.", ephemeral=True)
        member = ctx.guild.get_member(user.id)
        if member and (err := self.hierarchy_error(ctx, member)):
            return await ctx.send(err, ephemeral=True)
        await ctx.guild.ban(user, reason=self.audit_reason(ctx, reason))
        await ctx.send(f"Banned **{user}**.")
        await self.log(ctx.guild, "Ban", user, ctx.author, reason)

    @commands.hybrid_command(description="Unban a user")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx, user: discord.User, *, reason: Optional[str] = None):
        try:
            await ctx.guild.unban(user, reason=self.audit_reason(ctx, reason))
        except discord.NotFound:
            return await ctx.send("That user isn't banned.", ephemeral=True)
        await ctx.send(f"Unbanned **{user}**.")
        await self.log(ctx.guild, "Unban", user, ctx.author, reason, color=0x2ECC71)

    @commands.hybrid_command(description="Kick a member")
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: Optional[str] = None):
        if err := self.hierarchy_error(ctx, member):
            return await ctx.send(err, ephemeral=True)
        await member.kick(reason=self.audit_reason(ctx, reason))
        await ctx.send(f"Kicked **{member}**.")
        await self.log(ctx.guild, "Kick", member, ctx.author, reason, color=0xE67E22)

    # ---------- timeout ----------

    @commands.hybrid_command(description="Timeout a member, e.g. duration 10m, 2h, 1d (max 28d)")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, duration: str, *, reason: Optional[str] = None):
        delta = parse_duration(duration)
        if not delta or delta > MAX_TIMEOUT:
            return await ctx.send("Use a duration like `30m`, `2h` or `1d` (max 28d).", ephemeral=True)
        if err := self.hierarchy_error(ctx, member):
            return await ctx.send(err, ephemeral=True)
        await member.timeout(delta, reason=self.audit_reason(ctx, reason))
        await ctx.send(f"Timed out **{member}** for {duration}.")
        await self.log(ctx.guild, f"Timeout ({duration})", member, ctx.author, reason, color=0xF1C40F)

    @commands.hybrid_command(description="Remove a member's timeout")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member, *, reason: Optional[str] = None):
        await member.timeout(None, reason=self.audit_reason(ctx, reason))
        await ctx.send(f"Removed timeout from **{member}**.")
        await self.log(ctx.guild, "Timeout removed", member, ctx.author, reason, color=0x2ECC71)

    # ---------- warnings ----------

    @commands.hybrid_command(description="Warn a member")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str):
        if err := self.hierarchy_error(ctx, member):
            return await ctx.send(err, ephemeral=True)
        db = self.bot.db
        await db.execute(
            "INSERT INTO warnings (guild_id, user_id, mod_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, member.id, ctx.author.id, reason, discord.utils.utcnow().isoformat()),
        )
        row = await db.fetchone(
            "SELECT COUNT(*) AS c FROM warnings WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, member.id),
        )
        await ctx.send(f"Warned **{member}** (warning #{row['c']}).")
        try:
            await member.send(f"You were warned in **{ctx.guild.name}**: {reason}")
        except discord.HTTPException:
            pass
        await self.log(ctx.guild, "Warning", member, ctx.author, reason, color=0xF1C40F)

    @commands.hybrid_command(description="List a member's warnings")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx, member: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT id, mod_id, reason, created_at FROM warnings "
            "WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
            (ctx.guild.id, member.id),
        )
        if not rows:
            return await ctx.send(f"**{member}** has no warnings.")
        lines = []
        for r in rows:
            ts = int(dt.datetime.fromisoformat(r["created_at"]).timestamp())
            lines.append(f"`#{r['id']}` {r['reason']} (by <@{r['mod_id']}>, <t:{ts}:R>)")
        embed = discord.Embed(
            title=f"Warnings for {member}", description="\n".join(lines), color=0xF1C40F
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(description="Clear all of a member's warnings")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def clearwarnings(self, ctx, member: discord.Member):
        cur = await self.bot.db.execute(
            "DELETE FROM warnings WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id)
        )
        await ctx.send(f"Cleared {cur.rowcount} warning(s) for **{member}**.")

    # ---------- channel tools ----------

    @commands.hybrid_command(description="Bulk delete messages (optionally only from one member)")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(self, ctx, amount: commands.Range[int, 1, 500], user: Optional[discord.Member] = None):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        else:
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass

        matched = 0

        def check(message):
            nonlocal matched
            if matched >= amount:
                return False
            if user and message.author.id != user.id:
                return False
            matched += 1
            return True

        # With a user filter, scan further back so we can find enough of their messages.
        deleted = await ctx.channel.purge(limit=1000 if user else amount, check=check)
        await ctx.send(
            f"Deleted {len(deleted)} message(s).",
            ephemeral=True,
            delete_after=None if ctx.interaction else 5,
        )

    @commands.hybrid_command(description="Set slowmode for this channel in seconds (0 turns it off)")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: commands.Range[int, 0, 21600]):
        await ctx.channel.edit(slowmode_delay=seconds, reason=self.audit_reason(ctx, "slowmode"))
        await ctx.send("Slowmode disabled." if seconds == 0 else f"Slowmode set to {seconds}s.")

    @commands.hybrid_command(description="Stop @everyone from sending messages in this channel")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def lock(self, ctx):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send("Channel locked.")

    @commands.hybrid_command(description="Let @everyone send messages in this channel again")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unlock(self, ctx):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send("Channel unlocked.")

    # ---------- mod log ----------

    @commands.hybrid_command(description="Set the mod log channel (leave empty to turn it off)")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def modlog(self, ctx, channel: Optional[discord.TextChannel] = None):
        if channel is None:
            await self.bot.db.del_setting(ctx.guild.id, "modlog_channel")
            return await ctx.send("Mod log turned off.")
        await self.bot.db.set_setting(ctx.guild.id, "modlog_channel", channel.id)
        await ctx.send(f"Mod actions will be logged in {channel.mention}.")


async def setup(bot):
    await bot.add_cog(Moderation(bot))
