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
            async with session.get(SakugaAPI.BASE_URL, params=params) as response:
                if response.status != 200:
                    print(f"[DEBUG] Sakugabooru API Error (Post): {response.status}")
                    return None, "api_error"
                
                posts = await response.json()
                print(f"[DEBUG] API returned {len(posts)} posts.")
                if not posts:
                    return None, "invalid_tags"
                
                video_posts = [p for p in posts if p.get('file_ext') in ['mp4', 'webm', 'gif']]
                print(f"[DEBUG] {len(video_posts)} posts are videos.")
                if not video_posts:
                    return None, "no_videos"
                
                unique_posts = [p for p in video_posts if p.get('id') not in exclude_ids]
                print(f"[DEBUG] {len(unique_posts)} unique video posts available.")
                if not unique_posts:
                    return None, "out_of_videos"
                
                selected = random.choice(unique_posts)
                print(f"[DEBUG] Selected post ID: {selected.get('id')}")
                return selected, None

    @staticmethod
    async def get_artist_from_tags(tag_string):
        tags = tag_string.split()
        print(f"[DEBUG] Checking artists for tags: {tags}")
        metadata = {'animated', 'video', 'sound', 'presumed', 'artist_unknown', 'liquid', 'effects', 'fighting', 'backgrounds', 'explosions', 'hair', 'debris'}
        tags_to_check = [t for t in tags if t not in metadata]
        
        if not tags_to_check:
            print("[DEBUG] No candidate tags for artist search.")
            return []

        artists = []
        async with aiohttp.ClientSession(headers=SakugaAPI.HEADERS) as session:
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
        
        print(f"[DEBUG] Found artists: {artists}")
        return artists

    @staticmethod
    async def get_tag_types(tags_string):
        tags = tags_string.split()
        if not tags:
            return {}
            
        tag_map = {}
        async with aiohttp.ClientSession(headers=SakugaAPI.HEADERS) as session:
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