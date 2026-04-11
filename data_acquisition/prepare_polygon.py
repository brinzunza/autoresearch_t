#!/usr/bin/env python3
"""
Data preparation using Polygon.io 1-minute stock data.
Adapts the autoresearch preparation pipeline to work with stock market data.

Usage:
    python data_acquisition/prepare_polygon.py                    # use latest data
    python data_acquisition/prepare_polygon.py --ticker AAPL      # specify ticker
    python data_acquisition/prepare_polygon.py --csv path/to/data.csv  # use specific CSV

Data is stored in ~/.cache/autotrade/.
"""

import os
import sys
import argparse
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from ta.trend import SMAIndicator, EMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, AverageTrueRange
from sklearn.preprocessing import RobustScaler

# Add parent directory to path to import from prepare.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import functions we can reuse from prepare.py
from prepare import (
    add_technical_indicators,
    create_train_test_split,
    fit_scaler,
    create_sequences,
    CACHE_DIR,
    DATA_DIR,
    SCALER_DIR,
    TRAIN_RATIO,
    TEST_RATIO,
)

# ---------------------------------------------------------------------------
# Polygon.io data loading
# ---------------------------------------------------------------------------

def load_polygon_data(csv_path=None, ticker=None):
    """
    Load 1-minute bar data from Polygon.io CSV.

    Args:
        csv_path: Path to CSV file (if None, looks for latest in data_acquisition/)
        ticker: Ticker symbol (used if csv_path not provided)

    Returns:
        pd.DataFrame with OHLCV data in same format as prepare.py expects
    """
    data_acq_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data_acquisition"
    )

    if csv_path is None:
        # Look for latest data
        if ticker:
            latest_link = os.path.join(data_acq_dir, f"{ticker}_1min_latest.csv")
            if os.path.exists(latest_link):
                csv_path = latest_link
            else:
                # Find most recent file for this ticker
                pattern = f"{ticker}_1min_*.csv"
                files = list(Path(data_acq_dir).glob(pattern))
                if files:
                    csv_path = max(files, key=lambda p: p.stat().st_mtime)
                else:
                    raise FileNotFoundError(
                        f"No Polygon.io data found for {ticker} in {data_acq_dir}\n"
                        f"Run: python data_acquisition/fetch_data.py"
                    )
        else:
            # Find any latest link
            latest_links = list(Path(data_acq_dir).glob("*_1min_latest.csv"))
            if latest_links:
                csv_path = latest_links[0]
            else:
                raise FileNotFoundError(
                    f"No Polygon.io data found in {data_acq_dir}\n"
                    f"Run: python data_acquisition/fetch_data.py"
                )

    print(f"Loading data from: {csv_path}")

    # Load CSV
    df = pd.read_csv(csv_path)

    # Convert timestamp to datetime if needed
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    else:
        raise ValueError("CSV must have 'timestamp' column")

    # Verify required columns
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"CSV missing required columns: {missing_cols}")

    # Sort by timestamp
    df = df.sort_values('timestamp').reset_index(drop=True)

    print(f"Loaded {len(df):,} bars from {df['timestamp'].min()} to {df['timestamp'].max()}")

    return df


def prepare_polygon_data(csv_path=None, ticker=None, **indicator_params):
    """
    Load Polygon.io data and prepare features.

    Args:
        csv_path: Path to CSV file
        ticker: Ticker symbol
        **indicator_params: Parameters for technical indicators

    Returns:
        pd.DataFrame with features
    """
    # Load raw data
    df = load_polygon_data(csv_path=csv_path, ticker=ticker)

    # Add technical indicators (reuse from prepare.py)
    df = add_technical_indicators(df, **indicator_params)

    # Drop NaN rows (from indicator calculations)
    df = df.dropna().reset_index(drop=True)

    print(f"After feature engineering: {len(df):,} bars with {len(df.columns)} features")

    return df


def save_prepared_data(df, ticker, symbol_name=None):
    """
    Save prepared data to cache directory in same format as prepare.py.

    Args:
        df: DataFrame with prepared features
        ticker: Ticker symbol
        symbol_name: Optional name to use for file (defaults to ticker)
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    if symbol_name is None:
        symbol_name = ticker.replace('/', '_')

    filepath = os.path.join(DATA_DIR, f"{symbol_name}_1m.parquet")

    # Save as parquet (same as prepare.py)
    df.to_parquet(filepath, index=False)

    print(f"Saved prepared data to: {filepath}")
    print(f"  Rows: {len(df):,}")
    print(f"  Columns: {len(df.columns)}")
    print(f"  Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Prepare Polygon.io data for autoresearch training"
    )
    parser.add_argument(
        "--ticker",
        type=str,
        default=None,
        help="Stock ticker symbol (e.g., AAPL, TSLA)"
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to specific CSV file (if not using latest)"
    )
    parser.add_argument(
        "--save-as",
        type=str,
        default=None,
        help="Symbol name to use when saving (e.g., 'AAPL_STOCK' instead of 'AAPL')"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("POLYGON.IO DATA PREPARATION FOR AUTORESEARCH")
    print("=" * 70)
    print(f"Cache directory: {CACHE_DIR}")
    print()

    # Step 1: Load and prepare data
    print("Step 1: Loading and preparing data...")
    print("-" * 70)

    try:
        df = prepare_polygon_data(csv_path=args.csv, ticker=args.ticker)
    except FileNotFoundError as e:
        print(f"\nError: {e}")
        print("\nPlease run the data acquisition script first:")
        print("  python data_acquisition/fetch_data.py")
        sys.exit(1)
    except Exception as e:
        print(f"\nError loading data: {e}")
        sys.exit(1)

    # Extract ticker from data if not provided
    ticker = args.ticker
    if ticker is None and args.csv:
        # Try to extract from filename
        filename = os.path.basename(args.csv)
        ticker = filename.split('_')[0]

    if ticker is None:
        ticker = "STOCK"

    print()

    # Step 2: Save to cache directory
    print("Step 2: Saving prepared data...")
    print("-" * 70)
    save_prepared_data(df, ticker, symbol_name=args.save_as)
    print()

    # Step 3: Create train/test split preview
    print("Step 3: Train/test split preview...")
    print("-" * 70)
    train_df, test_df = create_train_test_split(df, train_ratio=TRAIN_RATIO)

    print(f"Training data:")
    print(f"  Rows: {len(train_df):,}")
    print(f"  Date range: {train_df['timestamp'].min()} to {train_df['timestamp'].max()}")
    print()
    print(f"Testing data:")
    print(f"  Rows: {len(test_df):,}")
    print(f"  Date range: {test_df['timestamp'].min()} to {test_df['timestamp'].max()}")
    print()

    # Step 4: Display feature summary
    print("Step 4: Feature summary...")
    print("-" * 70)

    # Get feature columns (exclude timestamp and basic OHLCV)
    exclude_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    feature_cols = [col for col in df.columns if col not in exclude_cols]

    print(f"Total features: {len(feature_cols)}")
    print(f"Feature columns: {', '.join(feature_cols[:10])}", end="")
    if len(feature_cols) > 10:
        print(f"... (+{len(feature_cols) - 10} more)")
    else:
        print()
    print()

    # Display basic statistics
    print("Basic statistics (close price):")
    print(df['close'].describe())
    print()

    print("=" * 70)
    print("✓ Data preparation complete!")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Update train.py to use this symbol:")
    print(f"     python train.py --symbols {args.save_as or ticker}")
    print()
    print("  2. Or run the full training pipeline:")
    print(f"     python train.py")
    print()


if __name__ == "__main__":
    main()
