# pagination.py
import discord
from loguru import logger

class PaginationView(discord.ui.View):
    def __init__(self, items: list, embed_builder, timeout=180):
        """
        items: list of items to paginate.
        embed_builder: function(item, current_index, total) -> discord.Embed.
        """
        super().__init__(timeout=timeout)
        self.items = items
        self.embed_builder = embed_builder
        self.current_index = 0
        logger.debug(f"PaginationView created with {len(items)} items.")

    async def update_message(self, interaction: discord.Interaction):
        embed = self.embed_builder(self.items[self.current_index], self.current_index, len(self.items))
        logger.debug(f"Updating pagination message: item {self.current_index}")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="<<", style=discord.ButtonStyle.primary)
    async def first(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_index = 0
        logger.debug("Pagination: moved to first item.")
        await self.update_message(interaction)

    @discord.ui.button(label="<", style=discord.ButtonStyle.primary)
    async def previous(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_index = (self.current_index - 1) % len(self.items)
        logger.debug("Pagination: moved to previous item.")
        await self.update_message(interaction)

    @discord.ui.button(label=">", style=discord.ButtonStyle.primary)
    async def next(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_index = (self.current_index + 1) % len(self.items)
        logger.debug("Pagination: moved to next item.")
        await self.update_message(interaction)

    @discord.ui.button(label=">>", style=discord.ButtonStyle.primary)
    async def last(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_index = len(self.items) - 1
        logger.debug("Pagination: moved to last item.")
        await self.update_message(interaction)
