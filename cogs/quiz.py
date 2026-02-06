import discord
from discord import app_commands
from discord.ext import commands
from utils.game_manager import GameManager
from utils.db_manager import DatabaseManager
from utils.sakuga_api import SakugaAPI
import re

class Quiz(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game_manager = GameManager()
        self.db = DatabaseManager()

    @app_commands.command(name="leaderboard", description="Show the global leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        top_scores = self.db.get_top_scores(10)
        
        if not top_scores:
            await interaction.response.send_message("The leaderboard is empty!")
            return

        embed = discord.Embed(title="Global Pekuga Leaderboard", color=0xffd700)
        description = ""
        for i, (uid, points) in enumerate(top_scores, 1):
            description += f"{i}. <@{uid}> - {points} points\n"
        
        embed.description = description
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="cancel", description="Cancel the current quiz in this channel")
    async def cancel(self, interaction: discord.Interaction):
        session = self.game_manager.get_session(interaction.channel_id)
        
        if not session or not session.active:
            await interaction.response.send_message("There is no active quiz in this channel!", ephemeral=True)
            return

        if interaction.user.id != session.creator_id:
            await interaction.response.send_message("Only the person who started the quiz can cancel it!", ephemeral=True)
            return

        session.active = False
        session.is_waiting_for_answer = False
        if hasattr(session, 'timeout_task'):
            session.timeout_task.cancel()
            
        self.game_manager.remove_session(interaction.channel_id)
        await interaction.response.send_message(f"Quiz cancelled by <@{interaction.user.id}>.")

    @app_commands.command(name="g", description="Guess the animator (Used in Blind/Hardcore mode)")
    @app_commands.describe(name="The full name of the animator")
    async def guess(self, interaction: discord.Interaction, name: str):
        session = self.game_manager.get_session(interaction.channel_id)
        
        if not session or not session.active:
            await interaction.response.send_message("There is no active quiz in this channel!", ephemeral=True)
            return

        if not session.is_waiting_for_answer:
            await interaction.response.send_message("The round has already finished!", ephemeral=True)
            return

        if interaction.user.id not in session.players:
            await interaction.response.send_message("You are not part of this game!", ephemeral=True)
            return

        content = name.strip().lower()
        
        # Check correctness
        is_correct = False
        for artist in session.current_artists:
            if content == artist.lower():
                is_correct = True
                break
        
        if is_correct:
            await interaction.response.send_message(f"Checking guess: `{name}`...", ephemeral=True)
            await session.handle_correct_answer(interaction.user, interaction.channel)
        else:
            msg = f"Incorrect! (`{name}`)"
            if session.mode in ["strict", "hardcore"]:
                session.scores[interaction.user.id] -= 0.5
                session.deduct_global_points(interaction.user.id)
                msg += " (-0.5 points)"
            
            await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="quiz", description="Start a Pekuga Quiz")
    @app_commands.describe(
        tags="Sakugabooru tags to filter (separate by space, e.g. 'explosions effects')",
        rounds="Number of rounds to play",
        players="Mention users to whitelist (e.g. '@User1 @User2'). If empty, only you play.",
        mode="Game mode: Normal, Strict, Blind, Hardcore"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="Normal", value="normal"),
        app_commands.Choice(name="Strict (khắc chế sv Hs :tri:)", value="strict"),
        app_commands.Choice(name="Blind", value="blind"),
        app_commands.Choice(name="Hardcore", value="hardcore")
    ])
    async def quiz(self, interaction: discord.Interaction, tags: str = "none", rounds: int = 5, players: str = None, mode: app_commands.Choice[str] = None):
        """
        Starts a quiz game using Slash Commands.
        """
        # Default mode
        selected_mode = mode.value if mode else "normal"
        
        # Parse players from the string
        player_ids = []
        if players:
            # Extract all numbers from the string that look like user IDs (usually inside <@...>)
            # But users might just mention them.
            # Regex to find user mentions <@123456> or <@!123456>
            matches = re.findall(r'<@!?(\d+)>', players)
            player_ids = [int(uid) for uid in matches]
        
        # If no one valid was mentioned or field was empty, default to author
        if not player_ids:
            player_ids = [interaction.user.id]
        else:
            # Add author too if not already in list
            if interaction.user.id not in player_ids:
                player_ids.append(interaction.user.id)

        # Parse tags - cleanup and normalize multiple spaces
        if tags.lower() == "none":
            tags = ""
        else:
            # Join multiple spaces into single ones for the API
            tags = " ".join(tags.split())
            
            # Check for artist tags to prevent cheating
            tag_types = await SakugaAPI.get_tag_types(tags)
            artist_tags = [name for name, ttype in tag_types.items() if ttype == 1]
            if artist_tags:
                await interaction.response.send_message(f"You cannot use artist name as tags: `{', '.join(artist_tags)}`", ephemeral=True)
                return
        
        # Limit rounds
        if rounds > 20:
            rounds = 20
        elif rounds < 1:
            rounds = 1
        
        # Create session
        session = self.game_manager.create_session(interaction.channel_id, interaction.user.id, player_ids, rounds, tags, selected_mode)
        
        if not session:
            await interaction.response.send_message("A game is already in progress in this channel!", ephemeral=True)
            return

        # Respond to the slash command
        player_mentions = ', '.join([f'<@{pid}>' for pid in player_ids])
        await interaction.response.send_message(f"Starting Pekuga Quiz! {rounds} rounds.\nTags: `{tags if tags else 'Any'}`\nMode: **{selected_mode.capitalize()}**\nPlayers: {player_mentions}")
        
        # Start the game logic
        # We need a 'ctx' like object for start_round, but start_round uses ctx.send.
        # interaction.channel behaves like a TextChannel, so we can pass that.
        await session.start_round(interaction.channel)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        session = self.game_manager.get_session(message.channel.id)
        if session and session.active:
            # Check answer
            await session.check_answer(message)
            # Cleanup is handled inside game_manager now or we check status
            if not session.active:
                 self.game_manager.remove_session(message.channel.id)

async def setup(bot):
    await bot.add_cog(Quiz(bot))