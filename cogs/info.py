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
        
        super().__init__(placeholder="Select a show...", min_values=1, max_values=1, options=options, row=0)

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
            statistics_mode=self.filters.get('statistics')
        )

        embeds = self.view.create_embeds(processed, data.get('anilist', {}).get('coverImage', {}).get('large'))
        
        if not embeds:
            await interaction.followup.send("No matches found with the current filters.", ephemeral=True)
            return

        # Update view state
        self.view.embeds = embeds
        self.view.current_page = 0
        self.view.update_buttons()
        
        # Edit message with new embed and SAME view (to keep dropdown)
        await interaction.followup.edit_message(
            message_id=self.original_interaction.message.id if self.original_interaction.message else interaction.message.id, 
            content=None, 
            embed=embeds[0], 
            view=self.view
        )

class ShowSelectView(discord.ui.View):
    def __init__(self, search_results, interaction, filters, bot):
        super().__init__(timeout=120)
        self.bot = bot
        self.embeds = []
        self.current_page = 0
        
        # Add Select Menu
        self.add_item(ShowSelect(search_results, interaction, filters))

    def update_buttons(self):
        # Enable/Disable buttons based on pages
        has_pages = len(self.embeds) > 1
        
        # We need to find the buttons in children. 
        # They are usually at indices 1 and 2 if Select is 0.
        # But to be safe, we can reference them by custom_id or type if we set them.
        # Easier: Just iterate and check type or label.
        
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if not has_pages:
                    child.disabled = True
                else:
                    if child.label == "Previous":
                        child.disabled = (self.current_page == 0)
                    elif child.label == "Next":
                        child.disabled = (self.current_page == len(self.embeds) - 1)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, row=1, disabled=True)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, row=1, disabled=True)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(len(self.embeds) - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    def create_embeds(self, processed, image_url=None):
        embeds = []
        title = processed['title']
        
        # 1. Stats Embed
        if processed.get('stats'):
            s = processed['stats']
            stat_type = s.get('type')
            
            embed_title = f"Staff Statistics ({'Appearance' if stat_type == 'appearance' else 'Role Average'}): {title}"
            embed = discord.Embed(title=embed_title, color=0x00ff00)
            if image_url: embed.set_thumbnail(url=image_url)
            
            # Format data based on type
            data_list = s.get('data', [])
            
            if not data_list:
                embed.description = "No data available."
            else:
                desc = ""
                for i, (name, value) in enumerate(data_list):
                    if stat_type == 'appearance':
                        # value is a Set of groups
                        count = len(value)
                        desc += f"**{i+1}. {name}**: {count} eps\n"
                    elif stat_type == 'role_average':
                        # value is average count
                        desc += f"**{i+1}. {name}**: {value:.2f} per ep\n"
                
                # Truncate if too long
                if len(desc) > 4000:
                    desc = desc[:4000] + "... (truncated)"
                embed.description = desc
            
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
            entries = "\n\n".join(group['entries']) # Double newline for separation
            
            # Check limits (Embed total 6000, Field value 1024)
            if len(entries) > 1000:
                entries = entries[:1000] + "... (truncated)"
            
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
    @app_commands.choices(statistics=[
        app_commands.Choice(name="Staff Appearance", value="appearance"),
        app_commands.Choice(name="Role Average", value="role_average")
    ])
    async def staff(self, interaction: discord.Interaction, query: str, group: str = None, role: str = None, artist: str = None, statistics: app_commands.Choice[str] = None):
        if not any([group, role, artist, statistics]):
            await interaction.response.send_message(
                "❌ **Missing Filters**: You must provide at least one filter option.\n"
                "Please use one of: `group`, `role`, `artist`, or `statistics`.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        results, error = await KeyframeAPI.search(self.bot.session, query)
        
        if error:
            await interaction.followup.send(f"API Error: {error}")
            return
        
        if not results:
            await interaction.followup.send(f"No shows found for `{query}`.")
            return
            
        stats_value = statistics.value if statistics else None
        filters = {
            'group': group,
            'role': role,
            'artist': artist,
            'statistics': stats_value
        }

        # Use the combined view for both single and multiple results to ensure consistent behavior
        view = ShowSelectView(results, interaction, filters, self.bot)
        
        if len(results) == 1:
            # Auto-select logic using the view's internal methods
            slug = results[0]['slug']
            data, error = await KeyframeAPI.get_staff_data(self.bot.session, slug)
            if error:
                await interaction.followup.send(f"Error fetching data: {error}")
                return

            processed = KeyframeAPI.process_data(
                data, 
                group_filter=filters.get('group'),
                role_filter=filters.get('role'),
                artist_filter=filters.get('artist'),
                statistics_mode=filters.get('statistics')
            )
            
            embeds = view.create_embeds(processed, data.get('anilist', {}).get('coverImage', {}).get('large'))
            
            if not embeds:
                await interaction.followup.send("No matches found with the current filters.")
                return

            view.embeds = embeds
            view.update_buttons()
            
            # Send with the view so the dropdown (and buttons) are present
            await interaction.followup.send(embed=embeds[0], view=view)
        
        else:
            await interaction.followup.send(f"Found {len(results)} matches for `{query}`. Please select one:", view=view)

async def setup(bot):
    await bot.add_cog(Info(bot))
