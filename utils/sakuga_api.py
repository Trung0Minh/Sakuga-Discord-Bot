import aiohttp
import random
import urllib.parse
import asyncio

class SakugaAPI:
    BASE_URL = "https://sakugabooru.com/post.json"
    TAG_API = "https://sakugabooru.com/tag.json"
    HEADERS = {
        "User-Agent": "SakugaQuizBot/1.0 (Discord Bot; contact: your_discord_tag)"
    }

    @staticmethod
    async def fetch_json(session, url, params=None):
        """Helper to ensure responses are closed."""
        try:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    return await response.json(), None
                return None, response.status
        except Exception as e:
            return None, str(e)

    @staticmethod
    async def get_random_post(tags=None, exclude_ids=None):
        print(f"[DEBUG] Fetching post with tags: {tags}")
        if not tags:
            tags = ""
        
        if "-artist_unknown" not in tags:
            tags += " -artist_unknown"
        
        if exclude_ids is None:
            exclude_ids = []

        if "order:random" not in tags:
            tags += " order:random"

        params = {
            "limit": 100,
            "tags": tags.strip()
        }

        async with aiohttp.ClientSession(headers=SakugaAPI.HEADERS) as session:
            data, error = await SakugaAPI.fetch_json(session, SakugaAPI.BASE_URL, params)
            
            if error:
                print(f"[DEBUG] API Error (Post): {error}")
                return None, "api_error"
            
            if not data:
                return None, "invalid_tags"
            
            video_posts = [p for p in data if p.get('file_ext') in ['mp4', 'webm', 'gif']]
            if not video_posts:
                return None, "no_videos"
            
            unique_posts = [p for p in video_posts if p.get('id') not in exclude_ids]
            if not unique_posts:
                return None, "out_of_videos"
            
            selected = random.choice(unique_posts)
            print(f"[DEBUG] Selected post ID: {selected.get('id')}")
            return selected, None

    @staticmethod
    async def get_artist_from_tags(tag_string):
        tags = tag_string.split()
        metadata = {'animated', 'video', 'sound', 'presumed', 'artist_unknown', 'liquid', 'effects', 'fighting', 'backgrounds', 'explosions', 'hair', 'debris'}
        tags_to_check = [t for t in tags if t not in metadata]
        
        if not tags_to_check:
            return []

        artists = []
        async with aiohttp.ClientSession(headers=SakugaAPI.HEADERS) as session:
            tasks = []
            for t in tags_to_check:
                url = f"{SakugaAPI.TAG_API}?name={urllib.parse.quote(t)}"
                tasks.append(SakugaAPI.fetch_json(session, url))

            results = await asyncio.gather(*tasks)
            
            for i, (data, error) in enumerate(results):
                if data:
                    original_tag = tags_to_check[i]
                    for t in data:
                        if t['name'] == original_tag and t['type'] == 1:
                            artists.append(t['name'].replace('_', ' '))
                            break
        
        print(f"[DEBUG] Found artists: {artists}")
        return artists

    @staticmethod
    async def get_tag_types(tags_string):
        tags = tags_string.split()
        if not tags:
            return {}
            
        tag_map = {}
        async with aiohttp.ClientSession(headers=SakugaAPI.HEADERS) as session:
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
