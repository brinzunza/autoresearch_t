# Data Acquisition from Polygon.io

This folder contains scripts to fetch 1-minute bar data from Polygon.io for use with autoresearch.

**Primary use case:** Fetching EUR/USD forex data to match the autoresearch training pipeline.

## Scripts

### 1. `test_access_limits.py`
Tests how far back you can access historical data with your API key (free tier typically allows ~2 years).

**Usage:**
```bash
python3 data_acquisition/test_access_limits.py
```

**Output:**
- Displays earliest accessible date
- Saves results to `access_limits.txt`

### 2. `fetch_data.py`
Fetches all available 1-minute bar data for a given ticker symbol and saves it to CSV.

**Usage:**
```bash
python3 data_acquisition/fetch_data.py
```

**Interactive prompts:**
- Enter ticker symbol (default: EUR/USD)
  - Forex: `EUR/USD`, `EURUSD`, `GBP/USD`, etc.
  - Stocks: `AAPL`, `TSLA`, `SPY`, etc.
- Confirms date range before fetching
- Shows progress during download

**Output:**
- CSV file: `EURUSD_1min_{START_DATE}_{END_DATE}.csv`
- Symlink: `EURUSD_1min_latest.csv` (always points to most recent data)

## Data Format

The CSV files contain the following columns:
- `timestamp`: Date and time of the bar
- `open`: Opening price
- `high`: Highest price
- `low`: Lowest price
- `close`: Closing price
- `volume`: Trading volume
- `vwap`: Volume-weighted average price
- `transactions`: Number of transactions

## API Rate Limits

Polygon.io free tier limits:
- 5 API requests per minute
- Scripts automatically handle rate limiting with delays
- Typical download time for 2 years of data: ~30-60 minutes

## Example Workflow

### For EUR/USD (recommended for autoresearch):

1. **Automated setup (easiest):**
   ```bash
   ./data_acquisition/setup_data.sh
   ```
   - Just press Enter to use EUR/USD default
   - Follow prompts

2. **Manual setup:**

   a. **Test access limits (optional):**
   ```bash
   python3 data_acquisition/test_access_limits.py
   ```

   b. **Fetch data:**
   ```bash
   python3 data_acquisition/fetch_data.py
   ```
   - Press Enter to use EUR/USD default
   - Confirm to start download (~30-60 minutes)

   c. **Prepare for training:**
   ```bash
   python3 data_acquisition/prepare_polygon.py --ticker EUR/USD
   ```

   d. **Train:**
   ```bash
   python3 train.py
   ```

### For other pairs/stocks:

Follow the same steps but enter your desired ticker when prompted:
- Forex examples: `GBP/USD`, `USD/JPY`, `GBPUSD`
- Stock examples: `AAPL`, `TSLA`, `SPY`

## Notes

- Free tier typically provides 2 years of historical data
- Data is fetched in 7-day chunks to avoid API limits
- Weekends are automatically skipped
- Progress is displayed during fetching
- Failed requests are automatically retried
