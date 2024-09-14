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
import itertools  # Import itertools for creating combinations

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

async def fetch_page(session, url, params, page):
    """
    Fetch a single page of recent tracks from the Last.fm API.
    """
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

async def fetch_all_pages(username):
    """
    Fetch all pages of recent tracks from the Last.fm API.
    """
    url = "https://ws.audioscrobbler.com/2.0/"
    params = {
        'method': 'user.getrecenttracks',
        'user': username,
        'api_key': API_KEY,
        'format': 'json',
        'limit': 200  # Maximum number of tracks per page
    }

    all_tracks = []
    async with aiohttp.ClientSession() as session:
        # Fetch the first page to determine total pages
        first_page_data = await fetch_page(session, url, params, 1)
        if not first_page_data:
            return []

        # Extract total number of pages from the response
        try:
            recent_tracks = first_page_data['recenttracks']
            attr = recent_tracks.get('@attr', {})
            total_pages = int(attr.get('totalPages', 1))
        except (KeyError, ValueError) as e:
            logger.error(f"Error parsing total pages: {e}")
            return []

        logger.info(f"Total pages to fetch: {total_pages}")

        # Extract tracks from the first page
        tracks = recent_tracks.get('track', [])
        all_tracks.extend(tracks)

        # Sequentially fetch remaining pages
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
            await asyncio.sleep(0.2)  # 200ms delay

    return all_tracks

def process_scrobble_data(all_tracks):
    """
    Process the fetched tracks to calculate daily listening counts.
    """
    scrobbles = []
    for track in all_tracks:
        # Skip currently playing tracks
        if '@attr' in track and track['@attr'].get('nowplaying') == 'true':
            continue
        scrobble_time = track.get('date', {}).get('uts')
        if scrobble_time:
            scrobbles.append(datetime.fromtimestamp(int(scrobble_time)))

    if not scrobbles:
        return pd.DataFrame(columns=['month', 'day', 'count'])

    df = pd.DataFrame(scrobbles, columns=['datetime'])
    df['month'] = df['datetime'].dt.to_period('M').astype(str)
    df['day'] = df['datetime'].dt.day

    # Group by month and day to get counts
    daily_counts = df.groupby(['month', 'day']).size().reset_index(name='count')

    # Generate all combinations of months and days
    first_month = df['datetime'].dt.to_period('M').min()
    last_month = df['datetime'].dt.to_period('M').max()
    months = pd.period_range(start=first_month, end=last_month, freq='M').astype(str)
    days = range(1, 32)

    all_months_days = pd.DataFrame(list(itertools.product(months, days)), columns=['month', 'day'])
    all_months_days['day'] = all_months_days['day'].astype(int)

    # Add 'month_period' column
    all_months_days['month_period'] = pd.PeriodIndex(all_months_days['month'], freq='M')

    # Get number of days in each month
    all_months_days['days_in_month'] = all_months_days['month_period'].dt.days_in_month

    # Flag valid days
    all_months_days['valid_day'] = all_months_days['day'] <= all_months_days['days_in_month']

    # Merge counts
    merged_counts = pd.merge(all_months_days, daily_counts, how='left', on=['month', 'day'])

    # Set counts to None for invalid days
    merged_counts['count'] = merged_counts.apply(
        lambda row: row['count'] if row['valid_day'] else None, axis=1
    )

    return merged_counts

def create_heatmap(merged_counts, palette):
    """
    Create a 2D heatmap using Plotly based on daily listening counts.
    """
    if merged_counts.empty:
        return "<p>No data available to display the heatmap.</p>"

    # Pivot the data to create a matrix suitable for a heatmap
    heatmap_data = merged_counts.pivot(index='day', columns='month', values='count')

    # Sort the months chronologically
    heatmap_data = heatmap_data.reindex(sorted(heatmap_data.columns, key=lambda x: pd.Period(x, freq='M')), axis=1)

    # Create the heatmap figure
    fig = go.Figure(data=go.Heatmap(
        z=heatmap_data.values,
        x=heatmap_data.columns,
        y=heatmap_data.index,
        colorscale=palette,
        showscale=True,
        hoverongaps=False  # Show gaps for invalid days
    ))

    # Update the layout for better visualization
    fig.update_layout(
        title='Monthly Music Listening Heatmap',
        xaxis_title='Month',
        yaxis_title='Day of Month',
        yaxis_autorange='reversed',  # So that day 1 is at the top
        height=600
    )

    # Generate the HTML div string for embedding in the template
    return plot(fig, output_type='div')

@app.route('/', methods=['GET', 'POST'])
async def index():
    """
    The main route for the application.
    """
    plot_div = None
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        palette = request.form.get('palette', 'Viridis')  # Default palette is 'Viridis'

        if not username:
            error = "Username is required."
            return render_template('index.html', plot_div=plot_div, error=error)

        try:
            # Fetch all tracks from the user's listening history
            all_tracks = await fetch_all_pages(username)
            if not all_tracks:
                error = "No tracks found or API error."
                return render_template('index.html', plot_div=plot_div, error=error)

            # Process the fetched data to get daily counts
            merged_counts = process_scrobble_data(all_tracks)
            if merged_counts.empty:
                error = "No scrobbles available to generate a heatmap."
                return render_template('index.html', plot_div=plot_div, error=error)

            # Create the heatmap HTML div
            plot_div = create_heatmap(merged_counts, palette)
        except Exception as e:
            error = f"An unexpected error occurred: {e}"
            logger.error(f"Error in index route: {e}")

    return render_template('index.html', plot_div=plot_div, error=error)

if __name__ == '__main__':
    # Run the Flask app
    app.run(debug=True)
