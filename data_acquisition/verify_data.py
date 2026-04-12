#!/usr/bin/env python3
"""
Data Verification Script for Polygon.io 1-minute bar data.

Scans CSV files and detects:
- Missing 1-minute gaps (expected: exactly 1 minute between consecutive bars)
- Time travel (timestamps going backward)
- Duplicate timestamps
- Unusual large gaps (weekends, holidays, API issues)
- Data quality issues (NaN, zero volume, invalid prices)

Usage:
    python3 data_acquisition/verify_data.py                          # Verify latest
    python3 data_acquisition/verify_data.py --csv path/to/data.csv   # Verify specific file
    python3 data_acquisition/verify_data.py --ticker EURUSD          # Verify ticker

Output:
    - Console report with all issues found
    - Optional JSON report file with detailed anomalies
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import argparse
import json
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Expected time difference between consecutive bars
EXPECTED_DELTA = pd.Timedelta(minutes=1)

# Tolerance for "normal" gaps (weekends, holidays)
WEEKEND_GAP_THRESHOLD = pd.Timedelta(hours=48)  # 2 days
HOLIDAY_GAP_THRESHOLD = pd.Timedelta(hours=120)  # 5 days

# Data quality thresholds
MIN_PRICE = 0.0001  # Minimum valid price
MAX_PRICE = 1000000  # Maximum valid price


# ---------------------------------------------------------------------------
# Verification Functions
# ---------------------------------------------------------------------------

def load_csv_data(csv_path):
    """Load CSV and parse timestamps."""
    print(f"Loading data from: {csv_path}")

    df = pd.read_csv(csv_path)

    # Parse timestamp
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    else:
        raise ValueError("CSV must have 'timestamp' column")

    # Ensure sorted
    df = df.sort_values('timestamp').reset_index(drop=True)

    print(f"  Loaded {len(df):,} rows")
    print(f"  Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print()

    return df


def detect_time_issues(df):
    """
    Detect all time-related issues in the dataset.

    Returns:
        dict: Dictionary of issue types and their occurrences
    """
    print("=" * 70)
    print("TIME CONTINUITY ANALYSIS")
    print("=" * 70)

    issues = {
        'time_travel': [],      # Timestamps going backward
        'duplicates': [],        # Same timestamp appearing twice
        'missing_1min': [],      # Expected 1-min gap but got more
        'large_gaps': [],        # Gaps > 2 days (excluding weekends)
        'weekend_gaps': [],      # Normal weekend gaps (Fri close to Mon open)
    }

    # Calculate time differences
    df['time_diff'] = df['timestamp'].diff()

    # 1. Detect time travel (negative or zero time differences)
    print("\n1. Time Travel Detection (backward timestamps)")
    print("-" * 70)

    time_travel = df[df['time_diff'] <= pd.Timedelta(0)].copy()

    if len(time_travel) > 0:
        print(f"❌ Found {len(time_travel)} instances of time travel!")
        for idx, row in time_travel.iterrows():
            if idx > 0:
                prev_time = df.loc[idx - 1, 'timestamp']
                curr_time = row['timestamp']
                delta = row['time_diff']

                issue = {
                    'index': int(idx),
                    'previous_timestamp': str(prev_time),
                    'current_timestamp': str(curr_time),
                    'time_delta': str(delta),
                }
                issues['time_travel'].append(issue)

                print(f"  Row {idx}: {prev_time} → {curr_time} (delta: {delta})")
    else:
        print("✓ No time travel detected")

    # 2. Detect duplicates
    print("\n2. Duplicate Timestamp Detection")
    print("-" * 70)

    duplicates = df[df.duplicated(subset=['timestamp'], keep=False)]

    if len(duplicates) > 0:
        print(f"❌ Found {len(duplicates)} rows with duplicate timestamps!")

        # Group by timestamp to show duplicates together
        for timestamp, group in duplicates.groupby('timestamp'):
            print(f"  Timestamp {timestamp} appears {len(group)} times at rows: {list(group.index)}")

            issues['duplicates'].append({
                'timestamp': str(timestamp),
                'count': int(len(group)),
                'rows': [int(i) for i in group.index]
            })
    else:
        print("✓ No duplicate timestamps")

    # 3. Detect missing 1-minute gaps
    print("\n3. Missing 1-Minute Bars (gaps between consecutive bars)")
    print("-" * 70)

    # Filter out time travel and duplicates for this analysis
    valid_diffs = df[df['time_diff'] > pd.Timedelta(0)]['time_diff']

    # Find gaps that are not exactly 1 minute
    missing_bars = df[(df['time_diff'] > EXPECTED_DELTA) &
                      (df['time_diff'] <= WEEKEND_GAP_THRESHOLD)].copy()

    if len(missing_bars) > 0:
        print(f"⚠️  Found {len(missing_bars)} gaps where 1-minute bars are missing")
        print("\nTop 20 largest gaps:")
        print(f"{'Row':<8} {'Previous Time':<20} {'Current Time':<20} {'Gap':<15} {'Missing Bars':<15}")
        print("-" * 80)

        # Sort by gap size
        missing_bars = missing_bars.sort_values('time_diff', ascending=False)

        for idx, row in missing_bars.head(20).iterrows():
            if idx > 0:
                prev_time = df.loc[idx - 1, 'timestamp']
                curr_time = row['timestamp']
                gap = row['time_diff']
                missing_count = int(gap / EXPECTED_DELTA) - 1

                issue = {
                    'index': int(idx),
                    'previous_timestamp': str(prev_time),
                    'current_timestamp': str(curr_time),
                    'gap': str(gap),
                    'missing_bars': missing_count
                }
                issues['missing_1min'].append(issue)

                print(f"{idx:<8} {str(prev_time):<20} {str(curr_time):<20} {str(gap):<15} {missing_count:<15}")

        if len(missing_bars) > 20:
            print(f"\n... and {len(missing_bars) - 20} more gaps")
    else:
        print("✓ All consecutive bars are exactly 1 minute apart (within trading hours)")

    # 4. Detect large gaps (potential data issues)
    print("\n4. Large Gaps (> 48 hours, excluding weekends)")
    print("-" * 70)

    large_gaps = df[df['time_diff'] > WEEKEND_GAP_THRESHOLD].copy()

    if len(large_gaps) > 0:
        print(f"⚠️  Found {len(large_gaps)} large gaps (>48 hours)")
        print("\nAll large gaps:")
        print(f"{'Row':<8} {'Previous Time':<20} {'Current Time':<20} {'Gap':<15} {'Days':<10}")
        print("-" * 80)

        for idx, row in large_gaps.iterrows():
            if idx > 0:
                prev_time = df.loc[idx - 1, 'timestamp']
                curr_time = row['timestamp']
                gap = row['time_diff']
                days = gap.total_seconds() / 86400

                # Check if it's a weekend gap
                is_weekend = (prev_time.weekday() == 4 and  # Friday
                             curr_time.weekday() == 0 and   # Monday
                             gap < pd.Timedelta(hours=72))  # < 3 days

                issue = {
                    'index': int(idx),
                    'previous_timestamp': str(prev_time),
                    'current_timestamp': str(curr_time),
                    'gap': str(gap),
                    'gap_days': float(days),
                    'is_weekend': is_weekend
                }

                if is_weekend:
                    issues['weekend_gaps'].append(issue)
                    gap_type = "(Weekend)"
                else:
                    issues['large_gaps'].append(issue)
                    gap_type = "(UNUSUAL)"

                print(f"{idx:<8} {str(prev_time):<20} {str(curr_time):<20} {str(gap):<15} {days:<10.1f} {gap_type}")
    else:
        print("✓ No unusually large gaps found")

    return issues


def detect_data_quality_issues(df):
    """
    Detect data quality issues (NaN, invalid prices, zero volume, etc.).

    Returns:
        dict: Dictionary of data quality issues
    """
    print("\n" + "=" * 70)
    print("DATA QUALITY ANALYSIS")
    print("=" * 70)

    issues = {
        'nan_values': {},
        'invalid_prices': [],
        'zero_volume': [],
        'price_spikes': []
    }

    # 1. Check for NaN values
    print("\n1. Missing Values (NaN)")
    print("-" * 70)

    nan_counts = df.isnull().sum()
    nan_columns = nan_counts[nan_counts > 0]

    if len(nan_columns) > 0:
        print(f"❌ Found NaN values in {len(nan_columns)} columns:")
        for col, count in nan_columns.items():
            pct = (count / len(df)) * 100
            print(f"  {col}: {count:,} NaN values ({pct:.2f}%)")
            issues['nan_values'][col] = {'count': int(count), 'percentage': float(pct)}
    else:
        print("✓ No NaN values found")

    # 2. Check for invalid prices
    print("\n2. Invalid Price Values")
    print("-" * 70)

    price_cols = ['open', 'high', 'low', 'close']
    invalid_found = False

    for col in price_cols:
        if col in df.columns:
            # Check for prices outside valid range
            invalid = df[(df[col] < MIN_PRICE) | (df[col] > MAX_PRICE)]

            if len(invalid) > 0:
                invalid_found = True
                print(f"❌ Found {len(invalid)} invalid {col} prices:")
                for idx, row in invalid.head(10).iterrows():
                    print(f"  Row {idx}: {col}={row[col]} at {row['timestamp']}")

                    issues['invalid_prices'].append({
                        'index': int(idx),
                        'column': col,
                        'value': float(row[col]),
                        'timestamp': str(row['timestamp'])
                    })

    if not invalid_found:
        print("✓ All prices within valid range")

    # 3. Check for zero volume
    print("\n3. Zero Volume Bars")
    print("-" * 70)

    if 'volume' in df.columns:
        zero_vol = df[df['volume'] == 0]

        if len(zero_vol) > 0:
            print(f"⚠️  Found {len(zero_vol)} bars with zero volume ({len(zero_vol)/len(df)*100:.2f}%)")
            print("First 10 occurrences:")
            for idx, row in zero_vol.head(10).iterrows():
                print(f"  Row {idx}: {row['timestamp']}")

                issues['zero_volume'].append({
                    'index': int(idx),
                    'timestamp': str(row['timestamp'])
                })
        else:
            print("✓ No zero volume bars")
    else:
        print("⚠️  Volume column not found")

    # 4. Check for price spikes (potential errors)
    print("\n4. Price Spike Detection")
    print("-" * 70)

    if 'close' in df.columns:
        # Calculate percentage change
        df['pct_change'] = df['close'].pct_change().abs()

        # Flag changes > 5% in 1 minute (unusual for forex)
        spikes = df[df['pct_change'] > 0.05]

        if len(spikes) > 0:
            print(f"⚠️  Found {len(spikes)} price spikes (>5% change in 1 minute)")
            print("Largest spikes:")
            print(f"{'Row':<8} {'Timestamp':<20} {'Previous':<12} {'Current':<12} {'Change %':<12}")
            print("-" * 70)

            spikes_sorted = spikes.sort_values('pct_change', ascending=False)

            for idx, row in spikes_sorted.head(10).iterrows():
                if idx > 0:
                    prev_price = df.loc[idx - 1, 'close']
                    curr_price = row['close']
                    change_pct = row['pct_change'] * 100

                    print(f"{idx:<8} {str(row['timestamp']):<20} {prev_price:<12.5f} {curr_price:<12.5f} {change_pct:<12.2f}")

                    issues['price_spikes'].append({
                        'index': int(idx),
                        'timestamp': str(row['timestamp']),
                        'previous_price': float(prev_price),
                        'current_price': float(curr_price),
                        'change_pct': float(change_pct)
                    })
        else:
            print("✓ No unusual price spikes detected")

        # Clean up
        df.drop('pct_change', axis=1, inplace=True)

    return issues


def generate_summary(df, time_issues, quality_issues):
    """Generate a summary report."""
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)

    total_issues = (
        len(time_issues['time_travel']) +
        len(time_issues['duplicates']) +
        len(time_issues['missing_1min']) +
        len(time_issues['large_gaps']) +
        len(quality_issues['invalid_prices']) +
        len(quality_issues['zero_volume']) +
        len(quality_issues['price_spikes'])
    )

    print(f"\nDataset: {len(df):,} rows")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"Duration: {(df['timestamp'].max() - df['timestamp'].min()).days} days")
    print()

    print("Issue Counts:")
    print(f"  Time travel (backward timestamps): {len(time_issues['time_travel'])}")
    print(f"  Duplicate timestamps: {len(time_issues['duplicates'])}")
    print(f"  Missing 1-minute bars: {len(time_issues['missing_1min'])}")
    print(f"  Large gaps (>48h, non-weekend): {len(time_issues['large_gaps'])}")
    print(f"  Weekend gaps (normal): {len(time_issues['weekend_gaps'])}")
    print(f"  Invalid prices: {len(quality_issues['invalid_prices'])}")
    print(f"  Zero volume bars: {len(quality_issues['zero_volume'])}")
    print(f"  Price spikes (>5%): {len(quality_issues['price_spikes'])}")
    print()

    if total_issues == 0:
        print("✅ DATA QUALITY: EXCELLENT - No major issues found!")
    elif total_issues < 10:
        print("✅ DATA QUALITY: GOOD - Minor issues found")
    elif total_issues < 100:
        print("⚠️  DATA QUALITY: FAIR - Some issues found")
    else:
        print("❌ DATA QUALITY: POOR - Many issues found")

    print()

    # Calculate completeness
    expected_bars = (df['timestamp'].max() - df['timestamp'].min()).total_seconds() / 60
    actual_bars = len(df)
    completeness = (actual_bars / expected_bars) * 100 if expected_bars > 0 else 0

    print(f"Data Completeness:")
    print(f"  Expected bars (continuous): {int(expected_bars):,}")
    print(f"  Actual bars: {actual_bars:,}")
    print(f"  Completeness: {completeness:.2f}%")
    print(f"  (Note: <100% is normal due to weekends/holidays)")

    return {
        'total_rows': int(len(df)),
        'date_range': {
            'start': str(df['timestamp'].min()),
            'end': str(df['timestamp'].max()),
            'days': int((df['timestamp'].max() - df['timestamp'].min()).days)
        },
        'issue_counts': {
            'time_travel': len(time_issues['time_travel']),
            'duplicates': len(time_issues['duplicates']),
            'missing_1min': len(time_issues['missing_1min']),
            'large_gaps': len(time_issues['large_gaps']),
            'weekend_gaps': len(time_issues['weekend_gaps']),
            'invalid_prices': len(quality_issues['invalid_prices']),
            'zero_volume': len(quality_issues['zero_volume']),
            'price_spikes': len(quality_issues['price_spikes'])
        },
        'completeness': {
            'expected_bars': int(expected_bars),
            'actual_bars': actual_bars,
            'percentage': float(completeness)
        }
    }


def save_report(csv_path, time_issues, quality_issues, summary):
    """Save detailed report to JSON file."""
    report = {
        'csv_file': csv_path,
        'verification_timestamp': datetime.now().isoformat(),
        'summary': summary,
        'time_issues': time_issues,
        'quality_issues': quality_issues
    }

    # Generate report filename
    report_path = csv_path.replace('.csv', '_verification_report.json')

    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\n📄 Detailed report saved to: {report_path}")

    return report_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Verify Polygon.io 1-minute bar data quality"
    )
    parser.add_argument(
        '--csv',
        type=str,
        help='Path to CSV file to verify'
    )
    parser.add_argument(
        '--ticker',
        type=str,
        help='Ticker symbol (will find latest CSV for this ticker)'
    )
    parser.add_argument(
        '--save-report',
        action='store_true',
        help='Save detailed JSON report'
    )

    args = parser.parse_args()

    # Find CSV file
    if args.csv:
        csv_path = args.csv
    elif args.ticker:
        # Look for latest file
        data_acq_dir = os.path.dirname(os.path.abspath(__file__))
        ticker_clean = args.ticker.replace('C:', '').replace('/', '').replace('_', '').upper()

        latest_link = os.path.join(data_acq_dir, f"{ticker_clean}_1min_latest.csv")
        if os.path.exists(latest_link):
            csv_path = latest_link
        else:
            # Find most recent file
            pattern = f"{ticker_clean}_1min_*.csv"
            files = list(Path(data_acq_dir).glob(pattern))
            if files:
                csv_path = str(max(files, key=lambda p: p.stat().st_mtime))
            else:
                print(f"❌ No CSV found for ticker {args.ticker}")
                return
    else:
        # Find any latest file
        data_acq_dir = os.path.dirname(os.path.abspath(__file__))
        latest_links = list(Path(data_acq_dir).glob("*_1min_latest.csv"))
        if latest_links:
            csv_path = str(latest_links[0])
        else:
            print("❌ No CSV files found. Please specify --csv or --ticker")
            return

    print("=" * 70)
    print("POLYGON.IO DATA VERIFICATION")
    print("=" * 70)
    print()

    # Load data
    df = load_csv_data(csv_path)

    # Run verifications
    time_issues = detect_time_issues(df)
    quality_issues = detect_data_quality_issues(df)

    # Generate summary
    summary = generate_summary(df, time_issues, quality_issues)

    # Save report if requested
    if args.save_report:
        save_report(csv_path, time_issues, quality_issues, summary)

    print("\n" + "=" * 70)
    print("VERIFICATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
