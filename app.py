import os
from flask import Flask, request, render_template
import asyncio
import pandas as pd
import aiohttp
from datetime import datetime
import nest_asyncio
from dotenv import load_dotenv
import plotly.graph_objs as go
from plotly.offline import plot
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Apply nest_asyncio to allow nested event loops (useful for certain environments)
nest_asyncio.apply()

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Retrieve the Last.fm API key from environment variables
API_KEY = os.getenv('LASTFM_API_KEY')

# Ensure the API key is set
if not API_KEY:
    raise ValueError("LASTFM_API_KEY is not set in environment variables.")

# Define the maximum number of pages to fetch to prevent excessive API calls
MAX_PAGES = 10

async def fetch_page(session, url, params, page):
    params['page'] = page
    clean_params = {k: v for k, v in params.items() if v is not None}
    logger.info(f"Fetching page {page} with params: {clean_params}")

    try:
        async with session.get(url, params=clean_params, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                return data
            elif response.status == 429:
                retry_after = int(response.headers.get('Retry-After', 5))
                logger.warning(f"Rate limited. Retrying after {retry_after} seconds.")
                await asyncio.sleep(retry_after)
                return await fetch_page(session, url, params, page)
            else:
                logger.error(f"Error fetching page {page}: HTTP {response.status}")
                return None
    except aiohttp.ClientError as e:
        logger.error(f"Client error fetching page {page}: {e}")
        return None
    except asyncio.TimeoutError:
        logger.error(f"Timeout error fetching page {page}.")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching page {page}: {e}")
        return None

async def fetch_all_pages(username, max_pages=MAX_PAGES):
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

        try:
            recent_tracks = first_page_data['recenttracks']
            attr = recent_tracks.get('@attr', {})
            total_pages = int(attr.get('totalPages', 1))
        except (KeyError, ValueError) as e:
            logger.error(f"Error parsing total pages: {e}")
            return []

        total_pages = min(total_pages, max_pages)
        logger.info(f"Total pages to fetch: {total_pages}")

        tracks = recent_tracks.get('track', [])
        all_tracks.extend(tracks)

        for page in range(2, total_pages + 1):
            page_data = await fetch_page(session, url, params, page)
            if page_data:
                tracks = page_data.get('recenttracks', {}).get('track', [])
                if tracks:
                    all_tracks.extend(tracks)
                else:
                    logger.info(f"No tracks found on page {page}. Stopping fetch.")
                    break
            else:
                logger.error(f"Failed to fetch page {page}. Stopping fetch.")
                break
            await asyncio.sleep(0.2)

    return all_tracks

def process_scrobble_data(all_tracks):
    scrobbles = []
    for track in all_tracks:
        if '@attr' in track and track['@attr'].get('nowplaying') == 'true':
            continue
        scrobble_time = track.get('date', {}).get('uts')
        if scrobble_time:
            scrobbles.append(datetime.fromtimestamp(int(scrobble_time)))

    if not scrobbles:
        return pd.DataFrame(columns=['date', 'count'])

    df = pd.DataFrame(scrobbles, columns=['datetime'])
    df['date'] = df['datetime'].dt.date
    df['year_month'] = df['datetime'].dt.to_period('M')
    df['day'] = df['datetime'].dt.day
    daily_counts = df.groupby(['year_month', 'day']).size().reset_index(name='count')

    return daily_counts

def create_heatmap(daily_counts, palette):
    if daily_counts.empty:
        return "<p>No data available to display the heatmap.</p>"

    months = pd.date_range(start=daily_counts['year_month'].min().start_time, 
                           end=daily_counts['year_month'].max().end_time, freq='M')
    days = list(range(1, 32))

    heatmap_data = pd.DataFrame(index=days, columns=months.to_period('M'))
    
    for _, row in daily_counts.iterrows():
        heatmap_data.at[row['day'], row['year_month']] = row['count']
    
    heatmap_data = heatmap_data.fillna(0)  # Fill missing values with 0 for no plays

    fig = go.Figure(data=go.Heatmap(
        z=heatmap_data.values,
        x=[str(month) for month in heatmap_data.columns],
        y=heatmap_data.index,
        colorscale=palette,
        colorbar=dict(title='Number of Songs Played'),
        zmin=0,
        zmax=heatmap_data.max().max()
    ))

    fig.update_layout(
        title='Daily Music Listening Heatmap',
        xaxis_title='Month',
        yaxis_title='Day of Month',
        yaxis=dict(tickmode='array', tickvals=list(range(1, 32))),
        height=600
    )

    return plot(fig, output_type='div')

@app.route('/', methods=['GET', 'POST'])
async def index():
    plot_div = None
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        palette = request.form.get('palette', 'Viridis')

        if not username:
            error = "Username is required."
            return render_template('index.html', plot_div=plot_div, error=error)

        try:
            all_tracks = await fetch_all_pages(username, max_pages=MAX_PAGES)
            if not all_tracks:
                error = "No tracks found or API error."
                return render_template('index.html', plot_div=plot_div, error=error)

            daily_counts = process_scrobble_data(all_tracks)
            if daily_counts.empty:
                error = "No scrobbles available to generate a heatmap."
                return render_template('index.html', plot_div=plot_div, error=error)

            plot_div = create_heatmap(daily_counts, palette)
        except Exception as e:
            error = f"An unexpected error occurred: {e}"
            logger.error(f"Error in index route: {e}")

    return render_template('index.html', plot_div=plot_div, error=error)

if __name__ == '__main__':
    app.run(debug=True)
