import asyncio
import os
from typing import Optional

import discord
from discord.ext import commands

import theme

STAR = "⭐"
admin = commands.has_permissions(manage_guild=True)

DEFAULT_MESSAGES = {
    "welcome": "Welcome {user} to **{server}**! You are member #{count}.",
    "leave": "**{user.name}** has left the server.",
}


def render(template: str, member: discord.Member) -> str:
    return (
        template.replace("{user}", member.mention)
        .replace("{user.name}", member.name)
        .replace("{server}", member.guild.name)
        .replace("{count}", str(member.guild.member_count))
    )


def star_for(count: int) -> str:
    if count >= 20:
        return "✨"
    if count >= 10:
        return "💫"
    if count >= 5:
        return "🌟"
    return STAR


# ---------- ticket views (persistent: custom_ids survive restarts) ----------


class TicketControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        topic = getattr(channel, "topic", None) or ""
        if not topic.startswith("ticket:"):
            return await interaction.response.send_message("This isn't a ticket channel.", ephemeral=True)

        db = interaction.client.db
        is_owner = topic == f"ticket:{interaction.user.id}"
        is_staff = interaction.user.guild_permissions.manage_channels
        staff_id = await db.get_setting(interaction.guild.id, "ticket_staff_role")
        if staff_id and any(r.id == int(staff_id) for r in interaction.user.roles):
            is_staff = True
        if not (is_owner or is_staff):
            return await interaction.response.send_message(
                "Only staff or the ticket owner can close this.", ephemeral=True
            )

        await interaction.response.send_message(
            embed=theme.make("🔒 Closing this ticket in **5 seconds**...", kind="warn", prefix=False)
        )
        await asyncio.sleep(5)
        await channel.delete(reason=f"Ticket closed by {interaction.user}")


class TicketPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open a ticket", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        db = interaction.client.db

        for ch in guild.text_channels:
            if ch.topic == f"ticket:{interaction.user.id}":
                return await interaction.response.send_message(
                    f"You already have a ticket open: {ch.mention}", ephemeral=True
                )

        category_id = await db.get_setting(guild.id, "ticket_category")
        staff_id = await db.get_setting(guild.id, "ticket_staff_role")
        category = guild.get_channel(int(category_id)) if category_id else None
        staff_role = guild.get_role(int(staff_id)) if staff_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True
            ),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_messages=True
            )

        channel = await guild.create_text_channel(
            f"ticket-{interaction.user.name}"[:90],
            category=category if isinstance(category, discord.CategoryChannel) else None,
            topic=f"ticket:{interaction.user.id}",
            overwrites=overwrites,
            reason=f"Ticket opened by {interaction.user}",
        )
        ping = f"{interaction.user.mention} {staff_role.mention if staff_role else ''}".strip()
        embed = discord.Embed(
            title="🎫 Ticket opened",
            description="Thanks for reaching out! Describe your issue and a staff member will be with you shortly.\n\nPress the button below when you're done.",
            color=theme.PURPLE,
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await channel.send(
            content=ping,
            embed=embed,
            view=TicketControls(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
        )
        await interaction.response.send_message(f"🎫 Ticket created: {channel.mention}", ephemeral=True)


class ServerSetup(commands.Cog, name="Server Setup"):
    """Welcome/leave messages, autorole, reaction roles, tickets, starboard."""

    emoji = "⚙️"

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TicketPanel())
        self.bot.add_view(TicketControls())

    # ---------- prefix & overview ----------

    @commands.hybrid_command(aliases=["setprefix"], description="Show or change the command prefix")
    @commands.guild_only()
    async def prefix(self, ctx, new_prefix: Optional[str] = None):
        default = os.getenv("DEFAULT_PREFIX", ";")
        if new_prefix is None:
            current = await self.bot.db.get_setting(ctx.guild.id, "prefix", default)
            return await theme.info(ctx, f"The prefix here is `{current}`.")
        if not ctx.author.guild_permissions.manage_guild:
            return await theme.bad(ctx, "You need the Manage Server permission to change the prefix.")
        if len(new_prefix) > 5:
            return await theme.bad(ctx, "The prefix can be at most 5 characters.")
        await self.bot.db.set_setting(ctx.guild.id, "prefix", new_prefix)
        await theme.ok(ctx, f"Prefix changed to `{new_prefix}`.")

    @commands.hybrid_command(aliases=["config", "serversettings"], description="Show this server's bot settings")
    @commands.guild_only()
    @admin
    async def settings(self, ctx):
        db = self.bot.db
        g = ctx.guild

        async def chan(key):
            value = await db.get_setting(g.id, key)
            return f"<#{value}>" if value else "*not set*"

        async def role(key):
            value = await db.get_setting(g.id, key)
            return f"<@&{value}>" if value else "*not set*"

        prefix = await db.get_setting(g.id, "prefix", os.getenv("DEFAULT_PREFIX", ";"))
        threshold = await db.get_setting(g.id, "starboard_threshold", 3)
        rr_count = await db.fetchone("SELECT COUNT(*) AS c FROM reaction_roles WHERE guild_id=?", (g.id,))

        embed = discord.Embed(title=f"⚙️ Settings · {g.name}", color=theme.PURPLE)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="Prefix", value=f"`{prefix}`")
        embed.add_field(name="📜 Mod log", value=await chan("modlog_channel"))
        embed.add_field(name="🎭 Autorole", value=await role("autorole"))
        embed.add_field(name="👋 Welcome", value=await chan("welcome_channel"))
        embed.add_field(name="🚪 Leave", value=await chan("leave_channel"))
        embed.add_field(name="⭐ Starboard", value=f"{await chan('starboard_channel')} · {threshold} stars")
        embed.add_field(name="🎫 Ticket category", value=await chan("ticket_category"))
        embed.add_field(name="🛠️ Ticket staff", value=await role("ticket_staff_role"))
        embed.add_field(name="🎯 Reaction roles", value=str(rr_count["c"]))
        await ctx.send(embed=embed)

    # ---------- welcome / leave ----------

    async def _greet(self, member: discord.Member, kind: str):
        db = self.bot.db
        chan_id = await db.get_setting(member.guild.id, f"{kind}_channel")
        if not chan_id:
            return
        channel = member.guild.get_channel(int(chan_id))
        if not channel:
            return
        template = await db.get_setting(member.guild.id, f"{kind}_message", DEFAULT_MESSAGES[kind])
        count = member.guild.member_count

        if kind == "welcome":
            embed = discord.Embed(
                title="👋 Welcome!",
                description=render(template, member),
                color=theme.PURPLE,
                timestamp=discord.utils.utcnow(),
            )
            embed.set_footer(text=f"Member #{count}")
            content = member.mention
        else:
            embed = discord.Embed(
                title="🚪 Goodbye",
                description=render(template, member),
                color=theme.RED,
                timestamp=discord.utils.utcnow(),
            )
            embed.set_footer(text=f"{count} members left")
            content = None
        embed.set_thumbnail(url=member.display_avatar.url)
        try:
            await channel.send(
                content=content, embed=embed, allowed_mentions=discord.AllowedMentions(users=True)
            )
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._greet(member, "welcome")
        role_id = await self.bot.db.get_setting(member.guild.id, "autorole")
        if role_id:
            role = member.guild.get_role(int(role_id))
            if role:
                try:
                    await member.add_roles(role, reason="Autorole")
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._greet(member, "leave")

    @commands.hybrid_group(name="welcome", invoke_without_command=True)
    @commands.guild_only()
    @admin
    async def welcome(self, ctx):
        """Welcome messages. Placeholders: {user} {user.name} {server} {count}"""
        await theme.group_help(ctx)

    @welcome.command(name="channel", description="Set the welcome channel")
    @admin
    async def welcome_channel(self, ctx, channel: discord.TextChannel):
        await self.bot.db.set_setting(ctx.guild.id, "welcome_channel", channel.id)
        await theme.ok(ctx, f"👋 Welcome messages will be sent in {channel.mention}.", prefix=False)

    @welcome.command(name="message", description="Set the welcome message text")
    @admin
    async def welcome_message(self, ctx, *, text: str):
        await self.bot.db.set_setting(ctx.guild.id, "welcome_message", text)
        await theme.ok(ctx, "Welcome message updated. Use `welcome test` to preview it.")

    @welcome.command(name="test", description="Preview the welcome message")
    @admin
    async def welcome_test(self, ctx):
        await self._greet(ctx.author, "welcome")
        await theme.info(ctx, "Sent a test welcome message.", ephemeral=True)

    @welcome.command(name="off", description="Turn welcome messages off")
    @admin
    async def welcome_off(self, ctx):
        await self.bot.db.del_setting(ctx.guild.id, "welcome_channel")
        await theme.ok(ctx, "Welcome messages turned off.")

    @commands.hybrid_group(name="leave", invoke_without_command=True)
    @commands.guild_only()
    @admin
    async def leave(self, ctx):
        """Leave messages. Placeholders: {user} {user.name} {server} {count}"""
        await theme.group_help(ctx)

    @leave.command(name="channel", description="Set the leave message channel")
    @admin
    async def leave_channel(self, ctx, channel: discord.TextChannel):
        await self.bot.db.set_setting(ctx.guild.id, "leave_channel", channel.id)
        await theme.ok(ctx, f"🚪 Leave messages will be sent in {channel.mention}.", prefix=False)

    @leave.command(name="message", description="Set the leave message text")
    @admin
    async def leave_message(self, ctx, *, text: str):
        await self.bot.db.set_setting(ctx.guild.id, "leave_message", text)
        await theme.ok(ctx, "Leave message updated.")

    @leave.command(name="off", description="Turn leave messages off")
    @admin
    async def leave_off(self, ctx):
        await self.bot.db.del_setting(ctx.guild.id, "leave_channel")
        await theme.ok(ctx, "Leave messages turned off.")

    # ---------- autorole ----------

    @commands.hybrid_command(description="Give new members a role automatically (leave empty to turn off)")
    @commands.guild_only()
    @admin
    @commands.bot_has_permissions(manage_roles=True)
    async def autorole(self, ctx, role: Optional[discord.Role] = None):
        if role is None:
            await self.bot.db.del_setting(ctx.guild.id, "autorole")
            return await theme.ok(ctx, "Autorole turned off.")
        if role >= ctx.guild.me.top_role:
            return await theme.bad(ctx, "That role is higher than my top role, so I can't hand it out.")
        await self.bot.db.set_setting(ctx.guild.id, "autorole", role.id)
        await theme.ok(ctx, f"🎭 New members will get **{role.name}**.", prefix=False)

    # ---------- reaction roles ----------

    @commands.hybrid_group(name="reactionrole", aliases=["rr"], invoke_without_command=True)
    @commands.guild_only()
    @admin
    async def reactionrole(self, ctx):
        """Hand out roles when members react to a message."""
        await theme.group_help(ctx)

    @reactionrole.command(name="add", description="React with an emoji on a message to get a role")
    @admin
    @commands.bot_has_permissions(manage_roles=True)
    async def rr_add(self, ctx, message: discord.Message, emoji: str, role: discord.Role):
        if role >= ctx.guild.me.top_role:
            return await theme.bad(ctx, "That role is higher than my top role.")
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            return await theme.bad(ctx, "I couldn't use that emoji (custom emoji must be from a server I'm in).")
        key = str(discord.PartialEmoji.from_str(emoji))
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO reaction_roles (guild_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?)",
            (ctx.guild.id, message.id, key, role.id),
        )
        await theme.ok(ctx, f"Reacting with {emoji} on that message now gives **{role.name}**.")

    @reactionrole.command(name="remove", description="Remove a reaction role")
    @admin
    async def rr_remove(self, ctx, message: discord.Message, emoji: str):
        key = str(discord.PartialEmoji.from_str(emoji))
        cur = await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE message_id=? AND emoji=?", (message.id, key)
        )
        if cur.rowcount:
            await theme.ok(ctx, "Reaction role removed.")
        else:
            await theme.bad(ctx, "No reaction role found for that emoji.")

    @reactionrole.command(name="list", description="List reaction roles in this server")
    @admin
    async def rr_list(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT message_id, emoji, role_id FROM reaction_roles WHERE guild_id=?", (ctx.guild.id,)
        )
        if not rows:
            return await theme.info(ctx, "No reaction roles set up yet.")
        groups = theme.chunk(rows, 10)
        embeds = []
        for number, group in enumerate(groups, start=1):
            lines = [f"{r['emoji']} → <@&{r['role_id']}> · message `{r['message_id']}`" for r in group]
            embed = discord.Embed(title="🎯 Reaction roles", description="\n".join(lines), color=theme.PURPLE)
            embed.set_footer(text=f"{len(rows)} total · page {number}/{len(groups)}")
            embeds.append(embed)
        await theme.paginate(ctx, embeds)

    @commands.Cog.listener("on_raw_reaction_add")
    async def rr_on_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or (payload.member and payload.member.bot):
            return
        row = await self.bot.db.fetchone(
            "SELECT role_id FROM reaction_roles WHERE message_id=? AND emoji=?",
            (payload.message_id, str(payload.emoji)),
        )
        if not row or not payload.member:
            return
        role = payload.member.guild.get_role(row["role_id"])
        if role:
            try:
                await payload.member.add_roles(role, reason="Reaction role")
            except discord.HTTPException:
                pass

    @commands.Cog.listener("on_raw_reaction_remove")
    async def rr_on_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        row = await self.bot.db.fetchone(
            "SELECT role_id FROM reaction_roles WHERE message_id=? AND emoji=?",
            (payload.message_id, str(payload.emoji)),
        )
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        role = guild.get_role(row["role_id"]) if guild else None
        if member and role and not member.bot:
            try:
                await member.remove_roles(role, reason="Reaction role")
            except discord.HTTPException:
                pass

    # ---------- starboard ----------

    @commands.hybrid_group(name="starboard", invoke_without_command=True)
    @commands.guild_only()
    @admin
    async def starboard(self, ctx):
        """Repost messages that get enough ⭐ reactions."""
        await theme.group_help(ctx)

    @starboard.command(name="channel", description="Set the starboard channel")
    @admin
    async def starboard_channel(self, ctx, channel: discord.TextChannel):
        await self.bot.db.set_setting(ctx.guild.id, "starboard_channel", channel.id)
        await theme.ok(ctx, f"⭐ Starred messages will be posted in {channel.mention}.", prefix=False)

    @starboard.command(name="threshold", description="How many stars a message needs")
    @admin
    async def starboard_threshold(self, ctx, stars: commands.Range[int, 1, 50]):
        await self.bot.db.set_setting(ctx.guild.id, "starboard_threshold", stars)
        await theme.ok(ctx, f"Messages now need **{stars}** ⭐ to hit the starboard.")

    @starboard.command(name="off", description="Turn the starboard off")
    @admin
    async def starboard_off(self, ctx):
        await self.bot.db.del_setting(ctx.guild.id, "starboard_channel")
        await theme.ok(ctx, "Starboard turned off.")

    async def _update_star(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or str(payload.emoji) != STAR:
            return
        db = self.bot.db
        star_chan_id = await db.get_setting(payload.guild_id, "starboard_channel")
        if not star_chan_id or int(star_chan_id) == payload.channel_id:
            return
        threshold = int(await db.get_setting(payload.guild_id, "starboard_threshold", 3))

        guild = self.bot.get_guild(payload.guild_id)
        star_channel = guild.get_channel(int(star_chan_id)) if guild else None
        channel = guild.get_channel_or_thread(payload.channel_id) if guild else None
        if not star_channel or not channel:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return

        reaction = discord.utils.get(message.reactions, emoji=STAR)
        count = 0
        if reaction:
            users = [u async for u in reaction.users() if u.id != message.author.id and not u.bot]
            count = len(users)

        content = f"{star_for(count)} **{count}** | {channel.mention}"
        row = await db.fetchone(
            "SELECT star_message_id FROM starboard_posts WHERE message_id=?", (message.id,)
        )
        if row:
            try:
                star_msg = await star_channel.fetch_message(row["star_message_id"])
                await star_msg.edit(content=content)
            except discord.NotFound:
                pass
        elif count >= threshold:
            embed = discord.Embed(
                description=message.content or None, color=theme.GOLD, timestamp=message.created_at
            )
            embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
            embed.add_field(name="Source", value=f"[Jump to message]({message.jump_url})", inline=False)
            image = next(
                (a for a in message.attachments if a.content_type and a.content_type.startswith("image/")),
                None,
            )
            if image:
                embed.set_image(url=image.url)
            star_msg = await star_channel.send(content, embed=embed)
            await db.execute(
                "INSERT INTO starboard_posts (guild_id, message_id, star_message_id) VALUES (?, ?, ?)",
                (payload.guild_id, message.id, star_msg.id),
            )

    @commands.Cog.listener("on_raw_reaction_add")
    async def star_on_add(self, payload: discord.RawReactionActionEvent):
        await self._update_star(payload)

    @commands.Cog.listener("on_raw_reaction_remove")
    async def star_on_remove(self, payload: discord.RawReactionActionEvent):
        await self._update_star(payload)

    # ---------- tickets ----------

    @commands.hybrid_group(name="ticket", invoke_without_command=True)
    @commands.guild_only()
    @admin
    async def ticket(self, ctx):
        """Support tickets opened with a button."""
        await theme.group_help(ctx)

    @ticket.command(name="panel", description="Post the 'Open a ticket' button")
    @admin
    @commands.bot_has_permissions(manage_channels=True)
    async def ticket_panel(self, ctx, channel: Optional[discord.TextChannel] = None):
        channel = channel or ctx.channel
        embed = discord.Embed(
            title="🎫 Support",
            description="Need help? Press the button below to open a **private** ticket with the staff team.",
            color=theme.PURPLE,
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await channel.send(embed=embed, view=TicketPanel())
        await theme.ok(ctx, f"Ticket panel posted in {channel.mention}.", ephemeral=True)

    @ticket.command(name="category", description="Category where new tickets are created")
    @admin
    async def ticket_category(self, ctx, category: discord.CategoryChannel):
        await self.bot.db.set_setting(ctx.guild.id, "ticket_category", category.id)
        await theme.ok(ctx, f"New tickets will be created under **{category.name}**.")

    @ticket.command(name="staffrole", description="Role that can see and close tickets")
    @admin
    async def ticket_staffrole(self, ctx, role: discord.Role):
        await self.bot.db.set_setting(ctx.guild.id, "ticket_staff_role", role.id)
        await theme.ok(ctx, f"**{role.name}** can now see and close tickets.")


async def setup(bot):
    await bot.add_cog(ServerSetup(bot))
