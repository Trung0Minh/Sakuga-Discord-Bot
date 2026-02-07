import discord
from discord import app_commands
from discord.ext import commands
from utils.keyframe_api import KeyframeAPI

class ShowSelect(discord.ui.Select):
    def __init__(self, search_results, original_interaction, filters):
        self.original_interaction = original_interaction
        self.filters = filters
        
        options = []
        # Limit to 25 options (Discord limit)
        for show in search_results[:25]:
            label = show.get('name', 'Unknown')[:100]
            desc = str(show.get('seasonYear') or 'Unknown Year')
            slug = show.get('slug')
            if slug:
                options.append(discord.SelectOption(label=label, description=desc, value=slug))
        
        super().__init__(placeholder="Select a show...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        slug = self.values[0]
        # Fetch full data
        session = self.view.bot.session
        data, error = await KeyframeAPI.get_staff_data(session, slug)
        
        if error:
            await interaction.followup.send(f"Error fetching data: {error}", ephemeral=True)
            return
            
        # Process data with stored filters
        processed = KeyframeAPI.process_data(
            data, 
            group_filter=self.filters.get('group'),
            role_filter=self.filters.get('role'),
            artist_filter=self.filters.get('artist'),
            show_stats=self.filters.get('statistics')
        )

        embeds = self.view.create_embeds(processed, data.get('anilist', {}).get('coverImage', {}).get('large'))
        
        if not embeds:
            await interaction.followup.send("No matches found with the current filters.", ephemeral=True)
            return

        # Edit original message with the first page
        view = PaginationView(embeds) if len(embeds) > 1 else None
        await interaction.followup.edit_message(message_id=self.original_interaction.message.id if self.original_interaction.message else interaction.message.id, content=None, embed=embeds[0], view=view)

class ShowSelectView(discord.ui.View):
    def __init__(self, search_results, interaction, filters, bot):
        super().__init__(timeout=60)
        self.bot = bot
        self.add_item(ShowSelect(search_results, interaction, filters))

    def create_embeds(self, processed, image_url=None):
        embeds = []
        title = processed['title']
        
        # 1. Stats Embed
        if processed.get('stats'):
            s = processed['stats']
            embed = discord.Embed(title=f"Staff Statistics: {title}", color=0x00ff00)
            if image_url: embed.set_thumbnail(url=image_url)
            
            embed.add_field(name="Total Staff", value=str(s['total_staff']), inline=True)
            embed.add_field(name="Total Groups/Episodes", value=str(s['groups']), inline=True)
            
            top_roles_str = "\n".join([f"{r}: {c}" for r, c in s['top_roles']])
            embed.add_field(name="Top Roles", value=top_roles_str or "N/A", inline=False)
            
            top_artists_str = "\n".join([f"{a}: {c}" for a, c in s['top_artists']])
            embed.add_field(name="Most Credited Artists", value=top_artists_str or "N/A", inline=False)
            
            embeds.append(embed)
            return embeds

        # 2. List Embeds (Paginated)
        if processed['filtered_empty']:
            return []

        current_embed = discord.Embed(title=f"Staff List: {title}", color=0x00b0f4)
        if image_url: current_embed.set_thumbnail(url=image_url)
        current_length = 0
        
        for group in processed['matches']:
            group_name = group['group']
            entries = "\n".join(group['entries'])
            
            # Check limits (Embed total 6000, Field value 1024)
            # We cut slightly conservatively
            if len(entries) > 1000:
                entries = entries[:1000] + "... (truncated)"
            
            # If adding this field exceeds limit, start new embed
            if current_length + len(entries) > 3000 or len(current_embed.fields) >= 20:
                embeds.append(current_embed)
                current_embed = discord.Embed(title=f"Staff List: {title} (Cont.)", color=0x00b0f4)
                if image_url: current_embed.set_thumbnail(url=image_url)
                current_length = 0
            
            current_embed.add_field(name=group_name, value=entries, inline=False)
            current_length += len(entries)
        
        if current_embed.fields:
            embeds.append(current_embed)
            
        return embeds

class PaginationView(discord.ui.View):
    def __init__(self, embeds):
        super().__init__(timeout=120)
        self.embeds = embeds
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.children[0].disabled = (self.current_page == 0) # Previous
        self.children[1].disabled = (self.current_page == len(self.embeds) - 1) # Next

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(len(self.embeds) - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="staff", description="Search specific staff credits from keyframe-staff-list.com")
    @app_commands.describe(
        query="The name of the anime to search for",
        group="Filter by Group/Episode (e.g., '#01', 'OP', 'ED')",
        role="Filter by Role (e.g., 'Key Animation', 'Director')",
        artist="Filter by Artist Name",
        statistics="Show summary statistics instead of a list"
    )
    async def staff(self, interaction: discord.Interaction, query: str, group: str = None, role: str = None, artist: str = None, statistics: bool = False):
        # 1. Validate Inputs
        if not any([group, role, artist, statistics]):
            await interaction.response.send_message(
                "❌ **Missing Filters**: You must provide at least one filter option to prevent large data dumps.\n"
                "Please use one of: `group`, `role`, `artist`, or `statistics`.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        # 2. Search for the show
        results, error = await KeyframeAPI.search(self.bot.session, query)
        
        if error:
            await interaction.followup.send(f"API Error: {error}")
            return
        
        if not results:
            await interaction.followup.send(f"No shows found for `{query}`.")
            return

        # 3. Store filters for the callback
        filters = {
            'group': group,
            'role': role,
            'artist': artist,
            'statistics': statistics
        }

        # 4. If exact match or only 1 result, auto-select?
        if len(results) == 1:
            slug = results[0]['slug']
            data, error = await KeyframeAPI.get_staff_data(self.bot.session, slug)
            if error:
                await interaction.followup.send(f"Error fetching data: {error}")
                return

            processed = KeyframeAPI.process_data(data, **filters)
            
            # Create a temporary View just to access the helper method
            temp_view = ShowSelectView([], interaction, filters, self.bot)
            embeds = temp_view.create_embeds(processed, data.get('anilist', {}).get('coverImage', {}).get('large'))
            
            if not embeds:
                await interaction.followup.send("No matches found with the current filters.")
                return

            view = PaginationView(embeds) if len(embeds) > 1 else None
            await interaction.followup.send(embed=embeds[0], view=view)
        
        else:
            # 5. Show Select Menu
            view = ShowSelectView(results, interaction, filters, self.bot)
            await interaction.followup.send(f"Found {len(results)} matches for `{query}`. Please select one:", view=view)

async def setup(bot):
    await bot.add_cog(Info(bot))