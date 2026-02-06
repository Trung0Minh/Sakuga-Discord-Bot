import aiohttp
import random
import urllib.parse
import asyncio

class SakugaAPI:
    BASE_URL = "https://sakugabooru.com/post.json"
    TAG_API = "https://sakugabooru.com/tag.json"

    @staticmethod
    async def get_random_post(tags=None, exclude_ids=None):
        if not tags:
            tags = ""
        
        if "-artist_unknown" not in tags:
            tags += " -artist_unknown"
        
        if exclude_ids is None:
            exclude_ids = []

        if "order:random" not in tags:
            tags += " order:random"

        params = {
            "limit": 100, # Increased limit to check for total existence
            "tags": tags.strip()
        }

        headers = {
            "User-Agent": "SakugaQuizBot/1.0 (Discord Bot)"
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(SakugaAPI.BASE_URL, params=params) as response:
                if response.status != 200:
                    print(f"Sakugabooru API Error: {response.status}")
                    return None, "api_error"
                
                posts = await response.json()
                if not posts:
                    return None, "invalid_tags"
                
                # Filter for videos
                video_posts = [p for p in posts if p.get('file_ext') in ['mp4', 'webm', 'gif']]
                if not video_posts:
                    return None, "no_videos"
                
                # Filter for unique ones
                unique_posts = [p for p in video_posts if p.get('id') not in exclude_ids]
                if not unique_posts:
                    return None, "out_of_videos"
                
                return random.choice(unique_posts), None

    @staticmethod
    async def get_artist_from_tags(tag_string):
        tags = tag_string.split()
        metadata = {'animated', 'video', 'sound', 'presumed', 'artist_unknown', 'liquid', 'effects', 'fighting', 'backgrounds', 'explosions', 'hair', 'debris'}
        tags_to_check = [t for t in tags if t not in metadata]
        
        if not tags_to_check:
            return []

        artists = []
        async with aiohttp.ClientSession() as session:
            tasks = [session.get(f"{SakugaAPI.TAG_API}?name={urllib.parse.quote(t)}") for t in tags_to_check]
            responses = await asyncio.gather(*tasks)
            
            for i, resp in enumerate(responses):
                if resp.status == 200:
                    data = await resp.json()
                    original_tag = tags_to_check[i]
                    for t in data:
                        if t['name'] == original_tag and t['type'] == 1:
                            artists.append(t['name'].replace('_', ' '))
                            break
        
        return artists

    @staticmethod
    async def get_tag_types(tags_string):
        tags = tags_string.split()
        if not tags:
            return {}
            
        tag_map = {}
        async with aiohttp.ClientSession() as session:
            tasks = [session.get(f"{SakugaAPI.TAG_API}?name={urllib.parse.quote(t)}") for t in tags]
            responses = await asyncio.gather(*tasks)
            
            for i, resp in enumerate(responses):
                if resp.status == 200:
                    data = await resp.json()
                    original_tag = tags[i]
                    for t in data:
                        if t['name'] == original_tag:
                            tag_map[original_tag] = t['type']
                            break
        return tag_map