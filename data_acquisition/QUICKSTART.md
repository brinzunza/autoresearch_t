# Quick Start Guide - EUR/USD Data for Autoresearch

## TL;DR - Get EUR/USD data in 3 steps:

```bash
# Step 1: Run automated setup
./data_acquisition/setup_data.sh

# Step 2: Press Enter (uses EUR/USD default)
# Step 3: Wait 30-60 minutes for download to complete
```

That's it! Your data will be ready for training.

---

## What happens behind the scenes:

1. **Data Fetch** (`fetch_data.py`)
   - Connects to Polygon.io API with your key
   - Tests how far back you can access data (~2 years for free tier)
   - Downloads all 1-minute EUR/USD bars
   - Saves to: `data_acquisition/EURUSD_1min_YYYYMMDD_YYYYMMDD.csv`

2. **Data Preparation** (`prepare_polygon.py`)
   - Loads the CSV data
   - Adds technical indicators (RSI, MACD, Bollinger Bands, etc.)
   - Saves to training cache: `~/.cache/autotrade/data/EUR_USD_1m.parquet`

3. **Ready for Training**
   - Run: `python train.py`
   - The model will use your real EUR/USD data instead of proxy crypto data

---

## File Format

Polygon.io ticker format for forex pairs:
- **User-friendly:** `EUR/USD`, `EURUSD`
- **Polygon.io API:** `C:EURUSD` (scripts handle this automatically)
- **Saved filename:** `EURUSD_1min_YYYYMMDD_YYYYMMDD.csv`
- **Training data:** `EUR_USD_1m.parquet` (matches prepare.py convention)

---

## Common Issues

### Q: "No data found" error when preparing
**A:** Make sure you ran `fetch_data.py` first. Check that `data_acquisition/EURUSD_1min_latest.csv` exists.

### Q: Download is taking forever
**A:** This is normal! Free tier has 5 requests/minute limit. 2 years of data takes ~30-60 minutes.

### Q: API returns "403 Forbidden"
**A:** Your API key may be invalid or expired. Check your Polygon.io account.

### Q: "Rate limit exceeded"
**A:** Scripts automatically wait when hitting rate limits. Just let it run.

---

## Testing First (Optional)

Before downloading all data, test your API access:

```bash
python3 data_acquisition/test_access_limits.py
```

This will:
- Verify your API key works
- Find the earliest date you can access
- Save results to `access_limits.txt`
- Only takes ~2-3 minutes

---

## Manual Control

If you prefer step-by-step control:

```bash
# 1. Fetch raw data
python3 data_acquisition/fetch_data.py
# Enter: EUR/USD (or just press Enter)

# 2. Prepare for training
python3 data_acquisition/prepare_polygon.py --ticker EUR/USD

# 3. Train
python3 train.py
```

---

## Using Different Pairs

Want GBP/USD instead? Just enter it when prompted:

```bash
./data_acquisition/setup_data.sh
# Enter ticker symbol: GBP/USD
```

Or for stocks:

```bash
./data_acquisition/setup_data.sh
# Enter ticker symbol: AAPL
```

The scripts automatically detect if it's forex (6 letters) or stock ticker.

---

## Next Steps

Once data is downloaded and prepared:

1. **Verify data:**
   ```bash
   ls -lh ~/.cache/autotrade/data/
   # Should see EUR_USD_1m.parquet
   ```

2. **Start training:**
   ```bash
   python3 train.py
   ```

3. **Monitor progress:**
   The autoresearch system will optimize hyperparameters using your real EUR/USD data!
