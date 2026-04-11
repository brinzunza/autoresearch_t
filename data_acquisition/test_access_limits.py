#!/usr/bin/env python3
"""
Test script to determine how far back Polygon.io free tier allows data access.
"""

import requests
from datetime import datetime, timedelta
import time

API_KEY = "abEgGQWtzBpMvz1H4o00DHvEMoG1G_Md"
BASE_URL = "https://api.polygon.io/v2/aggs/ticker"

# Common stock ticker to test with
TICKER = "AAPL"

def test_date_access(ticker, date_str):
    """
    Test if we can access data for a specific date.

    Args:
        ticker: Stock ticker symbol
        date_str: Date in YYYY-MM-DD format

    Returns:
        tuple: (success: bool, response_data: dict, status_code: int)
    """
    # Format: /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}
    url = f"{BASE_URL}/{ticker}/range/1/minute/{date_str}/{date_str}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": API_KEY
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()

        # Check if we got results
        if response.status_code == 200 and data.get("resultsCount", 0) > 0:
            return True, data, response.status_code
        else:
            return False, data, response.status_code
    except Exception as e:
        return False, {"error": str(e)}, 0


def binary_search_earliest_date(ticker, start_date, end_date, max_attempts=20):
    """
    Use binary search to find the earliest accessible date.

    Args:
        ticker: Stock ticker symbol
        start_date: Earliest date to try (datetime object)
        end_date: Latest date to try (datetime object)
        max_attempts: Maximum number of API calls to make

    Returns:
        datetime: Earliest accessible date found
    """
    earliest_success = None
    attempts = 0

    left = start_date
    right = end_date

    print(f"Starting binary search between {left.date()} and {right.date()}")
    print("-" * 70)

    while left <= right and attempts < max_attempts:
        # Calculate midpoint
        mid = left + (right - left) // 2
        mid_str = mid.strftime("%Y-%m-%d")

        # Skip weekends (market closed)
        while mid.weekday() >= 5:  # Saturday = 5, Sunday = 6
            mid += timedelta(days=1)
            if mid > right:
                break

        if mid > right:
            break

        mid_str = mid.strftime("%Y-%m-%d")

        print(f"Attempt {attempts + 1}: Testing {mid_str}...", end=" ")
        success, data, status_code = test_date_access(ticker, mid_str)
        attempts += 1

        if success:
            print(f"✓ SUCCESS ({data.get('resultsCount', 0)} bars)")
            earliest_success = mid
            # Try going earlier
            right = mid - timedelta(days=1)
        else:
            print(f"✗ FAILED (Status: {status_code}, Message: {data.get('message', 'No data')})")
            # Try going later
            left = mid + timedelta(days=1)

        # Rate limiting - be respectful to the API
        time.sleep(0.5)

    return earliest_success


def main():
    print("=" * 70)
    print("POLYGON.IO FREE TIER DATA ACCESS LIMIT TEST")
    print("=" * 70)
    print(f"Testing with ticker: {TICKER}")
    print(f"API Key: {API_KEY[:10]}...")
    print()

    # Test today first
    today = datetime.now()
    # Go back to most recent trading day
    test_date = today - timedelta(days=1)
    while test_date.weekday() >= 5:
        test_date -= timedelta(days=1)

    print("Step 1: Testing recent data access...")
    print("-" * 70)
    success, data, status_code = test_date_access(TICKER, test_date.strftime("%Y-%m-%d"))

    if success:
        print(f"✓ Recent data accessible: {test_date.date()} ({data.get('resultsCount', 0)} bars)")
    else:
        print(f"✗ Cannot access recent data. Status: {status_code}")
        print(f"   Message: {data.get('message', 'Unknown error')}")
        print("\nThere may be an issue with the API key or ticker symbol.")
        return

    print("\n" + "=" * 70)
    print("Step 2: Finding earliest accessible date...")
    print("=" * 70)

    # Free tier typically allows 2 years of historical data
    # Let's search between 3 years ago and yesterday
    end_date = test_date
    start_date = today - timedelta(days=3*365)  # 3 years ago

    earliest_date = binary_search_earliest_date(TICKER, start_date, end_date)

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    if earliest_date:
        days_back = (today - earliest_date).days
        print(f"✓ Earliest accessible date: {earliest_date.date()}")
        print(f"✓ Days of historical data: ~{days_back} days")
        print(f"✓ Approximate date range: {earliest_date.date()} to {end_date.date()}")

        # Save results to file
        with open("data_acquisition/access_limits.txt", "w") as f:
            f.write(f"Polygon.io Free Tier Access Limits\n")
            f.write(f"={'=' * 50}\n")
            f.write(f"Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Ticker: {TICKER}\n")
            f.write(f"Earliest Accessible Date: {earliest_date.strftime('%Y-%m-%d')}\n")
            f.write(f"Most Recent Date: {end_date.strftime('%Y-%m-%d')}\n")
            f.write(f"Historical Days Available: ~{days_back}\n")

        print(f"\n✓ Results saved to data_acquisition/access_limits.txt")
    else:
        print("✗ Could not determine earliest accessible date")
        print("  This might indicate API issues or restrictions")


if __name__ == "__main__":
    main()
