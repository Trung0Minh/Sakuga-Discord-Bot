import discord
from discord import app_commands
from discord.ext import commands
from utils.keyframe_api import KeyframeAPI

class ShowSelect(discord.ui.Select):
    def __init__(self, search_results, original_interaction, filters):
        self.original_interaction = original_interaction
        self.filters = filters
        
        options = []
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
        await self.view.update_show(interaction, slug)

class EpisodeSelect(discord.ui.Select):
    def __init__(self, menus, current_val=None):
        options = []
        for menu in menus[:25]:
            name = menu.get('name', 'Unknown')
            # Mark as default if it matches current filter
            is_default = (name == current_val)
            options.append(discord.SelectOption(label=name, value=name, default=is_default))
        
        super().__init__(placeholder="Select an episode/group...", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.view.filters['episode'] = self.values[0]
        await self.view.refresh_display(interaction)

class ShowSelectView(discord.ui.View):
    def __init__(self, search_results, interaction, filters, bot):
        super().__init__(timeout=180)
        self.bot = bot
        self.interaction = interaction
        self.filters = filters
        self.embeds = []
        self.current_page = 0
        self.current_data = None
        
        if search_results:
            self.add_item(ShowSelect(search_results, interaction, filters))

    async def update_show(self, interaction, slug):
        data, error = await KeyframeAPI.get_staff_data(self.bot.session, slug)
        if error:
            await interaction.followup.send(f"Error fetching data: {error}", ephemeral=True)
            return
        
        self.current_data = data
        menus = data.get('menus', [])
        
        # Default Logic: If no filters set, default to first menu (Overview)
        if not any([self.filters.get('role'), self.filters.get('artist'), self.filters.get('statistics')]):
            if not self.filters.get('episode') and menus:
                self.filters['episode'] = menus[0]['name']

        # Update Episode Select
        self.children = [c for child in self.children if not isinstance(child, EpisodeSelect)]
        if menus:
            self.add_item(EpisodeSelect(menus, self.filters.get('episode')))
            
        await self.refresh_display(interaction)

    async def refresh_display(self, interaction):
        if not self.current_data:
            return

        processed = KeyframeAPI.process_data(
            self.current_data, 
            episode_filter=self.filters.get('episode'),
            role_filter=self.filters.get('role'),
            artist_filter=self.filters.get('artist'),
            statistics_mode=self.filters.get('statistics')
        )

        image_url = self.current_data.get('anilist', {}).get('coverImage', {}).get('large')
        self.embeds = self.create_embeds(processed, image_url)
        
        if not self.embeds:
            await interaction.followup.send("No matches found with the current filters.", ephemeral=True)
            return

        self.current_page = 0
        self.update_buttons()
        
        await interaction.followup.edit_message(
            message_id=self.interaction.message.id if self.interaction.message else interaction.message.id, 
            content=None, 
            embed=self.embeds[0], 
            view=self
        )

    def update_buttons(self):
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

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, row=2, disabled=True)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, row=2, disabled=True)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(len(self.embeds) - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    def create_embeds(self, processed, image_url=None):
        embeds = []
        title = processed['title']
        
        if processed.get('stats'):
            s = processed['stats']
            stat_type = s.get('type')
            embed_title = f"Staff Statistics ({'Appearance' if stat_type == 'appearance' else 'Role Average'}): {title}"
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
        role="Filter by Role (e.g., 'Key Animation', 'Director')",
        artist="Filter by Artist Name",
        statistics="Show summary statistics instead of a list"
    )
    @app_commands.choices(statistics=[
        app_commands.Choice(name="Staff Appearance", value="appearance"),
        app_commands.Choice(name="Role Average", value="role_average")
    ])
    async def staff(self, interaction: discord.Interaction, query: str, role: str = None, artist: str = None, statistics: app_commands.Choice[str] = None):
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
            'episode': None, # Default None, View logic handles "Overview" default
            'role': role,
            'artist': artist,
            'statistics': stats_value
        }

        view = ShowSelectView(results, interaction, filters, self.bot)
        
        if len(results) == 1:
            await view.update_show(interaction, results[0]['slug'])
        else:
            await interaction.followup.send(f"Found {len(results)} matches for `{query}`. Please select one:", view=view)

async def setup(bot):
    await bot.add_cog(Info(bot))