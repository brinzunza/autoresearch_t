#!/bin/bash
# Automated data acquisition and preparation for autoresearch using Polygon.io

set -e  # Exit on error

echo "=============================================================================="
echo "AUTORESEARCH POLYGON.IO DATA SETUP"
echo "=============================================================================="
echo ""

# Get ticker from user
read -p "Enter ticker symbol (default: AAPL): " TICKER
TICKER=${TICKER:-AAPL}

echo ""
echo "Using ticker: $TICKER"
echo ""

# Step 1: Test access limits (optional)
read -p "Test data access limits first? (y/n, default: n): " TEST_LIMITS
TEST_LIMITS=${TEST_LIMITS:-n}

if [[ "$TEST_LIMITS" == "y" ]]; then
    echo ""
    echo "=============================================================================="
    echo "Step 1: Testing data access limits..."
    echo "=============================================================================="
    python data_acquisition/test_access_limits.py
    echo ""
    read -p "Press Enter to continue with data fetch..."
fi

# Step 2: Fetch data
echo ""
echo "=============================================================================="
echo "Step 2: Fetching 1-minute data from Polygon.io..."
echo "=============================================================================="
echo ""
echo "This will:"
echo "  - Find the earliest accessible date for your API tier"
echo "  - Download all available 1-minute bars"
echo "  - Save to data_acquisition/${TICKER}_1min_YYYYMMDD_YYYYMMDD.csv"
echo ""
echo "NOTE: This may take 30-60 minutes due to API rate limits (5 requests/min)"
echo ""
read -p "Proceed? (yes/no): " PROCEED

if [[ "$PROCEED" != "yes" ]]; then
    echo "Cancelled."
    exit 0
fi

# Run fetch script with ticker pre-filled
echo "$TICKER" | python data_acquisition/fetch_data.py

# Step 3: Prepare data for autoresearch
echo ""
echo "=============================================================================="
echo "Step 3: Preparing data for autoresearch training..."
echo "=============================================================================="
python data_acquisition/prepare_polygon.py --ticker "$TICKER"

# Step 4: Done
echo ""
echo "=============================================================================="
echo "SETUP COMPLETE!"
echo "=============================================================================="
echo ""
echo "Your data is ready for training. You can now run:"
echo ""
echo "  python train.py"
echo ""
echo "Or specify this symbol explicitly:"
echo ""
echo "  python train.py --symbols ${TICKER}"
echo ""
