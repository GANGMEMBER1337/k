import os
import platform
import random
import re
from typing import Literal, Optional

import aiohttp
import discord
from discord.ext import commands

import theme

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"
PERIODS = Literal["7day", "1month", "3month", "6month", "12month", "overall"]
PERIOD_NAMES = {
    "7day": "last 7 days",
    "1month": "last month",
    "3month": "last 3 months",
    "6month": "last 6 months",
    "12month": "last year",
    "overall": "all time",
}

EIGHT_BALL = [
    "It is certain.", "Without a doubt.", "Yes, definitely.", "Most likely.",
    "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
    "Better not tell you now.", "Don't count on it.", "My sources say no.",
    "Very doubtful.", "Outlook not so good.",
]
NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
DICE_RE = re.compile(r"^(\d{1,2})?d(\d{1,4})$", re.IGNORECASE)


# ---------- help menu helpers ----------


def visible(cog):
    return [c for c in cog.get_commands() if not c.hidden]


def count_commands(cmds):
    total = 0
    for c in cmds:
        total += 1
        if isinstance(c, commands.Group):
            total += len(c.commands)
    return total


def usage(prefix, cmd):
    return f"{prefix}{cmd.qualified_name} {cmd.signature}".strip()


def describe(cmd):
    return cmd.description or cmd.short_doc or "No description"


def command_lines(prefix, cmds):
    lines = []
    for c in sorted(cmds, key=lambda c: c.name):
        lines.append(f"`{usage(prefix, c)}`\n> {describe(c)}")
        if isinstance(c, commands.Group):
            for s in sorted(c.commands, key=lambda s: s.name):
                lines.append(f"`{usage(prefix, s)}`\n> {describe(s)}")
    return lines


def category_embed(ctx, cog):
    prefix = ctx.clean_prefix
    embed = discord.Embed(
        title=f"{getattr(cog, 'emoji', '•')} {cog.qualified_name}",
        description="\n".join(command_lines(prefix, visible(cog)))[:4000],
        color=theme.PURPLE,
    )
    embed.set_footer(text=f"<> required · [] optional · {prefix}help <command> for details")
    return embed


class HelpView(discord.ui.View):
    def __init__(self, ctx, home):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.home = home
        self.message = None
        options = [discord.SelectOption(label="Home", value="__home__", emoji="🏠")]
        for name, cog in ctx.bot.cogs.items():
            cmds = visible(cog)
            if cmds:
                options.append(
                    discord.SelectOption(
                        label=name,
                        value=name,
                        emoji=getattr(cog, "emoji", None),
                        description=f"{count_commands(cmds)} commands",
                    )
                )
        self.menu.options = options

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Run `help` yourself to use the menu.", ephemeral=True)
            return False
        return True

    @discord.ui.select(
        placeholder="Browse a category...",
        options=[discord.SelectOption(label="Home", value="__home__")],
    )
    async def menu(self, interaction: discord.Interaction, select: discord.ui.Select):
        choice = select.values[0]
        if choice == "__home__":
            embed = self.home
        else:
            cog = interaction.client.get_cog(choice)
            embed = category_embed(self.ctx, cog) if cog else self.home
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Info(commands.Cog, name="Info"):
    """Help, bot info and profile lookups."""

    emoji = "📖"

    def __init__(self, bot):
        self.bot = bot

    def home_embed(self, ctx):
        prefix = ctx.clean_prefix
        embed = discord.Embed(
            title=f"✨ {self.bot.user.name} · Help",
            description=(
                f"Pick a category from the menu below, or run `{prefix}help <command>` for details.\n"
                "Every command also works as a slash command."
            ),
            color=theme.PURPLE,
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        total = 0
        for name, cog in self.bot.cogs.items():
            cmds = visible(cog)
            if not cmds:
                continue
            total += count_commands(cmds)
            names = " ".join(f"`{c.name}`" for c in sorted(cmds, key=lambda c: c.name))
            embed.add_field(name=f"{getattr(cog, 'emoji', '•')} {name}", value=names[:1024], inline=False)
        embed.set_footer(text=f"Prefix: {prefix} · {total} commands")
        return embed

    @commands.hybrid_command(name="help", aliases=["h", "commands"], description="Show everything the bot can do")
    async def help_cmd(self, ctx, *, command: Optional[str] = None):
        prefix = ctx.clean_prefix
        if command:
            query = command.strip().lower()
            if query.startswith(prefix):
                query = query[len(prefix):]
            cmd = self.bot.get_command(query)
            if not cmd or cmd.hidden:
                return await theme.bad(ctx, f"I don't have a command called `{query}`.")
            embed = discord.Embed(title=f"✨ {usage(prefix, cmd)}", description=describe(cmd), color=theme.PURPLE)
            if cmd.aliases:
                base = f"{cmd.full_parent_name} " if cmd.full_parent_name else ""
                embed.add_field(name="Aliases", value=" ".join(f"`{prefix}{base}{a}`" for a in cmd.aliases))
            if isinstance(cmd, commands.Group):
                embed.add_field(
                    name="Subcommands",
                    value="\n".join(command_lines(prefix, sorted(cmd.commands, key=lambda c: c.name)))[:1024],
                    inline=False,
                )
            embed.set_footer(text="<> required · [] optional")
            return await ctx.send(embed=embed)

        home = self.home_embed(ctx)
        view = HelpView(ctx, home)
        view.message = await ctx.send(embed=home, view=view)

    @commands.hybrid_command(description="Check how fast the bot is responding")
    async def ping(self, ctx):
        await theme.info(ctx, f"🏓 Pong! **{round(self.bot.latency * 1000)}ms**", prefix=False)

    @commands.hybrid_command(aliases=["botinfo", "stats"], description="About this bot")
    async def about(self, ctx):
        bot = self.bot
        embed = discord.Embed(title=f"✨ {bot.user.name}", color=theme.PURPLE)
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.add_field(name="Servers", value=f"{len(bot.guilds):,}")
        embed.add_field(name="Members", value=f"{sum(g.member_count or 0 for g in bot.guilds):,}")
        embed.add_field(name="Commands", value=str(len({c.qualified_name for c in bot.walk_commands()})))
        embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)}ms")
        embed.add_field(name="Up since", value=discord.utils.format_dt(bot.started_at, "R"))
        embed.add_field(name="Built with", value=f"Python {platform.python_version()} · discord.py {discord.__version__}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(aliases=["av", "pfp"], description="Show someone's avatar")
    async def avatar(self, ctx, user: Optional[discord.User] = None):
        user = user or ctx.author
        embed = discord.Embed(title=f"🖼️ {user.display_name}'s avatar", color=theme.PURPLE)
        embed.set_image(url=user.display_avatar.url)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Open full size", url=user.display_avatar.url))
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(aliases=["bn"], description="Show someone's profile banner")
    async def banner(self, ctx, user: Optional[discord.User] = None):
        user = await self.bot.fetch_user((user or ctx.author).id)
        if not user.banner:
            return await theme.info(ctx, "That user doesn't have a banner.")
        embed = discord.Embed(
            title=f"🎨 {user.display_name}'s banner", color=user.accent_color or theme.PURPLE
        )
        embed.set_image(url=user.banner.url)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Open full size", url=user.banner.url))
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(aliases=["ui", "whois"], description="Show info about a member")
    @commands.guild_only()
    async def userinfo(self, ctx, member: Optional[discord.Member] = None):
        member = member or ctx.author
        embed = discord.Embed(
            title=f"{'🤖' if member.bot else '👤'} {member}",
            color=member.color if member.color.value else theme.PURPLE,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=f"`{member.id}`")
        embed.add_field(name="Created", value=discord.utils.format_dt(member.created_at, "R"))
        if member.joined_at:
            embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, "R"))
        if member.premium_since:
            embed.add_field(name="Boosting since", value=discord.utils.format_dt(member.premium_since, "R"))
        if member.top_role != ctx.guild.default_role:
            embed.add_field(name="Top role", value=member.top_role.mention)
        roles = [r.mention for r in reversed(member.roles) if r != ctx.guild.default_role]
        if roles:
            embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:15]), inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(aliases=["si", "guildinfo"], description="Show info about this server")
    @commands.guild_only()
    async def serverinfo(self, ctx):
        g = ctx.guild
        embed = discord.Embed(title=f"🏠 {g.name}", description=g.description, color=theme.PURPLE)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        if g.banner:
            embed.set_image(url=g.banner.url)
        embed.add_field(name="Owner", value=f"<@{g.owner_id}>")
        embed.add_field(name="Members", value=f"{g.member_count:,}")
        embed.add_field(name="Channels", value=f"💬 {len(g.text_channels)} · 🔊 {len(g.voice_channels)}")
        embed.add_field(name="Roles", value=str(len(g.roles)))
        embed.add_field(name="Emojis", value=str(len(g.emojis)))
        embed.add_field(name="Boosts", value=f"{g.premium_subscription_count} (level {g.premium_tier})")
        embed.add_field(name="Verification", value=g.verification_level.name.title())
        embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, "R"))
        embed.set_footer(text=f"ID: {g.id}")
        await ctx.send(embed=embed)


class Fun(commands.Cog, name="Fun"):
    """Games and small utilities."""

    emoji = "🎉"

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="8ball", aliases=["8b"], description="Ask the magic 8ball")
    async def eightball(self, ctx, *, question: str):
        embed = discord.Embed(color=theme.PURPLE)
        embed.add_field(name="❓ Question", value=question[:1000], inline=False)
        embed.add_field(name="🎱 Answer", value=random.choice(EIGHT_BALL), inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(aliases=["flip", "coin"], description="Flip a coin")
    async def coinflip(self, ctx):
        await theme.send(ctx, f"🪙 It's **{random.choice(['Heads', 'Tails'])}**!", prefix=False)

    @commands.hybrid_command(aliases=["dice"], description="Roll dice, like 2d6 or d20")
    async def roll(self, ctx, dice: str = "1d6"):
        match = DICE_RE.match(dice.strip())
        if not match:
            return await theme.bad(ctx, "Use dice like `d20`, `2d6` or `4d10`.")
        count = int(match[1] or 1)
        sides = int(match[2])
        if not (1 <= count <= 20 and 2 <= sides <= 1000):
            return await theme.bad(ctx, "Roll 1 to 20 dice with 2 to 1000 sides.")
        rolls = [random.randint(1, sides) for _ in range(count)]
        text = f"🎲 You rolled **{sum(rolls)}**"
        if count > 1:
            text += f"  ·  `{', '.join(str(r) for r in rolls)}`"
        await theme.send(ctx, text, prefix=False)

    @commands.hybrid_command(aliases=["pick"], description="Let me pick for you: pizza, tacos, sushi")
    async def choose(self, ctx, *, options: str):
        parts = [p.strip() for p in re.split(r"[,|]", options) if p.strip()]
        if len(parts) < 2:
            return await theme.bad(ctx, "Give me at least two options, separated by commas.")
        await theme.send(ctx, f"🤔 I choose... **{random.choice(parts)}**!", prefix=False)

    @commands.hybrid_command(description="Start a poll: question | option | option (or just a question)")
    @commands.guild_only()
    @commands.bot_has_permissions(add_reactions=True)
    async def poll(self, ctx, *, question: str):
        parts = [p.strip() for p in question.split("|") if p.strip()]
        if not parts:
            return await theme.bad(ctx, "Give me a question for the poll.")
        title, options = parts[0], parts[1:]
        if len(options) == 1:
            return await theme.bad(ctx, "A poll needs at least two options, or none for a yes/no poll.")
        if len(options) > 9:
            return await theme.bad(ctx, "Polls can have at most 9 options.")
        if options:
            body = "\n".join(f"{NUMBERS[i]} {option}" for i, option in enumerate(options))
            emojis = NUMBERS[: len(options)]
        else:
            body = "👍 Yes\n👎 No"
            emojis = ["👍", "👎"]
        embed = discord.Embed(title=f"📊 {title}", description=body, color=theme.BLUE)
        embed.set_footer(text=f"Poll by {ctx.author.display_name}")
        message = await ctx.send(embed=embed)
        for emoji in emojis:
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                break


class LastFM(commands.Cog, name="Last.fm"):
    """Show your listening stats."""

    emoji = "🎧"

    def __init__(self, bot):
        self.bot = bot
        self.api_key = os.getenv("LASTFM_API_KEY")
        self.session = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    # ---------- helpers ----------

    async def _lastfm(self, method, **params):
        params.update({"method": method, "api_key": self.api_key, "format": "json"})
        async with self.session.get(LASTFM_URL, params=params) as resp:
            return await resp.json(content_type=None)

    async def _username(self, ctx, member) -> Optional[str]:
        if not self.api_key:
            await theme.bad(ctx, "Last.fm isn't set up on this bot yet (missing `LASTFM_API_KEY`).")
            return None
        row = await self.bot.db.fetchone("SELECT username FROM lastfm_users WHERE user_id=?", (member.id,))
        if not row:
            who = "You haven't" if member.id == ctx.author.id else f"**{member.display_name}** hasn't"
            await theme.info(ctx, f"{who} linked a Last.fm account. Use `{ctx.clean_prefix}lastfm set <username>`.")
            return None
        return row["username"]

    @staticmethod
    def _as_list(value):
        if isinstance(value, dict):
            return [value]
        return value or []

    async def _now_playing(self, ctx, member):
        await ctx.defer()
        member = member or ctx.author
        username = await self._username(ctx, member)
        if not username:
            return
        data = await self._lastfm("user.getrecenttracks", user=username, limit=1)
        if "error" in data:
            return await theme.bad(ctx, "Last.fm returned an error for that account.")
        tracks = self._as_list(data["recenttracks"]["track"])
        if not tracks:
            return await theme.info(ctx, "No scrobbles yet.")
        t = tracks[0]
        playing = t.get("@attr", {}).get("nowplaying") == "true"
        artist = t["artist"]["#text"]
        album = t.get("album", {}).get("#text", "")
        description = f"by **{artist}**" + (f"\n💿 {album}" if album else "")
        embed = discord.Embed(title=t["name"], url=t.get("url"), description=description, color=theme.LASTFM)
        embed.set_author(
            name=f"{'🎶 Now playing' if playing else '⏸️ Last played'} · {member.display_name}",
            icon_url=member.display_avatar.url,
        )
        images = t.get("image") or []
        if images and images[-1].get("#text"):
            embed.set_thumbnail(url=images[-1]["#text"])
        footer = f"Last.fm · {username}"
        try:
            extra = await self._lastfm("track.getinfo", username=username, artist=artist, track=t["name"])
            plays = extra.get("track", {}).get("userplaycount")
            if plays is not None:
                footer += f" · {int(plays):,} scrobbles of this track"
        except Exception:
            pass
        embed.set_footer(text=footer)
        await ctx.send(embed=embed)

    async def _top(self, ctx, member, period, *, method, root, item, title, fmt):
        await ctx.defer()
        member = member or ctx.author
        username = await self._username(ctx, member)
        if not username:
            return
        data = await self._lastfm(method, user=username, period=period, limit=10)
        if "error" in data:
            return await theme.bad(ctx, "Last.fm returned an error for that account.")
        items = self._as_list(data.get(root, {}).get(item))
        if not items:
            return await theme.info(ctx, "Nothing to show for that period.")
        lines = [f"`{i}.` {fmt(x)}" for i, x in enumerate(items, start=1)]
        embed = discord.Embed(
            title=f"{title} · {PERIOD_NAMES[period]}", description="\n".join(lines), color=theme.LASTFM
        )
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.set_footer(text=f"Last.fm · {username}")
        await ctx.send(embed=embed)

    # ---------- commands ----------

    @commands.hybrid_group(name="lastfm", aliases=["lf"], invoke_without_command=True)
    async def lastfm(self, ctx):
        """Last.fm commands."""
        await theme.group_help(ctx)

    @lastfm.command(name="set", description="Link your Last.fm account")
    async def lastfm_set(self, ctx, username: str):
        if not self.api_key:
            return await theme.bad(ctx, "Last.fm isn't set up on this bot yet (missing `LASTFM_API_KEY`).")
        await ctx.defer()
        data = await self._lastfm("user.getinfo", user=username)
        if "error" in data:
            return await theme.bad(ctx, "I couldn't find that Last.fm user.")
        real_name = data["user"]["name"]
        await self.bot.db.execute(
            "INSERT INTO lastfm_users (user_id, username) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
            (ctx.author.id, real_name),
        )
        await theme.ok(ctx, f"Linked your account to **{real_name}** on Last.fm. Try `{ctx.clean_prefix}np`!")

    @lastfm.command(name="nowplaying", aliases=["np"], description="Show what someone is listening to")
    async def lastfm_nowplaying(self, ctx, member: Optional[discord.Member] = None):
        await self._now_playing(ctx, member)

    @commands.hybrid_command(name="np", aliases=["fm"], description="Show what someone is listening to")
    async def np(self, ctx, member: Optional[discord.Member] = None):
        await self._now_playing(ctx, member)

    @lastfm.command(name="topartists", aliases=["ta"], description="Top artists for a time period")
    async def lastfm_topartists(self, ctx, period: PERIODS = "7day", member: Optional[discord.Member] = None):
        await self._top(
            ctx, member, period,
            method="user.gettopartists", root="topartists", item="artist", title="🎤 Top artists",
            fmt=lambda a: f"**{a['name']}** · {a['playcount']} plays",
        )

    @lastfm.command(name="toptracks", aliases=["tt"], description="Top tracks for a time period")
    async def lastfm_toptracks(self, ctx, period: PERIODS = "7day", member: Optional[discord.Member] = None):
        await self._top(
            ctx, member, period,
            method="user.gettoptracks", root="toptracks", item="track", title="🎵 Top tracks",
            fmt=lambda t: f"**{t['name']}** by {t['artist']['name']} · {t['playcount']} plays",
        )

    @lastfm.command(name="topalbums", aliases=["tal"], description="Top albums for a time period")
    async def lastfm_topalbums(self, ctx, period: PERIODS = "7day", member: Optional[discord.Member] = None):
        await self._top(
            ctx, member, period,
            method="user.gettopalbums", root="topalbums", item="album", title="💿 Top albums",
            fmt=lambda a: f"**{a['name']}** by {a['artist']['name']} · {a['playcount']} plays",
        )

    @lastfm.command(name="recent", aliases=["rt"], description="Show the last 10 scrobbles")
    async def lastfm_recent(self, ctx, member: Optional[discord.Member] = None):
        await ctx.defer()
        member = member or ctx.author
        username = await self._username(ctx, member)
        if not username:
            return
        data = await self._lastfm("user.getrecenttracks", user=username, limit=10)
        if "error" in data:
            return await theme.bad(ctx, "Last.fm returned an error for that account.")
        tracks = self._as_list(data["recenttracks"]["track"])
        if not tracks:
            return await theme.info(ctx, "No scrobbles yet.")
        lines = []
        for t in tracks[:10]:
            playing = t.get("@attr", {}).get("nowplaying") == "true"
            lines.append(f"{'🎶' if playing else '•'} **{t['name']}** · {t['artist']['#text']}")
        embed = discord.Embed(title="🕒 Recent tracks", description="\n".join(lines), color=theme.LASTFM)
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.set_footer(text=f"Last.fm · {username}")
        await ctx.send(embed=embed)

    @lastfm.command(name="profile", aliases=["me"], description="Show a Last.fm profile summary")
    async def lastfm_profile(self, ctx, member: Optional[discord.Member] = None):
        await ctx.defer()
        member = member or ctx.author
        username = await self._username(ctx, member)
        if not username:
            return
        data = await self._lastfm("user.getinfo", user=username)
        if "error" in data:
            return await theme.bad(ctx, "Last.fm returned an error for that account.")
        u = data["user"]
        embed = discord.Embed(title=f"🎧 {u.get('name', username)}", url=u.get("url"), color=theme.LASTFM)
        images = u.get("image") or []
        if images and images[-1].get("#text"):
            embed.set_thumbnail(url=images[-1]["#text"])
        embed.add_field(name="Scrobbles", value=f"{int(u.get('playcount', 0)):,}")
        registered = u.get("registered", {}).get("unixtime")
        if registered:
            embed.add_field(name="Scrobbling since", value=f"<t:{int(registered)}:D>")
        if u.get("country") and u["country"] != "None":
            embed.add_field(name="Country", value=u["country"])
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Info(bot))
    await bot.add_cog(Fun(bot))
    await bot.add_cog(LastFM(bot))
