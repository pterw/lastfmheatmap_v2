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
            else:
                print(f"Error fetching page {page}: {response.status}")
                return None
    except Exception as e:
        print(f"Exception during fetch_page: {e}")
        return None

async def fetch_all_pages(username):
    url = "https://ws.audioscrobbler.com/2.0/"
    params = {
        'method': 'user.getrecenttracks',
        'user': username,
        'api_key': API_KEY,
        'format': 'json',
        'limit': 200
    }

    async with aiohttp.ClientSession() as session:
        first_page_data = await fetch_page(session, url, params, 1)
        if not first_page_data:
            return []

        total_pages = int(first_page_data.get('recenttracks', {}).get('@attr', {}).get('totalPages', 1))
        all_tracks = first_page_data.get('recenttracks', {}).get('track', [])

        tasks = [
            fetch_page(session, url, params, page)
            for page in range(2, total_pages + 1)
        ]

        pages = await asyncio.gather(*tasks)
        for page_data in pages:
            if page_data:
                all_tracks.extend(page_data.get('recenttracks', {}).get('track', []))

        return all_tracks

def process_scrobble_data(all_tracks):
    # Your data processing logic here
    pass

def create_heatmap(daily_counts, palette):
    # Your heatmap creation logic here
    pass

@app.route('/', methods=['GET', 'POST'])
async def index():
    plot_div = None
    if request.method == 'POST':
        username = request.form.get('username')
        palette = request.form.get('palette', 'Viridis')

        if not username:
            return render_template('index.html', plot_div=plot_div, error="Username is required.")

        all_tracks = await fetch_all_pages(username)
        if not all_tracks:
            return render_template('index.html', plot_div=plot_div, error="No tracks found or API error.")

        daily_counts = process_scrobble_data(all_tracks)
        plot_div = create_heatmap(daily_counts, palette)
    return render_template('index.html', plot_div=plot_div)

if __name__ == '__main__':
    app.run(debug=True)
