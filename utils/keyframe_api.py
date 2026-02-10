import aiohttp
import json
import re
import html
import urllib.parse
from collections import defaultdict

class KeyframeAPI:
    SEARCH_URL = "https://keyframe-staff-list.com/api/search/?q={}"
    STAFF_PAGE_URL = "https://keyframe-staff-list.com/staff/{}"
    BOORU_SEARCH_URL = "https://sakugabooru.com/post?tags={}"

    @staticmethod
    async def fetch_json(session, url):
        try:
            # Add Accept header and use content_type=None to be more flexible with mimetypes
            headers = {"Accept": "application/json"}
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    # Use content_type=None because some APIs return JSON with text/html mimetype
                    return await response.json(content_type=None), None
                return None, f"HTTP {response.status}"
        except Exception as e:
            return None, str(e)

    @staticmethod
    async def fetch_text(session, url):
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.text(), None
                return None, f"HTTP {response.status}"
        except Exception as e:
            return None, str(e)

    @classmethod
    async def search(cls, session, query):
        """
        Searches for a show by title.
        Returns a list of dicts: {'slug': str, 'name': str, 'year': int, 'kv': str}
        """
        encoded_query = urllib.parse.quote(query)
        data, error = await cls.fetch_json(session, cls.SEARCH_URL.format(encoded_query))
        if error:
            return [], error
        
        # API returns {'staff': [...], 'stafflists': [...]}
        # We only care about 'stafflists' (the shows)
        return data.get('stafflists', []), None

    @classmethod
    async def get_staff_data(cls, session, slug):
        """
        Fetches the full staff data for a specific show slug.
        Extracts JSON embedded in the HTML.
        """
        html_content, error = await cls.fetch_text(session, cls.STAFF_PAGE_URL.format(slug))
        if error:
            return None, error

        # Regex to find <script id="staffListData" type="application/json">...</script>
        match = re.search(r'<script id="staffListData" type="application/json">(.*?)</script>', html_content, re.DOTALL)
        if not match:
            return None, "json_not_found"

        try:
            json_str = match.group(1)
            data = json.loads(json_str)
            return data, None
        except json.JSONDecodeError:
            return None, "json_decode_error"

    @staticmethod
    def get_role_categories(data, episode_name=None):
        """
        Extracts categories from the data settings for the role dropdown.
        If episode_name is provided, returns only categories present in that episode.
        """
        categories = []
        seen = set()

        # If filtering by episode, scan that episode specifically
        if episode_name:
            for menu in data.get('menus', []):
                if menu.get('name') == episode_name:
                    for credit in menu.get('credits', []):
                        cat_name = credit.get('name')
                        if cat_name and cat_name not in seen:
                            categories.append(cat_name)
                            seen.add(cat_name)
            return categories

        # Otherwise use global settings or scan all
        if 'settings' in data and 'categories' in data['settings']:
            for cat in data['settings']['categories']:
                if isinstance(cat, dict) and 'name' in cat:
                    categories.append(cat['name'])
                elif isinstance(cat, str):
                    categories.append(cat)
        
        # Fallback if settings are missing or empty
        if not categories:
            for menu in data.get('menus', []):
                for credit in menu.get('credits', []):
                    cat_name = credit.get('name')
                    if cat_name and cat_name not in seen:
                        categories.append(cat_name)
                        seen.add(cat_name)
        return categories

    @classmethod
    def process_data(cls, data, episode_filter=None, role_filter=None, artist_filter=None, statistics_mode=None, category_filter=None, status_filter=None):
        """
        Filters and processes the raw staff data based on user criteria.
        Returns a structured result object or text.
        """
        
        results = {
            "title": data.get("title", "Unknown"),
            "matches": [],
            "stats": {},
            "filtered_empty": False,
            "error_msg": None
        }

        # Helper to filter menus based on status
        def filter_menus_by_status(menus, status):
            if not status or status == "All":
                return menus
            if status == "Episodes Only":
                return [m for m in menus if m.get("name", "").startswith("#")]
            if status == "OP/ED Only":
                return [m for m in menus if not m.get("name", "").startswith("#")]
            return menus

        # 1. Statistics Mode
        if statistics_mode:
            results["stats_mode"] = statistics_mode
            
            # Apply status filter first
            filtered_menus = filter_menus_by_status(data.get("menus", []), status_filter)
            
            # Common loop for stats
            if statistics_mode == "appearance":
                # Require Role Filter for Appearance Stats
                if not role_filter:
                    results["error_msg"] = "Please select a Role to view Staff Appearance statistics."
                    return results

                # "Staff Appearance": List of staff sorted by number of episodes they are credited in for a SPECIFIC ROLE
                artist_episodes = defaultdict(set)
                
                rf = role_filter.lower()
                
                for menu in filtered_menus:
                    ep_name = menu.get("name", "")
                    for credit in menu.get("credits", []):
                        for role_obj in credit.get("roles", []):
                            role_name = role_obj.get("name", "").strip()
                            if not role_name or role_name.lower() == "unknown":
                                continue

                            # Filter by the required role
                            if rf not in role_name.lower():
                                continue
                                
                            for person in role_obj.get("staff", []):
                                name_link = cls._format_name_link(
                                    person.get("en"), 
                                    person.get("ja"), 
                                    person.get("id"),
                                    is_studio=person.get("isStudio", False)
                                )
                                if not name_link:
                                    continue
                                
                                name_link = name_link.strip()
                                artist_episodes[name_link].add(ep_name)
                
                # Sort by count
                sorted_artists = sorted(artist_episodes.items(), key=lambda x: len(x[1]), reverse=True)[:50] # Top 50
                results["stats"] = {
                    "type": "appearance",
                    "data": sorted_artists # List of (NameLink, Set(Groups))
                }

            elif statistics_mode == "role_average":
                # "Role Average": Average staff count per episode for each role
                role_counts_per_ep = defaultdict(list)
                
                total_groups = len(filtered_menus)
                
                for menu in filtered_menus:
                    current_ep_role_counts = defaultdict(int)
                    
                    for credit in menu.get("credits", []):
                        for role_obj in credit.get("roles", []):
                            role_name = role_obj.get("name", "").strip()
                            if not role_name or role_name.lower() == "unknown":
                                continue
                            
                            # Filter out staff with no names before counting
                            valid_staff_count = 0
                            for person in role_obj.get("staff", []):
                                if person.get("en") or person.get("ja"):
                                    valid_staff_count += 1
                                    
                            current_ep_role_counts[role_name] += valid_staff_count
                    
                    for r, c in current_ep_role_counts.items():
                        role_counts_per_ep[r].append(c)
                
                avg_data = []
                for role, counts in role_counts_per_ep.items():
                    avg = sum(counts) / total_groups if total_groups > 0 else 0
                    if avg > 0:
                        avg_data.append((role, avg))
                
                avg_data.sort(key=lambda x: x[1], reverse=True)
                results["stats"] = {
                    "type": "role_average",
                    "data": avg_data[:50]
                }

            return results

        # 2. Artist Filter Mode (Aggregated View)
        if artist_filter:
            artist_data = defaultdict(lambda: defaultdict(list))
            af = artist_filter.lower()
            
            for menu in data.get("menus", []):
                group_name = menu.get("name", "")
                
                for credit in menu.get("credits", []):
                    # Filter by Category (Role Group) if provided
                    if category_filter and category_filter != "All" and credit.get("name") != category_filter:
                        continue

                    for role_obj in credit.get("roles", []):
                        role_name = role_obj.get("name", "").strip()
                        if not role_name or role_name.lower() == "unknown":
                            continue
                        
                        # Apply role filter if present
                        if role_filter and role_filter.lower() not in role_name.lower():
                            continue

                        for person in role_obj.get("staff", []):
                            p_en = person.get("en", "")
                            p_ja = person.get("ja", "")
                            p_id = person.get("id")
                            
                            # Check if this person matches the artist filter
                            if (not p_en or af not in p_en.lower()) and (not p_ja or af not in p_ja.lower()):
                                continue
                            
                            # Construct Link
                            name_link = cls._format_name_link(
                                p_en, 
                                p_ja, 
                                p_id,
                                is_studio=person.get("isStudio", False)
                            )
                            if not name_link:
                                continue
                            
                            # Determine display name for grouping
                            display_name = p_en or p_ja

                            artist_data[(display_name, name_link)][role_name].append(group_name)

            # Format the output for the embed
            for (display_name, name_link), roles in artist_data.items():
                entries = []
                # Add the clickable link as the first line if it's actually a link
                if "(" in name_link and "[" in name_link:
                    entries.append(name_link)

                # Sort roles alphabetically
                for role, groups in sorted(roles.items()):
                    group_str = ", ".join(groups) 
                    entries.append(f"**{role}**:\n{group_str}") # Role then newline
                
                results["matches"].append({
                    "group": display_name, 
                    "entries": entries,
                    "sep": "\n\n"
                })
                
            if not results["matches"]:
                results["filtered_empty"] = True
                
            return results

        # 3. Role Filter Mode (Aggregated View - Pivot: Role -> Artist -> Groups)
        if role_filter:
            # Structure: { "Role Name": { "Artist Name": ["Group1", "Group2"] } }
            role_data = defaultdict(lambda: defaultdict(list))
            rf = role_filter.lower()

            for menu in data.get("menus", []):
                group_name = menu.get("name", "")

                for credit in menu.get("credits", []):
                    if category_filter and category_filter != "All" and credit.get("name") != category_filter:
                        continue

                    for role_obj in credit.get("roles", []):
                        role_name = role_obj.get("name", "").strip()
                        if not role_name or role_name.lower() == "unknown":
                            continue

                        # Filter by Role
                        if rf not in role_name.lower():
                            continue

                        for person in role_obj.get("staff", []):
                            name_link = cls._format_name_link(
                                person.get("en"), 
                                person.get("ja"), 
                                person.get("id"),
                                is_studio=person.get("isStudio", False)
                            )
                            if not name_link:
                                continue

                            role_data[role_name][name_link].append(group_name)

            # Format output
            for role_name, artists in role_data.items():
                entries = []
                for artist_name, groups in sorted(artists.items()):
                    group_str = ", ".join(groups) 
                    entries.append(f"**{artist_name}**:\n{group_str}") # Artist then newline

                results["matches"].append({
                    "group": role_name, # Header will be the Role Name
                    "entries": entries,
                    "sep": "\n" # Names stay next to each other vertically
                })

            if not results["matches"]:
                results["filtered_empty"] = True
            
            return results

        # 4. Standard Episode Filter (Default)
        for menu in data.get("menus", []):
            group_name = menu.get("name", "")
            
            # Filter by Episode
            if episode_filter and episode_filter.lower() not in group_name.lower():
                continue

            group_match = {
                "group": group_name,
                "entries": []
            }

            for credit in menu.get("credits", []):
                # Filter by Category (Role Group)
                if category_filter and category_filter != "All" and credit.get("name") != category_filter:
                    continue

                for role_obj in credit.get("roles", []):
                    role_name = role_obj.get("name", "").strip()
                    if not role_name or role_name.lower() == "unknown":
                        continue
                    
                    # Process staff with studio-aware formatting
                    staff_list = role_obj.get("staff", [])
                    processed_staff = []
                    for person in staff_list:
                        is_studio = person.get("isStudio", False)
                        name_link = cls._format_name_link(
                            person.get("en"), 
                            person.get("ja"), 
                            person.get("id"),
                            is_studio=is_studio
                        )
                        if name_link:
                            processed_staff.append({"link": name_link, "is_studio": is_studio})

                    if processed_staff:
                        staff_str = ""
                        for i in range(len(processed_staff)):
                            current = processed_staff[i]
                            staff_str += current["link"]
                            
                            if i < len(processed_staff) - 1:
                                next_person = processed_staff[i+1]
                                
                                if not current["is_studio"] and next_person["is_studio"]:
                                    # Staff followed by Studio: 2 newlines
                                    staff_str += "\n\n"
                                elif current["is_studio"] or next_person["is_studio"]:
                                    # Studio followed by anything, OR anything followed by Studio (handled above)
                                    # This covers Studio -> Staff and Studio -> Studio: 1 newline
                                    staff_str += "\n"
                                else:
                                    # Staff -> Staff: comma
                                    staff_str += ", "
                                
                        group_match["entries"].append(f"**{role_name}**:\n{staff_str}")

            if group_match["entries"]:
                results["matches"].append(group_match)

        if not results["matches"] and not results["stats"]:
            results["filtered_empty"] = True

        return results

    @classmethod
    def _format_name_link(cls, en_name, ja_name, person_id=None, is_studio=False):
        """Helper to format name as a Markdown link. Prefers keyframe-staff-list ID."""
        display_name = en_name or ja_name
        if not display_name:
            return None
            
        if is_studio:
            display_name = f"**{display_name}**"

        # Create link
        if person_id:
            return f"[{display_name}](https://keyframe-staff-list.com/person/{person_id})"
        
        if en_name:
            # Replace spaces with underscores for Sakugabooru tag format fallback
            tag = en_name.lower().replace(' ', '_')
            encoded_tag = urllib.parse.quote(tag)
            return f"[{display_name}]({cls.BOORU_SEARCH_URL.format(encoded_tag)})"
        
        return display_name