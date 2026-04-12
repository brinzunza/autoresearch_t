# Data Fetching Strategy - Technical Documentation

## Overview

The improved `fetch_data_v2.py` implements an intelligent data acquisition strategy optimized for Polygon.io's API constraints and forex market characteristics.

---

## Key Improvements Over v1

### 1. **Binary Search for Earliest Date** (Previously: Linear Search)

**Old Approach (v1):**
```python
# Tested specific dates: 1 month, 3 months, 6 months, 1 year, 2 years
# Required: 5-6 API calls
# Inefficient for finding exact boundary
```

**New Approach (v2):**
```python
# Binary search algorithm
# Search space: 5 years = 1,825 days
# API calls needed: log2(1825) ≈ 11 calls
# Finds EXACT earliest accessible date
```

**How it works:**
1. Set search bounds: `left = 5 years ago`, `right = yesterday`
2. Test midpoint: `mid = left + (right - left) / 2`
3. If data exists at mid → try earlier (move right to mid)
4. If no data at mid → try later (move left to mid)
5. Repeat until convergence

**Example for 2 years of access:**
```
Attempt 1: Test 2.5 years ago → No data → Move left forward
Attempt 2: Test 1.25 years ago → Data exists → Move right backward
Attempt 3: Test 1.875 years ago → Data exists → Move right backward
Attempt 4: Test 2.1875 years ago → No data → Move left forward
...
Converges to: ~730 days (2 years) in ~11 API calls
```

---

## 2. **Optimal Batch Sizing** (Previously: Fixed 7-day chunks)

### Understanding Polygon.io Limits

**API Constraint:**
- Maximum bars per request: **50,000**
- Rate limit: **5 requests/minute** (free tier)

### Calculating Optimal Batch Size

**For Forex (24/5 trading):**
```
Minutes per day: 1440 (24 hours × 60 minutes)
Trading days per week: 5 (Mon-Fri)
Minutes per week: 1440 × 5 = 7,200

To get ~50,000 bars:
50,000 ÷ 7,200 = ~6.94 weeks ≈ 49 days

Optimal batch: 49 days
```

**For Stocks (6.5 hours/day):**
```
Trading hours: 9:30 AM - 4:00 PM ET = 6.5 hours
Minutes per day: 390 (6.5 × 60)

To get ~50,000 bars:
50,000 ÷ 390 = ~128 days

Optimal batch: 128 days
```

### Why This Matters

**Old v1 approach (7-day chunks):**
```
For 2 years of EUR/USD data:
- Total days: 730
- Batches needed: 730 ÷ 7 = 104 batches
- API calls: 104
- Time: 104 × 13s = 1,352s ≈ 23 minutes
- Bars per request: ~10,080 (only 20% of limit!)
```

**New v2 approach (49-day chunks):**
```
For 2 years of EUR/USD data:
- Total days: 730
- Batches needed: 730 ÷ 49 = 15 batches
- API calls: 15
- Time: 15 × 13s = 195s ≈ 3 minutes
- Bars per request: ~48,000 (96% of limit!)
```

**Result: 87% reduction in API calls and fetch time!**

---

## 3. **Fetch Direction: Oldest to Newest**

**Why fetch from oldest to newest?**

1. **Historical completeness:** Start with foundation data
2. **Error recovery:** If interrupted, have oldest (most important) data
3. **Logical ordering:** Natural chronological progression
4. **Easier debugging:** Can verify data continuity

**Implementation:**
```python
current_date = start_date  # Start at EARLIEST
while current_date <= end_date:
    batch_end = min(current_date + timedelta(days=batch_days), end_date)
    fetch_bars(current_date, batch_end)  # Fetch this chunk
    current_date = batch_end + 1  # Move forward in time
```

---

## 4. **Batch Merging and Deduplication**

### The Problem

When fetching overlapping or adjacent time ranges, we may get:
- **Duplicate bars** (same timestamp fetched twice)
- **Out-of-order bars** (if batches fetched in parallel)
- **Missing bars** (gaps between batches)

### Our Solution

#### Step 1: Collect All Batches
```python
all_batches = [
    {'bars': [...], 'start': date1, 'end': date2, 'count': 48000},
    {'bars': [...], 'start': date2, 'end': date3, 'count': 47500},
    ...
]
```

#### Step 2: Concatenate
```python
all_bars = []
for batch in all_batches:
    all_bars.extend(batch['bars'])  # Combine all bars into single list

# At this point: may have duplicates, may be unsorted
```

#### Step 3: Convert to DataFrame
```python
df = pd.DataFrame(all_bars)
df['timestamp'] = pd.to_datetime(df['t'], unit='ms')

# Before: List of dicts with unix timestamps
# After: DataFrame with datetime index
```

#### Step 4: Sort by Timestamp
```python
df = df.sort_values('timestamp').reset_index(drop=True)

# Ensures chronological order regardless of fetch order
```

#### Step 5: Remove Duplicates
```python
initial_count = len(df)
df = df.drop_duplicates(subset=['timestamp'], keep='first')
duplicates_removed = initial_count - len(df)

# Keeps first occurrence of each timestamp
# Removes any redundant bars from overlapping requests
```

### Example of Deduplication

**Scenario:** Batches have 1-minute overlap

```
Batch 1: 2024-01-01 00:00 to 2024-02-19 23:59
Batch 2: 2024-02-19 23:59 to 2024-04-09 23:58  ← Overlap at 2024-02-19 23:59

Before dedup:
  2024-02-19 23:57  → 1.08455
  2024-02-19 23:58  → 1.08456
  2024-02-19 23:59  → 1.08457  ← From Batch 1
  2024-02-19 23:59  → 1.08457  ← From Batch 2 (DUPLICATE)
  2024-02-20 00:00  → 1.08458

After dedup:
  2024-02-19 23:57  → 1.08455
  2024-02-19 23:58  → 1.08456
  2024-02-19 23:59  → 1.08457  ← Single instance
  2024-02-20 00:00  → 1.08458
```

---

## 5. **Data Quality Verification**

After merging, we verify data quality:

### A. Timestamp Coverage
```python
print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
# Expected: Matches requested start_date to end_date
```

### B. Gap Detection
```python
time_diffs = df['timestamp'].diff()  # Time between consecutive bars
expected_diff = pd.Timedelta(minutes=1)

large_gaps = time_diffs[time_diffs > pd.Timedelta(hours=72)]  # >3 days
```

**Normal gaps:**
- Weekends (Sat-Sun): ~48 hours
- Holidays: Varies

**Abnormal gaps:**
- >1 week: May indicate missing data
- Random large gaps: API issues

### C. Bar Count Validation
```python
expected_bars = calculate_expected_bars(start_date, end_date, is_forex=True)
actual_bars = len(df)
coverage = actual_bars / expected_bars * 100

print(f"Data coverage: {coverage:.1f}%")
# For forex: Expect ~95-98% (accounting for holidays)
```

---

## Complete Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. BINARY SEARCH FOR EARLIEST DATE                         │
│    Input: Max search range (5 years)                        │
│    Output: Earliest accessible date (e.g., 2022-04-12)     │
│    API Calls: ~11                                           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. CALCULATE OPTIMAL BATCH SIZE                             │
│    For forex: 49 days (~48,000 bars)                        │
│    For stocks: 128 days (~50,000 bars)                      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. FETCH BATCHES (Oldest → Newest)                          │
│    Batch 1: 2022-04-12 to 2022-05-31 (49 days) → 48,234 bars│
│    Batch 2: 2022-06-01 to 2022-07-20 (49 days) → 47,891 bars│
│    ...                                                       │
│    Batch 15: 2024-03-15 to 2024-04-11 (27 days) → 27,104 bars│
│    API Calls: 15                                            │
│    Time: ~3 minutes                                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. MERGE ALL BATCHES                                        │
│    all_bars = batch1 + batch2 + ... + batch15               │
│    Total bars: 726,543                                      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. CONVERT TO DATAFRAME                                     │
│    - Parse timestamps (ms → datetime)                       │
│    - Rename columns (t→timestamp, c→close, etc.)            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. SORT BY TIMESTAMP                                        │
│    Ensure chronological order                               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. REMOVE DUPLICATES                                        │
│    Before: 726,543 bars                                     │
│    After: 725,891 bars (652 duplicates removed)             │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 8. VERIFY DATA QUALITY                                      │
│    ✓ Date coverage: 2022-04-12 to 2024-04-11               │
│    ✓ No unexpected gaps                                     │
│    ✓ Bar count: 725,891 (expected: ~730,000)               │
│    ✓ Coverage: 99.4%                                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 9. SAVE TO FILES                                            │
│    - EURUSD_1min_20220412_20240411.csv (main data)         │
│    - EURUSD_1min_20220412_20240411_metadata.json           │
│    - EURUSD_1min_latest.csv (symlink)                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Performance Comparison

| Metric | Old (v1) | New (v2) | Improvement |
|--------|----------|----------|-------------|
| Find earliest date | Linear search (6 calls) | Binary search (11 calls) | More thorough |
| Batch size | 7 days | 49 days | 7x larger |
| API calls for 2 years | ~104 | ~15 | 87% reduction |
| Fetch time | ~23 min | ~3 min | 87% faster |
| Bars per request | ~10,000 | ~48,000 | 4.8x efficiency |
| Deduplication | Manual | Automatic | More reliable |
| Gap detection | None | Automatic | Better quality |
| Metadata | None | JSON file | More info |

---

## Usage

```bash
# Run the improved version
python3 data_acquisition/fetch_data_v2.py

# Enter ticker (default: EUR/USD)
# Script will:
# 1. Binary search for earliest date (~11 API calls, ~2 min)
# 2. Calculate optimal batching
# 3. Fetch data (~15 API calls, ~3 min)
# 4. Merge and deduplicate
# 5. Verify quality
# 6. Save with metadata

# Total time: ~5 minutes (vs 25 minutes with v1)
```

---

## Edge Cases Handled

1. **Weekends/Holidays:** Skipped automatically during binary search
2. **API Rate Limits:** 13-second delay between requests
3. **Network Errors:** Retry logic with exponential backoff
4. **Partial Data:** Continues fetching even if some batches fail
5. **Duplicates:** Removed during merge phase
6. **Large Gaps:** Detected and reported in verification
7. **Boundary Conditions:** Start/end dates aligned to trading days

---

## Future Enhancements

1. **Resume capability:** Save progress, resume if interrupted
2. **Parallel fetching:** Multiple tickers concurrently
3. **Incremental updates:** Only fetch new data since last run
4. **Compression:** GZIP CSV files to save disk space
5. **Database storage:** Option to store in SQLite/PostgreSQL
