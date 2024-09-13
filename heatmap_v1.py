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

API_KEY = os.getenv('47a3bb30787578c70e3bf827e0281936')

async def fetch_page(session, url, params, page):
    params['page'] = page
    async with session.get(url, params=params) as response:
        if response.status == 200:
            data = await response.json()
            return data
        else:
            print(f"Error fetching page {page}: {response.status}")
            return None

async def fetch_all_pages(username):
    url = 'http://ws.audioscrobbler.com/2.0/'
    params = {
        'method': 'user.getRecentTracks',
        'flounder14': username,
        '47a3bb30787578c70e3bf827e0281936': API_KEY,
        'format': 'json',
        'limit': 200,
    }

    all_tracks = []
    async with aiohttp.ClientSession() as session:
        first_page_data = await fetch_page(session, url, params, 1)
        if not first_page_data or 'recenttracks' not in first_page_data or 'track' not in first_page_data['recenttracks']:
            return []
        
        total_pages = int(first_page_data['recenttracks']['@attr']['totalPages'])
        print(f"Total pages: {total_pages}")

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

def create_heatmap(daily_counts, palette):
    if daily_counts.empty:
        return None

    daily_counts['Day'] = pd.to_datetime(daily_counts['Day'])
    daily_counts['DayOfMonth'] = daily_counts['Day'].dt.day
    daily_counts['Month'] = daily_counts['Day'].dt.to_period('M')
    pivot_table = daily_counts.pivot_table(values='Counts', index='DayOfMonth', columns='Month', fill_value=0)

    full_index = pd.Index(range(1, 32), name='DayOfMonth')
    pivot_table = pivot_table.reindex(full_index)

    # Handle missing days
    for day in range(29, 32):
        for month in pivot_table.columns:
            if day > month.days_in_month:
                pivot_table.at[day, month] = None  # Use None for days that don't exist

    # Prepare data for Plotly
    z = pivot_table.values

    x = [str(date.to_timestamp().strftime('%Y-%m')) for date in pivot_table.columns]
    y = pivot_table.index.tolist()

    # Prepare hover text
    hover_text = []
    for yi, day in enumerate(y):
        hover_text_row = []
        for xi, month in enumerate(pivot_table.columns):
            count = pivot_table.iloc[yi, xi]
            if count is None:
                hover_text_row.append('Day does not exist')
            else:
                hover_text_row.append(f"{month.strftime('%Y-%m')}-{int(day)}: {int(count)} songs")
        hover_text.append(hover_text_row)

    colorscales = {
        'Viridis': 'Viridis',
        'Cividis': 'Cividis',
        'Plasma': 'Plasma',
        'Magma': 'Magma',
        'Inferno': 'Inferno',
        'Turbo': 'Turbo',
    }

    colorscale = colorscales.get(palette, 'Viridis')

    max_count = np.nanmax(z)
    zmin = 0
    zmax = max_count

    heatmap = go.Heatmap(
        z=z,
        x=x,
        y=y,
        colorscale=colorscale,
        hoverinfo='text',
        text=hover_text,
        zmin=zmin,
        zmax=zmax,
        colorbar=dict(title='Number of Songs Played'),
        showscale=True,
        coloraxis='coloraxis'
    )

    layout = go.Layout(
        title='Heatmap of Songs Listened to Per Day',
        xaxis=dict(title='Month', tickangle=45, nticks=10),
        yaxis=dict(title='Day of Month'),
        height=600,
        width=1000,
    )

    fig = go.Figure(data=[heatmap], layout=layout)
    fig.update_layout(coloraxis=dict(colorscale=colorscale, cmin=zmin, cmax=zmax, 
                                     colorbar=dict(title='Number of Songs Played'), 
                                     missingcolor='gray'))

    # Convert the figure to HTML div
    plot_div = plot(fig, output_type='div', include_plotlyjs='cdn')

    return plot_div

@app.route('/', methods=['GET', 'POST'])
async def index():
    plot_div = None
    if request.method == 'POST':
        username = request.form['username']
        palette = request.form.get('palette', 'Viridis')

        all_tracks = await fetch_all_pages(username)
        daily_counts = process_scrobble_data(all_tracks)
        plot_div = create_heatmap(daily_counts, palette)
    return render_template('index.html', plot_div=plot_div)

if __name__ == '__main__':
    app.run()
