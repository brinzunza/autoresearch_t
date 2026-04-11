# Data Acquisition from Polygon.io

This folder contains scripts to fetch 1-minute bar data from Polygon.io for use with autoresearch.

## Scripts

### 1. `test_access_limits.py`
Tests how far back you can access historical data with your API key (free tier typically allows ~2 years).

**Usage:**
```bash
python data_acquisition/test_access_limits.py
```

**Output:**
- Displays earliest accessible date
- Saves results to `access_limits.txt`

### 2. `fetch_data.py`
Fetches all available 1-minute bar data for a given ticker symbol and saves it to CSV.

**Usage:**
```bash
python data_acquisition/fetch_data.py
```

**Interactive prompts:**
- Enter ticker symbol (default: AAPL)
- Confirms date range before fetching
- Shows progress during download

**Output:**
- CSV file: `{TICKER}_1min_{START_DATE}_{END_DATE}.csv`
- Symlink: `{TICKER}_1min_latest.csv` (always points to most recent data)

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

1. **Test access limits (optional):**
   ```bash
   python data_acquisition/test_access_limits.py
   ```

2. **Fetch data:**
   ```bash
   python data_acquisition/fetch_data.py
   ```
   - Enter ticker when prompted (e.g., AAPL, TSLA, SPY)
   - Confirm to start download
   - Wait for completion

3. **Use with autoresearch:**
   The data will be saved in CSV format ready for use with your training pipeline.

## Notes

- Free tier typically provides 2 years of historical data
- Data is fetched in 7-day chunks to avoid API limits
- Weekends are automatically skipped
- Progress is displayed during fetching
- Failed requests are automatically retried
