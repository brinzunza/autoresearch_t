# autotrade

This is an experiment to have an AI agent autonomously improve algorithmic trading strategies.

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `apr11`). The branch `autotrade/<tag>` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b autotrade/<tag>` from current master.
3. **Read the in-scope files**: The repo is small. Read these files for full context:
   - `README.md` — repository context.
   - `prepare.py` — fixed data download (1-min candles), feature engineering, backtesting, evaluation. Do not modify.
   - `train.py` — the file you modify. **Focus on trading logic**, then features, minimal model changes.
4. **Verify data exists**: Check that `~/.cache/autotrade/` contains forex data (1-min candles, parquet files). If not, tell the human to run `uv run prepare.py`.
5. **Initialize results.tsv**: Create `results.tsv` with just the header row. The baseline will be recorded after the first run.
6. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

Each experiment trains a trading strategy model on a training set and evaluates on a test set. Model training uses a **fixed 5-minute time budget**. The full experiment takes ~5-10 minutes total.

**What you CAN do (in priority order):**

1. **TRADING LOGIC (PRIMARY FOCUS)**:
   - Position sizing: `POSITION_SIZING` ('fixed', 'proportional', 'kelly'), `MAX_POSITION`
   - Entry rules: `ENTRY_THRESHOLD` (minimum prediction confidence)
   - Exit rules: `TAKE_PROFIT_PCT`, `STOP_LOSS_PCT`, `USE_TRAILING_STOP`, `TRAILING_STOP_PCT`
   - Risk management: `MAX_DRAWDOWN_EXIT`, `TRANSACTION_COST`

2. **FEATURE ENGINEERING (moderate changes)**:
   - Which indicators to use: `USE_INDICATORS` list
   - Indicator parameters: `RSI_PERIOD`, `MACD_FAST/SLOW`, `SMA_SHORT/LONG`, etc.
   - Lookback window: `LOOKBACK_MINUTES`
   - Forecast horizon: `FORECAST_HORIZON_MINUTES`

3. **MODEL ARCHITECTURE (minimal changes)**:
   - Model type: `MODEL_TYPE` ("LSTM" or "Transformer")
   - Hidden dim, layers, dropout (keep simple)

**What you CANNOT do:**
- Modify `prepare.py`. It is read-only. It contains the fixed data download, backtesting engine, and evaluation.
- Install new packages or add dependencies. You can only use what's already in `pyproject.toml`.
- Modify the core evaluation logic.

**The goal is simple: get the highest Calmar ratio on the test set.** The Calmar ratio is annualized return divided by maximum drawdown — it measures risk-adjusted performance. Higher is better.

Since training is 5 minutes, experiments are fast. Your main leverage is in **trading logic** (how to enter/exit trades, position sizing, risk management) and **feature selection** (which indicators help predict returns).

**Simplicity criterion**: All else being equal, simpler is better. Prefer changes that improve Calmar ratio without adding complexity.

**The first run**: Your very first run should always be to establish the baseline, so you will run the training script as is.

## Output format

Once the script finishes it prints a summary like this:

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

---
calmar_ratio:     1.234567
sharpe_ratio:     1.500000
total_return_pct: 15.50
max_drawdown_pct: 12.30
win_rate_pct:     55.00
num_trades:       150
training_seconds: 300.0
model_type:       LSTM
position_sizing:  proportional
entry_threshold:  0.001
take_profit:      0.02
stop_loss:        0.01
```

You can extract the key metric from the log file:

```
grep "^calmar_ratio:" run.log
```

## Logging results

When an experiment is done, log it to `results.tsv` (tab-separated, NOT comma-separated — commas break in descriptions).

The TSV has a header row and 6 columns:

```
commit	calmar_ratio	sharpe_ratio	max_dd_pct	status	description
```

1. git commit hash (short, 7 chars)
2. Calmar ratio (e.g. 1.234567) — use 0.000000 for crashes
3. Sharpe ratio (e.g. 1.500000) — use 0.000000 for crashes
4. Max drawdown as percentage (e.g. 12.3) — use 0.0 for crashes
5. status: `keep`, `discard`, or `crash`
6. short text description of what this experiment tried

Example:

```
commit	calmar_ratio	sharpe_ratio	max_dd_pct	status	description
a1b2c3d	1.234567	1.500000	12.3	keep	baseline: proportional sizing + 2% TP
b2c3d4e	1.456789	1.650000	11.2	keep	added RSI filter (entry_threshold=0.002)
c3d4e5f	1.623456	1.800000	10.1	keep	Kelly criterion + trailing stop 0.5%
d4e5f6g	0.987654	1.200000	15.5	discard	removed stop-loss (worse DD)
e5f6g7h	0.000000	0.000000	0.0	crash	changed LOOKBACK to 300 (OOM)
```

## The experiment loop

The experiment runs on a dedicated branch (e.g. `autotrade/apr11`).

LOOP FOREVER:

1. Look at the git state: the current branch/commit we're on
2. Tune `train.py` with an experimental idea by directly hacking the code
   - **Prioritize trading logic changes** (position sizing, entry/exit rules, risk management)
   - Then try feature engineering
   - Minimize model architecture changes
3. git commit
4. Run the experiment: `uv run train.py > run.log 2>&1` (redirect everything — do NOT use tee or let output flood your context)
5. Read out the results: `grep "^calmar_ratio:\|^sharpe_ratio:\|^max_drawdown_pct:" run.log`
6. If the grep output is empty, the run crashed. Run `tail -n 100 run.log` to read the Python stack trace and attempt a fix. If you can't get things to work after more than a few attempts, give up and move on.
7. Record the results in the tsv (NOTE: do not commit the results.tsv file, leave it untracked by git)
8. If average Calmar ratio improved (higher), you "advance" the branch, keeping the git commit
9. If average Calmar ratio is equal or worse, you git reset back to where you started

The idea is that you are a completely autonomous researcher trying things out. If they work, keep. If they don't, discard. And you're advancing the branch so that you can iterate.

**Timeout**: Each experiment should take ~5-10 minutes (5 min training + backtesting). If a run exceeds 15 minutes, kill it and treat it as a failure (discard and revert).

**Crashes**: If a run crashes (OOM, or a bug, or etc.), use your judgment: If it's something dumb and easy to fix (e.g. a typo, a missing import), fix it and re-run. If the idea itself is fundamentally broken, just skip it, log "crash" as the status in the tsv, and move on.

**NEVER STOP**: Once the experiment loop has begun (after the initial setup), do NOT pause to ask the human if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep, or gone from a computer and expects you to continue working *indefinitely* until you are manually stopped. You are autonomous. If you run out of ideas, think harder — see the ideas section below. The loop runs until the human interrupts you, period.

As an example use case, a user might leave you running overnight. If each experiment takes ~7 minutes then you can run approx 70 experiments over 8 hours. The user then wakes up to experimental results!

## Strategy improvement ideas (in priority order)

### 1. Trading Logic (PRIMARY FOCUS)

**Position sizing:**
- Try 'fixed' (always same size), 'proportional' (scale by prediction), 'kelly' (Kelly criterion)
- Adjust `MAX_POSITION` (0.5 = 50%, 1.0 = 100%, 0.25 = 25%)
- Consider prediction confidence threshold

**Entry rules:**
- Vary `ENTRY_THRESHOLD` (0.0001 to 0.01)
- Add RSI filters (only enter if RSI between 30-70)
- Add trend filters (only enter if price > SMA_50)
- Combine multiple signal confirmations

**Exit rules:**
- Optimize `TAKE_PROFIT_PCT` (0.01 to 0.05)
- Optimize `STOP_LOSS_PCT` (0.005 to 0.02)
- Try `USE_TRAILING_STOP` = True with different `TRAILING_STOP_PCT`
- Time-based exits (close position after N minutes)
- Opposite signal exits (close long if prediction turns negative)

**Risk management:**
- Enable `MAX_DRAWDOWN_EXIT` (e.g., 0.15 = 15%)
- Add `TRANSACTION_COST` for realism (e.g., 0.001 = 0.1% per trade)
- Adjust position size based on recent volatility (ATR)

### 2. Feature Engineering (moderate changes)

**Indicator selection:**
- Remove redundant/correlated indicators from `USE_INDICATORS`
- Add combinations (e.g., RSI * MACD_diff)
- Focus on proven indicators (RSI, MACD, BB, ATR)

**Indicator parameters:**
- Try different RSI periods (9, 14, 21)
- Try different MACD settings (fast/slow)
- Try different SMA windows (10/30, 20/50, 50/200)

**Time horizons:**
- Vary `LOOKBACK_MINUTES` (30, 60, 120, 240)
- Vary `FORECAST_HORIZON_MINUTES` (5, 15, 30, 60)
- Match horizon to trading timeframe

### 3. Model Architecture (minimal changes)

- Try "Transformer" vs "LSTM"
- Adjust `HIDDEN_DIM` (64, 128, 256)
- Adjust `NUM_LAYERS` (1, 2, 3)
- Keep it simple — complex models often overfit

## Important notes

- **Focus on trading logic**: In practice, entry/exit rules matter more than model architecture
- **Avoid overfitting**: The test set is out-of-sample (future data). Don't tune excessively to training performance.
- **Transaction costs matter**: Even 0.1% per trade can kill a high-frequency strategy
- **Risk-adjusted returns**: Calmar ratio balances returns with drawdown - a 30% return with 5% DD beats 50% return with 40% DD
