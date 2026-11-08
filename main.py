import logging
import os

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

import theme
from db import Database

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit(
        "DISCORD_TOKEN is not set. Put it in a .env file locally, "
        "or add it as a variable in your Railway service."
    )
DEFAULT_PREFIX = os.getenv("DEFAULT_PREFIX", ";")
GUILD_ID = os.getenv("GUILD_ID")  # optional: sync slash commands to one server instantly

EXTENSIONS = ["cog_moderation", "cog_setup", "cog_fun"]

log = logging.getLogger("bot")


async def get_prefix(bot, message):
    prefix = DEFAULT_PREFIX
    if message.guild:
        prefix = await bot.db.get_setting(message.guild.id, "prefix", DEFAULT_PREFIX)
    return commands.when_mentioned_or(prefix)(bot, message)


def usage_of(ctx):
    if not ctx.command:
        return ""
    return f"{ctx.clean_prefix}{ctx.command.qualified_name} {ctx.command.signature}".strip()


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # privileged: enable in the Developer Portal
        intents.members = True  # privileged: enable in the Developer Portal
        super().__init__(
            command_prefix=get_prefix,
            intents=intents,
            help_command=None,  # replaced by the button help menu in cog_fun
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False),
        )
        self.db = Database()
        self.started_at = discord.utils.utcnow()
        self._status_index = 0

    async def setup_hook(self):
        await self.db.connect()
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def close(self):
        await self.db.close()
        await super().close()

    async def on_ready(self):
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        if not self.rotate_status.is_running():
            self.rotate_status.start()

    # ---------- rotating status ----------

    @tasks.loop(seconds=45)
    async def rotate_status(self):
        guilds = len(self.guilds)
        members = sum(g.member_count or 0 for g in self.guilds)
        plural = "" if guilds == 1 else "s"
        activities = [
            discord.Activity(type=discord.ActivityType.listening, name=f"{DEFAULT_PREFIX}help"),
            discord.Activity(type=discord.ActivityType.watching, name=f"{guilds} server{plural}"),
            discord.Activity(type=discord.ActivityType.watching, name=f"{members:,} members"),
        ]
        activity = activities[self._status_index % len(activities)]
        self._status_index += 1
        await self.change_presence(activity=activity)

    @rotate_status.before_loop
    async def before_rotate_status(self):
        await self.wait_until_ready()

    # ---------- reply when pinged on its own ----------

    async def on_message(self, message):
        if message.author.bot:
            return
        if self.user and message.content.strip() in (self.user.mention, f"<@!{self.user.id}>"):
            prefix = DEFAULT_PREFIX
            if message.guild:
                prefix = await self.db.get_setting(message.guild.id, "prefix", DEFAULT_PREFIX)
            embed = theme.make(
                f"Hey {message.author.mention}! My prefix here is `{prefix}`. Try `{prefix}help` to see what I can do.",
                prefix=False,
            )
            try:
                await message.reply(embed=embed, mention_author=False)
            except discord.HTTPException:
                pass
            return
        await self.process_commands(message)

    # ---------- friendly errors ----------

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        error = getattr(error, "original", error)

        if isinstance(error, commands.MissingPermissions):
            msg = "You don't have permission to do that."
        elif isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(p.replace("_", " ") for p in error.missing_permissions)
            msg = f"I'm missing permissions: **{perms}**. Give them to me and try again."
        elif isinstance(error, commands.MissingRequiredArgument):
            msg = f"You forgot `{error.param.name}`.\nUsage: `{usage_of(ctx)}`"
        elif isinstance(error, commands.RangeError):
            msg = f"That number needs to be between **{error.minimum}** and **{error.maximum}**."
        elif isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
            msg = f"I couldn't understand one of those arguments.\nUsage: `{usage_of(ctx)}`"
        elif isinstance(error, commands.NoPrivateMessage):
            msg = "That command only works in servers."
        elif isinstance(error, commands.CommandOnCooldown):
            msg = f"Easy there! Try again in **{error.retry_after:.0f}s**."
        elif isinstance(error, commands.CheckFailure):
            msg = "You can't use that command."
        elif isinstance(error, discord.Forbidden):
            msg = "I can't do that. Check that my role is above the target and that I have the right permissions."
        else:
            log.exception("Unhandled command error in %s", ctx.command, exc_info=error)
            msg = "Something went wrong on my end. Try again in a moment."

        try:
            await theme.bad(ctx, msg)
        except discord.HTTPException:
            pass


if __name__ == "__main__":
    Bot().run(TOKEN)
