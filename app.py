import os
from flask import Flask, request, render_template, jsonify
import asyncio
import pandas as pd
import numpy as np
import aiohttp
from datetime import datetime
from dotenv import load_dotenv
import plotly.express as px
import plotly.io as pio
import nest_asyncio

load_dotenv()
nest_asyncio.apply()

app = Flask(__name__)

API_KEY = os.getenv('LASTFM_API_KEY')

<<<<<<< HEAD
# Check if API Key is loaded properly
if not API_KEY:
    raise ValueError("LASTFM_API_KEY is not set in environment variables.")

=======
>>>>>>> 2401ab97fecc3046866c842dbecb83be5176c8b5
async def fetch_page(session, url, params, page):
    params['page'] = page
    async with session.get(url, params=params) as response:
        if response.status == 200:
            data = await response.json()
            return data
        else:
            print(f"Error fetching page {page}: {response.status}")
            return None

<<<<<<< HEAD
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
=======
async def fetch_all_pages(username):
    url = 'http://ws.audioscrobbler.com/2.0/'
>>>>>>> 2401ab97fecc3046866c842dbecb83be5176c8b5
    params = {
        'method': 'user.getRecentTracks',
        'user': username,
        'api_key': API_KEY,
        'format': 'json',
<<<<<<< HEAD
        'limit': 200
=======
        'limit': 200,
>>>>>>> 2401ab97fecc3046866c842dbecb83be5176c8b5
    }

    all_tracks = []
    async with aiohttp.ClientSession() as session:
        first_page_data = await fetch_page(session, url, params, 1)
        if not first_page_data or 'recenttracks' not in first_page_data or 'track' not in first_page_data['recenttracks']:
            return []
        
        total_pages = int(first_page_data['recenttracks']['@attr']['totalPages'])
        print(f"Total pages: {total_pages}")

<<<<<<< HEAD
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
=======
        all_tracks.extend(first_page_data['recenttracks']['track'])
        for page in range(2, total_pages + 1):
            data = await fetch_page(session, url, params, page)
            if data and 'recenttracks' in data and 'track' in data['recenttracks']:
                all_tracks.extend(data['recenttracks']['track'])

            # Avoid fetching too many pages at once
            if page % 10 == 0:
                await asyncio.sleep(1)

    return all_tracks

def process_scrobble_data(tracks):
    df = pd.DataFrame(tracks)
    if df.empty:
        return pd.DataFrame()

    def extract_date(x):
        if isinstance(x, dict):
            return x.get('#text', None)
        return None

    df['date'] = pd.to_datetime(df['date'].apply(extract_date), format='%d %b %Y, %H:%M')
    df['Day'] = df['date'].dt.date
    daily_counts = df.groupby('Day').size().reset_index(name='Counts')
    return daily_counts

def create_heatmap(daily_counts, color_palette='rocket'):
    daily_counts['Day'] = pd.to_datetime(daily_counts['Day'])
    daily_counts['DayOfMonth'] = daily_counts['Day'].dt.day
    daily_counts['Month'] = daily_counts['Day'].dt.to_period('M')

    # Pivot table to create a grid
    pivot_table = daily_counts.pivot_table(values='Counts', index='DayOfMonth', columns='Month', fill_value=0)

    # Set the max days dynamically based on the month
    for day in range(29, 32):
        for month in pivot_table.columns:
            if day > month.days_in_month:
                pivot_table.at[day, month] = np.nan  # Gray-out days that do not exist

    # Convert month periods to timestamps for proper visualization in Plotly
    pivot_table.columns = pivot_table.columns.to_timestamp()

    # Create interactive heatmap using Plotly
    fig = px.imshow(
        pivot_table,
        color_continuous_scale=color_palette,
        labels={'x': 'Month', 'y': 'Day of Month', 'color': 'Number of Songs Played'},
        aspect='auto'
    )

    # Adjust the hover information
    fig.update_traces(
        hovertemplate="Month: %{x}<br>Day: %{y}<br>Songs: %{z}<extra></extra>"
    )

    # Gray-out non-existing days
    fig.update_xaxes(tickangle=45)
    fig.update_layout(title='Heatmap of Songs Listened to Per Day')

    # Save the figure as an HTML file
    pio.write_html(fig, 'static/heatmap.html')
    return 'static/heatmap.html'

@app.route('/', methods=['GET', 'POST'])
async def index():
    filename = None
    if request.method == 'POST':
        username = request.form['username']
        color_palette = request.form.get('color_palette', 'rocket')  # Default to 'rocket'

        all_tracks = await fetch_all_pages(username)
        daily_counts = process_scrobble_data(all_tracks)
        filename = create_heatmap(daily_counts, color_palette)
    return render_template('index.html', filename=filename)

if __name__ == '__main__':
    app.run()
>>>>>>> 2401ab97fecc3046866c842dbecb83be5176c8b5
