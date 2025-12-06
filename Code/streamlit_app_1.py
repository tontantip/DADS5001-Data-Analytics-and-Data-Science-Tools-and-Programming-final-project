# streamlit_app.py
import os
import streamlit as st
import pandas as pd
import numpy as np
import duckdb
from datetime import datetime
import time
import random
import plotly.graph_objects as go
con = duckdb.connect("ai_result.db")
ai_result = con.execute("select * from ai_result").df()
con.close()

## import index stock
con = duckdb.connect("index_stock.db")
index_stock = con.execute("select * from index_stock_data").df()
con.close()

ai_result["final_score"] = (((ai_result["ai_fin_score"]*0.5)+(ai_result["ai_price_score"]*0.35)+(ai_result["ai_envi_score"]*0.15))/2)

comb = duckdb.sql("""select * 
                  from index_stock as id left join ai_result as ar
                  on  id.symbol = ar.symbol
                  """).df()


con = duckdb.connect('my_stock_data.db')

news_data_soure = con.execute("select * from stock_news").df()
#table = con.execute("SHOW TABLES").df()
con.close()


st.set_page_config(
    page_title="US Stock Screener",
    page_icon="🇺🇸",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("AI-Powered Stock Ranker 🥇")

# Sector emoji mapping
SECTOR_EMOJI = {
    'Information Technology': '💻',
    'Health Care': '🏥',
    'Financials': '💰',
    'Consumer Discretionary': '🛍️',
    'Communication Services': '📡',
    'Industrials': '🏭',
    'Consumer Staples': '🛒',
    'Energy': '⚡',
    'Utilities': '💡',
    'Real Estate': '🏢',
    'Materials': '⚒️'
}

def add_sector_emoji(sector):
    """Add emoji prefix to sector name"""
    if pd.isna(sector) or sector == '':
        return sector
    emoji = SECTOR_EMOJI.get(str(sector), '📊')
    return f"{emoji} {sector}"

# Choose CSV: prefer provided final_score file
CSV_FILE = 'final_score(in).csv'
if not os.path.exists(CSV_FILE):
    CSV_FILE = 'index_stock.csv'

# Load data
df = comb.copy()

# Ensure final_score exists; create sensible fallback
if 'final_score' not in df.columns:
    df['final_score'] = 0.0

if 'ai_comment' not in df.columns:
    if 'Investment_Signal' in df.columns:
        df['ai_comment'] = df['Investment_Signal']
    elif 'Market_Regime' in df.columns:
        df['ai_comment'] = df['Market_Regime']
    else:
        df['ai_comment'] = ''

# Function to create star rating display
def score_to_stars(score):
    if pd.isna(score):
        return "N/A"
    # Assuming score is 0-5 scale
    full_stars = int(score)
    half_star = 1 if (score - full_stars) >= 0.5 else 0
    empty_stars = 5 - full_stars - half_star
    
    # Use Unicode characters that support color better
    filled = '⭐' * full_stars  # Star emoji (naturally yellow)
    half = '✨' if half_star else ''  # Sparkles for half (visually distinct)
    empty = '☆' * empty_stars  # Empty star outline
    
    stars_line = filled + half + empty
    return f"{score:.2f}<br>{stars_line}"

# Top 20 by final_score (descending)
st.header("🌟 Top 20 Stocks")
try:
    top_20 = df.sort_values(by='final_score', ascending=False).head(20)[['symbol', 'security', 'gics_sector', 'final_score', 'ai_comment']].copy()
except Exception:
    # If column selection fails, ensure columns exist then reselect
    for c in ['symbol', 'security', 'gics_sector', 'final_score', 'ai_comment']:
        if c not in df.columns:
            df[c] = ''
    top_20 = df.sort_values(by='final_score', ascending=False).head(20)[['symbol', 'security', 'gics_sector', 'final_score', 'ai_comment']].copy()

# Rename for display
top_20.columns = ['Symbol', 'Stock Name', 'Sector', 'final_score', 'ai_comment']

# Add emoji to sector names
top_20['Sector'] = top_20['Sector'].apply(add_sector_emoji)

# Create score with stars
top_20['score_with_stars'] = top_20['final_score'].apply(score_to_stars)

# build values in column order
values_top20 = [
    list(range(1, len(top_20) + 1)),
    top_20['Symbol'].tolist(),
    top_20['Stock Name'].tolist(),
    top_20['Sector'].tolist(),
    top_20['score_with_stars'].tolist(),
    top_20['ai_comment'].tolist(),
]

fig_top20 = go.Figure(data=[go.Table(
    columnorder=[1,2,3,4,5,6],
    columnwidth=[40,80,220,160,90,1100],
    header=dict(
        values=[['<b>#</b>'], ['<b>SYMBOL</b>'], ['<b>STOCK NAME</b>'], ['<b>SECTOR</b>'], ['<b>FINAL SCORE</b>'], ['<b>AI COMMENT</b>']],
        line_color='darkslategray',
        fill_color='royalblue',
        align=['center','left','left','left','center','left'],
        font=dict(color='white', size=12),
        height=40
    ),
    cells=dict(
        values=values_top20,
        line_color='darkslategray',
        fill=dict(color=['paleturquoise', 'white']),
        align=['center','left','left','left','center','left'],
        font=dict(color='black', size=12),
        height=30
    )
)])
fig_top20.update_layout(height=800)
st.plotly_chart(fig_top20, use_container_width=True)

# Sector selector + Top 5 in sector
st.divider()
st.header("🌟 Top 5 Stocks by Sector")
sectors = sorted(df['gics_sector'].dropna().unique()) if 'gics_sector' in df.columns else ['All']
sectors_with_emoji = ['All'] + [add_sector_emoji(s) for s in sectors if s != 'All']
selected_sector_display = st.selectbox("Select a Sector:", sectors_with_emoji, index=0, key='sector_top5')

# Get the actual sector name (without emoji)
if selected_sector_display == 'All':
    selected_sector = 'All'
else:
    # Remove emoji prefix
    selected_sector = selected_sector_display.split(' ', 1)[1] if ' ' in selected_sector_display else selected_sector_display

if selected_sector == 'All':
    sector_data = df
else:
    sector_data = df[df['gics_sector'] == selected_sector]

try:
    top_5 = sector_data.sort_values(by='final_score', ascending=False).head(5)[['symbol', 'security', 'gics_sector', 'final_score', 'ai_comment']].copy()
except Exception:
    for c in ['symbol', 'security', 'gics_sector', 'final_score', 'ai_comment']:
        if c not in sector_data.columns:
            sector_data[c] = ''
    top_5 = sector_data.sort_values(by='final_score', ascending=False).head(5)[['symbol', 'security', 'gics_sector', 'final_score', 'ai_comment']].copy()

top_5.columns = ['Symbol', 'Stock Name', 'Sector', 'final_score', 'ai_comment']

# Add emoji to sector names
top_5['Sector'] = top_5['Sector'].apply(add_sector_emoji)

# Create score with stars
top_5['score_with_stars'] = top_5['final_score'].apply(score_to_stars)

col1, col2, col3 = st.columns(3)
with col1:
    st.metric('Selected Sector', selected_sector)
with col2:
    st.metric('Stocks in Sector', len(sector_data))
with col3:
    # Show average final_score for the selected sector (avoid using marketcap)
    avg_score = sector_data['final_score'].mean() if len(sector_data) > 0 else float('nan')
    if np.isnan(avg_score):
        st.metric('Avg final_score', 'N/A')
    else:
        st.metric('Avg final_score', f"{avg_score:.3f}")


values_top5 = [
    list(range(1, len(top_5) + 1)),
    top_5['Symbol'].tolist(),
    top_5['Stock Name'].tolist(),
    top_5['Sector'].tolist(),
    top_5['score_with_stars'].tolist(),
    top_5['ai_comment'].tolist(),
]

fig_top5 = go.Figure(data=[go.Table(
    columnorder=[1,2,3,4,5,6],
    columnwidth=[40,80,220,160,90,1100],
    header=dict(
        values=[['<b>#</b>'], ['<b>SYMBOL</b>'], ['<b>STOCK NAME</b>'], ['<b>SECTOR</b>'], ['<b>FINAL SCORE</b>'], ['<b>AI COMMENT</b>']],
        line_color='darkslategray',
        fill_color='royalblue',
        align=['center','left','left','left','center','left'],
        font=dict(color='white', size=12),
        height=40
    ),
    cells=dict(
        values=values_top5,
        line_color='darkslategray',
        fill=dict(color=['paleturquoise', 'white']),
        align=['center','left','left','left','center','left'],
        font=dict(color='black', size=12),
        height=25
    )
 )])
fig_top5.update_layout(height=500)
st.plotly_chart(fig_top5, use_container_width=True)
st.divider()

# ============================
# ฟังก์ชันโหลด parquet + cache
# ============================
@st.cache_data(show_spinner=False)
def load_parquet_from_gdrive(file_id):
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    con = duckdb.connect()
    return con.execute(f"SELECT * FROM read_parquet('{url}')").df()


# ============================
# ฟังก์ชันสร้าง ALL1 (feature dataset)
# ============================
@st.cache_data(show_spinner=False)
def build_all1(stock_price, stock_ticker, macro_indicators_m, stock_financials_quarterly):
    # copy กัน side-effect
    stock_price = stock_price.copy()
    stock_ticker = stock_ticker.copy()
    macro_indicators_m = macro_indicators_m.copy()
    stock_financials_quarterly = stock_financials_quarterly.copy()

    # =====================================================
    # 1) daily → quarterly (price / volume)
    # =====================================================
    stock_price["Date"] = pd.to_datetime(stock_price["Date"])
    stock_price = stock_price.sort_values(["tickers", "Date"])

    stock_price["quarter"] = stock_price["Date"].dt.to_period("Q")

    g = stock_price.groupby(["tickers", "quarter"])

    quarterly = g.agg(
        open_q     = ("Price_Open",  "first"),
        high_q     = ("Price_High",  "max"),
        low_q      = ("Price_Low",   "min"),
        close_q    = ("Price_Close", "last"),
        vol_sum_q  = ("Volume",      "sum"),
        vol_mean_q = ("Volume",      "mean"),
        days_q     = ("Date",        "nunique"),
    ).reset_index()

    quarterly["year"] = quarterly["quarter"].dt.year
    quarterly["q"]    = quarterly["quarter"].dt.quarter

    # =====================================================
    # 1.1 meta จาก stock_ticker (sector / sub-industry)
    # =====================================================
    stock_meta = stock_ticker[["symbol", "gics_sector", "gics_sub-industry"]].drop_duplicates()

    quarterly = quarterly.merge(
        stock_meta,
        left_on="tickers",
        right_on="symbol",
        how="left"
    )

    quarterly = quarterly.drop(columns=["symbol"])

    # =====================================================
    # 2) return ของไตรมาสปัจจุบัน + feature จาก price/volume
    # =====================================================
    quarterly["ret_q"] = (quarterly["close_q"] / quarterly["open_q"]) - 1

    # ---------- Candle structure ----------
    quarterly["body_q"] = (quarterly["close_q"] - quarterly["open_q"]).abs()
    quarterly["dir_q"]  = np.where(quarterly["close_q"] >= quarterly["open_q"], 1, -1)

    quarterly["upper_shadow_q"] = quarterly["high_q"] - quarterly[["open_q", "close_q"]].max(axis=1)
    quarterly["lower_shadow_q"] = quarterly[["open_q", "close_q"]].min(axis=1) - quarterly["low_q"]
    quarterly["range_q"]        = (quarterly["high_q"] - quarterly["low_q"]) / quarterly["open_q"]

    # ---------- Volatility / body volatility ----------
    quarterly["volatility_q"] = (quarterly["high_q"] - quarterly["low_q"]) / quarterly["close_q"]
    quarterly["body_vol_q"]   = quarterly["body_q"] / quarterly["open_q"]

    # ---------- Price strength ----------
    quarterly["close_to_high_q"] = (
        (quarterly["close_q"] - quarterly["low_q"]) /
        (quarterly["high_q"] - quarterly["low_q"] + 1e-9)
    )
    quarterly["close_to_open_q"] = (quarterly["close_q"] - quarterly["open_q"]) / quarterly["open_q"]

    # ---------- Momentum ----------
    group_t = quarterly.groupby("tickers")

    quarterly["ret_last_1q"] = group_t["ret_q"].shift(1)
    quarterly["ret_last_2q"] = group_t["ret_q"].shift(2)
    quarterly["momentum_accel"] = quarterly["ret_last_1q"] - quarterly["ret_last_2q"]

    # ---------- Rolling price stats ----------
    quarterly["roll_close_mean_3q"] = group_t["close_q"].transform(lambda x: x.rolling(3).mean())
    quarterly["roll_close_std_3q"]  = group_t["close_q"].transform(lambda x: x.rolling(3).std())

    # ---------- Volume dynamics ----------
    quarterly["vol_std_3q"] = group_t["vol_mean_q"].transform(lambda x: x.rolling(3).std())
    quarterly["vol_mom_q"]  = quarterly["vol_mean_q"] / group_t["vol_mean_q"].shift(1)
    quarterly["vol_pressure_q"] = quarterly["vol_sum_q"] / (quarterly["close_q"] + 1e-9)

    # =====================================================
    # 3) Target: mult_next_q
    # =====================================================
    quarterly["close_next_q"] = group_t["close_q"].shift(-1)
    quarterly["mult_next_q"]  = quarterly["close_next_q"] / quarterly["close_q"]
    quarterly["ret_next_q"]   = quarterly["mult_next_q"] - 1

    quarterly = quarterly.dropna(subset=["mult_next_q"]).copy()

    # =====================================================
    # 4) Cross-features จาก price+volume
    # =====================================================
    quarterly["cf_vol_mom_x_close_high"]   = quarterly["vol_mom_q"] * quarterly["close_to_high_q"]
    quarterly["cf_vol_pressure_x_dir"]     = quarterly["vol_pressure_q"] * quarterly["dir_q"]
    quarterly["cf_volatility_x_vol_std"]   = quarterly["volatility_q"] * quarterly["vol_std_3q"]
    quarterly["cf_range_x_roll_std"]       = quarterly["range_q"] * quarterly["roll_close_std_3q"]

    quarterly["cf_mom1_x_strength"]        = quarterly["ret_last_1q"] * quarterly["close_to_high_q"]
    quarterly["cf_momaccel_x_vol"]         = quarterly["momentum_accel"] * quarterly["volatility_q"]

    quarterly["cf_body_x_volmom_x_dir"]    = quarterly["body_q"] * quarterly["vol_mom_q"] * quarterly["dir_q"]
    quarterly["cf_strength_x_volpressure"] = quarterly["close_to_high_q"] * quarterly["vol_pressure_q"]

    # เคลียร์รอบแรก
    quarterly = quarterly.replace([np.inf, -np.inf], 0).fillna(0)

    # =====================================================
    # 5) macro_indicators_m: monthly → quarterly แล้ว merge
    # =====================================================
    macro = macro_indicators_m.copy()
    macro["date"] = pd.to_datetime(macro["date"])

    macro["year"] = macro["date"].dt.year
    macro["q"]    = macro["date"].dt.quarter

    macro_q = macro[macro["date"].dt.month.isin([3, 6, 9, 12])].copy()

    macro_cols = [c for c in macro_q.columns if c not in ["date", "year", "q"]]
    macro_q = macro_q[["year", "q"] + macro_cols]

    quarterly = quarterly.merge(
        macro_q,
        on=["year", "q"],
        how="left"
    )

    # =====================================================
    # 5.1 stock_financials_quarterly → quarterly แล้ว merge
    # =====================================================
    fin = stock_financials_quarterly.copy()

    fin["end_date"] = pd.to_datetime(fin["end_date"])
    fin["year"] = fin["end_date"].dt.year
    fin["q"]    = fin["end_date"].dt.quarter

    fin = fin.rename(columns={"ticker": "tickers"})

    fin_feature_cols = [
        "revenue",
        "cost_of_revenue",
        "gross_profit",
        "operating_income",
        "income_tax_expense",
        "net_income",
        "eps_basic",
        "eps_diluted",
        "assets",
        "liabilities",
        "equity",
        "current_assets",
        "current_liabilities",
        "operating_cashflow",
        "cf_investing",
        "cf_financing",
    ]

    fin = fin[["tickers", "year", "q"] + fin_feature_cols]

    quarterly = quarterly.merge(
        fin,
        on=["tickers", "year", "q"],
        how="left"
    )

    # =====================================================
    # 5.2 Momentum & rolling ของ "งบการเงิน"
    # =====================================================
    group_f = quarterly.groupby("tickers")

    fin_momentum_cols = []

    for col in fin_feature_cols:
        lag_col        = f"{col}_last_1q"        # ค่าไตรมาสก่อนหน้า
        qoq_col        = f"{col}_qoq"            # QoQ growth (col / lag - 1)
        roll_mean_col  = f"{col}_roll_mean_4q"   # rolling mean 4 ไตรมาส (ประมาณ 1 ปี)
        roll_std_col   = f"{col}_roll_std_4q"    # rolling std 4 ไตรมาส

        quarterly[lag_col]       = group_f[col].shift(1)
        quarterly[qoq_col]       = (quarterly[col] / quarterly[lag_col]) - 1
        quarterly[roll_mean_col] = group_f[col].transform(lambda x: x.rolling(4).mean())
        quarterly[roll_std_col]  = group_f[col].transform(lambda x: x.rolling(4).std())

        fin_momentum_cols.extend([lag_col, qoq_col, roll_mean_col, roll_std_col])

    # เคลียร์ค่า inf / NaN ของงบ (base + momentum)
    quarterly[fin_feature_cols + fin_momentum_cols] = (
        quarterly[fin_feature_cols + fin_momentum_cols]
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
    )

    # =====================================================
    # 6) รวมชื่อฟีเจอร์ทั้งหมด
    # =====================================================
    feature_cols = [
        # ----- price-volume base -----
        "open_q", "high_q", "low_q", "close_q",
        "vol_sum_q", "vol_mean_q", "days_q",
        "ret_q",

        # ----- candle / volatility / strength -----
        "body_q", "dir_q", "upper_shadow_q", "lower_shadow_q",
        "range_q", "volatility_q", "body_vol_q",
        "close_to_high_q", "close_to_open_q",

        # ----- momentum & rolling (price) -----
        "ret_last_1q", "ret_last_2q", "momentum_accel",
        "roll_close_mean_3q", "roll_close_std_3q",

        # ----- volume dynamics -----
        "vol_std_3q", "vol_mom_q", "vol_pressure_q",

        # ----- cross-features -----
        "cf_vol_mom_x_close_high",
        "cf_vol_pressure_x_dir",
        "cf_volatility_x_vol_std",
        "cf_range_x_roll_std",
        "cf_mom1_x_strength",
        "cf_momaccel_x_vol",
        "cf_body_x_volmom_x_dir",
        "cf_strength_x_volpressure",
    ]

    feature_macro_cols    = macro_cols
    feature_fin_base_cols = fin_feature_cols
    feature_fin_mom_cols  = fin_momentum_cols
    feature_fin_all_cols  = feature_fin_base_cols + feature_fin_mom_cols

    all_feature_cols = feature_cols + feature_macro_cols + feature_fin_all_cols

    id_cols = ["tickers", "year", "q", "gics_sector", "gics_sub-industry"]
    target_col = "mult_next_q"

    ALL1 = quarterly[id_cols + all_feature_cols + [target_col]].copy()

    return ALL1


stock_ticker = load_parquet_from_gdrive("1Bd-WwzSp3wTHq30DUtnZQkzBSMyeFZp0")
macro_indicators_m = load_parquet_from_gdrive("1zWEOdbO-dPf6C4iQHgYPXffBrbu_XjiT")
stock_price = load_parquet_from_gdrive("1Xg2UkYQVhBBOnZGxWM0bVUoFNy2gQp4K")
stock_financials_quarterly = load_parquet_from_gdrive("1L3QlfcA3_y4XtR0RBXHsbdlfWO-WmRQe")
stock_news = load_parquet_from_gdrive("1s2qCI530GqZ1XC7fyWKZQSloX2HPgmj9")
ALL1 = build_all1(stock_price, stock_ticker, macro_indicators_m, stock_financials_quarterly)

st.header("📈 Stock Price Trend")

# Three filters in one line
col_sector, col_ticker, col_period = st.columns(3)

with col_sector:
    sectors_list = [str(s) for s in ALL1['gics_sector'].dropna().unique() if s]
    sectors_with_emoji = ['All'] + [add_sector_emoji(s) for s in sorted(sectors_list)]
    selected_sector_display = st.selectbox("Select Sector:", sectors_with_emoji, key='candlestick_sector')
    
    # Get the actual sector name (without emoji)
    if selected_sector_display == 'All':
        selected_sector_candle = 'All'
    else:
        selected_sector_candle = selected_sector_display.split(' ', 1)[1] if ' ' in selected_sector_display else selected_sector_display

# Filter tickers by sector
if selected_sector_candle == 'All':
    filtered_data = ALL1
else:
    filtered_data = ALL1[ALL1['gics_sector'] == selected_sector_candle]

with col_ticker:
    available_tickers = sorted(filtered_data['tickers'].unique())
    selected_ticker = st.selectbox("Select a Stock Ticker:", available_tickers, key='candlestick_ticker')

with col_period:
    period_options = ['7D', '1M', '3M', '6M', '1Y', 'Max']
    selected_period = st.selectbox("Select Period:", period_options, index=4, key='candlestick_period')

# Get daily price data for selected ticker
ticker_price_data = stock_price[stock_price['tickers'] == selected_ticker].copy()
ticker_price_data['Date'] = pd.to_datetime(ticker_price_data['Date'])
ticker_price_data = ticker_price_data.sort_values('Date')

# Filter by selected period
if selected_period != 'Max' and len(ticker_price_data) > 0:
    cutoff_date = ticker_price_data['Date'].max()
    if selected_period == '7D':
        cutoff_date = cutoff_date - pd.Timedelta(days=7)
    elif selected_period == '1M':
        cutoff_date = cutoff_date - pd.Timedelta(days=30)
    elif selected_period == '3M':
        cutoff_date = cutoff_date - pd.Timedelta(days=90)
    elif selected_period == '6M':
        cutoff_date = cutoff_date - pd.Timedelta(days=180)
    elif selected_period == '1Y':
        cutoff_date = cutoff_date - pd.Timedelta(days=365)
    
    ticker_price_data = ticker_price_data[ticker_price_data['Date'] >= cutoff_date]

# Create candlestick chart
if len(ticker_price_data) > 0:
    fig_candle = go.Figure(data=[go.Candlestick(
        x=ticker_price_data['Date'],
        open=ticker_price_data['Price_Open'],
        high=ticker_price_data['Price_High'],
        low=ticker_price_data['Price_Low'],
        close=ticker_price_data['Price_Close'],
        name=selected_ticker
    )])
    
    fig_candle.update_layout(
        title=f"{selected_ticker} Price Movement ({selected_period})",
        xaxis_title="Date",
        yaxis_title="Price ($)",
        xaxis_rangeslider_visible=False,
        xaxis=dict(
            rangebreaks=[
                dict(bounds=["sat", "mon"]),  # Hide weekends
                # Hide US market holidays (2025)
                dict(values=["2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", 
                           "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-11-28", "2025-12-25"])
            ]
        ),
        height=600
    )
    
    st.plotly_chart(fig_candle, use_container_width=True)
    
    # Display some stats
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Latest Close", f"${ticker_price_data['Price_Close'].iloc[-1]:.2f}")
    with col2:
        st.metric("Latest Open", f"${ticker_price_data['Price_Open'].iloc[-1]:.2f}")
    with col3:
        st.metric("Period High", f"${ticker_price_data['Price_High'].max():.2f}")
    with col4:
        st.metric("Period Low", f"${ticker_price_data['Price_Low'].min():.2f}")
else:
    st.warning("No data available for the selected ticker.")


# ============================
# RANDOM STOCK NEWS
# ============================
st.divider()

news_data = news_data_soure
st.title("📰 What’s Happening Now")

if len(news_data) > 0:
    # Create a placeholder for the news content
    news_placeholder = st.empty()

    while True:
        # Select 3 random news items
        random_indices = random.sample(range(len(news_data)), min(3, len(news_data)))
        
        # Update the placeholder with 3 cards in one row
        with news_placeholder.container():
            cols = st.columns(3)
            
            for idx, col in enumerate(cols):
                if idx < len(random_indices):
                    news_idx = random_indices[idx]
                    title = news_data["title"][news_idx]
                    description = news_data["description"][news_idx]
                    url = news_data["url"][news_idx] if "url" in news_data.columns else "#"
                    source = news_data["source"][news_idx] if "source" in news_data.columns else "News"
                    time_ago = news_data["time"][news_idx] if "time" in news_data.columns else "Recently"
                    
                    with col:
                        st.markdown(f"""
                            <div style='border: 1px solid #ddd; border-radius: 8px; padding: 15px; height: 280px; background-color: #1e1e1e; display: flex; flex-direction: column;'>
                                <div style='margin-bottom: 8px;'>
                                    <span style='font-size: 12px; color: #888;'>{source} · {time_ago}</span>
                                </div>
                                <a href='{url}' target='_blank' style='text-decoration: none; color: inherit;'>
                                    <h3 style='margin: 0; font-size: 16px; color: #fff; font-weight: 600; line-height: 1.3;'>{title[:80]}...</h3>
                                </a>
                                <p style='margin-top: 8px; font-size: 13px; color: #ccc; flex-grow: 1; overflow: hidden;'>{description[:100]}...</p>
                                <div style='margin-top: 10px;'>
                                    <a href='{url}' target='_blank' style='color: #1a73e8; text-decoration: none; font-size: 13px;'>Read more →</a>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)
            
            st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")
        
        # Wait for 30 seconds
        time.sleep(30)
else:
    st.write("No news data found.")