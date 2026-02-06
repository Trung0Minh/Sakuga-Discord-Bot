import asyncio
import discord
from collections import defaultdict
from .sakuga_api import SakugaAPI
from .db_manager import DatabaseManager

db = DatabaseManager()

class GameSession:
    def __init__(self, session, channel_id, creator_id, players, rounds, tags, mode="normal"):
        self.session = session
        self.channel_id = channel_id
        self.creator_id = creator_id
        self.players = players
        self.total_rounds = rounds
        self.current_round = 0
        self.scores = defaultdict(float)
        self.tags = tags
        self.mode = mode
        self.active = True
        self.current_artists = [] 
        self.is_waiting_for_answer = False
        self.skips = set()
        self.seen_post_ids = []

    def deduct_global_points(self, user_id):
        db.add_point(user_id, -0.5)

    async def handle_correct_answer(self, user, channel):
        if not self.is_waiting_for_answer:
            return
        
        self.is_waiting_for_answer = False
        self.timeout_task.cancel()
        
        self.scores[user.id] += 1
        db.add_point(user.id) # Global leaderboard update
        artist_list = ", ".join([a.title() for a in self.current_artists])
        await channel.send(f"Correct! <@{user.id}> got it! The animator(s) was **{artist_list}**.")
        
        await asyncio.sleep(2)
        await self.start_round(channel)

    async def handle_skip(self, user, channel):
        if not self.is_waiting_for_answer:
            return

        self.skips.add(user.id)
        needed = len(self.players)
        current = len(self.skips)
        
        if current >= needed:
            self.is_waiting_for_answer = False
            self.timeout_task.cancel()
            artist_list = ", ".join([a.title() for a in self.current_artists])
            await channel.send(f"Round skipped! The answer was: **{artist_list}**")
            await asyncio.sleep(2)
            await self.start_round(channel)
        else:
            await channel.send(f"Skip vote registered ({current}/{needed})")

    async def start_round(self, ctx):
        if self.current_round >= self.total_rounds:
            await self.end_game(ctx)
            return

        # Fetch video
        post, error = await SakugaAPI.get_random_post(self.session, self.tags, exclude_ids=self.seen_post_ids)
        if error:
            if error == "invalid_tags":
                await ctx.send(f"Error: The tags `{self.tags}` do not return any results. Please check for typos!")
            elif error == "out_of_videos":
                await ctx.send("No more unique videos found with those tags! Finishing early...")
            elif error == "no_videos":
                await ctx.send(f"The tags `{self.tags}` return results, but none are videos (MP4/WebM).")
            else:
                await ctx.send("An error occurred while fetching the video. Ending game.")
            
            if self.current_round > 0:
                await self.end_game(ctx)
            else:
                self.active = False
            return

        # Identify artist
        artists = await SakugaAPI.get_artist_from_tags(self.session, post['tags'])
        
        if not artists:
            # Retry if no artist tags found (e.g. unknown artist post slipped through)
            self.seen_post_ids.append(post['id'])
            await self.start_round(ctx) 
            return

        self.current_round += 1
        self.seen_post_ids.append(post['id'])
        self.skips = set()
        self.current_artists = artists
        self.is_waiting_for_answer = True
        
        video_url = post.get('file_url') or post.get('sample_url')
        
        embed = discord.Embed(title=f"Round {self.current_round}/{self.total_rounds}", description="Guess the animator!", color=0x00ff00)
        
        view = None
        if self.mode in ["blind", "hardcore"]:
            from .views import GuessView # Local import
            view = GuessView(self)
            embed.set_footer(text="Blind Mode: Use /g <name> to guess!")

        try:
            await ctx.send(embed=embed, view=view)
            await ctx.send(video_url)
        except Exception as e:
            print(f"Error sending message: {e}")
            # If we fail to send, the game is likely broken in this channel
            self.active = False
            return

        self.timeout_task = asyncio.create_task(self.round_timeout(ctx))

    async def round_timeout(self, ctx):
        await asyncio.sleep(60)
        if self.is_waiting_for_answer:
            self.is_waiting_for_answer = False
            artist_list = ", ".join([a.title() for a in self.current_artists])
            await ctx.send(f"Time's up! The correct answer was: **{artist_list}**")
            await asyncio.sleep(2)
            await self.start_round(ctx)

    async def check_answer(self, message):
        if not self.is_waiting_for_answer:
            return False

        if message.author.id not in self.players:
            return False

        if self.mode in ["blind", "hardcore"]:
            try:
                await message.delete()
                await message.channel.send(f"<@{message.author.id}>, use `/g` to guess in {self.mode.capitalize()} mode!", delete_after=3)
            except:
                pass
            return False

        content = message.content.strip().lower()
        
        if content == "skip":
            await self.handle_skip(message.author, message.channel)
            return True

        is_correct = False
        for artist in self.current_artists:
            if content == artist.lower():
                is_correct = True
                break
        
        if is_correct:
            await self.handle_correct_answer(message.author, message.channel)
            return True
        else:
            if self.mode == "strict":
                self.scores[message.author.id] -= 0.5
                self.deduct_global_points(message.author.id)
            return False

    async def end_game(self, ctx):
        self.active = False
        self.is_waiting_for_answer = False
        
        sorted_scores = sorted(self.scores.items(), key=lambda item: item[1], reverse=True)
        
        embed = discord.Embed(title="Game Over!", color=0xffd700)
        if sorted_scores:
            description = ""
            for i, (uid, score) in enumerate(sorted_scores, 1):
                description += f"{i}. <@{uid}> - {score:.1f} points\n" # Format float nicely
            embed.description = description
        else:
            embed.description = "No one scored any points!"
            
        await ctx.send(embed=embed)

class GameManager:
    def __init__(self, session):
        self.sessions = {}
        self.session = session

    def create_session(self, channel_id, creator_id, players, rounds, tags, mode="normal"):
        if channel_id in self.sessions and self.sessions[channel_id].active:
            return None
        
        session = GameSession(self.session, channel_id, creator_id, players, rounds, tags, mode)
        self.sessions[channel_id] = session
        return session

    def get_session(self, channel_id):
        return self.sessions.get(channel_id)

    def remove_session(self, channel_id):
        if channel_id in self.sessions:
            del self.sessions[channel_id]