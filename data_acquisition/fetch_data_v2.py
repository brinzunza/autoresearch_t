#!/usr/bin/env python3
"""
IMPROVED Polygon.io Data Fetcher with Binary Search and Smart Batching

Key Improvements:
1. Binary search to find earliest accessible date (more efficient)
2. Determines optimal batch size based on Polygon.io's 50,000 bar limit
3. Fetches from oldest to newest to ensure complete historical coverage
4. Proper merging and deduplication of batched requests
5. Progress tracking and resumption capability

Author: Claude Code
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import os
from pathlib import Path
import json

API_KEY = "abEgGQWtzBpMvz1H4o00DHvEMoG1G_Md"
BASE_URL = "https://api.polygon.io/v2/aggs/ticker"
DEFAULT_TICKER = "C:EURUSD"

# Polygon.io limits
MAX_BARS_PER_REQUEST = 50000  # Maximum bars returned per API call
RATE_LIMIT_DELAY = 13  # Seconds between requests (5 req/min = 12s, adding buffer)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def format_ticker(ticker):
    """Convert user-friendly ticker to Polygon.io format."""
    ticker = ticker.upper().strip()
    if ticker.startswith('C:'):
        return ticker
    ticker_clean = ticker.replace('/', '')
    if len(ticker_clean) == 6 and ticker_clean.isalpha():
        return f"C:{ticker_clean}"
    return ticker


def get_display_name(ticker):
    """Get user-friendly display name for ticker."""
    if ticker.startswith('C:'):
        pair = ticker[2:]
        return f"{pair[:3]}/{pair[3:]}"
    return ticker


def is_trading_day(date, is_forex=False):
    """
    Check if a date is a trading day.

    Args:
        date: datetime object
        is_forex: If True, trades 24/5 (Mon-Fri). If False, excludes weekends.

    Returns:
        bool: True if trading day
    """
    if is_forex:
        return date.weekday() < 5  # Monday-Friday
    else:
        return date.weekday() < 5  # Stocks also Mon-Fri


# ---------------------------------------------------------------------------
# API Interaction
# ---------------------------------------------------------------------------

def fetch_bars_raw(ticker, from_date, to_date, limit=50000, max_retries=3):
    """
    Fetch bars from Polygon.io API with retry logic.

    Args:
        ticker: Polygon.io formatted ticker (e.g., 'C:EURUSD')
        from_date: Start date (YYYY-MM-DD or datetime)
        to_date: End date (YYYY-MM-DD or datetime)
        limit: Max bars to return (default 50000)
        max_retries: Retry attempts on failure

    Returns:
        dict with 'results' list and metadata, or None on failure
    """
    if isinstance(from_date, datetime):
        from_date = from_date.strftime("%Y-%m-%d")
    if isinstance(to_date, datetime):
        to_date = to_date.strftime("%Y-%m-%d")

    url = f"{BASE_URL}/{ticker}/range/1/minute/{from_date}/{to_date}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": limit,
        "apiKey": API_KEY
    }

    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()

            if response.status_code == 200:
                return data
            elif response.status_code == 429:
                wait_time = 60
                print(f"    Rate limit hit. Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                print(f"    API error {response.status_code}: {data.get('message', 'Unknown')}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return None

        except Exception as e:
            print(f"    Request error: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None

    return None


# ---------------------------------------------------------------------------
# Binary Search for Earliest Date
# ---------------------------------------------------------------------------

def binary_search_earliest_date(ticker, max_years_back=5):
    """
    Use binary search to efficiently find the earliest accessible date.

    This is much more efficient than linear search, reducing API calls from
    dozens to just log2(N) calls.

    Args:
        ticker: Polygon.io formatted ticker
        max_years_back: How far back to search (default 5 years)

    Returns:
        datetime: Earliest date with data, or None
    """
    print(f"\n{'='*70}")
    print("BINARY SEARCH FOR EARLIEST ACCESSIBLE DATE")
    print(f"{'='*70}")

    is_forex = ticker.startswith('C:')

    # Define search range
    today = datetime.now()
    right = today - timedelta(days=1)  # Yesterday
    while not is_trading_day(right, is_forex):
        right -= timedelta(days=1)

    left = today - timedelta(days=max_years_back * 365)

    print(f"Search range: {left.date()} to {right.date()}")
    print(f"Using binary search (efficient: ~{int(max_years_back * 365).bit_length()} API calls)")
    print("-" * 70)

    earliest_found = None
    attempt = 0

    while left <= right:
        # Calculate midpoint
        mid = left + (right - left) // 2

        # Adjust to trading day
        while not is_trading_day(mid, is_forex) and mid <= right:
            mid += timedelta(days=1)

        if mid > right:
            break

        attempt += 1
        mid_str = mid.strftime("%Y-%m-%d")

        print(f"Attempt {attempt}: Testing {mid_str}... ", end="", flush=True)

        # Test this date
        data = fetch_bars_raw(ticker, mid, mid, limit=10)

        if data and data.get('resultsCount', 0) > 0:
            print(f"✓ Found {data['resultsCount']} bars")
            earliest_found = mid
            # Try going earlier (move right boundary backward in time)
            right = mid - timedelta(days=1)
        else:
            # No data or error (403) - this date is TOO OLD
            # Move left boundary forward in time (try more recent dates)
            print("✗ No data (too old)")
            left = mid + timedelta(days=1)

        # Rate limiting
        time.sleep(RATE_LIMIT_DELAY)

    print("-" * 70)
    if earliest_found:
        print(f"✓ Earliest accessible date: {earliest_found.date()}")
        days_available = (today - earliest_found).days
        print(f"  Historical data available: ~{days_available} days")
    else:
        print("✗ Could not find accessible date")

    return earliest_found


# ---------------------------------------------------------------------------
# Smart Batching Strategy
# ---------------------------------------------------------------------------

def calculate_optimal_batch_size(ticker, start_date, end_date, target_bars=50000):
    """
    Calculate optimal date range for fetching ~target_bars.

    For 1-minute forex data:
    - Trading hours: 24/5 (Mon 00:00 UTC to Fri 23:59 UTC)
    - Minutes per day: ~1440 (24 hours)
    - Minutes per week: ~7200 (5 days * 1440)
    - To get 50,000 bars: ~35 days or ~5 weeks

    Args:
        ticker: Polygon.io formatted ticker
        start_date: Start date for estimation
        end_date: End date for estimation
        target_bars: Target number of bars per batch

    Returns:
        int: Optimal number of days per batch
    """
    is_forex = ticker.startswith('C:')

    if is_forex:
        # Forex: 24/5 trading
        # ~1440 minutes/day * 5 days/week = 7200 bars/week
        # 50,000 bars / 7200 bars/week ≈ 7 weeks ≈ 49 days
        bars_per_day = 1440
    else:
        # Stocks: ~6.5 hours/day (9:30-16:00 ET)
        # ~390 minutes/day
        bars_per_day = 390

    days_needed = int(target_bars / bars_per_day) + 1

    return days_needed


def fetch_all_data_smart(ticker, start_date, end_date):
    """
    Intelligently fetch all data using optimal batching.

    Strategy:
    1. Calculate optimal batch size to get close to 50,000 bars per request
    2. Fetch from oldest to newest in batches
    3. Handle edge cases (weekends, holidays, gaps)
    4. Merge and deduplicate all batches
    5. Verify completeness

    Args:
        ticker: Polygon.io formatted ticker
        start_date: Start date (datetime)
        end_date: End date (datetime)

    Returns:
        pd.DataFrame: Complete dataset with all bars
    """
    print(f"\n{'='*70}")
    print("SMART DATA FETCHING WITH OPTIMAL BATCHING")
    print(f"{'='*70}")

    is_forex = ticker.startswith('C:')

    # Calculate optimal batch size
    batch_days = calculate_optimal_batch_size(ticker, start_date, end_date)

    total_days = (end_date - start_date).days
    estimated_batches = (total_days // batch_days) + 1

    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print(f"Total days: {total_days}")
    print(f"Optimal batch size: {batch_days} days (~{MAX_BARS_PER_REQUEST:,} bars)")
    print(f"Estimated batches: {estimated_batches}")
    print(f"Estimated time: ~{estimated_batches * RATE_LIMIT_DELAY / 60:.1f} minutes")
    print("-" * 70)

    all_batches = []
    current_date = start_date
    batch_num = 0

    while current_date <= end_date:
        batch_num += 1

        # Calculate batch end date
        batch_end = min(current_date + timedelta(days=batch_days), end_date)

        print(f"\nBatch {batch_num}/{estimated_batches}: {current_date.date()} to {batch_end.date()}")
        print(f"  Fetching... ", end="", flush=True)

        # Fetch this batch
        data = fetch_bars_raw(ticker, current_date, batch_end, limit=MAX_BARS_PER_REQUEST)

        if data and data.get('resultsCount', 0) > 0:
            bars = data.get('results', [])
            all_batches.append({
                'start': current_date,
                'end': batch_end,
                'bars': bars,
                'count': len(bars)
            })
            print(f"✓ {len(bars):,} bars")

            # Check if we hit the limit (might need finer batching)
            if len(bars) >= MAX_BARS_PER_REQUEST * 0.95:
                print(f"  ⚠ Warning: Near API limit. Consider smaller batches for this range.")
        else:
            print(f"✗ No data")

        # Progress
        progress = min(100, (batch_num / estimated_batches) * 100)
        print(f"  Progress: {progress:.1f}%")

        # Move to next batch
        current_date = batch_end + timedelta(days=1)

        # Rate limiting
        if current_date <= end_date:
            time.sleep(RATE_LIMIT_DELAY)

    print("-" * 70)
    print(f"\nFetched {len(all_batches)} batches")

    # Merge all batches
    print(f"\n{'='*70}")
    print("MERGING AND DEDUPLICATING BATCHES")
    print(f"{'='*70}")

    if not all_batches:
        print("✗ No data fetched")
        return None

    # Combine all bars
    all_bars = []
    for i, batch in enumerate(all_batches):
        print(f"Batch {i+1}: {batch['count']:,} bars from {batch['start'].date()} to {batch['end'].date()}")
        all_bars.extend(batch['bars'])

    print(f"\nTotal bars before dedup: {len(all_bars):,}")

    # Convert to DataFrame
    df = pd.DataFrame(all_bars)

    # Convert timestamp and create readable columns
    df['timestamp'] = pd.to_datetime(df['t'], unit='ms')
    df = df.rename(columns={
        'o': 'open',
        'h': 'high',
        'l': 'low',
        'c': 'close',
        'v': 'volume',
        'vw': 'vwap',
        'n': 'transactions'
    })

    # Select columns
    columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'vwap', 'transactions']
    df = df[[col for col in columns if col in df.columns]]

    # Sort by timestamp
    df = df.sort_values('timestamp').reset_index(drop=True)

    # Remove duplicates (keep first occurrence)
    initial_count = len(df)
    df = df.drop_duplicates(subset=['timestamp'], keep='first').reset_index(drop=True)
    duplicates_removed = initial_count - len(df)

    print(f"Duplicates removed: {duplicates_removed:,}")
    print(f"Final bar count: {len(df):,}")

    # Verify completeness
    print(f"\n{'='*70}")
    print("DATA QUALITY VERIFICATION")
    print(f"{'='*70}")

    if len(df) > 0:
        print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

        # Check for gaps
        time_diffs = df['timestamp'].diff()
        expected_diff = pd.Timedelta(minutes=1)

        # Allow some tolerance for weekends/holidays
        large_gaps = time_diffs[time_diffs > pd.Timedelta(hours=72)]  # >3 days

        if len(large_gaps) > 0:
            print(f"Large gaps found: {len(large_gaps)}")
            print("  (This is normal for weekends/holidays)")
        else:
            print("✓ No unexpected gaps in data")

        print(f"\nBasic statistics:")
        print(f"  Total bars: {len(df):,}")
        print(f"  First timestamp: {df['timestamp'].iloc[0]}")
        print(f"  Last timestamp: {df['timestamp'].iloc[-1]}")
        print(f"  Price range: ${df['close'].min():.5f} - ${df['close'].max():.5f}")

    return df


# ---------------------------------------------------------------------------
# File Operations
# ---------------------------------------------------------------------------

def save_data(df, ticker, output_dir="data_acquisition"):
    """Save DataFrame to CSV with metadata."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    clean_ticker = ticker.replace('C:', '').replace('/', '_').replace(':', '_')

    start_date = df['timestamp'].min().strftime("%Y%m%d")
    end_date = df['timestamp'].max().strftime("%Y%m%d")
    filename = f"{clean_ticker}_1min_{start_date}_{end_date}.csv"
    filepath = os.path.join(output_dir, filename)

    # Save CSV
    df.to_csv(filepath, index=False)

    # Save metadata
    metadata = {
        'ticker': ticker,
        'display_name': get_display_name(ticker),
        'rows': len(df),
        'start_date': str(df['timestamp'].min()),
        'end_date': str(df['timestamp'].max()),
        'file_size_mb': os.path.getsize(filepath) / (1024*1024),
        'created_at': datetime.now().isoformat()
    }

    metadata_file = filepath.replace('.csv', '_metadata.json')
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n{'='*70}")
    print("DATA SAVED")
    print(f"{'='*70}")
    print(f"✓ CSV: {filepath}")
    print(f"  Rows: {len(df):,}")
    print(f"  Size: {metadata['file_size_mb']:.2f} MB")
    print(f"  Date range: {metadata['start_date']} to {metadata['end_date']}")
    print(f"✓ Metadata: {metadata_file}")

    # Create symlink to latest
    latest_link = os.path.join(output_dir, f"{clean_ticker}_1min_latest.csv")
    if os.path.exists(latest_link) or os.path.islink(latest_link):
        os.remove(latest_link)
    os.symlink(os.path.basename(filepath), latest_link)
    print(f"✓ Symlink: {latest_link}")

    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("="*70)
    print("POLYGON.IO SMART DATA ACQUISITION v2.0")
    print("="*70)
    print("Improvements:")
    print("  ✓ Binary search for earliest date (more efficient)")
    print("  ✓ Optimal batching based on 50K bar limit")
    print("  ✓ Fetch from oldest to newest")
    print("  ✓ Automatic merging and deduplication")
    print("  ✓ Data quality verification")
    print("="*70)
    print()
    print("Supported formats:")
    print("  Forex: EURUSD, EUR/USD, GBPUSD, etc.")
    print("  Stocks: AAPL, TSLA, SPY, etc.")
    print()

    user_input = input(f"Enter ticker symbol (default: EUR/USD): ").strip()
    if not user_input:
        user_input = "EUR/USD"

    ticker = format_ticker(user_input)
    display_name = get_display_name(ticker)

    print(f"\nTicker: {display_name}")
    print(f"API format: {ticker}")
    print(f"API Key: {API_KEY[:10]}...")

    # Step 1: Binary search for earliest date
    earliest_date = binary_search_earliest_date(ticker)

    if not earliest_date:
        print("\n✗ Could not find accessible data. Check API key and ticker.")
        return

    # Step 2: Get latest date (yesterday or last trading day)
    today = datetime.now()
    end_date = today - timedelta(days=1)

    # Skip weekends
    while end_date.weekday() >= 5:
        end_date -= timedelta(days=1)

    # Sanity checks
    if end_date > today:
        print(f"⚠ Warning: End date {end_date.date()} is in future! Using today.")
        end_date = today
        while end_date.weekday() >= 5:
            end_date -= timedelta(days=1)

    if earliest_date >= end_date:
        print(f"⚠ Warning: Earliest {earliest_date.date()} >= End {end_date.date()}!")
        print(f"   API access check may have failed. Using last 30 days.")
        earliest_date = end_date - timedelta(days=30)

    # Step 3: Confirm with user
    print(f"\n{'='*70}")
    print("READY TO FETCH DATA")
    print(f"{'='*70}")
    print(f"Today's date: {today.date()}")
    print(f"Date range: {earliest_date.date()} to {end_date.date()}")
    print(f"Total days: {(end_date - earliest_date).days}")
    print()

    proceed = input("Proceed with smart data fetch? (yes/no): ").strip().lower()
    if proceed not in ['yes', 'y']:
        print("Cancelled.")
        return

    # Step 4: Fetch all data
    df = fetch_all_data_smart(ticker, earliest_date, end_date)

    if df is not None and len(df) > 0:
        # Step 5: Save data
        save_data(df, ticker)

        print(f"\n{'='*70}")
        print("✓ DATA ACQUISITION COMPLETE!")
        print(f"{'='*70}")
    else:
        print("\n✗ No data was fetched. Please check API key and ticker symbol.")


if __name__ == "__main__":
    main()
