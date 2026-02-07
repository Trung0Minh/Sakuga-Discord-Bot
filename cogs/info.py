import discord
from discord import app_commands
from discord.ext import commands
from utils.keyframe_api import KeyframeAPI
import traceback

class ShowSelect(discord.ui.Select):
    def __init__(self, search_results, filters):
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
        await self.view.update_show(interaction, self.values[0])

class EpisodeSelect(discord.ui.Select):
    def __init__(self, menus, current_val=None):
        options = []
        for menu in menus[:25]:
            name = menu.get('name', 'Unknown')
            is_default = (name == current_val)
            options.append(discord.SelectOption(label=name, value=name, default=is_default))
        
        super().__init__(placeholder="Select an episode/group...", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.view.filters['episode'] = self.values[0]
        await self.view.update_categories(interaction)

class CategorySelect(discord.ui.Select):
    def __init__(self, categories, current_val=None):
        options = [discord.SelectOption(label="All Roles", value="All", default=(current_val == "All" or current_val is None))]
        for cat in categories[:24]:
            is_default = (cat == current_val)
            options.append(discord.SelectOption(label=cat, value=cat, default=is_default))
        
        super().__init__(placeholder="Filter by Role Group...", min_values=1, max_values=1, options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.view.filters['category'] = self.values[0]
        await self.view.refresh_display(interaction)

class StatusSelect(discord.ui.Select):
    def __init__(self, current_val=None):
        options = [
            discord.SelectOption(label="All", value="All", default=(current_val == "All" or current_val is None)),
            discord.SelectOption(label="Episodes Only", value="Episodes Only", default=(current_val == "Episodes Only")),
            discord.SelectOption(label="OP/ED Only", value="OP/ED Only", default=(current_val == "OP/ED Only"))
        ]
        super().__init__(placeholder="Filter Statistics Scope...", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.view.filters['status'] = self.values[0]
        await self.view.refresh_display(interaction)

class RoleSelect(discord.ui.Select):
    def __init__(self, roles, current_val=None):
        options = []
        for role in roles[:25]:
            is_default = (role == current_val)
            options.append(discord.SelectOption(label=role, value=role, default=is_default))
        
        super().__init__(placeholder="Select Role for Statistics...", min_values=1, max_values=1, options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.view.filters['role'] = self.values[0]
        await self.view.refresh_display(interaction)

class ShowSelectView(discord.ui.View):
    def __init__(self, search_results, filters, bot, user_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.filters = filters
        self.user_id = user_id # Store user ID to restrict interaction
        self.search_results = search_results
        self.embeds = []
        self.current_page = 0
        self.current_data = None
        self.message_sent = False
        self._setup_initial_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your search! Run `/staff` to start your own.", ephemeral=True)
            return False
        return True

    def _setup_initial_items(self):
        self.clear_items()
        if self.search_results:
            self.add_item(ShowSelect(self.search_results, self.filters))
        self._add_pagination_buttons()

    def _add_pagination_buttons(self):
        prev_btn = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, row=3, disabled=True)
        prev_btn.callback = self.prev_button_callback
        self.add_item(prev_btn)

        next_btn = discord.ui.Button(label="Next", style=discord.ButtonStyle.primary, row=3, disabled=True)
        next_btn.callback = self.next_button_callback
        self.add_item(next_btn)

    async def prev_button_callback(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    async def next_button_callback(self, interaction: discord.Interaction):
        self.current_page = min(len(self.embeds) - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    async def update_show(self, interaction, slug):
        try:
            print(f"[DEBUG] update_show called for slug: {slug}")
            data, error = await KeyframeAPI.get_staff_data(self.bot.session, slug)
            if error:
                await interaction.followup.send(f"Error fetching data: {error}", ephemeral=True)
                return
            
            self.current_data = data
            menus = data.get('menus', [])
            
            self.clear_items()
            if self.search_results:
                self.add_item(ShowSelect(self.search_results, self.filters))

            stats_mode = self.filters.get('statistics')
            artist_mode = bool(self.filters.get('artist'))
            role_search_mode = bool(self.filters.get('role') and not stats_mode)

            if stats_mode:
                self.add_item(StatusSelect(self.filters.get('status')))
                if stats_mode == 'appearance':
                    all_roles = set()
                    for menu in data.get('menus', []):
                        for credit in menu.get('credits', []):
                            for role_obj in credit.get('roles', []):
                                all_roles.add(role_obj.get('name', ''))
                    sorted_roles = sorted(list(all_roles))
                    if sorted_roles:
                        self.add_item(RoleSelect(sorted_roles, self.filters.get('role')))
            
            elif not artist_mode and not role_search_mode:
                if not self.filters.get('episode') and menus:
                    self.filters['episode'] = menus[0]['name']
                if menus:
                    self.add_item(EpisodeSelect(menus, self.filters.get('episode')))
                categories = KeyframeAPI.get_role_categories(data, self.filters.get('episode'))
                if categories:
                    self.add_item(CategorySelect(categories, self.filters.get('category')))

            self._add_pagination_buttons()
            await self.refresh_display(interaction)
        except Exception as e:
            traceback.print_exc()

    async def update_categories(self, interaction):
        try:
            if not self.current_data: return
            if self.filters.get('statistics') or self.filters.get('artist') or (self.filters.get('role') and not self.filters.get('statistics')):
                return

            to_remove = [c for c in self.children if isinstance(c, CategorySelect)]
            for item in to_remove: self.remove_item(item)

            categories = KeyframeAPI.get_role_categories(self.current_data, self.filters.get('episode'))
            if categories:
                current_cat = self.filters.get('category')
                if current_cat != "All" and current_cat not in categories:
                    self.filters['category'] = "All"
                self.add_item(CategorySelect(categories, self.filters.get('category')))
            await self.refresh_display(interaction)
        except Exception as e:
            traceback.print_exc()

    async def refresh_display(self, interaction):
        try:
            if not self.current_data: return

            for child in self.children:
                if isinstance(child, discord.ui.Select):
                    current_val = None
                    if isinstance(child, EpisodeSelect): current_val = self.filters.get('episode')
                    elif isinstance(child, CategorySelect): current_val = self.filters.get('category') or "All"
                    elif isinstance(child, StatusSelect): current_val = self.filters.get('status') or "All"
                    elif isinstance(child, RoleSelect): current_val = self.filters.get('role')
                    if current_val:
                        for option in child.options: option.default = (option.value == current_val)

            processed = KeyframeAPI.process_data(
                self.current_data, 
                episode_filter=self.filters.get('episode'),
                role_filter=self.filters.get('role'),
                artist_filter=self.filters.get('artist'),
                statistics_mode=self.filters.get('statistics'),
                category_filter=self.filters.get('category'),
                status_filter=self.filters.get('status')
            )

            if processed.get('error_msg'):
                await interaction.edit_original_response(content=f"⚠️ {processed['error_msg']}", embed=None, view=self)
                return

            image_url = self.current_data.get('anilist', {}).get('coverImage', {}).get('large')
            self.embeds = self.create_embeds(processed, image_url)
            
            if not self.embeds:
                await interaction.followup.send("No matches found with the current filters.", ephemeral=True)
                return

            self.current_page = 0
            self.update_buttons()
            
            if not self.message_sent:
                await interaction.followup.send(embed=self.embeds[0], view=self)
                self.message_sent = True
            else:
                await interaction.edit_original_response(content=None, embed=self.embeds[0], view=self)
        except Exception as e:
            traceback.print_exc()

    def update_buttons(self):
        has_pages = len(self.embeds) > 1
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if not has_pages: child.disabled = True
                else:
                    if child.label == "Previous": child.disabled = (self.current_page == 0)
                    elif child.label == "Next": child.disabled = (self.current_page == len(self.embeds) - 1)

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
                for i, (name_link, value) in enumerate(data_list):
                    count = len(value) if isinstance(value, (set, list)) else value
                    lines.append(f"**{i+1}. {name_link}**: {count} eps")
                
                current_desc = ""
                for line in lines:
                    if len(current_desc) + len(line) + 1 > 3800:
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

        if processed['filtered_empty']: return []

        def get_new_embed(is_cont=False):
            t = f"Staff List: {title}" + (" (Cont.)" if is_cont else "")
            emb = discord.Embed(title=t, color=0x00b0f4)
            if image_url: emb.set_thumbnail(url=image_url)
            return emb

        current_embed = get_new_embed()
        current_total_length = len(current_embed.title)
        last_group_added = None

        for group in processed['matches']:
            group_name = group['group']
            field_content = ""
            for entry in group['entries']:
                if len(field_content) + len(entry) + 2 > 1000:
                    if field_content:
                        if current_total_length + len(field_content) > 5500 or len(current_embed.fields) >= 24:
                            embeds.append(current_embed)
                            current_embed = get_new_embed(True)
                            current_total_length = len(current_embed.title)
                            last_group_added = None
                        fname = group_name if last_group_added != group_name else "\u200b"
                        current_embed.add_field(name=fname, value=field_content, inline=False)
                        current_total_length += len(fname) + len(field_content)
                        last_group_added = group_name
                        field_content = ""
                    
                    if len(entry) > 1000:
                        parts = entry.split(", ")
                        temp_part = ""
                        for p in parts:
                            if len(temp_part) + len(p) + 2 > 1000:
                                if current_total_length + len(temp_part) > 5500 or len(current_embed.fields) >= 24:
                                    embeds.append(current_embed)
                                    current_embed = get_new_embed(True)
                                    current_total_length = len(current_embed.title)
                                    last_group_added = None
                                fname = group_name if last_group_added != group_name else "\u200b"
                                current_embed.add_field(name=fname, value=temp_part, inline=False)
                                current_total_length += len(fname) + len(temp_part)
                                last_group_added = group_name
                                temp_part = p
                            else: temp_part += (", " if temp_part else "") + p
                        field_content = temp_part
                    else: field_content = entry
                else: field_content += ("\n\n" if field_content else "") + entry

            if field_content:
                if current_total_length + len(field_content) > 5500 or len(current_embed.fields) >= 24:
                    embeds.append(current_embed)
                    current_embed = get_new_embed(True)
                    current_total_length = len(current_embed.title)
                    last_group_added = None
                fname = group_name if last_group_added != group_name else "\u200b"
                current_embed.add_field(name=fname, value=field_content, inline=False)
                current_total_length += len(fname) + len(field_content)
                last_group_added = group_name
        
        if current_embed.fields: embeds.append(current_embed)
        return embeds

class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="staff", description="Search specific staff credits from keyframe-staff-list.com")
    @app_commands.describe(
        query="The name of the anime to search for",
        role="Filter by Role (Keyword)",
        artist="Filter by Artist Name",
        statistics="Show summary statistics instead of a list"
    )
    @app_commands.choices(statistics=[
        app_commands.Choice(name="Staff Appearance", value="appearance"),
        app_commands.Choice(name="Role Average", value="role_average")
    ])
    async def staff(self, interaction: discord.Interaction, query: str, role: str = None, artist: str = None, statistics: app_commands.Choice[str] = None):
        active_filters = [f for f in [role, artist, statistics] if f is not None]
        if len(active_filters) > 1:
            await interaction.response.send_message(
                "❌ **Conflicting Filters**: You can only choose ONE mode among: `role`, `artist`, or `statistics`.",
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
            
        filters = {
            'episode': None,
            'role': role,
            'artist': artist,
            'statistics': statistics.value if statistics else None,
            'category': None,
            'status': "All"
        }

        view = ShowSelectView(results, filters, self.bot, interaction.user.id)
        if len(results) == 1:
            await view.update_show(interaction, results[0]['slug'])
        else:
            await interaction.followup.send(f"Found {len(results)} matches for `{query}`. Please select one:", view=view)
            view.message_sent = True

async def setup(bot):
    await bot.add_cog(Info(bot))