import pandas as pd
import numpy as np

df = pd.read_csv('data_acquisition/data_acquisition/EURUSD_1min_20240412_20260410.csv')
horizon = 15
# Calculate horizon returns
df['future_price'] = df['close'].shift(-horizon)
df['returns'] = (df['future_price'] - df['close']) / df['close']
abs_returns = df['returns'].abs().dropna()

print(f"Mean abs return (15m): {abs_returns.mean():.6f}")
print(f"Max abs return (15m):  {abs_returns.max():.6f}")
print(f"Std abs return (15m):  {abs_returns.std():.6f}")
print(f"Percent of returns > 0.001: {(abs_returns > 0.001).mean()*100:.2f}%")
print(f"Percent of returns > 0.0001: {(abs_returns > 0.0001).mean()*100:.2f}%")
