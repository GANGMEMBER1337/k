import os
import random
from typing import Literal, Optional

import aiohttp
import discord
from discord.ext import commands

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"
LASTFM_RED = 0xD51007
PERIODS = Literal["7day", "1month", "3month", "6month", "12month", "overall"]

EIGHT_BALL = [
    "It is certain.", "Without a doubt.", "Yes, definitely.", "Most likely.",
    "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
    "Better not tell you now.", "Don't count on it.", "My sources say no.",
    "Very doubtful.", "Outlook not so good.",
]


class Fun(commands.Cog):
    """Last.fm and a few fun/utility commands."""

    def __init__(self, bot):
        self.bot = bot
        self.api_key = os.getenv("LASTFM_API_KEY")
        self.session = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    # ---------- last.fm helpers ----------

    async def _lastfm(self, method, **params):
        params.update({"method": method, "api_key": self.api_key, "format": "json"})
        async with self.session.get(LASTFM_URL, params=params) as resp:
            return await resp.json(content_type=None)

    async def _username(self, ctx, member) -> Optional[str]:
        if not self.api_key:
            await ctx.send("Last.fm isn't configured on this bot (missing `LASTFM_API_KEY`).")
            return None
        row = await self.bot.db.fetchone("SELECT username FROM lastfm_users WHERE user_id=?", (member.id,))
        if not row:
            who = "You haven't" if member.id == ctx.author.id else f"**{member.display_name}** hasn't"
            await ctx.send(f"{who} linked a Last.fm account. Use `lastfm set <username>`.")
            return None
        return row["username"]

    async def _now_playing(self, ctx, member):
        await ctx.defer()
        member = member or ctx.author
        username = await self._username(ctx, member)
        if not username:
            return
        data = await self._lastfm("user.getrecenttracks", user=username, limit=1)
        if "error" in data:
            return await ctx.send("Last.fm returned an error for that account.")
        tracks = data["recenttracks"]["track"]
        if isinstance(tracks, dict):
            tracks = [tracks]
        if not tracks:
            return await ctx.send("No scrobbles yet.")
        t = tracks[0]
        playing = t.get("@attr", {}).get("nowplaying") == "true"
        artist = t["artist"]["#text"]
        album = t.get("album", {}).get("#text", "")
        description = f"by **{artist}**" + (f" · {album}" if album else "")
        embed = discord.Embed(title=t["name"], url=t.get("url"), description=description, color=LASTFM_RED)
        embed.set_author(
            name=f"{'Now playing' if playing else 'Last played'} · {member.display_name}",
            icon_url=member.display_avatar.url,
        )
        images = t.get("image") or []
        if images and images[-1].get("#text"):
            embed.set_thumbnail(url=images[-1]["#text"])
        embed.set_footer(text=f"Last.fm: {username}")
        await ctx.send(embed=embed)

    # ---------- last.fm commands ----------

    @commands.hybrid_group(name="lastfm", aliases=["lf"], invoke_without_command=True)
    async def lastfm(self, ctx):
        """Last.fm commands."""
        await ctx.send_help(ctx.command)

    @lastfm.command(name="set", description="Link your Last.fm account")
    async def lastfm_set(self, ctx, username: str):
        if not self.api_key:
            return await ctx.send("Last.fm isn't configured on this bot (missing `LASTFM_API_KEY`).")
        await ctx.defer()
        data = await self._lastfm("user.getinfo", user=username)
        if "error" in data:
            return await ctx.send("I couldn't find that Last.fm user.")
        real_name = data["user"]["name"]
        await self.bot.db.execute(
            "INSERT INTO lastfm_users (user_id, username) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
            (ctx.author.id, real_name),
        )
        await ctx.send(f"Linked your account to **{real_name}** on Last.fm.")

    @lastfm.command(name="nowplaying", aliases=["np"], description="Show what someone is listening to")
    async def lastfm_nowplaying(self, ctx, member: Optional[discord.Member] = None):
        await self._now_playing(ctx, member)

    @commands.hybrid_command(name="np", description="Show what someone is listening to")
    async def np(self, ctx, member: Optional[discord.Member] = None):
        await self._now_playing(ctx, member)

    @lastfm.command(name="topartists", description="Top artists for a time period")
    async def lastfm_topartists(self, ctx, period: PERIODS = "7day", member: Optional[discord.Member] = None):
        await ctx.defer()
        member = member or ctx.author
        username = await self._username(ctx, member)
        if not username:
            return
        data = await self._lastfm("user.gettopartists", user=username, period=period, limit=10)
        if "error" in data:
            return await ctx.send("Last.fm returned an error for that account.")
        artists = data["topartists"]["artist"]
        if not artists:
            return await ctx.send("Nothing to show for that period.")
        lines = [
            f"`{i}.` **{a['name']}** · {a['playcount']} plays" for i, a in enumerate(artists, start=1)
        ]
        embed = discord.Embed(
            title=f"Top artists ({period})", description="\n".join(lines), color=LASTFM_RED
        )
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @lastfm.command(name="toptracks", description="Top tracks for a time period")
    async def lastfm_toptracks(self, ctx, period: PERIODS = "7day", member: Optional[discord.Member] = None):
        await ctx.defer()
        member = member or ctx.author
        username = await self._username(ctx, member)
        if not username:
            return
        data = await self._lastfm("user.gettoptracks", user=username, period=period, limit=10)
        if "error" in data:
            return await ctx.send("Last.fm returned an error for that account.")
        tracks = data["toptracks"]["track"]
        if not tracks:
            return await ctx.send("Nothing to show for that period.")
        lines = [
            f"`{i}.` **{t['name']}** by {t['artist']['name']} · {t['playcount']} plays"
            for i, t in enumerate(tracks, start=1)
        ]
        embed = discord.Embed(
            title=f"Top tracks ({period})", description="\n".join(lines), color=LASTFM_RED
        )
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        await ctx.send(embed=embed)

    # ---------- fun / utility ----------

    @commands.hybrid_command(name="8ball", description="Ask the magic 8ball")
    async def eightball(self, ctx, *, question: str):
        await ctx.send(f"🎱 {random.choice(EIGHT_BALL)}")

    @commands.hybrid_command(description="Show someone's avatar")
    async def avatar(self, ctx, user: Optional[discord.User] = None):
        user = user or ctx.author
        embed = discord.Embed(title=f"{user.display_name}'s avatar", color=0x5865F2)
        embed.set_image(url=user.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.hybrid_command(description="Show someone's profile banner")
    async def banner(self, ctx, user: Optional[discord.User] = None):
        user = await self.bot.fetch_user((user or ctx.author).id)
        if not user.banner:
            return await ctx.send("That user doesn't have a banner.")
        embed = discord.Embed(title=f"{user.display_name}'s banner", color=user.accent_color or 0x5865F2)
        embed.set_image(url=user.banner.url)
        await ctx.send(embed=embed)

    @commands.hybrid_command(description="Show info about a member")
    @commands.guild_only()
    async def userinfo(self, ctx, member: Optional[discord.Member] = None):
        member = member or ctx.author
        embed = discord.Embed(title=str(member), color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=member.id)
        embed.add_field(name="Created", value=discord.utils.format_dt(member.created_at, "R"))
        if member.joined_at:
            embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, "R"))
        roles = [r.mention for r in reversed(member.roles) if r != ctx.guild.default_role]
        if roles:
            embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:15]), inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(description="Show info about this server")
    @commands.guild_only()
    async def serverinfo(self, ctx):
        g = ctx.guild
        embed = discord.Embed(title=g.name, color=0x5865F2)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="Owner", value=f"<@{g.owner_id}>")
        embed.add_field(name="Members", value=g.member_count)
        embed.add_field(name="Channels", value=len(g.channels))
        embed.add_field(name="Roles", value=len(g.roles))
        embed.add_field(name="Boosts", value=g.premium_subscription_count)
        embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, "R"))
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Fun(bot))
