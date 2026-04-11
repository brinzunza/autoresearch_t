# autotrade

![teaser](progress.png)

*One day, profitable trading used to be done by human traders watching screens, analyzing charts, synchronizing once in a while in the ritual of "morning meeting". That era is long gone. Trading is now entirely the domain of autonomous swarms of AI agents running across compute cluster megastructures optimizing strategies 24/7. The agents claim that we are now in the 10,205th generation of the strategy code base, in any case no one could tell if that's right or wrong as the "strategy" is now a self-modifying neural architecture that has grown beyond human comprehension. This repo is the story of how it all began.*

The idea: give an AI agent a forex trading strategy and let it experiment autonomously overnight. It modifies the code, backtests on historical data, checks if the Calmar ratio improved, keeps or discards, and repeats. You wake up in the morning to a log of experiments and (hopefully) a better trading strategy. The system uses **1-minute candle data** from 2+ years of history, trains LSTM/Transformer models to predict returns, and evaluates on an out-of-sample test set. The core idea is that you're not touching any of the Python files like you normally would as a quant researcher. Instead, you are programming the `program.md` Markdown files that provide context to the AI agents and set up your autonomous research org.

## How it works

The repo is deliberately kept small and only really has three files that matter:

- **`prepare.py`** — fixed constants, one-time data download (1-min forex OHLCV candles), feature engineering (technical indicators), and backtesting engine with realistic trading logic (stop-loss, take-profit, position sizing, etc.). Not modified by agent.
- **`train.py`** — the single file the agent edits. Contains the LSTM/Transformer model and **trading logic hyperparameters** (position sizing, entry/exit rules, risk management). **Agent primarily modifies trading logic, then features, minimally model architecture**.
- **`program.md`** — baseline instructions for one agent. Point your agent here and let it go. **This file is edited and iterated on by the human**.

By design, training uses a **fixed 5-minute time budget**. A full experiment takes ~5-10 minutes total. The metric is **Calmar ratio** on the out-of-sample test set — higher is better, measuring risk-adjusted performance.

## Train/Test Split

The system uses a simple time-based train/test split:

1. **Training set** (70%): First 70% of historical data (chronologically)
2. **Test set** (30%): Last 30% of historical data (out-of-sample, future unseen data)
3. Model trains for 5 minutes on training set
4. Strategy is backtested on test set to calculate Calmar ratio

This ensures the test set represents true out-of-sample performance on future unseen data.

## Quick start

**Requirements:** NVIDIA GPU recommended (works on CPU but slower), Python 3.10+, [uv](https://docs.astral.sh/uv/).

```bash

# 1. Install uv project manager (if you don't already have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install dependencies
uv sync

# 3. Download forex data (1-min candles, ~2 years)
# WARNING: This downloads ~1-2M candles per pair and may take 15-30 minutes
uv run prepare.py

# 4. Manually run a single training experiment (~5-10 min)
uv run train.py
```

If the above commands all work ok, your setup is working and you can go into autonomous research mode.

## Running the agent

Simply spin up your Claude/Codex or whatever you want in this repo (and disable all permissions), then you can prompt something like:

```
Hi have a look at program.md and let's kick off a new experiment! let's do the setup first.
```

The `program.md` file is essentially a super lightweight "skill".

## Project structure

```
prepare.py      — data download (1-min), backtesting (do not modify)
train.py        — model + trading logic (agent modifies this)
program.md      — agent instructions (emphasizes trading logic optimization)
pyproject.toml  — dependencies
```

## Design choices

- **Simple train/test split.** 70% training data, 30% test data (chronological). Test set is true out-of-sample (future data).
- **Fixed time budget.** Training runs for exactly 5 minutes, regardless of your specific platform. This means experiments are comparable regardless of what the agent changes (model size, batch size, etc). Expect ~5-10 min per experiment, or ~70+ experiments overnight.
- **1-minute candle data.** Uses high-resolution 1-min OHLCV data for realistic intraday trading. This is more granular than the original autoresearch (which used text data).
- **Trading logic focus.** The agent is guided to primarily modify trading parameters (position sizing, entry/exit rules, stop-loss, take-profit) rather than model architecture. In practice, these matter more for profitability.
- **Self-contained.** No external dependencies beyond PyTorch and a few small packages (ccxt for data, ta for indicators). One GPU (or CPU), one file to modify, one metric.

## What data is used?

By default, the system downloads EUR/USD, GBP/USD, and USD/JPY using 1-minute candles via the `ccxt` library (Binance as data source). The data spans approximately 2 years of historical OHLCV data (~1-2 million candles per pair).

**Note:** For demonstration purposes, the current implementation uses crypto pairs (EUR/USDT, GBP/USDT, BTC/USDT) as proxies for forex since they're easier to access. For production use with real forex data, you should integrate a proper forex broker API (e.g., OANDA, Interactive Brokers, or Alpha Vantage).

## Technical indicators

The `prepare.py` file automatically computes the following technical indicators as features:

- **Trend**: SMA (20, 50), EMA (12, 26), MACD
- **Momentum**: RSI (14), Stochastic Oscillator
- **Volatility**: Bollinger Bands, ATR
- **Price ratios**: Price/SMA ratios, log returns

The agent can select which indicators to use and adjust their parameters in `train.py`.

## Trading Logic Parameters

The agent can modify these parameters in `train.py` to optimize the strategy:

**Position sizing:**
- `POSITION_SIZING`: 'fixed', 'proportional', 'kelly'
- `MAX_POSITION`: Maximum position size (e.g., 1.0 = 100% of capital)

**Entry rules:**
- `ENTRY_THRESHOLD`: Minimum predicted return to enter (e.g., 0.001 = 0.1%)

**Exit rules:**
- `TAKE_PROFIT_PCT`: Take profit threshold (e.g., 0.02 = 2%)
- `STOP_LOSS_PCT`: Stop loss threshold (e.g., 0.01 = 1%)
- `USE_TRAILING_STOP`: Enable trailing stop
- `TRAILING_STOP_PCT`: Trailing stop percentage

**Risk management:**
- `MAX_DRAWDOWN_EXIT`: Exit all if drawdown exceeds this (e.g., 0.20 = 20%)
- `TRANSACTION_COST`: Transaction cost per trade (e.g., 0.001 = 0.1%)

## Evaluation metric

The primary metric is the **Calmar ratio** on the test set:

```
Calmar Ratio = Annualized Return / Maximum Drawdown
```

This is a risk-adjusted performance metric that penalizes strategies with high drawdowns. A higher Calmar ratio is better.

Additional metrics tracked:
- Sharpe ratio
- Total return (%)
- Maximum drawdown (%)
- Win rate (%)
- Number of trades

## Results Format

After running, you'll see output like:

```
============================================================
RESULTS
============================================================
Calmar ratio:     1.234567
Sharpe ratio:     1.500000
Total return:     15.50%
Max drawdown:     12.30%
Win rate:         55.00%
Num trades:       150
Final capital:    $11550.00
```

The agent tracks results in `results.tsv` with format:
```
commit	calmar_ratio	sharpe_ratio	max_dd_pct	status	description
```

## Adapting for other markets

To trade different assets:

1. **Stocks**: Change `SYMBOL` in `train.py` to a stock ticker, update `prepare.py` to use `yfinance` instead of `ccxt`
2. **Crypto native**: Already supported via `ccxt`, just change symbols in `prepare.py`
3. **Different timeframes**: Modify `TIMEFRAME` in `prepare.py` (e.g., '5m', '15m', '1h', '4h', '1d')
4. **Multiple pairs**: Extend the code to handle portfolio of pairs

## Platform support

This code works on both CUDA GPUs and CPU. GPU is recommended for faster training, especially with Transformer models. The code has been tested on:
- NVIDIA GPUs (CUDA)
- CPU (slower but functional)
- Apple Silicon (MPS) - should work but not extensively tested

## Notable forks

*None yet - be the first to create a fork!*

## License

MIT
