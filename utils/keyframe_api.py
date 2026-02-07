import aiohttp
import json
import re
import html
from collections import defaultdict

class KeyframeAPI:
    SEARCH_URL = "https://keyframe-staff-list.com/api/search/?q={}"
    STAFF_PAGE_URL = "https://keyframe-staff-list.com/staff/{}"

    @staticmethod
    async def fetch_json(session, url):
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.json(), None
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
        data, error = await cls.fetch_json(session, cls.SEARCH_URL.format(query))
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
    def process_data(data, group_filter=None, role_filter=None, artist_filter=None, show_stats=False):
        """
        Filters and processes the raw staff data based on user criteria.
        Returns a structured result object or text.
        
        Structure of 'data':
        {
            "title": "Show Title",
            "menus": [
                {
                    "name": "#01" (Group Name),
                    "credits": [
                        {
                            "name": "Key Animation" (Category),
                            "roles": [
                                {
                                    "name": "Key Animation" (Role Name),
                                    "staff": [
                                        {"en": "Name", "ja": "Name", ...}
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        """
        
        results = {
            "title": data.get("title", "Unknown"),
            "matches": [],
            "stats": {},
            "filtered_empty": False
        }

        # 1. Statistics Mode
        if show_stats:
            stats = {
                "total_staff": 0,
                "groups": len(data.get("menus", [])),
                "top_roles": defaultdict(int),
                "top_artists": defaultdict(int)
            }
            
            seen_artists = set()
            
            for menu in data.get("menus", []):
                for credit in menu.get("credits", []):
                    for role_obj in credit.get("roles", []):
                        role_name = role_obj.get("name", "Unknown")
                        for person in role_obj.get("staff", []):
                            name = person.get("en") or person.get("ja") or "Unknown"
                            
                            stats["top_roles"][role_name] += 1
                            stats["top_artists"][name] += 1
                            
                            # Count unique people if possible (using ID if available, else name)
                            pid = person.get("id") or name
                            if pid not in seen_artists:
                                stats["total_staff"] += 1
                                seen_artists.add(pid)
            
            # Sort tops
            stats["top_roles"] = sorted(stats["top_roles"].items(), key=lambda x: x[1], reverse=True)[:5]
            stats["top_artists"] = sorted(stats["top_artists"].items(), key=lambda x: x[1], reverse=True)[:5]
            results["stats"] = stats
            return results

        # 2. Filtering Mode
        for menu in data.get("menus", []):
            group_name = menu.get("name", "")
            
            # Filter by Group (Partial match, case-insensitive)
            if group_filter and group_filter.lower() not in group_name.lower():
                continue

            group_match = {
                "group": group_name,
                "entries": []
            }

            for credit in menu.get("credits", []):
                # We usually skip the "category" (credit['name']) and go straight to roles
                # unless we want to filter by category? The prompt asked for "role".
                
                for role_obj in credit.get("roles", []):
                    role_name = role_obj.get("name", "")
                    
                    # Filter by Role
                    if role_filter and role_filter.lower() not in role_name.lower():
                        continue
                    
                    matching_staff = []
                    for person in role_obj.get("staff", []):
                        p_en = person.get("en", "")
                        p_ja = person.get("ja", "")
                        
                        # Filter by Artist
                        if artist_filter:
                            af = artist_filter.lower()
                            if (not p_en or af not in p_en.lower()) and (not p_ja or af not in p_ja.lower()):
                                continue
                        
                        # Display name preference: EN (JA) or just EN or just JA
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
                        group_match["entries"].append(f"**{role_name}**: {', '.join(matching_staff)}")

            if group_match["entries"]:
                results["matches"].append(group_match)

        if not results["matches"] and not results["stats"]:
            results["filtered_empty"] = True

        return results
