import aiohttp
import json
import re
import html
import urllib.parse
from collections import defaultdict

class KeyframeAPI:
    SEARCH_URL = "https://keyframe-staff-list.com/api/search/?q={}"
    STAFF_PAGE_URL = "https://keyframe-staff-list.com/staff/{}"

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
    def process_data(data, episode_filter=None, role_filter=None, artist_filter=None, statistics_mode=None):
        """
        Filters and processes the raw staff data based on user criteria.
        Returns a structured result object or text.
        """
        
        results = {
            "title": data.get("title", "Unknown"),
            "matches": [],
            "stats": {},
            "filtered_empty": False
        }

        # 1. Statistics Mode
        if statistics_mode:
            results["stats_mode"] = statistics_mode
            
            # Common loop for stats
            if statistics_mode == "appearance":
                # "Staff Appearance": List of staff sorted by number of episodes they are credited in
                artist_episodes = defaultdict(set)
                
                for menu in data.get("menus", []):
                    ep_name = menu.get("name", "")
                    for credit in menu.get("credits", []):
                        for role_obj in credit.get("roles", []):
                            for person in role_obj.get("staff", []):
                                p_en = person.get("en", "")
                                p_ja = person.get("ja", "")
                                
                                full_name = "Unknown"
                                if p_ja and p_en:
                                    full_name = f"{p_ja} / {p_en}"
                                elif p_ja:
                                    full_name = p_ja
                                elif p_en:
                                    full_name = p_en
                                
                                artist_episodes[full_name].add(ep_name)
                
                # Sort by count
                sorted_artists = sorted(artist_episodes.items(), key=lambda x: len(x[1]), reverse=True)[:20] # Top 20
                results["stats"] = {
                    "type": "appearance",
                    "data": sorted_artists # List of (Name, Set(Groups))
                }

            elif statistics_mode == "role_average":
                # "Role Average": Average staff count per episode for each role
                role_counts_per_ep = defaultdict(list)
                
                # Only count actual episodes (starting with #) for the average denominator logic
                episodes = [m for m in data.get("menus", []) if m.get("name", "").startswith("#")]
                total_episodes = len(episodes)
                
                for menu in episodes:
                    current_ep_role_counts = defaultdict(int)
                    
                    for credit in menu.get("credits", []):
                        for role_obj in credit.get("roles", []):
                            role_name = role_obj.get("name", "Unknown")
                            count = len(role_obj.get("staff", []))
                            current_ep_role_counts[role_name] += count
                    
                    for r, c in current_ep_role_counts.items():
                        role_counts_per_ep[r].append(c)
                
                avg_data = []
                for role, counts in role_counts_per_ep.items():
                    avg = sum(counts) / total_episodes if total_episodes > 0 else 0
                    avg_data.append((role, avg))
                
                avg_data.sort(key=lambda x: x[1], reverse=True)
                results["stats"] = {
                    "type": "role_average",
                    "data": avg_data[:20]
                }

            return results

        # 2. Artist Filter Mode (Aggregated View)
        if artist_filter:
            artist_data = defaultdict(lambda: defaultdict(list))
            af = artist_filter.lower()
            
            for menu in data.get("menus", []):
                ep_name = menu.get("name", "")
                
                for credit in menu.get("credits", []):
                    for role_obj in credit.get("roles", []):
                        role_name = role_obj.get("name", "")
                        
                        if role_filter and role_filter.lower() not in role_name.lower():
                            continue

                        for person in role_obj.get("staff", []):
                            p_en = person.get("en", "")
                            p_ja = person.get("ja", "")
                            
                            if (not p_en or af not in p_en.lower()) and (not p_ja or af not in p_ja.lower()):
                                continue
                            
                            full_name = "Unknown"
                            if p_ja and p_en:
                                full_name = f"{p_ja} / {p_en}"
                            elif p_ja:
                                full_name = p_ja
                            elif p_en:
                                full_name = p_en
                                
                            artist_data[full_name][role_name].append(ep_name)

            for artist_name, roles in artist_data.items():
                entries = []
                for role, eps in sorted(roles.items()):
                    ep_str = ", ".join(eps)
                    entries.append(f"**{role}**:\n{ep_str}")
                
                results["matches"].append({
                    "group": artist_name, 
                    "entries": entries
                })
                
            if not results["matches"]:
                results["filtered_empty"] = True
                
            return results

        # 3. Role Filter Mode (Aggregated View)
        if role_filter:
            role_data = defaultdict(lambda: defaultdict(list))
            rf = role_filter.lower()

            for menu in data.get("menus", []):
                ep_name = menu.get("name", "")

                for credit in menu.get("credits", []):
                    for role_obj in credit.get("roles", []):
                        role_name = role_obj.get("name", "")

                        if rf not in role_name.lower():
                            continue

                        for person in role_obj.get("staff", []):
                            p_en = person.get("en", "")
                            p_ja = person.get("ja", "")
                            
                            full_name = "Unknown"
                            if p_ja and p_en:
                                full_name = f"{p_ja} / {p_en}"
                            elif p_ja:
                                full_name = p_ja
                            elif p_en:
                                full_name = p_en
                            
                            role_data[role_name][full_name].append(ep_name)

            for role_name, artists in role_data.items():
                entries = []
                for artist_name, eps in sorted(artists.items()):
                    ep_str = ", ".join(eps)
                    entries.append(f"**{artist_name}**:\n{ep_str}")

                results["matches"].append({
                    "group": role_name,
                    "entries": entries
                })

            if not results["matches"]:
                results["filtered_empty"] = True
            
            return results

        # 4. Standard Episode Filter (Default)
        for menu in data.get("menus", []):
            ep_name = menu.get("name", "")
            
            if episode_filter and episode_filter.lower() not in ep_name.lower():
                continue

            ep_match = {
                "group": ep_name,
                "entries": []
            }

            for credit in menu.get("credits", []):
                for role_obj in credit.get("roles", []):
                    role_name = role_obj.get("name", "")
                    
                    matching_staff = []
                    for person in role_obj.get("staff", []):
                        p_en = person.get("en", "")
                        p_ja = person.get("ja", "")
                        
                        d_name = p_en
                        if p_ja and p_en != p_ja:
                            if not d_name:
                                d_name = p_ja
                            else:
                                d_name = f"{p_en} ({p_ja})"
                        elif not d_name:
                            d_name = p_ja or "Unknown"

                        matching_staff.append(d_name)
                    
                    if matching_staff:
                        ep_match["entries"].append(f"**{role_name}**:\n{', '.join(matching_staff)}")

            if ep_match["entries"]:
                results["matches"].append(ep_match)

        if not results["matches"] and not results["stats"]:
            results["filtered_empty"] = True

        return results