import os
import discord
import asyncio
import aiohttp
from discord.ext import commands
from dotenv import load_dotenv
from aiohttp import web

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Setup bot
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 

class SakugaBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.session = None

    async def setup_hook(self):
        # Create a single session for the entire bot lifecycle
        self.session = aiohttp.ClientSession(
            headers={"User-Agent": "SakugaQuizBot/1.0 (Discord Bot)"}
        )
        await self.load_extension('cogs.quiz')
        print("Bot setup complete.")

    async def on_ready(self):
        print(f'Logged in as {self.user.name} ({self.user.id})')
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")
        print('------')

    async def close(self):
        # Ensure the session is closed when the bot shuts down
        if self.session:
            await self.session.close()
        await super().close()

bot = SakugaBot()

# Tiny web server to satisfy Koyeb health checks
async def health_check(request):
    return web.Response(text="Bot is running")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
    print("Web server started on port 8000")

async def main():
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found in .env")
        return

    await start_web_server()
    await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
