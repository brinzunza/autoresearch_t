#!/usr/bin/env python3
"""
Fetch 1-minute bar data from Polygon.io for the maximum available time range.
Saves data in a clean CSV format for use with autoresearch.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import os
from pathlib import Path

API_KEY = "abEgGQWtzBpMvz1H4o00DHvEMoG1G_Md"
BASE_URL = "https://api.polygon.io/v2/aggs/ticker"

# Default ticker - can be changed
DEFAULT_TICKER = "AAPL"


def fetch_minute_bars(ticker, from_date, to_date, max_retries=3):
    """
    Fetch 1-minute aggregate bars from Polygon.io.

    Args:
        ticker: Stock ticker symbol
        from_date: Start date (YYYY-MM-DD format or datetime)
        to_date: End date (YYYY-MM-DD format or datetime)
        max_retries: Maximum number of retry attempts

    Returns:
        list: List of bar data dictionaries, or None if failed
    """
    if isinstance(from_date, datetime):
        from_date = from_date.strftime("%Y-%m-%d")
    if isinstance(to_date, datetime):
        to_date = to_date.strftime("%Y-%m-%d")

    url = f"{BASE_URL}/{ticker}/range/1/minute/{from_date}/{to_date}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,  # Maximum allowed
        "apiKey": API_KEY
    }

    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()

            if response.status_code == 200:
                results = data.get("results", [])
                if results:
                    return results
                else:
                    print(f"  No data for {from_date} to {to_date}")
                    return []
            elif response.status_code == 429:
                # Rate limit hit
                wait_time = 60
                print(f"  Rate limit hit. Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                print(f"  API error: {response.status_code} - {data.get('message', 'Unknown')}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return None

        except Exception as e:
            print(f"  Request error: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None

    return None


def fetch_all_data(ticker, start_date, end_date, chunk_days=7):
    """
    Fetch all available data by chunking into smaller date ranges.

    Args:
        ticker: Stock ticker symbol
        start_date: Start date (datetime)
        end_date: End date (datetime)
        chunk_days: Number of days per request (to avoid hitting limits)

    Returns:
        pd.DataFrame: DataFrame with all fetched data
    """
    all_bars = []
    current_date = start_date

    print(f"\nFetching data from {start_date.date()} to {end_date.date()}")
    print("-" * 70)

    total_days = (end_date - start_date).days
    processed_days = 0

    while current_date <= end_date:
        chunk_end = min(current_date + timedelta(days=chunk_days), end_date)

        # Skip if entire chunk is on weekend
        if current_date.weekday() < 5 or chunk_end.weekday() < 5:
            print(f"Fetching: {current_date.date()} to {chunk_end.date()}...", end=" ")

            bars = fetch_minute_bars(ticker, current_date, chunk_end)

            if bars:
                all_bars.extend(bars)
                print(f"✓ Got {len(bars)} bars")
            else:
                print("✗ No data")

            # Rate limiting - free tier has 5 requests per minute
            time.sleep(13)  # ~4.6 requests per minute to be safe

        processed_days += chunk_days
        progress = min(100, (processed_days / total_days) * 100)
        print(f"Progress: {progress:.1f}%")

        current_date = chunk_end + timedelta(days=1)

    print("-" * 70)
    print(f"Total bars fetched: {len(all_bars)}")

    if not all_bars:
        return None

    # Convert to DataFrame
    df = pd.DataFrame(all_bars)

    # Convert timestamp (milliseconds) to datetime
    df['timestamp'] = pd.to_datetime(df['t'], unit='ms')

    # Rename columns to more readable names
    df = df.rename(columns={
        'o': 'open',
        'h': 'high',
        'l': 'low',
        'c': 'close',
        'v': 'volume',
        'vw': 'vwap',
        'n': 'transactions'
    })

    # Select and order columns
    columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'vwap', 'transactions']
    df = df[[col for col in columns if col in df.columns]]

    # Sort by timestamp
    df = df.sort_values('timestamp').reset_index(drop=True)

    return df


def find_earliest_accessible_date(ticker, years_back=3):
    """
    Quick search to find earliest accessible date.

    Args:
        ticker: Stock ticker symbol
        years_back: How many years back to start searching

    Returns:
        datetime: Earliest accessible date
    """
    print("Finding earliest accessible date...")

    today = datetime.now()
    # Start from most recent weekday
    test_date = today - timedelta(days=1)
    while test_date.weekday() >= 5:
        test_date -= timedelta(days=1)

    # Test increasingly older dates
    test_dates = [
        today - timedelta(days=30),    # 1 month
        today - timedelta(days=90),    # 3 months
        today - timedelta(days=180),   # 6 months
        today - timedelta(days=365),   # 1 year
        today - timedelta(days=730),   # 2 years
        today - timedelta(days=1095),  # 3 years
    ]

    earliest = None

    for test_date in test_dates:
        # Skip to weekday
        while test_date.weekday() >= 5:
            test_date -= timedelta(days=1)

        date_str = test_date.strftime("%Y-%m-%d")
        print(f"  Testing {date_str}...", end=" ")

        bars = fetch_minute_bars(ticker, test_date, test_date)

        if bars and len(bars) > 0:
            print(f"✓ ({len(bars)} bars)")
            earliest = test_date
        else:
            print("✗")
            break

        time.sleep(13)  # Rate limiting

    if earliest:
        print(f"✓ Earliest accessible: {earliest.date()}")
        return earliest
    else:
        # Default to 2 years (common for free tier)
        default = today - timedelta(days=730)
        print(f"Using default: {default.date()}")
        return default


def save_data(df, ticker, output_dir="data_acquisition"):
    """
    Save data to CSV file.

    Args:
        df: DataFrame with market data
        ticker: Stock ticker symbol
        output_dir: Directory to save file

    Returns:
        str: Path to saved file
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Create filename with date range
    start_date = df['timestamp'].min().strftime("%Y%m%d")
    end_date = df['timestamp'].max().strftime("%Y%m%d")
    filename = f"{ticker}_1min_{start_date}_{end_date}.csv"
    filepath = os.path.join(output_dir, filename)

    # Save to CSV
    df.to_csv(filepath, index=False)

    print(f"\n✓ Data saved to: {filepath}")
    print(f"  Rows: {len(df):,}")
    print(f"  Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"  File size: {os.path.getsize(filepath) / (1024*1024):.2f} MB")

    # Also create a symlink to latest data
    latest_link = os.path.join(output_dir, f"{ticker}_1min_latest.csv")
    if os.path.exists(latest_link) or os.path.islink(latest_link):
        os.remove(latest_link)
    os.symlink(os.path.basename(filepath), latest_link)
    print(f"  Latest data link: {latest_link}")

    return filepath


def main():
    print("=" * 70)
    print("POLYGON.IO DATA ACQUISITION")
    print("=" * 70)

    ticker = input(f"Enter ticker symbol (default: {DEFAULT_TICKER}): ").strip().upper()
    if not ticker:
        ticker = DEFAULT_TICKER

    print(f"\nTicker: {ticker}")
    print(f"API Key: {API_KEY[:10]}...")

    # Find earliest accessible date
    print("\n" + "=" * 70)
    earliest_date = find_earliest_accessible_date(ticker)

    # Get most recent date (yesterday or last trading day)
    end_date = datetime.now() - timedelta(days=1)
    while end_date.weekday() >= 5:
        end_date -= timedelta(days=1)

    # Confirm with user
    print("\n" + "=" * 70)
    print(f"Will fetch data from {earliest_date.date()} to {end_date.date()}")
    print(f"Estimated days: {(end_date - earliest_date).days}")
    print("This may take a while due to API rate limits (5 requests/minute)")
    print("=" * 70)

    proceed = input("\nProceed with data fetch? (yes/no): ").strip().lower()
    if proceed not in ['yes', 'y']:
        print("Cancelled.")
        return

    # Fetch all data
    print("\n" + "=" * 70)
    df = fetch_all_data(ticker, earliest_date, end_date)

    if df is not None and len(df) > 0:
        # Save data
        print("\n" + "=" * 70)
        save_data(df, ticker)

        # Display summary statistics
        print("\n" + "=" * 70)
        print("DATA SUMMARY")
        print("=" * 70)
        print(df.describe())

        print("\n" + "=" * 70)
        print("✓ Data acquisition complete!")
        print("=" * 70)
    else:
        print("\n✗ No data was fetched. Please check API key and ticker symbol.")


if __name__ == "__main__":
    main()
