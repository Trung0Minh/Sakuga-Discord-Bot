import discord
from discord import ui

class GuessView(ui.View):
    def __init__(self, session):
        super().__init__(timeout=None)
        self.session = session

    @ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id not in self.session.players:
            await interaction.response.send_message("You are not in this game!", ephemeral=True)
            return

        await interaction.response.defer()
        await self.session.handle_skip(interaction.user, interaction.channel)