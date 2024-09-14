import os
from flask import Flask, request, render_template
import asyncio
import pandas as pd
import numpy as np
import aiohttp
from datetime import datetime
import nest_asyncio
from dotenv import load_dotenv
import plotly.graph_objs as go
from plotly.offline import plot

load_dotenv()
nest_asyncio.apply()

app = Flask(__name__)

API_KEY = os.getenv('LASTFM_API_KEY')

# Check if API Key is loaded properly
if not API_KEY:
    raise ValueError("LASTFM_API_KEY is not set in environment variables.")

async def fetch_page(session, url, params, page):
    params['page'] = page

    # Remove None values from params
    clean_params = {k: v for k, v in params.items() if v is not None}

    # Debugging: Log the parameters being used
    print(f"Fetching page {page} with params: {clean_params}")

    try:
        async with session.get(url, params=clean_params) as response:
            if response.status == 200:
                data = await response.json()
                return data
            elif response.status == 429:
                # Handle rate limiting
                retry_after = int(response.headers.get('Retry-After', 1))
                print(f"Rate limited. Retrying after {retry_after} seconds.")
                await asyncio.sleep(retry_after)
                return await fetch_page(session, url, params, page)
            else:
                print(f"Error fetching page {page}: {response.status}")
                return None
    except aiohttp.ClientError as e:
        print(f"Client error fetching page {page}: {e}")
        return None
    except asyncio.TimeoutError:
        print(f"Timeout error fetching page {page}.")
        return None
    except Exception as e:
        print(f"Unexpected error fetching page {page}: {e}")
        return None

async def fetch_all_pages(username, max_pages=10):
    url = "https://ws.audioscrobbler.com/2.0/"
    params = {
        'method': 'user.getrecenttracks',
        'user': username,
        'api_key': API_KEY,
        'format': 'json',
        'limit': 200
    }

    all_tracks = []
    async with aiohttp.ClientSession() as session:
        first_page_data = await fetch_page(session, url, params, 1)
        if not first_page_data:
            return []

        total_pages = int(first_page_data.get('recenttracks', {}).get('@attr', {}).get('totalPages', 1))
        # Limit the total_pages to max_pages
        total_pages = min(total_pages, max_pages)
        all_tracks = first_page_data.get('recenttracks', {}).get('track', [])

        for page in range(2, total_pages + 1):
            page_data = await fetch_page(session, url, params, page)
            if page_data:
                tracks = page_data.get('recenttracks', {}).get('track', [])
                if tracks:
                    all_tracks.extend(tracks)
                else:
                    # No more tracks
                    break
            else:
                # If fetching a page fails, stop fetching further pages
                break
            # Optional: Add a short delay to respect API rate limits
            await asyncio.sleep(0.2)  # 200ms delay

    return all_tracks
