import aiohttp
import asyncio

async def check_tag_types():
    # Let's query a known animator, e.g., "yutaka_nakamura"
    url = "https://sakugabooru.com/tag.json?names=yutaka_nakamura"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            print(f"Data for 'yutaka_nakamura': {data}")

    # Let's query a known series, e.g., "naruto"
    url = "https://sakugabooru.com/tag.json?names=naruto"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            print(f"Data for 'naruto': {data}")

if __name__ == "__main__":
    asyncio.run(check_tag_types())
