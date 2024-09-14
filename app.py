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
    """
    Fetch a single page of recent tracks from the Last.fm API.

    Args:
        session (aiohttp.ClientSession): The aiohttp session for making requests.
        url (str): The API endpoint URL.
        params (dict): The query parameters for the API request.
        page (int): The page number to fetch.

    Returns:
        dict or None: The JSON response from the API if successful, else None.
    """
    # Update the page number in the parameters
    params['page'] = page

    # Remove any parameters with None values to prevent errors
    clean_params = {k: v for k, v in params.items() if v is not None}

    # Log the parameters being used for debugging
    logger.info(f"Fetching page {page} with params: {clean_params}")

    try:
        async with session.get(url, params=clean_params, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                return data
            elif response.status == 429:
                # Handle rate limiting by waiting and retrying
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
    """
    Fetch multiple pages of recent tracks from the Last.fm API.

    Args:
        username (str): The Last.fm username.
        max_pages (int): The maximum number of pages to fetch.

    Returns:
        list: A list of all fetched tracks.
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

        # Limit the total pages to max_pages to prevent excessive fetching
        total_pages = min(total_pages, max_pages)
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
                    # No more tracks available
                    logger.info(f"No tracks found on page {page}. Stopping fetch.")
                    break
            else:
                # If fetching a page fails, stop fetching further pages
                logger.error(f"Failed to fetch page {page}. Stopping fetch.")
                break
            # Optional: Add a short delay to respect API rate limits
            await asyncio.sleep(0.2)  # 200ms delay

    return all_tracks

def process_scrobble_data(all_tracks):
    """
    Process the fetched tracks to calculate daily listening counts.

    Args:
        all_tracks (list): A list of track dictionaries fetched from the API.

    Returns:
        pandas.DataFrame: A DataFrame with dates and corresponding track counts.
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
        return pd.DataFrame(columns=['date', 'count'])

    # Create a DataFrame for daily counts
    df = pd.DataFrame(scrobbles, columns=['datetime'])
    df['date'] = df['datetime'].dt.date
    daily_counts = df.groupby('date').size().reset_index(name='count')

    return daily_counts

def create_heatmap(daily_counts, palette):
    """
    Create a heatmap using Plotly based on daily listening counts.

    Args:
        daily_counts (pandas.DataFrame): DataFrame with dates and track counts.
        palette (str): The color palette for the heatmap.

    Returns:
        str: The HTML div string for the Plotly heatmap.
    """
    if daily_counts.empty:
        return "<p>No data available to display the heatmap.</p>"

    # Create a continuous color scale based on the selected palette
    colorscale = palette

    # Create the heatmap figure
    fig = go.Figure(data=go.Heatmap(
        z=daily_counts['count'],
        x=daily_counts['date'],
        y=[''] * len(daily_counts),  # Single row for dates
        colorscale=colorscale,
        showscale=True
    ))

    # Update the layout for better visualization
    fig.update_layout(
        title='Daily Music Listening Heatmap',
        xaxis_title='Date',
        yaxis_visible=False,
        height=400
    )

    # Generate the HTML div string for embedding in the template
    return plot(fig, output_type='div')

@app.route('/', methods=['GET', 'POST'])
async def index():
    """
    The main route for the application. Handles both GET and POST requests.

    GET: Renders the main page with the input form.
    POST: Processes the submitted username, fetches data, generates the heatmap, and renders the result.
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
            # Fetch recent tracks with a limit on the number of pages
            all_tracks = await fetch_all_pages(username, max_pages=MAX_PAGES)
            if not all_tracks:
                error = "No tracks found or API error."
                return render_template('index.html', plot_div=plot_div, error=error)

            # Process the fetched data to get daily counts
            daily_counts = process_scrobble_data(all_tracks)
            if daily_counts.empty:
                error = "No scrobbles available to generate a heatmap."
                return render_template('index.html', plot_div=plot_div, error=error)

            # Create the heatmap HTML div
            plot_div = create_heatmap(daily_counts, palette)
        except Exception as e:
            error = f"An unexpected error occurred: {e}"
            logger.error(f"Error in index route: {e}")

    return render_template('index.html', plot_div=plot_div, error=error)

if __name__ == '__main__':
    # Run the Flask app in debug mode for local development
    app.run(debug=True)
