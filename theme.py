"""Shared look and feel: colors, embed helpers, confirm buttons and paging."""
import discord

PURPLE = 0x9B5DE5
GREEN = 0x57F287
YELLOW = 0xFEE75C
RED = 0xED4245
BLUE = 0x5865F2
ORANGE = 0xE67E22
GOLD = 0xFFAC33
LASTFM = 0xD51007

KINDS = {
    "main": (PURPLE, "✨"),
    "ok": (GREEN, "✅"),
    "warn": (YELLOW, "⚠️"),
    "bad": (RED, "❌"),
    "info": (BLUE, "💡"),
}


def make(description=None, *, title=None, kind="main", prefix=True):
    color, emoji = KINDS[kind]
    if description and prefix:
        description = f"{emoji} {description}"
    return discord.Embed(title=title, description=description, color=color)


async def send(ctx, description=None, *, title=None, kind="main", ephemeral=None, prefix=True, **kwargs):
    """Send a styled embed. Errors are private (ephemeral) on slash commands."""
    if ephemeral is None:
        ephemeral = kind == "bad"
    embed = make(description, title=title, kind=kind, prefix=prefix)
    return await ctx.send(embed=embed, ephemeral=ephemeral, **kwargs)


async def ok(ctx, text, **kwargs):
    return await send(ctx, text, kind="ok", **kwargs)


async def bad(ctx, text, **kwargs):
    return await send(ctx, text, kind="bad", **kwargs)


async def warn(ctx, text, **kwargs):
    return await send(ctx, text, kind="warn", **kwargs)


async def info(ctx, text, **kwargs):
    return await send(ctx, text, kind="info", **kwargs)


def chunk(items, size):
    return [items[i : i + size] for i in range(0, len(items), size)]


# ---------- confirm buttons ----------


class Confirm(discord.ui.View):
    def __init__(self, author_id, *, timeout=30):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Those buttons aren't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", emoji="✅", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.defer()


async def confirm(ctx, question) -> bool:
    """Ask with Confirm/Cancel buttons. Returns True only if the author confirmed."""
    view = Confirm(ctx.author.id)
    message = await ctx.send(embed=make(question, kind="warn"), view=view)
    await view.wait()
    try:
        if view.value:
            await message.delete()
        elif view.value is False:
            await message.edit(embed=make("Cancelled.", kind="info"), view=None)
        else:
            await message.edit(embed=make("Timed out, nothing was changed.", kind="info"), view=None)
    except discord.HTTPException:
        pass
    return bool(view.value)


# ---------- pager ----------


class Pages(discord.ui.View):
    def __init__(self, author_id, embeds, *, timeout=120):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.embeds = embeds
        self.index = 0
        self.message = None
        self._sync()

    def _sync(self):
        self.prev_page.disabled = self.index == 0
        self.next_page.disabled = self.index >= len(self.embeds) - 1
        self.counter.label = f"{self.index + 1}/{len(self.embeds)}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Run the command yourself to flip pages.", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        self._sync()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def counter(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        self._sync()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


async def paginate(ctx, embeds):
    if len(embeds) == 1:
        return await ctx.send(embed=embeds[0])
    view = Pages(ctx.author.id, embeds)
    view.message = await ctx.send(embed=embeds[0], view=view)


# ---------- group help (shown when a command group is used on its own) ----------


async def group_help(ctx):
    cmd = ctx.command
    prefix = ctx.clean_prefix
    lines = []
    for sub in sorted(cmd.commands, key=lambda c: c.name):
        usage = f"{prefix}{sub.qualified_name} {sub.signature}".strip()
        lines.append(f"`{usage}`\n> {sub.description or sub.short_doc or 'No description'}")
    intro = cmd.short_doc or ""
    embed = discord.Embed(
        title=f"✨ {prefix}{cmd.qualified_name}",
        description=(intro + "\n\n" if intro else "") + "\n".join(lines),
        color=PURPLE,
    )
    await ctx.send(embed=embed)
