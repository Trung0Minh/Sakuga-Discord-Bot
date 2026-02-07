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
            
            # Format data based on type
            data_list = s.get('data', [])
            
            if not data_list:
                embed = discord.Embed(title=embed_title, color=0x00ff00, description="No data available.")
                if image_url: embed.set_thumbnail(url=image_url)
                embeds.append(embed)
            else:
                lines = []
                for i, (name, value) in enumerate(data_list):
                    if stat_type == 'appearance':
                        count = len(value)
                        lines.append(f"**{i+1}. {name}**: {count} eps")
                    elif stat_type == 'role_average':
                        lines.append(f"**{i+1}. {name}**: {value:.2f} per ep")
                
                current_desc = ""
                for line in lines:
                    if len(current_desc) + len(line) + 1 > 4000:
                        embed = discord.Embed(title=embed_title, color=0x00ff00, description=current_desc)
                        if image_url: embed.set_thumbnail(url=image_url)
                        embeds.append(embed)
                        current_desc = line + "\n"
                    else:
                        current_desc += line + "\n"
                
                if current_desc:
                    embed = discord.Embed(title=embed_title, color=0x00ff00, description=current_desc)
                    if image_url: embed.set_thumbnail(url=image_url)
                    embeds.append(embed)
            
            return embeds

        # 2. List Embeds (Paginated)
        if processed['filtered_empty']:
            return []

        def get_new_embed(is_cont=False):
            t = f"Staff List: {title}" + (" (Cont.)" if is_cont else "")
            emb = discord.Embed(title=t, color=0x00b0f4)
            if image_url: emb.set_thumbnail(url=image_url)
            return emb

        current_embed = get_new_embed()
        current_total_length = 0
        
        for group in processed['matches']:
            group_name = group['group']
            
            if len(current_embed.fields) >= 20 or current_total_length > 5000:
                embeds.append(current_embed)
                current_embed = get_new_embed(True)
                current_total_length = 0

            field_content = ""
            for entry in group['entries']:
                if len(field_content) + len(entry) + 2 > 1024:
                    if field_content:
                        current_embed.add_field(name=group_name if not current_embed.fields or current_embed.fields[-1].name != group_name else f"{group_name} (Cont.)", value=field_content, inline=False)
                        current_total_length += len(field_content)
                        field_content = ""
                    
                    if len(entry) > 1024:
                        parts = entry.split(", ")
                        temp_part = ""
                        for p in parts:
                            if len(temp_part) + len(p) + 2 > 1024:
                                current_embed.add_field(name=group_name + " (Cont.)", value=temp_part, inline=False)
                                current_total_length += len(temp_part)
                                temp_part = p
                            else:
                                temp_part += (", " if temp_part else "") + p
                        field_content = temp_part
                    else:
                        field_content = entry
                else:
                    field_content += ("\n\n" if field_content else "") + entry

            if field_content:
                current_embed.add_field(name=group_name if not current_embed.fields or current_embed.fields[-1].name != group_name else f"{group_name} (Cont.)", value=field_content, inline=False)
                current_total_length += len(field_content)
        
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

        view = ShowSelectView(results, interaction, filters, self.bot)
        
        if len(results) == 1:
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
            await interaction.followup.send(embed=embeds[0], view=view)
        
        else:
            await interaction.followup.send(f"Found {len(results)} matches for `{query}`. Please select one:", view=view)

async def setup(bot):
    await bot.add_cog(Info(bot))