import pandas as pd
import numpy as np
import duckdb
con = duckdb.connect("my_stock_data.db", read_only=True)

df_price = con.execute("SELECT * FROM stock_price").df()


df_financials = con.execute("SELECT * FROM stock_financials").df()

con.close()

data_price = df_price
data_fin = df_financials

# แปลงวันที่ + ทำให้ชื่อคอลัมน์ตรงกัน
data_price['Date'] = pd.to_datetime(df_price['Date'])
data_fin['end_date'] = pd.to_datetime(data_fin['end_date'])
data_price = df_price.rename(columns={'tickers': 'ticker'})

# =================================================================
# 2. สรุปข้อมูลราคา → รับประกันทุกหุ้นจะมีคอลัมน์ครบ!
# =================================================================
def summarize_price(group):
    g = group.sort_values('Date').copy()
    ticker = g['ticker'].iloc[0] if 'ticker' in g.columns else g.index[0]

    # ค่าเริ่มต้น
    result = {
        'ticker': ticker,
        'latest_price': np.nan,
        'latest_date': 'N/A',
        'total_return_10y': np.nan,
        'cagr_10y': 0.0,
        'volatility': np.nan,
        'momentum_12m': 0.0,
        'trading_days': len(g)
    }

    if len(g) < 2:
        return pd.Series(result)

    latest = g.iloc[-1]
    first = g.iloc[0]

    result['latest_price'] = latest['Price_Close']
    result['latest_date'] = str(latest['Date'].date())

    # Total return & CAGR
    if first['Price_Close'] > 0:
        total_ret = latest['Price_Close'] / first['Price_Close'] - 1
        years = (g['Date'].max() - g['Date'].min()).days / 365.25
        result['total_return_10y'] = total_ret
        result['cagr_10y'] = (latest['Price_Close'] / first['Price_Close']) ** (1/max(years, 0.1)) - 1 if years > 0 else 0

    # Volatility
    ret = g['Price_Close'].pct_change().dropna()
    if len(ret) > 10:
        result['volatility'] = ret.std() * np.sqrt(252)

    # Momentum 12m
    if len(g) >= 252:
        result['momentum_12m'] = latest['Price_Close'] / g['Price_Close'].iloc[-252] - 1
    elif len(g) >= 100:
        result['momentum_12m'] = latest['Price_Close'] / g['Price_Close'].iloc[-100] - 1

    return pd.Series(result)

# รันแล้วรับประกันทุกคอลัมน์มี!
price_summary = data_price.groupby('ticker', group_keys=False).apply(summarize_price).reset_index(drop=True)
