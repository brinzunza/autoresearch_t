#!/usr/bin/env python3
import pandas as pd
import sys
import os
from datetime import timedelta

def verify_csv_integrity(file_path):
    print(f"Scanning {file_path} for integrity issues...")
    
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        return

    try:
        # Load only necessary column to save memory
        df = pd.read_csv(file_path, usecols=['timestamp'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    # Ensure it's sorted by timestamp for sequential check
    # We'll check if it was already sorted
    is_sorted = df['timestamp'].is_monotonic_increasing
    if not is_sorted:
        print("⚠️ Warning: Data is NOT sorted by timestamp. Sorting now for analysis...")
        df = df.sort_values('timestamp').reset_index(drop=True)

    issues_found = 0
    log_entries = []

    def log_issue(msg):
        nonlocal issues_found
        issues_found += 1
        print(msg)
        log_entries.append(msg)

    # 1. Check for duplicates
    duplicates = df[df.duplicated('timestamp')]
    if not duplicates.empty:
        log_issue(f"❌ Found {len(duplicates)} duplicate timestamps.")
        for ts in duplicates['timestamp'].unique()[:5]:
            log_issue(f"   - Duplicate: {ts}")
        if len(duplicates) > 5:
            log_issue(f"   - ... and {len(duplicates) - 5} more.")

    # 1b. Check for NaN values and Zero values in other columns
    try:
        full_df = pd.read_csv(file_path)
        for col in full_df.columns:
            nan_count = full_df[col].isna().sum()
            if nan_count > 0:
                log_issue(f"❌ COLUMN {col}: Found {nan_count} NaN values.")
            
            if col in ['open', 'high', 'low', 'close', 'volume']:
                zero_count = (full_df[col] == 0).sum()
                if zero_count > 0:
                    log_issue(f"⚠️ COLUMN {col}: Found {zero_count} rows with ZERO value.")
    except Exception as e:
        log_issue(f"⚠️ Could not check other columns: {e}")

    # 2. Check for time travel and skips
    for i in range(1, len(df)):
        prev_ts = df.iloc[i-1]['timestamp']
        curr_ts = df.iloc[i]['timestamp']
        diff = curr_ts - prev_ts

        if diff == timedelta(0):
            # Already handled by duplicate check, but for completeness:
            continue
        elif diff < timedelta(0):
            log_issue(f"❌ TIME TRAVEL: {prev_ts} -> {curr_ts} (Backwards by {prev_ts - curr_ts}) at row {i}")
        elif diff > timedelta(minutes=1):
            # Check if it's a weekend (typically Fri 21:00/22:00 to Sun 21:00/22:00)
            # Forex markets usually close Friday 22:00 UTC and open Sunday 22:00 UTC
            # We'll flag any gap > 1 min, but note if it looks like a weekend
            is_weekend = False
            if prev_ts.weekday() == 4 and (curr_ts.weekday() == 6 or curr_ts.weekday() == 0):
                is_weekend = True
            
            gap_str = str(diff)
            missing_bars = int(diff.total_seconds() / 60) - 1
            
            status = "[WEEKEND?]" if is_weekend else "[MISSING DATA]"
            if not is_weekend or diff > timedelta(hours=50): # Normal weekend is ~48h
                 log_issue(f"⚠️ {status} GAP: {prev_ts} -> {curr_ts} ({gap_str}, {missing_bars} bars) at row {i}")

    print("-" * 50)
    if issues_found == 0:
        print("✅ No integrity issues found! (1-minute continuity preserved)")
    else:
        print(f"Total issues/gaps found: {issues_found}")
    
    # Save log to file
    log_file = file_path.replace('.csv', '_integrity.log')
    with open(log_file, 'w') as f:
        f.write("\n".join(log_entries))
    print(f"Detailed log saved to {log_file}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
    else:
        # Default to the known file if it exists
        csv_file = "data_acquisition/data_acquisition/EURUSD_1min_20240412_20260410.csv"
        if not os.path.exists(csv_file):
            print("Usage: python verify_integrity.py <path_to_csv>")
            sys.exit(1)
            
    verify_csv_integrity(csv_file)
