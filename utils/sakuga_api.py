import aiohttp
import random
import urllib.parse
import asyncio

class SakugaAPI:
    BASE_URL = "https://sakugabooru.com/post.json"
    TAG_API = "https://sakugabooru.com/tag.json"

    @staticmethod
    async def fetch_json(session, url, params=None):
        """Helper to ensure responses are handled safely with timeouts."""
        try:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data, None
                return None, f"HTTP {response.status}"
        except asyncio.TimeoutError:
            return None, "timeout"
        except Exception as e:
            return None, str(e)

    @staticmethod
    async def get_random_post(session, tags=None, exclude_ids=None):
        if not tags:
            tags = ""
        
        # Always exclude unknown artists to keep the game fair
        if "-artist_unknown" not in tags:
            tags += " -artist_unknown"
        
        if exclude_ids is None:
            exclude_ids = []

        # Ensure random order
        if "order:random" not in tags:
            tags += " order:random"

        params = {
            "limit": 100, # Fetch a batch to filter locally
            "tags": tags.strip()
        }

        data, error = await SakugaAPI.fetch_json(session, SakugaAPI.BASE_URL, params)
        if error:
            return None, "api_error"
        
        if not data:
            return None, "invalid_tags"
        
        # Filter: Must be a video (mp4/webm/gif)
        video_posts = [p for p in data if p.get('file_ext') in ['mp4', 'webm', 'gif']]
        if not video_posts:
            return None, "no_videos"
        
        # Filter: Must not have been played this session
        unique_posts = [p for p in video_posts if p.get('id') not in exclude_ids]
        if not unique_posts:
            return None, "out_of_videos"
        
        return random.choice(unique_posts), None

    @staticmethod
    async def get_artist_from_tags(session, tag_string):
        """
        Identifies artist tags from a post's tag string.
        """
        tags = tag_string.split()
        # Skip common metadata tags to save API calls
        metadata = {'animated', 'video', 'sound', 'presumed', 'artist_unknown', 'liquid', 'effects', 'fighting', 'backgrounds', 'explosions', 'hair', 'debris'}
        tags_to_check = [t for t in tags if t not in metadata]
        
        if not tags_to_check:
            return []

        artists = []
        tasks = []
        
        # Prepare parallel requests
        for t in tags_to_check:
            url = f"{SakugaAPI.TAG_API}?name={urllib.parse.quote(t)}"
            tasks.append(SakugaAPI.fetch_json(session, url))

        # Execute all requests at once
        results = await asyncio.gather(*tasks)
        
        for i, (data, error) in enumerate(results):
            if data:
                original_tag = tags_to_check[i]
                for t in data:
                    # Type 1 is Artist
                    if t['name'] == original_tag and t['type'] == 1:
                        artists.append(t['name'].replace('_', ' '))
                        break
        
        return artists

    @staticmethod
    async def get_tag_types(session, tags_string):
        """
        Used to validate user input tags (prevent using artist names as filters).
        """
        tags = tags_string.split()
        if not tags:
            return {}
            
        tag_map = {}
        tasks = []
        for t in tags:
            url = f"{SakugaAPI.TAG_API}?name={urllib.parse.quote(t)}"
            tasks.append(SakugaAPI.fetch_json(session, url))

        results = await asyncio.gather(*tasks)
        
        for i, (data, error) in enumerate(results):
            if data:
                original_tag = tags[i]
                for t in data:
                    if t['name'] == original_tag:
                        tag_map[original_tag] = t['type']
                        break
        return tag_map
