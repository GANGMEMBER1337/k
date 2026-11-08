import datetime as dt
import re
from typing import Optional

import discord
from discord.ext import commands

import theme

DURATION_RE = re.compile(r"^(\d+)([smhdw])$")
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
MAX_TIMEOUT = dt.timedelta(days=28)


def parse_duration(text: str) -> Optional[dt.timedelta]:
    match = DURATION_RE.match(text.strip().lower())
    if not match:
        return None
    return dt.timedelta(seconds=int(match[1]) * UNITS[match[2]])


class Moderation(commands.Cog, name="Moderation"):
    """Moderation commands."""

    emoji = "🛡️"

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

    async def log(self, guild, emoji, action, target, moderator, reason, color=theme.RED):
        chan_id = await self.bot.db.get_setting(guild.id, "modlog_channel")
        if not chan_id:
            return
        channel = guild.get_channel(int(chan_id))
        if not channel:
            return
        embed = discord.Embed(title=f"{emoji} {action}", color=color, timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="User", value=f"{target.mention}\n`{target.id}`")
        embed.add_field(name="Moderator", value=f"{moderator.mention}\n`{moderator.id}`")
        embed.add_field(name="Reason", value=(reason or "No reason given")[:1024], inline=False)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def notify(self, user, guild, verb, reason, color=theme.RED, duration=None) -> bool:
        """DM the user an embed. Returns True if it was delivered."""
        embed = discord.Embed(
            title=f"You were {verb} in {guild.name}", color=color, timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Reason", value=(reason or "No reason given")[:1024], inline=False)
        if duration:
            embed.add_field(name="Duration", value=duration)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        try:
            await user.send(embed=embed)
            return True
        except discord.HTTPException:
            return False

    @staticmethod
    def dm_note(sent: bool) -> str:
        return "" if sent else " *(couldn't DM them)*"

    @staticmethod
    def audit_reason(ctx, reason):
        return f"{ctx.author} ({ctx.author.id}): {reason or 'No reason given'}"[:512]

    # ---------- ban / kick ----------

    @commands.hybrid_command(aliases=["b"], description="Ban a user (works on users not in the server too)")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, user: discord.User, *, reason: Optional[str] = None):
        if user.id == ctx.author.id:
            return await theme.bad(ctx, "You can't ban yourself.")
        member = ctx.guild.get_member(user.id)
        if member and (err := self.hierarchy_error(ctx, member)):
            return await theme.bad(ctx, err)
        if not await theme.confirm(ctx, f"Ban **{user}**?\nReason: {reason or 'No reason given'}"):
            return
        sent = await self.notify(user, ctx.guild, "banned", reason)
        await ctx.guild.ban(user, reason=self.audit_reason(ctx, reason))
        await theme.ok(ctx, f"🔨 Banned **{user}**.{self.dm_note(sent)}", prefix=False)
        await self.log(ctx.guild, "🔨", "Ban", user, ctx.author, reason)

    @commands.hybrid_command(aliases=["ub"], description="Unban a user")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx, user: discord.User, *, reason: Optional[str] = None):
        try:
            await ctx.guild.unban(user, reason=self.audit_reason(ctx, reason))
        except discord.NotFound:
            return await theme.bad(ctx, "That user isn't banned.")
        await theme.ok(ctx, f"Unbanned **{user}**.")
        await self.log(ctx.guild, "🕊️", "Unban", user, ctx.author, reason, color=theme.GREEN)

    @commands.hybrid_command(aliases=["k"], description="Kick a member")
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: Optional[str] = None):
        if err := self.hierarchy_error(ctx, member):
            return await theme.bad(ctx, err)
        if not await theme.confirm(ctx, f"Kick **{member}**?\nReason: {reason or 'No reason given'}"):
            return
        sent = await self.notify(member, ctx.guild, "kicked", reason, color=theme.ORANGE)
        await member.kick(reason=self.audit_reason(ctx, reason))
        await theme.ok(ctx, f"👢 Kicked **{member}**.{self.dm_note(sent)}", prefix=False)
        await self.log(ctx.guild, "👢", "Kick", member, ctx.author, reason, color=theme.ORANGE)

    # ---------- timeout ----------

    @commands.hybrid_command(
        aliases=["mute", "to"], description="Timeout a member, e.g. duration 10m, 2h, 1d (max 28d)"
    )
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, duration: str, *, reason: Optional[str] = None):
        delta = parse_duration(duration)
        if not delta or delta > MAX_TIMEOUT:
            return await theme.bad(ctx, "Use a duration like `30m`, `2h` or `1d` (max 28d).")
        if err := self.hierarchy_error(ctx, member):
            return await theme.bad(ctx, err)
        sent = await self.notify(member, ctx.guild, "timed out", reason, color=theme.YELLOW, duration=duration)
        await member.timeout(delta, reason=self.audit_reason(ctx, reason))
        await theme.ok(ctx, f"🔇 Timed out **{member}** for **{duration}**.{self.dm_note(sent)}", prefix=False)
        await self.log(ctx.guild, "🔇", f"Timeout ({duration})", member, ctx.author, reason, color=theme.YELLOW)

    @commands.hybrid_command(aliases=["unmute"], description="Remove a member's timeout")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member, *, reason: Optional[str] = None):
        if not member.is_timed_out():
            return await theme.info(ctx, f"**{member}** isn't timed out.")
        await member.timeout(None, reason=self.audit_reason(ctx, reason))
        await theme.ok(ctx, f"🔊 Removed the timeout from **{member}**.", prefix=False)
        await self.log(ctx.guild, "🔊", "Timeout removed", member, ctx.author, reason, color=theme.GREEN)

    # ---------- warnings ----------

    @commands.hybrid_command(aliases=["w"], description="Warn a member")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str):
        if err := self.hierarchy_error(ctx, member):
            return await theme.bad(ctx, err)
        db = self.bot.db
        await db.execute(
            "INSERT INTO warnings (guild_id, user_id, mod_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, member.id, ctx.author.id, reason, discord.utils.utcnow().isoformat()),
        )
        row = await db.fetchone(
            "SELECT COUNT(*) AS c FROM warnings WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, member.id),
        )
        sent = await self.notify(member, ctx.guild, "warned", reason, color=theme.YELLOW)
        await theme.warn(
            ctx, f"Warned **{member}**. That's warning **#{row['c']}**.{self.dm_note(sent)}"
        )
        await self.log(ctx.guild, "⚠️", "Warning", member, ctx.author, reason, color=theme.YELLOW)

    @commands.hybrid_command(aliases=["warns", "infractions"], description="List a member's warnings")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx, member: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT id, mod_id, reason, created_at FROM warnings "
            "WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 50",
            (ctx.guild.id, member.id),
        )
        if not rows:
            return await theme.ok(ctx, f"**{member}** has a clean record.")
        groups = theme.chunk(rows, 5)
        embeds = []
        for number, group in enumerate(groups, start=1):
            lines = []
            for r in group:
                ts = int(dt.datetime.fromisoformat(r["created_at"]).timestamp())
                lines.append(f"`#{r['id']}` {r['reason']}\n> by <@{r['mod_id']}> · <t:{ts}:R>")
            embed = discord.Embed(
                title=f"⚠️ Warnings for {member}", description="\n\n".join(lines), color=theme.YELLOW
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"{len(rows)} total · page {number}/{len(groups)}")
            embeds.append(embed)
        await theme.paginate(ctx, embeds)

    @commands.hybrid_command(aliases=["clearwarns"], description="Clear all of a member's warnings")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def clearwarnings(self, ctx, member: discord.Member):
        if not await theme.confirm(ctx, f"Clear **all** warnings for **{member}**?"):
            return
        cur = await self.bot.db.execute(
            "DELETE FROM warnings WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id)
        )
        await theme.ok(ctx, f"Cleared **{cur.rowcount}** warning(s) for **{member}**.")

    # ---------- channel tools ----------

    @commands.hybrid_command(
        aliases=["p", "clear", "c"], description="Bulk delete messages (optionally only from one member)"
    )
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
        await theme.ok(
            ctx,
            f"🧹 Swept **{len(deleted)}** message(s).",
            prefix=False,
            ephemeral=True,
            delete_after=None if ctx.interaction else 5,
        )

    @commands.hybrid_command(aliases=["sm"], description="Set slowmode for this channel in seconds (0 turns it off)")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: commands.Range[int, 0, 21600]):
        await ctx.channel.edit(slowmode_delay=seconds, reason=self.audit_reason(ctx, "slowmode"))
        if seconds == 0:
            return await theme.ok(ctx, "🐇 Slowmode is off.", prefix=False)
        await theme.ok(ctx, f"🐢 Slowmode set to **{seconds}s**.", prefix=False)

    @commands.hybrid_command(aliases=["lockdown"], description="Stop @everyone from sending messages in this channel")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def lock(self, ctx):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await theme.ok(ctx, f"🔒 Locked {ctx.channel.mention}.", prefix=False)

    @commands.hybrid_command(aliases=["ul"], description="Let @everyone send messages in this channel again")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unlock(self, ctx):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await theme.ok(ctx, f"🔓 Unlocked {ctx.channel.mention}.", prefix=False)

    # ---------- members ----------

    @commands.hybrid_command(aliases=["nickname"], description="Change (or reset) a member's nickname")
    @commands.guild_only()
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, nickname: Optional[str] = None):
        if member.id != ctx.author.id and (err := self.hierarchy_error(ctx, member)):
            return await theme.bad(ctx, err)
        if nickname and len(nickname) > 32:
            return await theme.bad(ctx, "Nicknames can be at most 32 characters.")
        await member.edit(nick=nickname, reason=self.audit_reason(ctx, "nickname change"))
        if nickname:
            await theme.ok(ctx, f"✏️ **{member.name}** is now called **{nickname}**.", prefix=False)
        else:
            await theme.ok(ctx, f"✏️ Reset the nickname for **{member.name}**.", prefix=False)

    @commands.hybrid_command(aliases=["r"], description="Add a role to a member, or remove it if they have it")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role(self, ctx, member: discord.Member, *, role: discord.Role):
        if role.is_default() or role.managed:
            return await theme.bad(ctx, "I can't hand out that role.")
        if ctx.author.id != ctx.guild.owner_id and role >= ctx.author.top_role:
            return await theme.bad(ctx, "That role is equal to or higher than your top role.")
        if role >= ctx.guild.me.top_role:
            return await theme.bad(ctx, "That role is higher than my top role.")
        reason = self.audit_reason(ctx, "role command")
        if role in member.roles:
            await member.remove_roles(role, reason=reason)
            await theme.ok(ctx, f"➖ Removed **{role.name}** from **{member.name}**.", prefix=False)
        else:
            await member.add_roles(role, reason=reason)
            await theme.ok(ctx, f"➕ Gave **{role.name}** to **{member.name}**.", prefix=False)

    # ---------- mod log ----------

    @commands.hybrid_command(aliases=["logs"], description="Set the mod log channel (leave empty to turn it off)")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def modlog(self, ctx, channel: Optional[discord.TextChannel] = None):
        if channel is None:
            await self.bot.db.del_setting(ctx.guild.id, "modlog_channel")
            return await theme.ok(ctx, "Mod log turned off.")
        await self.bot.db.set_setting(ctx.guild.id, "modlog_channel", channel.id)
        await theme.ok(ctx, f"📜 Mod actions will be logged in {channel.mention}.", prefix=False)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
