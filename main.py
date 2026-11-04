import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

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


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # privileged: enable in the Developer Portal
        intents.members = True  # privileged: enable in the Developer Portal
        super().__init__(
            command_prefix=get_prefix,
            intents=intents,
            help_command=commands.MinimalHelpCommand(),
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False),
        )
        self.db = Database()

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

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        error = getattr(error, "original", error)

        if isinstance(error, commands.MissingPermissions):
            msg = "You don't have permission to do that."
        elif isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(p.replace("_", " ") for p in error.missing_permissions)
            msg = f"I'm missing permissions: {perms}."
        elif isinstance(error, commands.MissingRequiredArgument):
            msg = f"Missing argument: `{error.param.name}`."
        elif isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
            msg = "I couldn't understand one of those arguments."
        elif isinstance(error, commands.NoPrivateMessage):
            msg = "That command only works in servers."
        elif isinstance(error, commands.CommandOnCooldown):
            msg = f"Slow down, try again in {error.retry_after:.0f}s."
        elif isinstance(error, commands.CheckFailure):
            msg = "You can't use that command."
        elif isinstance(error, discord.Forbidden):
            msg = "I can't do that. Check that my role is above the target and I have the right permissions."
        else:
            log.exception("Unhandled command error in %s", ctx.command, exc_info=error)
            msg = "Something went wrong."

        try:
            await ctx.send(msg, ephemeral=True)
        except discord.HTTPException:
            pass


if __name__ == "__main__":
    Bot().run(TOKEN)
