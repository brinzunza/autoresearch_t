"""
Autotrade strategy training script with walk-forward analysis.
Trains an LSTM/Transformer to predict forex returns, then backtests with realistic trading logic.
Usage: uv run train.py
"""

import os
import gc
import math
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F

from prepare import (
    TIME_BUDGET, DATA_DIR,
    prepare_features, create_train_test_split,
    create_sequences, fit_scaler, evaluate_strategy
)

# ---------------------------------------------------------------------------
# Trading Strategy Models (Keep simple - minimal changes by agent)
# ---------------------------------------------------------------------------

class LSTMStrategy(nn.Module):
    """LSTM-based trading strategy."""

    def __init__(self, input_dim, hidden_dim=128, num_layers=2, dropout=0.2):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_dim, hidden_dim,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True
        )

        self.fc = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, 1)
        )

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        last_out = lstm_out[:, -1, :]
        return self.fc(last_out)


class TransformerStrategy(nn.Module):
    """Transformer-based trading strategy."""

    def __init__(self, input_dim, d_model=128, nhead=4, num_layers=2, dropout=0.2):
        super().__init__()
        self.input_dim = input_dim
        self.d_model = d_model

        self.input_proj = nn.Linear(input_dim, d_model)
        self.pos_encoder = PositionalEncoding(d_model, dropout)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=d_model * 4,
            dropout=dropout,
            batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

        self.fc = nn.Sequential(
            nn.Linear(d_model, d_model // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, 1)
        )

    def forward(self, x):
        x = self.input_proj(x)
        x = self.pos_encoder(x)
        mask = nn.Transformer.generate_square_subsequent_mask(x.size(1)).to(x.device)
        x = self.transformer(x, mask=mask, is_causal=True)
        last_out = x[:, -1, :]
        return self.fc(last_out)


class PositionalEncoding(nn.Module):
    def __init__(self, d_model, dropout=0.1, max_len=5000):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)
        self.register_buffer('pe', pe)

    def forward(self, x):
        x = x + self.pe[:, :x.size(1), :]
        return self.dropout(x)


# ---------------------------------------------------------------------------
# HYPERPARAMETERS - AGENT FOCUS AREAS
# ---------------------------------------------------------------------------

# ===== MODEL ARCHITECTURE (minimal changes) =====
MODEL_TYPE = "LSTM"  # "LSTM" or "Transformer"
HIDDEN_DIM = 128
NUM_LAYERS = 2
DROPOUT = 0.2
NHEAD = 4  # For Transformer only

# ===== FEATURE ENGINEERING (moderate changes) =====
LOOKBACK_MINUTES = 60  # Look back 60 minutes (1 hour)
FORECAST_HORIZON_MINUTES = 15  # Predict 15 minutes ahead

# Technical indicator parameters
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
SMA_SHORT = 20
SMA_LONG = 50
BB_WINDOW = 20
ATR_WINDOW = 14

# Feature selection (stationary features only)
USE_INDICATORS = [
    'returns', 'log_returns',
    'macd', 'macd_signal', 'macd_diff',
    'rsi', 'stoch_k', 'stoch_d',
    'bb_width', 'atr',
    f'price_to_sma{SMA_SHORT}', f'price_to_sma{SMA_LONG}',
]

# ===== TRADING LOGIC (PRIMARY FOCUS - heavy modifications) =====

# Position sizing strategy
POSITION_SIZING = 'proportional'  # 'fixed', 'proportional', 'kelly'
MAX_POSITION = 1.0  # Max 100% of capital in any position

# Entry rules
ENTRY_THRESHOLD = 0.0002  # Min abs(predicted_return) to enter (0.02%)

# Exit rules
TAKE_PROFIT_PCT = 0.02  # 2% take profit
STOP_LOSS_PCT = 0.01  # 1% stop loss
USE_TRAILING_STOP = False
TRAILING_STOP_PCT = 0.005  # 0.5% trailing stop

# ===== RISK MANAGEMENT (moderate changes) =====
MAX_DRAWDOWN_EXIT = None  # Exit all if drawdown exceeds this (e.g., 0.20 = 20%)
TRANSACTION_COST = 0.0  # Transaction cost per trade (e.g., 0.001 = 0.1%)

# ===== TRAINING PARAMETERS (minimal changes) =====
BATCH_SIZE = 128
LEARNING_RATE = 0.005
WEIGHT_DECAY = 0.0001

# Data
SYMBOL = 'EUR/USD'


# ---------------------------------------------------------------------------
# Training and Evaluation
# ---------------------------------------------------------------------------

def train_model(model, optimizer, scheduler, X_train, y_train, time_budget=TIME_BUDGET):
    """Train model for fixed time budget."""
    device = next(model.parameters()).device
    model.train()
    criterion = nn.SmoothL1Loss()  # More robust than MSE for financial data

    t_start = time.time()
    total_time = 0
    step = 0

    n_samples = X_train.shape[0]

    print(f"Training model on {device}...")
    while True:
        t0 = time.time()

        # Training epoch
        epoch_loss = 0
        indices = torch.randperm(n_samples)

        for i in range(0, n_samples, BATCH_SIZE):
            batch_indices = indices[i:i + BATCH_SIZE]
            X_batch = X_train[batch_indices].to(device)
            y_batch = y_train[batch_indices].to(device)

            predictions = model(X_batch).squeeze()
            loss = criterion(predictions, y_batch)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()

        scheduler.step()

        torch.cuda.synchronize() if torch.cuda.is_available() else None
        t1 = time.time()
        dt = t1 - t0

        # Only count after warmup
        if step > 2:
            total_time += dt

        avg_loss = epoch_loss / ((n_samples + BATCH_SIZE - 1) // BATCH_SIZE)
        lr = optimizer.param_groups[0]['lr']
        pct_done = 100 * min(total_time / time_budget, 1.0)

        print(f"\rStep {step:03d} ({pct_done:.0f}%) | loss: {avg_loss:.6f} | lr: {lr:.6f}", end="", flush=True)

        # Fast fail
        if math.isnan(avg_loss) or avg_loss > 100:
            print("\nFAIL: Loss exploded")
            exit(1)

        step += 1

        if step > 2 and total_time >= time_budget:
            break

    print()  # Newline
    return total_time


def run_training():
    """Train on train set and evaluate on test set."""

    print(f"Loading data for {SYMBOL}...")

    # Load and prepare features
    df = prepare_features(
        SYMBOL,
        rsi_period=RSI_PERIOD,
        macd_fast=MACD_FAST,
        macd_slow=MACD_SLOW,
        sma_short=SMA_SHORT,
        sma_long=SMA_LONG,
        bb_window=BB_WINDOW,
        atr_window=ATR_WINDOW
    )

    if df is None:
        print(f"ERROR: Could not load data for {SYMBOL}")
        print("Run 'uv run prepare.py' first to download data")
        exit(1)

    # Filter features based on USE_INDICATORS
    available_features = [col for col in df.columns
                         if col not in ['timestamp', 'close', 'open', 'high', 'low', 'volume']]
    feature_cols = [f for f in USE_INDICATORS if f in available_features]

    if len(feature_cols) == 0:
        print("ERROR: No valid features selected")
        exit(1)

    n_features = len(feature_cols)
    print(f"Using {n_features} features: {', '.join(feature_cols[:5])}{'...' if len(feature_cols) > 5 else ''}")

    # Create train/test split
    train_df, test_df = create_train_test_split(df)
    print(f"Data split - Train: {len(train_df):,} samples, Test: {len(test_df):,} samples")
    print()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    print()

    # Fit scaler on training data
    scaler = fit_scaler(train_df, feature_cols)

    # Scale features
    train_df_scaled = train_df.copy()
    test_df_scaled = test_df.copy()
    train_df_scaled[feature_cols] = scaler.transform(train_df[feature_cols])
    test_df_scaled[feature_cols] = scaler.transform(test_df[feature_cols])

    # Create sequences
    print("Creating sequences...")
    X_train, y_train, _ = create_sequences(
        train_df_scaled, feature_cols,
        lookback=LOOKBACK_MINUTES,
        horizon=FORECAST_HORIZON_MINUTES
    )
    X_test, y_test, prices_test = create_sequences(
        test_df_scaled, feature_cols,
        lookback=LOOKBACK_MINUTES,
        horizon=FORECAST_HORIZON_MINUTES
    )

    print(f"Sequences - Train: {X_train.shape}, Test: {X_test.shape}")
    print()

    # Move to device
    X_train = torch.FloatTensor(X_train).to(device)
    y_train = torch.FloatTensor(y_train).to(device)

    # Create model
    print(f"Building {MODEL_TYPE} model...")
    if MODEL_TYPE == "LSTM":
        model = LSTMStrategy(n_features, HIDDEN_DIM, NUM_LAYERS, DROPOUT)
    elif MODEL_TYPE == "Transformer":
        model = TransformerStrategy(n_features, HIDDEN_DIM, NHEAD, NUM_LAYERS, DROPOUT)
    else:
        raise ValueError(f"Unknown model type: {MODEL_TYPE}")

    model = model.to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {n_params:,}")
    print()

    # Optimizer and scheduler
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=int(TIME_BUDGET / 0.5), eta_min=LEARNING_RATE * 0.1
    )

    # Train
    training_time = train_model(model, optimizer, scheduler, X_train, y_train)

    # Backtest on test set
    print()
    print("Backtesting on test set...")

    backtest_params = {
        'initial_capital': 10000,
        'position_sizing': POSITION_SIZING,
        'max_position': MAX_POSITION,
        'entry_threshold': ENTRY_THRESHOLD,
        'take_profit_pct': TAKE_PROFIT_PCT,
        'stop_loss_pct': STOP_LOSS_PCT,
        'use_trailing_stop': USE_TRAILING_STOP,
        'trailing_stop_pct': TRAILING_STOP_PCT,
        'max_drawdown_exit': MAX_DRAWDOWN_EXIT,
        'transaction_cost': TRANSACTION_COST,
    }

    calmar_ratio, results = evaluate_strategy(model, X_test, y_test, prices_test, **backtest_params)

    # Final summary
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Calmar ratio:     {results['calmar_ratio']:.6f}")
    print(f"Sharpe ratio:     {results['sharpe_ratio']:.6f}")
    print(f"Total return:     {results['total_return']:.2f}%")
    print(f"Max drawdown:     {results['max_drawdown']:.2f}%")
    print(f"Win rate:         {results['win_rate']:.2f}%")
    print(f"Num trades:       {results['num_trades']}")
    print(f"Final capital:    ${results['final_capital']:.2f}")
    print()

    # Final summary for results.tsv
    print("---")
    print(f"calmar_ratio:     {results['calmar_ratio']:.6f}")
    print(f"sharpe_ratio:     {results['sharpe_ratio']:.6f}")
    print(f"total_return_pct: {results['total_return']:.2f}")
    print(f"max_drawdown_pct: {results['max_drawdown']:.2f}")
    print(f"win_rate_pct:     {results['win_rate']:.2f}")
    print(f"num_trades:       {results['num_trades']}")
    print(f"training_seconds: {training_time:.1f}")
    print(f"num_params:       {n_params:,}")
    print(f"model_type:       {MODEL_TYPE}")
    print(f"position_sizing:  {POSITION_SIZING}")
    print(f"entry_threshold:  {ENTRY_THRESHOLD}")
    print(f"take_profit:      {TAKE_PROFIT_PCT if TAKE_PROFIT_PCT else 'None'}")
    print(f"stop_loss:        {STOP_LOSS_PCT if STOP_LOSS_PCT else 'None'}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    torch.manual_seed(42)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(42)

    t_start = time.time()

    run_training()

    t_end = time.time()
    print(f"total_seconds:  {t_end - t_start:.1f}")
