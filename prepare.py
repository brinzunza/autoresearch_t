"""
One-time data preparation for autotrade experiments.
Downloads 1-minute forex OHLCV data and prepares features for walk-forward backtesting.

Usage:
    python prepare.py                      # full prep (download data)
    python prepare.py --symbols EURUSD     # download specific symbol

Data is stored in ~/.cache/autotrade/.
"""

import os
import sys
import time
import argparse
import pickle
from datetime import datetime, timedelta

import ccxt
import numpy as np
import pandas as pd
import torch
from ta.trend import SMAIndicator, EMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, AverageTrueRange
from sklearn.preprocessing import RobustScaler

# ---------------------------------------------------------------------------
# Constants (fixed, do not modify)
# ---------------------------------------------------------------------------

TIME_BUDGET = 300        # training time budget in seconds (5 minutes)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "autotrade")
DATA_DIR = os.path.join(CACHE_DIR, "data")
SCALER_DIR = os.path.join(CACHE_DIR, "scaler")

# Default forex pairs to download
DEFAULT_SYMBOLS = ['EUR/USD', 'GBP/USD', 'USD/JPY']
TIMEFRAME = '1m'  # 1-minute candles
LOOKBACK_DAYS = 730  # ~2 years of data (730 days = ~1M candles per pair)

# Train/test split configuration
TRAIN_RATIO = 0.7  # 70% for training
TEST_RATIO = 0.3   # 30% for testing

# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------

DATA_ACQUISITION_DIR = "data_acquisition/data_acquisition"

def download_forex_data(symbols=None, days=LOOKBACK_DAYS):
    """Download forex OHLCV data using ccxt (1-minute candles) or use existing local CSVs."""
    if symbols is None:
        symbols = DEFAULT_SYMBOLS

    os.makedirs(DATA_DIR, exist_ok=True)

    # Use Binance with stablecoin pairs as proxy for forex
    # In production, use a proper forex broker API (OANDA, IB, etc.)
    exchange = ccxt.binance({'enableRateLimit': True})

    # Map forex symbols to crypto pairs (for demo)
    symbol_map = {
        'EUR/USD': 'EUR/USDT',
        'GBP/USD': 'GBP/USDT',
        'USD/JPY': 'BTC/USDT',  # Using BTC as proxy
    }

    since = exchange.parse8601((datetime.now() - timedelta(days=days)).isoformat())

    for symbol in symbols:
        try:
            filepath = os.path.join(DATA_DIR, f"{symbol.replace('/', '_')}_1m.parquet")

            # Check if we have a local CSV file in data_acquisition first
            clean_symbol = symbol.replace('/', '').replace('_', '').upper()
            csv_pattern = f"{clean_symbol}_1min_*.csv"
            
            import glob
            local_csvs = glob.glob(os.path.join(DATA_ACQUISITION_DIR, csv_pattern))
            
            if local_csvs:
                latest_csv = max(local_csvs, key=os.path.getmtime)
                print(f"Found local data for {symbol}: {latest_csv}")
                df = pd.read_csv(latest_csv)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                # Ensure it has the columns we need
                required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                if all(col in df.columns for col in required_cols):
                    df = df[required_cols]
                    df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
                    df.to_parquet(filepath, index=False)
                    print(f"  Converted {latest_csv} to parquet: {len(df):,} candles")
                    continue
                else:
                    print(f"  Local CSV {latest_csv} is missing required columns. Falling back to download.")

            trading_symbol = symbol_map.get(symbol, symbol)
            print(f"Downloading {symbol} (as {trading_symbol}) - 1min candles...")

            filepath = os.path.join(DATA_DIR, f"{symbol.replace('/', '_')}_1m.parquet")

            # Check if data exists and is recent
            if os.path.exists(filepath):
                df = pd.read_parquet(filepath)
                if not df.empty:
                    last_date = pd.to_datetime(df['timestamp'].max())
                    if (datetime.now() - last_date).days < 1:
                        print(f"  {symbol} data is up to date ({len(df):,} candles)")
                        continue

            # Fetch OHLCV data in batches
            print(f"  Fetching data (this may take a few minutes)...")
            all_ohlcv = []
            current_since = since
            batch_count = 0

            while True:
                try:
                    ohlcv = exchange.fetch_ohlcv(trading_symbol, TIMEFRAME, since=current_since, limit=1000)
                    if not ohlcv:
                        break

                    all_ohlcv.extend(ohlcv)
                    current_since = ohlcv[-1][0] + 60000  # Next minute (in ms)
                    batch_count += 1

                    if batch_count % 100 == 0:
                        print(f"    Fetched {len(all_ohlcv):,} candles...")

                    if len(ohlcv) < 1000:  # Last batch
                        break

                    time.sleep(exchange.rateLimit / 1000)  # Respect rate limits

                except Exception as e:
                    print(f"    Error fetching batch: {e}, retrying...")
                    time.sleep(5)
                    continue

            # Convert to DataFrame and save as parquet (more efficient)
            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            df.to_parquet(filepath, index=False)

            print(f"  Downloaded {len(df):,} candles for {symbol}")

        except Exception as e:
            print(f"  Error downloading {symbol}: {e}")
            continue

    print(f"\nData downloaded to {DATA_DIR}")


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def add_technical_indicators(df, rsi_period=14, macd_fast=12, macd_slow=26,
                             sma_short=20, sma_long=50, bb_window=20, atr_window=14):
    """Add technical indicators as features. Parameters are configurable."""
    df = df.copy()

    # Price-based features
    df['returns'] = df['close'].pct_change()
    df['log_returns'] = np.log(df['close'] / df['close'].shift(1))

    # Trend indicators
    df[f'sma_{sma_short}'] = SMAIndicator(df['close'], window=sma_short).sma_indicator()
    df[f'sma_{sma_long}'] = SMAIndicator(df['close'], window=sma_long).sma_indicator()
    df['ema_12'] = EMAIndicator(df['close'], window=12).ema_indicator()
    df['ema_26'] = EMAIndicator(df['close'], window=26).ema_indicator()

    # MACD
    macd = MACD(df['close'], window_fast=macd_fast, window_slow=macd_slow)
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_diff'] = macd.macd_diff()

    # Momentum indicators
    df['rsi'] = RSIIndicator(df['close'], window=rsi_period).rsi()
    stoch = StochasticOscillator(df['high'], df['low'], df['close'])
    df['stoch_k'] = stoch.stoch()
    df['stoch_d'] = stoch.stoch_signal()

    # Volatility indicators
    bb = BollingerBands(df['close'], window=bb_window, window_dev=2)
    df['bb_high'] = bb.bollinger_hband()
    df['bb_low'] = bb.bollinger_lband()
    df['bb_mid'] = bb.bollinger_mavg()
    df['bb_width'] = (df['bb_high'] - df['bb_low']) / df['bb_mid']

    df['atr'] = AverageTrueRange(df['high'], df['low'], df['close'], window=atr_window).average_true_range()

    # Price position features
    df[f'price_to_sma{sma_short}'] = df['close'] / df[f'sma_{sma_short}']
    df[f'price_to_sma{sma_long}'] = df['close'] / df[f'sma_{sma_long}']

    # Volume features (if available)
    if 'volume' in df.columns and df['volume'].sum() > 0:
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']

    return df


def prepare_features(symbol='EUR/USD', **indicator_params):
    """Load data and prepare features for a symbol, ensuring local CSVs are used."""
    filepath = os.path.join(DATA_DIR, f"{symbol.replace('/', '_')}_1m.parquet")

    # Sync with local CSV if it exists and is newer or parquet is missing
    clean_symbol = symbol.replace('/', '').replace('_', '').upper()
    csv_pattern = f"{clean_symbol}_1min_*.csv"
    import glob
    local_csvs = glob.glob(os.path.join(DATA_ACQUISITION_DIR, csv_pattern))
    
    if local_csvs:
        latest_csv = max(local_csvs, key=os.path.getmtime)
        should_convert = False
        
        if not os.path.exists(filepath):
            should_convert = True
        else:
            csv_mtime = os.path.getmtime(latest_csv)
            parquet_mtime = os.path.getmtime(filepath)
            if csv_mtime > parquet_mtime:
                should_convert = True
        
        if should_convert:
            print(f"Syncing {symbol} from local CSV: {latest_csv}")
            df_csv = pd.read_csv(latest_csv)
            df_csv['timestamp'] = pd.to_datetime(df_csv['timestamp'])
            required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            if all(col in df_csv.columns for col in required_cols):
                df_csv = df_csv[required_cols]
                df_csv = df_csv.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
                os.makedirs(DATA_DIR, exist_ok=True)
                df_csv.to_parquet(filepath, index=False)
                print(f"  Updated cache: {len(df_csv):,} candles")
            else:
                print(f"  Warning: Local CSV {latest_csv} is missing columns. Using existing cache if possible.")

    if not os.path.exists(filepath):
        print(f"Data file not found: {filepath}")
        print(f"Please ensure a CSV exists in {DATA_ACQUISITION_DIR} or run download_forex_data()")
        return None

    df = pd.read_parquet(filepath)
    df = df.sort_values('timestamp').reset_index(drop=True)

    # Add technical indicators with configurable parameters
    df = add_technical_indicators(df, **indicator_params)

    # Drop NaN rows (from indicator calculations)
    df = df.dropna().reset_index(drop=True)

    return df


# ---------------------------------------------------------------------------
# Train/test split
# ---------------------------------------------------------------------------

def create_train_test_split(df, train_ratio=TRAIN_RATIO):
    """
    Create simple train/test split.

    Returns (train_df, test_df) tuple.
    Split is time-based: first train_ratio for training, rest for testing.
    """
    total_len = len(df)
    train_end = int(total_len * train_ratio)

    train_df = df.iloc[:train_end].copy()
    test_df = df.iloc[train_end:].copy()

    return train_df, test_df


def fit_scaler(train_df, feature_cols):
    """Fit RobustScaler on training data."""
    os.makedirs(SCALER_DIR, exist_ok=True)
    scaler = RobustScaler()
    scaler.fit(train_df[feature_cols])
    return scaler


def load_scaler():
    """Load fitted scaler."""
    scaler_path = os.path.join(SCALER_DIR, "scaler.pkl")
    if os.path.exists(scaler_path):
        with open(scaler_path, "rb") as f:
            return pickle.load(f)
    return None


# ---------------------------------------------------------------------------
# Data loader for training
# ---------------------------------------------------------------------------

def create_sequences(df, feature_cols, lookback=60, horizon=15):
    """
    Create sequences for time series prediction.
    Optimized version using numpy sliding windows.
    """
    print(f"  Processing {len(df):,} samples...")
    
    # Convert to numpy for speed
    data = df[feature_cols].values
    close_prices = df['close'].values
    
    # Create input sequences X: (n_samples, lookback, n_features)
    # n_samples = len(df) - lookback - horizon
    X = np.lib.stride_tricks.sliding_window_view(data[:-horizon], (lookback, data.shape[1]))
    X = X.reshape(-1, lookback, data.shape[1])
    
    # Create targets y: future returns (scaled by 100 for better loss range)
    # future_price is horizon minutes ahead of the END of the lookback window
    # current_price is at the END of the lookback window
    current_prices = close_prices[lookback:-horizon]
    future_prices = close_prices[lookback + horizon:]
    
    y = 100.0 * (future_prices - current_prices) / current_prices
    
    # prices for backtesting (at the end of lookback window)
    prices = current_prices
    
    # Ensure all have the same length (they should)
    n_samples = min(len(X), len(y), len(prices))
    X = X[:n_samples]
    y = y[:n_samples]
    prices = prices[:n_samples]

    return X.astype(np.float32), y.astype(np.float32), prices.astype(np.float32)


# ---------------------------------------------------------------------------
# Enhanced backtesting engine
# ---------------------------------------------------------------------------

def backtest_strategy(predictions, actuals, prices,
                     initial_capital=10000,
                     # Position sizing
                     position_sizing='proportional',
                     max_position=1.0,
                     # Entry/Exit rules
                     entry_threshold=0.0,
                     take_profit_pct=None,
                     stop_loss_pct=None,
                     use_trailing_stop=False,
                     trailing_stop_pct=0.01,
                     # Risk management
                     max_drawdown_exit=None,
                     # Transaction costs
                     transaction_cost=0.0):
    """
    Enhanced backtest with realistic trading logic.

    Args:
        predictions: Predicted returns (numpy array)
        actuals: Actual returns (numpy array)
        prices: Price series (for stop-loss/take-profit)
        position_sizing: 'fixed', 'proportional', or 'kelly'
        max_position: Max position size as fraction of capital
        entry_threshold: Min abs(prediction) to enter position
        take_profit_pct: Take profit threshold (e.g., 0.02 = 2%)
        stop_loss_pct: Stop loss threshold (e.g., 0.01 = 1%)
        use_trailing_stop: Whether to use trailing stop
        trailing_stop_pct: Trailing stop percentage
        max_drawdown_exit: Exit all positions if DD exceeds this
        transaction_cost: Cost per trade as fraction

    Returns:
        dict with performance metrics
    """
    capital = initial_capital
    position = 0.0  # Current position (-1 to 1)
    entry_price = 0.0  # Price at which we entered
    peak_capital = capital
    max_drawdown_reached = 0.0
    trailing_stop_price = 0.0

    equity_curve = [capital]
    positions = [position]
    trades = []

    for i in range(len(predictions)):
        pred_return = predictions[i]
        actual_return = actuals[i]
        current_price = prices[i]

        # Check max drawdown exit
        current_dd = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
        max_drawdown_reached = max(max_drawdown_reached, current_dd)
        if max_drawdown_exit and current_dd >= max_drawdown_exit:
            # Force exit all positions
            if position != 0:
                cost = abs(position) * capital * transaction_cost
                capital -= cost
                trades.append({'type': 'exit_dd', 'position': position, 'price': current_price})
            position = 0.0
            entry_price = 0.0

        # Calculate P&L from current position
        if position != 0:
            pnl = capital * position * actual_return
            capital += pnl

        # Update peak
        if capital > peak_capital:
            peak_capital = capital

        # Check stop-loss
        if position != 0 and entry_price > 0 and stop_loss_pct:
            if position > 0:  # Long position
                if current_price <= entry_price * (1 - stop_loss_pct):
                    # Stop-loss hit
                    cost = abs(position) * capital * transaction_cost
                    capital -= cost
                    trades.append({'type': 'stop_loss', 'position': position, 'price': current_price})
                    position = 0.0
                    entry_price = 0.0
            elif position < 0:  # Short position
                if current_price >= entry_price * (1 + stop_loss_pct):
                    cost = abs(position) * capital * transaction_cost
                    capital -= cost
                    trades.append({'type': 'stop_loss', 'position': position, 'price': current_price})
                    position = 0.0
                    entry_price = 0.0

        # Check take-profit
        if position != 0 and entry_price > 0 and take_profit_pct:
            if position > 0:  # Long position
                if current_price >= entry_price * (1 + take_profit_pct):
                    cost = abs(position) * capital * transaction_cost
                    capital -= cost
                    trades.append({'type': 'take_profit', 'position': position, 'price': current_price})
                    position = 0.0
                    entry_price = 0.0
            elif position < 0:  # Short position
                if current_price <= entry_price * (1 - take_profit_pct):
                    cost = abs(position) * capital * transaction_cost
                    capital -= cost
                    trades.append({'type': 'take_profit', 'position': position, 'price': current_price})
                    position = 0.0
                    entry_price = 0.0

        # Check trailing stop
        if use_trailing_stop and position != 0 and entry_price > 0:
            if position > 0:  # Long position
                # Update trailing stop
                if trailing_stop_price == 0 or current_price > trailing_stop_price:
                    trailing_stop_price = current_price * (1 - trailing_stop_pct)
                # Check if hit
                if current_price <= trailing_stop_price:
                    cost = abs(position) * capital * transaction_cost
                    capital -= cost
                    trades.append({'type': 'trailing_stop', 'position': position, 'price': current_price})
                    position = 0.0
                    entry_price = 0.0
                    trailing_stop_price = 0.0

        # Entry logic (only if not in position)
        if position == 0 and abs(pred_return) >= entry_threshold:
            # Determine position size
            if position_sizing == 'fixed':
                target_position = np.sign(pred_return) * max_position
            elif position_sizing == 'proportional':
                # Scale position by prediction confidence
                target_position = np.clip(pred_return * 10, -max_position, max_position)
            elif position_sizing == 'kelly':
                # Simplified Kelly criterion (would need win rate estimate)
                kelly_fraction = abs(pred_return) * 2  # Simplified
                target_position = np.sign(pred_return) * min(kelly_fraction, max_position)
            else:
                target_position = np.sign(pred_return) * max_position

            # Enter position
            cost = abs(target_position) * capital * transaction_cost
            capital -= cost
            position = target_position
            entry_price = current_price
            trailing_stop_price = 0.0  # Reset trailing stop
            trades.append({'type': 'entry', 'position': position, 'price': current_price})

        equity_curve.append(capital)
        positions.append(position)

    equity_curve = np.array(equity_curve)

    # Calculate metrics
    total_return = (equity_curve[-1] - initial_capital) / initial_capital

    # Calculate drawdown
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - running_max) / running_max
    max_drawdown = abs(drawdown.min())

    # Calmar ratio (annualized return / max drawdown)
    # For 1-min data: ~525,600 minutes per year
    minutes = len(equity_curve)
    years = minutes / 525600
    annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    calmar_ratio = annualized_return / max_drawdown if max_drawdown > 0 else 0

    # Sharpe ratio
    returns = np.diff(equity_curve) / equity_curve[:-1]
    sharpe_ratio = (returns.mean() / returns.std() * np.sqrt(525600)) if returns.std() > 0 else 0

    # Win rate
    winning_trades = sum(1 for r in returns if r > 0)
    total_trades_count = len(trades)
    win_rate = winning_trades / len(returns) if len(returns) > 0 else 0

    return {
        'calmar_ratio': calmar_ratio,
        'sharpe_ratio': sharpe_ratio,
        'total_return': total_return * 100,
        'max_drawdown': max_drawdown * 100,
        'win_rate': win_rate * 100,
        'final_capital': equity_curve[-1],
        'num_trades': total_trades_count,
        'equity_curve': equity_curve,
        'positions': positions,
        'trades': trades,
    }


@torch.no_grad()
def evaluate_strategy(model, X_val, y_val, prices_val, **backtest_params):
    """
    Evaluate trading strategy on validation set.

    Returns Calmar ratio and full results dict.
    """
    model.eval()

    # Get predictions
    device = next(model.parameters()).device
    X_tensor = torch.FloatTensor(X_val).to(device)

    # Handle batch size for inference
    batch_size = 1024
    predictions = []
    for i in range(0, len(X_tensor), batch_size):
        batch = X_tensor[i:i+batch_size]
        preds = model(batch).cpu().numpy().flatten()
        predictions.extend(preds)

    predictions = np.array(predictions) / 100.0
    y_val_decimal = np.array(y_val) / 100.0

    # Debug info
    print(f"  Prediction range: [{predictions.min():.8f}, {predictions.max():.8f}], mean: {predictions.mean():.8f}")
    print(f"  Target range:     [{y_val_decimal.min():.8f}, {y_val_decimal.max():.8f}], mean: {y_val_decimal.mean():.8f}")
    
    threshold = backtest_params.get('entry_threshold', 0)
    potential_trades = np.sum(np.abs(predictions) >= threshold)
    print(f"  Potential trades (above {threshold} threshold): {potential_trades}")

    # Backtest
    results = backtest_strategy(predictions, y_val_decimal, prices_val, **backtest_params)

    return results['calmar_ratio'], results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare forex data for autotrade")
    parser.add_argument("--symbols", nargs='+', default=DEFAULT_SYMBOLS,
                       help="Forex symbols to download")
    parser.add_argument("--days", type=int, default=LOOKBACK_DAYS,
                       help="Number of days of historical data")
    args = parser.parse_args()

    print(f"Cache directory: {CACHE_DIR}")
    print()

    # Step 1: Download data
    print("Step 1: Downloading forex data (1-minute candles)...")
    print("NOTE: This will download ~1-2 million candles per symbol and may take 15-30 minutes.")
    download_forex_data(symbols=args.symbols, days=args.days)
    print()

    # Step 2: Verify data
    print("Step 2: Verifying downloaded data...")
    for symbol in args.symbols:
        filepath = os.path.join(DATA_DIR, f"{symbol.replace('/', '_')}_1m.parquet")
        if os.path.exists(filepath):
            df = pd.read_parquet(filepath)
            print(f"  {symbol}: {len(df):,} candles ({df['timestamp'].min()} to {df['timestamp'].max()})")
        else:
            print(f"  {symbol}: NOT FOUND")

    print()
    print("Done! Ready to train.")
    print(f"Train/test split will use {int(TRAIN_RATIO*100)}% for training, {int(TEST_RATIO*100)}% for testing.")
