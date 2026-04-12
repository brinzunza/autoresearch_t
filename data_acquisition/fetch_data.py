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
DEFAULT_TICKER = "C:EURUSD"  # Forex pair format for Polygon.io


def format_ticker(ticker):
    """
    Convert user-friendly ticker to Polygon.io format.

    Examples:
        'EURUSD' -> 'C:EURUSD'
        'EUR/USD' -> 'C:EURUSD'
        'C:EURUSD' -> 'C:EURUSD' (already formatted)
        'AAPL' -> 'AAPL' (stocks stay as-is)

    Args:
        ticker: User input ticker

    Returns:
        str: Polygon.io formatted ticker
    """
    ticker = ticker.upper().strip()

    # Already in Polygon format
    if ticker.startswith('C:'):
        return ticker

    # Remove slash if present (EUR/USD -> EURUSD)
    ticker_clean = ticker.replace('/', '')

    # Check if it's a forex pair (6 characters, all letters)
    if len(ticker_clean) == 6 and ticker_clean.isalpha():
        return f"C:{ticker_clean}"

    # Otherwise assume it's a stock ticker
    return ticker


def get_display_name(ticker):
    """
    Get user-friendly display name for ticker.

    Args:
        ticker: Polygon.io formatted ticker

    Returns:
        str: Display name
    """
    if ticker.startswith('C:'):
        # Forex pair - format as EUR/USD
        pair = ticker[2:]  # Remove 'C:' prefix
        return f"{pair[:3]}/{pair[3:]}"
    return ticker


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
    Find earliest accessible date by testing progressively older dates.

    The logic is:
    - Test from recent to old (1 month, 3 months, 6 months, 1 year, 2 years)
    - STOP when we hit first FAILURE (403 or no data)
    - Return the MOST RECENT successful date BEFORE the failure

    This finds the boundary between accessible and inaccessible data.

    Args:
        ticker: Stock ticker symbol
        years_back: How many years back to start searching

    Returns:
        datetime: Earliest accessible date
    """
    print("Finding earliest accessible date...")
    print("(Testing from recent to old, stopping at first failure)")

    today = datetime.now()

    # Test increasingly older dates
    test_dates = [
        today - timedelta(days=30),    # 1 month
        today - timedelta(days=90),    # 3 months
        today - timedelta(days=180),   # 6 months
        today - timedelta(days=365),   # 1 year
        today - timedelta(days=730),   # 2 years
        today - timedelta(days=1095),  # 3 years
    ]

    last_successful = None

    for test_date in test_dates:
        # Skip to weekday (for both forex and stocks)
        while test_date.weekday() >= 5:
            test_date -= timedelta(days=1)

        date_str = test_date.strftime("%Y-%m-%d")
        print(f"  Testing {date_str}...", end=" ", flush=True)

        bars = fetch_minute_bars(ticker, test_date, test_date)

        if bars and len(bars) > 0:
            print(f"✓ ({len(bars)} bars)")
            last_successful = test_date  # Update the last date that worked
        else:
            print("✗ No access")
            # We hit the boundary - stop here
            break

        time.sleep(13)  # Rate limiting

    if last_successful:
        print(f"✓ Earliest accessible: {last_successful.date()}")
        return last_successful
    else:
        # If even 1 month ago fails, try just yesterday
        yesterday = today - timedelta(days=1)
        while yesterday.weekday() >= 5:
            yesterday -= timedelta(days=1)
        print(f"⚠ Using fallback: {yesterday.date()} (1 day ago)")
        return yesterday


def save_data(df, ticker, output_dir="data_acquisition"):
    """
    Save data to CSV file.

    Args:
        df: DataFrame with market data
        ticker: Ticker symbol (Polygon.io format)
        output_dir: Directory to save file

    Returns:
        str: Path to saved file
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Clean ticker for filename (remove 'C:' prefix and special chars)
    clean_ticker = ticker.replace('C:', '').replace('/', '_').replace(':', '_')

    # Create filename with date range
    start_date = df['timestamp'].min().strftime("%Y%m%d")
    end_date = df['timestamp'].max().strftime("%Y%m%d")
    filename = f"{clean_ticker}_1min_{start_date}_{end_date}.csv"
    filepath = os.path.join(output_dir, filename)

    # Save to CSV
    df.to_csv(filepath, index=False)

    print(f"\n✓ Data saved to: {filepath}")
    print(f"  Rows: {len(df):,}")
    print(f"  Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"  File size: {os.path.getsize(filepath) / (1024*1024):.2f} MB")

    # Also create a symlink to latest data
    latest_link = os.path.join(output_dir, f"{clean_ticker}_1min_latest.csv")
    if os.path.exists(latest_link) or os.path.islink(latest_link):
        os.remove(latest_link)
    os.symlink(os.path.basename(filepath), latest_link)
    print(f"  Latest data link: {latest_link}")

    return filepath


def main():
    print("=" * 70)
    print("POLYGON.IO DATA ACQUISITION")
    print("=" * 70)
    print("Supported formats:")
    print("  Forex: EURUSD, EUR/USD, GBPUSD, etc.")
    print("  Stocks: AAPL, TSLA, SPY, etc.")
    print()

    user_input = input(f"Enter ticker symbol (default: EUR/USD): ").strip()
    if not user_input:
        user_input = "EUR/USD"

    # Format ticker for Polygon.io API
    ticker = format_ticker(user_input)
    display_name = get_display_name(ticker)

    print(f"\nTicker: {display_name}")
    print(f"API format: {ticker}")
    print(f"API Key: {API_KEY[:10]}...")

    # Find earliest accessible date
    print("\n" + "=" * 70)
    earliest_date = find_earliest_accessible_date(ticker)

    # Get most recent date (yesterday or last trading day)
    today = datetime.now()
    end_date = today - timedelta(days=1)

    # Skip weekends
    while end_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
        end_date -= timedelta(days=1)

    # Sanity check: end_date should not be in the future
    if end_date > today:
        print(f"⚠ Warning: End date {end_date.date()} is in the future! Using today instead.")
        end_date = today
        while end_date.weekday() >= 5:
            end_date -= timedelta(days=1)

    # Sanity check: earliest_date should be before end_date
    if earliest_date >= end_date:
        print(f"⚠ Warning: Earliest date {earliest_date.date()} is not before end date {end_date.date()}!")
        print(f"   This suggests the API access check failed. Using last 30 days instead.")
        earliest_date = end_date - timedelta(days=30)

    # Confirm with user
    print("\n" + "=" * 70)
    print(f"Will fetch data from {earliest_date.date()} to {end_date.date()}")
    print(f"Total days: {(end_date - earliest_date).days}")
    print(f"Today's date: {today.date()}")
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
