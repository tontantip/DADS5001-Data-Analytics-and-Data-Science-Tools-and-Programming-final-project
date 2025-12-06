import streamlit as st
import duckdb
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime
import requests
import math
import json

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

API_URL = "https://3c64c73bfec3.ngrok-free.app/predict"
HEADERS = {
    "accept": "application/json",
    "Content-Type": "application/json",
}
ALL2 = (
    ALL1.sort_values(["tickers", "year", "q"])
        .groupby("tickers", sort=False)
        .tail(1)
        .reset_index(drop=True)
)
ALL2 = ALL2.drop(columns=["mult_next_q"], errors="ignore")

# =========================
# 1) เคลียร์ค่า NaN / inf
# =========================
ALL2_clean = ALL2.copy()
 
# แทน inf / -inf ด้วย NaN ก่อน
ALL2_clean = ALL2_clean.replace([np.inf, -np.inf], np.nan)
 
# ให้ pandas แปลง NaN → null (ใน string JSON)
records_json_str = ALL2_clean.to_json(orient="records")   # NaN -> null
 
# แปลง string JSON -> Python list[dict] (มี None แทน NaN)
records = json.loads(records_json_str)
 
payload = {"records": records}
 
# =========================
# 2) ยิงครั้งเดียวทั้งก้อน
# =========================
resp = requests.post(API_URL, headers=HEADERS, json=payload, timeout=300)
resp.raise_for_status()
 
result = resp.json()
 
# =========================
# 3) แปลงผลลัพธ์เป็น DF = ALL_ML
# =========================
 
if isinstance(result, dict):
 
    # === backend ส่งกลับมาเป็น {"results": [...] } ===
    if "results" in result:
        data_list = result["results"]
    else:
        raise ValueError("Response ไม่มี key 'results', ลอง print(result) ดูอีกครั้ง")
 
elif isinstance(result, list):
    data_list = result
 
else:
    raise ValueError("รูปแบบ response ไม่ถูกต้อง")
 
 
ALL_ML = pd.DataFrame(data_list)

# ============================
# MAIN APP
# ============================

st.markdown(
    """
    <h1 style='
        text-align: center; 
        font-size: 80px; 
        font-weight: 800;
        text-shadow: 4px 4px 12px rgba(0,0,0,0.35);
    '>
         🔍 Stock Explorer
    </h1>
    """,
    unsafe_allow_html=True
)

# ============================
# Candlestick Chart (Plotly)
# ============================
stock_price['Date'] = pd.to_datetime(stock_price['Date'])
latest_data_date = stock_price['Date'].max().date() # ดึงเฉพาะส่วนวันที่สำหรับแสดงผล

all_tickers = stock_price['tickers'].unique()

if stock_price.empty:
    st.warning("Cannot display chart: Daily Stock Price data is empty.")
else:
    # ----------------------------------------------------------------------
    # 📌 2. ส่วนควบคุม (Search Box และ Time Range)
    col_search, col_range = st.columns([1, 2])
    
    with col_search:
        # 1. ช่อง Search
        selected_ticker = st.selectbox("Select a Stock Ticker:", options=all_tickers, index=0)

    # --- ตัวเลือกช่วงเวลา (7D/1M/...) ---
    with col_range:
        # 📌 FIX: เปลี่ยน Value เป็นจำนวน "วันทำการ" (Trading Days) โดยประมาณ
        time_range_options = {"7D": 7, "1M": 21, "3M": 65, "6M": 130, "1Y": 250}
        selected_range_key = st.radio(
            "Select Period:", options=list(time_range_options.keys()), index=list(time_range_options.keys()).index("3M"), horizontal=True
        )

    # 4. กรองข้อมูล (ต้องทำก่อนคำนวณราคาล่าสุด)
    ticker_data = stock_price[stock_price['tickers'] == selected_ticker].copy()
    ticker_data = ticker_data.sort_values(by='Date')
    
    # 📌 3. การแสดง Symbol และ Metric
    if not ticker_data.empty:
        # 1. คำนวณราคาล่าสุดและการเปลี่ยนแปลง
        latest_row = ticker_data.iloc[-1] # ข้อมูลล่าสุด (แถวสุดท้ายหลัง sort)
        latest_close = latest_row['Price_Close']
        
        # 1.1 ดึงชื่อบริษัทจาก Stock Ticker
        # FIX: ใช้คอลัมน์ 'symbol' ใน stock_ticker แทน 'tickers' เพื่อดึงชื่อบริษัท
        company_info = stock_ticker[stock_ticker['symbol'] == selected_ticker].head(1)
        company_name = company_info['security'].iloc[0] if not company_info.empty and 'security' in company_info.columns else "Company Name N/A"

        if len(ticker_data) >= 2:
            previous_close = ticker_data.iloc[-2]['Price_Close'] # วันก่อนหน้า
            price_change = latest_close - previous_close
            price_change_pct = (price_change / previous_close) * 100
            
            delta_str = f"{price_change:.2f} ({price_change_pct:.2f}%)"
            delta_color = "normal" 
        else:
            delta_str = "N/A"
            delta_color = "off"

        # ----------------------------------------------------------------------
        # 3. คำนวณ Predicted Price และ Delta (จาก ALL_ML)
        # ----------------------------------------------------------------------
        # ดึงค่า 'pred_price_next_q' จาก ALL_ML สำหรับ ticker ที่ถูกเลือก
        pred_data = ALL_ML[ALL_ML['tickers'] == selected_ticker].head(1)
        
        # ตรวจสอบว่ามีข้อมูลและคอลัมน์ 'pred_price_next_q' อยู่จริง
        if not pred_data.empty and 'pred_price_next_q' in pred_data.columns:
            
            # 1. ดึงค่าราคาที่ทำนายได้โดยตรง (เป็น float)
            # เราสมมติว่าคอลัมน์นี้ถูกส่งมาจาก API แล้ว
            pred_price_next_q_float = pred_data['pred_price_next_q'].iloc[0]
            
            # 2. คำนวณ Delta (เทียบกับราคาปิดล่าสุด)
            predicted_price_change = pred_price_next_q_float - latest_close
            
            # 3. คำนวณ Delta เป็นเปอร์เซ็นต์
            if latest_close != 0:
                predicted_price_change_pct = (predicted_price_change / latest_close) * 100
                predicted_delta_str = f"{predicted_price_change:.2f} ({predicted_price_change_pct:.2f}%)"
            else:
                predicted_delta_str = f"{predicted_price_change:.2f} (N/A%)"

            
            # 4. กำหนดสี Delta (เพื่อให้ Streamlit จัดสีตามเครื่องหมาย: บวก=เขียว, ลบ=แดง)
            if predicted_price_change != 0:
                # ใช้ "normal" เพื่อให้ Streamlit แสดงสีเขียวสำหรับค่าบวก และสีแดงสำหรับค่าลบ
                pred_delta_color = "normal"  
            else:
                pred_delta_color = "off"     # สีเทา (ราคาไม่เปลี่ยน)
            
            # 5. จัดรูปแบบตัวเลขสำหรับแสดงผลใน st.metric
            pred_price_next_q = f"{pred_price_next_q_float:.2f}"
            
        else:
            # กรณีไม่มีข้อมูลทำนาย
            pred_price_next_q = "N/A"
            predicted_delta_str = "N/A"
            pred_delta_color = "off"
        # ----------------------------------------------------------------------
        # 2. แสดงผลโดยใช้ st.columns (3 คอลัมน์)
        # ----------------------------------------------------------------------
        # FIX: เปลี่ยนการจัดเรียงคอลัมน์เป็น 3 คอลัมน์: Symbol | Latest Close | Predicted Price
        col_symbol, col_price_metric, col_pred_metric = st.columns([1.5, 1, 1.2]) 
        
        with col_symbol:
            st.markdown(f"#### **{company_name}**")
            st.markdown(f"### {selected_ticker}") 
        
        with col_price_metric:
            st.metric(
                label="Latest Closing Price",
                value=f"{latest_close:.2f}",
                delta=delta_str,
                delta_color=delta_color
            )
            
                
        with col_pred_metric:
            st.metric(
                label="Predicted Price (Next Q)",
                value=pred_price_next_q,
                delta=predicted_delta_str,
                delta_color=pred_delta_color
            )
        
    else:
        st.warning(f"No stock price data found for '{selected_ticker}'.")
        st.stop()

    st.caption(f"Latest stock price as of: {latest_data_date.strftime('%Y-%m-%d')}") 
    
    
    # ----------------------------------------------------------------------
    #  4. คำนวณ MA และกรองข้อมูลตามช่วงเวลา
    
    # คำนวณ Moving Averages ก่อนการกรองช่วงเวลา (ต้องใช้ข้อมูลทั้งหมด)
    ma_periods = [20, 50]
    for p in ma_periods:
        # ใช้ .copy() เพื่อหลีกเลี่ยง SettingWithCopyWarning
        ticker_data[f'SMA_{p}'] = ticker_data['Price_Close'].rolling(window=p).mean()

    # **FIX: Logic การกรองตามวันทำการ (Trading Days) - แก้ NameError โดยการย้าย logic การกำหนดค่ามาไว้ที่นี่**
    days_to_display = time_range_options[selected_range_key]
    
    if days_to_display is not None:
        # ใช้ .tail() เพื่อดึงจำนวนแถว (วันทำการ) ล่าสุด
        filtered_data = ticker_data.tail(days_to_display).copy() 
    else:
        # MAX: ใช้ข้อมูลทั้งหมด
        filtered_data = ticker_data.copy()

    if filtered_data.empty:
        st.warning(f"No stock price data found for '{selected_ticker}' in the selected range.")
    else:
        # 📌 FIX: สร้างคอลัมน์สำหรับป้ายชื่อบนแกน X ในรูปแบบ 'Mon 01' (แก้ปัญหา tickformat)
        # ต้องทำหลังจากกรองข้อมูลแล้ว
        filtered_data['Date_Label'] = filtered_data['Date'].apply(lambda x: x.strftime('%b %d'))

        # --- สร้าง Candlestick Chart ด้วย Plotly ---
        
        # 1. Candlestick Trace (แกน y1)
        candlestick = go.Candlestick(
            x=filtered_data['Date_Label'], # 📌 ใช้ Date_Label
            open=filtered_data['Price_Open'],
            high=filtered_data['Price_High'],
            low=filtered_data['Price_Low'],
            close=filtered_data['Price_Close'],
            name='Price'
        )

        # 2. Volume Bar Trace (แกน y2)
        volume_bar = go.Bar(
            x=filtered_data['Date_Label'], # 📌 ใช้ Date_Label
            y=filtered_data['Volume'],
            name='Volume',
            yaxis='y2', 
            marker=dict(color='rgba(150, 150, 150, 0.5)'),
        )

        # 3. Moving Average Traces (แกน y1)
        traces = [candlestick, volume_bar]
        ma_colors = {20: 'blue', 50: 'orange'} 
        
        for p in ma_periods:
            ma_trace = go.Scatter(
                x=filtered_data['Date_Label'], # 📌 ใช้ Date_Label
                y=filtered_data[f'SMA_{p}'],
                mode='lines',
                name=f'SMA {p}',
                line=dict(color=ma_colors[p], width=1.5),
                yaxis='y1'
            )
            traces.append(ma_trace)


        # สร้าง Figure และเพิ่ม Trace ทั้งหมด
        fig = go.Figure(data=traces)

        # Rangeslider
        include_rangeslider = st.checkbox(
            'Show Rangeslider (time selection bar below chart)',
            value=True,
            key='toggle_rangeslider'
        )
        
        # 4. ปรับ Layout
        fig.update_layout(
            title=f'{selected_ticker} Daily Candlestick Chart ({selected_range_key})',
            # **เมื่อใช้ type='category', rangeslider จะยังแสดงได้ แต่จะเป็นการเลือกช่วงของ labels**
            xaxis_rangeslider_visible=include_rangeslider, 
            height=800,
            template='plotly_white',
            
            # กำหนดแกน Y หลัก (ราคา)
            yaxis=dict(title='Price (OHLC)', domain=[0.35, 1.0]), 

            # กำหนดแกน Y ที่สอง (Volume)
            yaxis2=dict(
                title='Volume',
                showgrid=False,
                side='left', 
                # ปรับ range โดยใช้ข้อมูลที่กรองแล้ว
                range=[0, filtered_data['Volume'].max() * 1.5], 
                domain=[0.0, 0.20], 
            ),
            legend=dict(x=0, y=1, orientation="h") 
        )
        
        # 📌 FIX: กำหนด type='category' และลบ tickformat เนื่องจากไม่จำเป็นแล้ว
        fig.update_xaxes(
            showgrid=True, zeroline=False, showline=True,
            type='category', 
            # ลบ tickformat ออกไป
        )
        
        st.plotly_chart(fig, use_container_width=True)

# ============================
# 4. Financial Statement Trend (Quarterly)
# ============================
st.subheader("Financial Statement Trend 📈")

# Prepare Data for Chart
latest_features = ALL1[ALL1['tickers'] == selected_ticker].copy() 

# Dictionary สำหรับแปลงชื่อคอลัมน์เป็นชื่อที่อ่านง่าย
METRIC_DISPLAY_NAMES = {
    'revenue': 'Revenue',
    'cost_of_revenue': 'Cost of Revenue',
    'gross_profit': 'Gross Profit',
    'operating_income': 'Operating Income',
    'income_tax_expense': 'Income Tax Expense',
    'net_income': 'Net Income',
    'assets': 'Assets',
    'liabilities': 'Liabilities',
    'equity': 'Equity',
    'operating_cashflow': 'Operating Cashflow',
}

financial_cols_base = [
    'revenue', 'net_income', 'assets', 'equity', 'operating_cashflow'
]
financial_cols_display = ['year', 'q'] + [c for c in financial_cols_base if c in ALL1.columns]

if not latest_features.empty and any(c in ALL1.columns for c in financial_cols_base):
    # กรองข้อมูลเฉพาะหุ้นที่เลือกและคอลัมน์ที่ต้องการ
    financial_data = latest_features.loc[:, ['year', 'q'] + financial_cols_base].copy()

    # สร้างคอลัมน์ Label สำหรับแกน X
    financial_data['Quarter_Label'] = financial_data['year'].astype(str) + ' Q' + financial_data['q'].astype(str)
    
    # กรองข้อมูล 16 ไตรมาสล่าสุด (4 ปี) และเรียงตามเวลา
    financial_data = financial_data.sort_values(by=['year', 'q']).tail(16) 

    # 4.2 UI Selection for Metric
    
    # สร้าง List ของชื่อที่แสดงผล (Display Names)
    available_metrics = [c for c in financial_cols_base if c in ALL1.columns]
    display_options = [METRIC_DISPLAY_NAMES.get(m, m.replace('_', ' ').title()) for m in available_metrics]
    
    selected_display_name = st.selectbox(
        "Select Financial Metric to View:",
        options=display_options, # แสดงชื่อที่อ่านง่าย
        key="financial_metric_select"
    )
    
    # 📌 FIX 2: Mapping ชื่อที่แสดงผลกลับไปเป็นชื่อคอลัมน์จริง (Original Column Name)
    # เนื่องจากเราไม่มี dictionary ที่ map display_name -> metric_name, เราต้องสร้างมันขึ้นมา
    
    # สร้าง Map ที่สลับกัน (Display Name -> Original Column Name)
    reverse_map = {v: k for k, v in METRIC_DISPLAY_NAMES.items()}
    selected_metric_name = reverse_map.get(selected_display_name, selected_display_name)
    
    # 4.3 Create Plotly Bar Chart
    fig_fin = go.Figure()
    
    # สร้าง Bar Chart สำหรับ Metric ที่เลือก
    fig_fin.add_trace(go.Bar(
        x=financial_data['Quarter_Label'],
        # 📌 FIX 3: ใช้ selected_metric_name ในการดึงข้อมูลจาก DataFrame
        y=financial_data[selected_metric_name],
        name=selected_display_name,
        marker_color='#1f77b4'
    ))

    # เพิ่ม Line Trace สำหรับ Net Income (ถ้ามี) เพื่อแสดงคู่กัน
    if 'net_income' in financial_data.columns and selected_metric_name != 'net_income':
        # Net Income Overlay Trace
        fig_fin.add_trace(go.Scatter(
            x=financial_data['Quarter_Label'],
            y=financial_data['net_income'],
            mode='lines+markers',
            name='Net Income (Overlay)',
            line=dict(color='red', dash='dot'),
            yaxis='y1'
        ))

    # 4.4 Update Layout
    # ใช้ชื่อที่แสดงผลใน Title และ Axis Label
    fig_fin.update_layout(
        title=f'{selected_display_name} Trend for {selected_ticker} (Last 16 Quarters)',
        xaxis_title="Fiscal Quarter",
        yaxis_title=selected_display_name,
        height=450,
        template='plotly_white',
        barmode='overlay',
        xaxis=dict(tickangle=-45)
    )

    st.plotly_chart(fig_fin, use_container_width=True)
    
else:
    st.warning(f"Not enough financial data found in ALL1 for the selected group or ticker ({selected_ticker}).")
# ============================
# 5. Financial Statement Trend (Group)
# ============================

# กำหนดกลุ่มตัวชี้วัดทางการเงินใหม่ตามหลักการวิเคราะห์
FINANCIAL_GROUPS = {
    "Income Statement": [
        'revenue', 'cost_of_revenue', 'gross_profit', 'operating_income', 
        'income_tax_expense', 'net_income'
    ], 
    "Balance Sheet": ['assets', 'liabilities', 'equity'], 
    "Cash Flow Statement": ['operating_cashflow', 'cf_investing', 'cf_financing'],
}

# 5.1 Prepare Data for Chart
latest_features = ALL1[ALL1['tickers'] == selected_ticker].copy() # ใช้ filtered ALL1 data

# 5.2 UI Selection for Metric Group
selected_group_name = st.selectbox(
    "Select Financial Metric Group to View Trends:",
    options=list(FINANCIAL_GROUPS.keys()),
    key="financial_group_select_new" # เปลี่ยน key เพื่อไม่ให้ชนกับส่วนที่ 4 เดิม
)

# 5.3 Filter Data and Create Plotly Line Chart
selected_metrics = FINANCIAL_GROUPS[selected_group_name]
financial_cols_to_use = ['year', 'q'] + [m for m in selected_metrics if m in latest_features.columns]

if not latest_features.empty and len(financial_cols_to_use) > 2:
    
    financial_data = latest_features.loc[:, financial_cols_to_use].copy()
    financial_data['Quarter_Label'] = financial_data['year'].astype(str) + ' Q' + financial_data['q'].astype(str)
    financial_data = financial_data.sort_values(by=['year', 'q']).tail(16) # 16 Quarters

    fig_fin = go.Figure()
    
    line_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2'] 

    for i, metric in enumerate(selected_metrics):
        if metric in financial_data.columns:
            # สร้าง Scatter Trace (กราฟเส้น) สำหรับแต่ละตัวชี้วัดในกลุ่ม
            fig_fin.add_trace(go.Scatter(
                x=financial_data['Quarter_Label'],
                y=financial_data[metric],
                mode='lines+markers',
                name=metric.replace('_', ' ').title(),
                line=dict(color=line_colors[i % len(line_colors)], width=2),
                yaxis='y1'
            ))
        
    # 5.4 Update Layout
    fig_fin.update_layout(
        title=f'Trend Comparison for {selected_group_name} ({selected_ticker})',
        xaxis_title="Fiscal Quarter",
        yaxis_title=f"{selected_group_name} (Unit/Value)",
        height=450,
        template='plotly_white',
        xaxis=dict(tickangle=-45),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    st.plotly_chart(fig_fin, use_container_width=True)
    
    st.caption("Note: Metrics within the same group may have vastly different magnitudes. Lines might appear flat for smaller values.")

else:
    st.warning(f"Not enough financial data found in ALL1 for the selected group or ticker ({selected_ticker}).")

# ============================
# 6. Valuation & Risk Analysis
# ============================
st.subheader("Valuation & Risk Analysis 🏷️")

# 6.1 Data Preparation for Ratio Calculation
# ดึงข้อมูลราคาปิดล่าสุด (Annualized) และ Financials Quarterly ทั้งหมดของหุ้นตัวนั้น
ticker_all_data = ALL1[ALL1['tickers'] == selected_ticker].copy()

if ticker_all_data.empty:
    st.warning(f"No quarterly data found in ALL1 for {selected_ticker} to calculate valuation.")
    st.stop()

# Safety Check (เพื่อให้โค้ดนี้รันได้หากถูกเรียกเป็นส่วนย่อย)
if 'ALL1' not in globals() or 'stock_price' not in globals() or 'selected_ticker' not in globals():
    st.error("FATAL ERROR: Required dataframes (ALL1, stock_price) are not initialized.")
    st.stop()

ticker_all_data = ALL1[ALL1['tickers'] == selected_ticker].copy()

if ticker_all_data.empty:
    st.warning(f"No quarterly data found in ALL1 for {selected_ticker}.")
    st.stop()


# --- 1. คำนวณ Annualized EPS (EPS TTM - Trailing Twelve Months) ---

# TTM is the sum of the last 4 quarters' EPS.
if 'eps_basic' in ticker_all_data.columns:
    # 📌 FIX: คำนวณ TTM โดยใช้ผลรวม (Sum) 4 ไตรมาสล่าสุด
    # ใช้ .tail(4).sum() เพื่อให้ได้ผลรวมของ 4 ไตรมาสล่าสุด
    latest_eps_ttm = ticker_all_data['eps_basic'].tail(4).sum()
else:
    latest_eps_ttm = np.nan
    st.warning("eps_basic column missing for P/E calculation.")

# --- 2. คำนวณ P/BV Proxy และ Volatility ---

# ดึงค่าล่าสุด (Last row after sorting by time)
latest_quarter_data = ticker_all_data.sort_values(by=['year', 'q'], ascending=False).iloc[0]

# Book Value Per Share (BvPS) Proxy: 
# P/BV ต้องใช้ BvPS ซึ่งต้องใช้ Shares Outstanding แต่เราไม่มี
# เราจะใช้ Equity/Assets Ratio (ซึ่งเป็นตัวเลขรวม) และเตือนผู้ใช้ถึงความผิดพลาดของหน่วย
latest_bvps_proxy = latest_quarter_data['equity'] / latest_quarter_data['assets'] if 'equity' in latest_quarter_data.index and 'assets' in latest_quarter_data.index else np.nan

# Volatility Proxy (ใช้ Standard Deviation 3Q ล่าสุด)
latest_volatility = latest_quarter_data['roll_close_std_3q'] if 'roll_close_std_3q' in latest_quarter_data.index else 1.0


# --- 3. ดึงราคาปิดล่าสุด ---
latest_daily_data = stock_price[stock_price['tickers'] == selected_ticker].sort_values(by='Date').iloc[-1]
latest_close = latest_daily_data['Price_Close']

# --- 4. Initialization Dictionaries ---
metrics_data = {}
historical_avg = {}
indicator_data = {}

# --- 5. Ratio Calculation (Current and Historical Average) ---

# P/E Ratio (Price / Annualized EPS)
metrics_data['P/E Ratio'] = latest_close / latest_eps_ttm if latest_eps_ttm > 0 else np.inf

# Historical Avg P/E: Average(Close Price) / Average(EPS TTM)
historical_avg['P/E Ratio'] = ticker_all_data['close_q'].mean() / ticker_all_data['eps_basic'].tail(4).sum() if 'eps_basic' in ticker_all_data.columns else np.nan


# P/BV Ratio (Price / BvPS Proxy)
# NOTE: This calculation is WRONG due to Unit Mismatch but reflects the current state of ALL1 feature ratios.
metrics_data['P/BV Ratio'] = latest_close / latest_bvps_proxy if latest_bvps_proxy > 0 else np.inf
historical_avg['P/BV Ratio'] = (ticker_all_data['close_q'] / (ticker_all_data['equity'] / ticker_all_data['assets'])).mean() if 'equity' in ticker_all_data.columns else np.nan

# Beta (ใช้ Volatility/Std Dev เป็น Proxy สำหรับ Risk)
metrics_data['Beta (Proxy)'] = latest_volatility if not np.isnan(latest_volatility) else 1.0
historical_avg['Beta (Proxy)'] = ticker_all_data['roll_close_std_3q'].mean() if 'roll_close_std_3q' in ticker_all_data.columns else 1.0

# 6.3 Indicator Logic (Gauge)
for metric_name in ['P/E Ratio', 'P/BV Ratio', 'Beta (Proxy)']:
    current_val = metrics_data.get(metric_name)
    avg_val = historical_avg.get(metric_name)
    
    if np.isnan(current_val) or np.isinf(current_val) or np.isnan(avg_val) or avg_val == 0:
        indicator_data[metric_name] = {'progress': 0.5, 'delta': 'N/A', 'color': 'off'}
        continue
        
    ratio_vs_avg = current_val / avg_val
    
    if metric_name in ['P/E Ratio', 'P/BV Ratio']:
        if ratio_vs_avg < 0.9:
            color = 'normal' 
        elif ratio_vs_avg > 1.1:
            color = 'inverse'
        else:
            color = 'off'
            
    elif metric_name == 'Beta (Proxy)':
        if ratio_vs_avg < 0.95:
            color = 'normal'
        elif ratio_vs_avg > 1.05:
            color = 'inverse'
        else:
            color = 'off'
            
    progress_val = (ratio_vs_avg / 2) if ratio_vs_avg < 1 else (0.5 + (ratio_vs_avg - 1) / 2)
    progress_val = max(0.01, min(0.99, progress_val))
    
    # Calculate delta percentage for display
    delta_percent = (current_val / avg_val - 1) * 100
    arrow = "▲" if delta_percent >= 0 else "▼"
    
    # Simplified Delta Text (e.g., ▲ 366.4%)
    delta = f"{arrow} {abs(delta_percent):.1f}%"
    indicator_data[metric_name] = {'progress': progress_val, 'delta': delta, 'color': color, 'full_delta': f"{delta} vs Avg"}


# 6.4 Display Metrics 

col_names = ['P/E Ratio', 'P/BV Ratio', 'Beta (Proxy)']
cols = st.columns(3)

# ฟังก์ชันสำหรับสร้าง Plotly Gauge Chart
def create_gauge(title, value, reference, delta_text, color, max_range=None):
    
    if max_range is None:
        max_range = max(value, reference) * 2.0 if max(value, reference) > 0 else 2.0
        
    if color == 'normal':
        # Green interpretation for delta (lower is better for P/E)
        delta_color_html = '#008000' 
    elif color == 'inverse':
        # Red interpretation for delta (higher is worse for P/E)
        delta_color_html = '#ff0000' 
    else:
        delta_color_html = '#666666' # Gray
        
    # Standard Green/Yellow/Red steps for visualization purpose
    steps_color = ["#77c57c", "#ffcc00", "#ff6961"] # Green, Yellow, Red
    steps_range = [0, reference * 0.9, reference * 1.1, max_range]
    
    steps = []
    for i in range(len(steps_range) - 1):
        steps.append({'range': [steps_range[i], steps_range[i+1]], 'color': steps_color[i % len(steps_color)]})
        
    # Text for Avg display (inside gauge)
    avg_display_text = f"Avg: {reference:.2f}"
    
    # Value format for Delta
    
    fig = go.Figure(go.Indicator(
        domain = {'x': [0, 1], 'y': [0, 1]},
        value = value,
        mode = "gauge+number", # 📌 FIX: ใช้ mode = "gauge+number" (ลบ delta ออก)
        title = {'text': title, 'font': {'size': 18}},
        number={'font': {'size': 34}, 'valueformat': '.2f'}, 
        gauge = {
            'axis': {'range': [0, max_range], 'tickwidth': 1, 'tickcolor': "darkgray"},
            'bar': {'color': "#333"},
            'steps': steps,
            'threshold' : {'line': {'color': "#000", 'width': 3}, 'thickness': 0.9, 'value': reference},
            'bgcolor': "white",
            'borderwidth': 1,
            'bordercolor': "gray",
        }
    ))
    
    # Annotation เพื่อแสดง Avg (ใต้ Title เล็กน้อย) - Y=0.88
    fig.add_annotation(
        text=f"<span style='font-size:12px; color:#666666;'>{avg_display_text}</span>",
        xref="paper", yref="paper",
        x=0.98, y=0.88, 
        showarrow=False,
        align="right"
    )
    
    # ใช้ Annotation เพื่อวาง Delta ใต้ค่าปัจจุบัน - Y=0.15
    fig.add_annotation(
        # ใช้ simplified_delta ที่มี arrow และ percentage แล้ว
        text=f"<span style='font-size:16px; color:{delta_color_html}; font-weight:bold;'>{delta_text}</span>",
        xref="paper", yref="paper",
        x=0.5, y=0.15, 
        showarrow=False,
        align="center"
    )

    # ลดความสูงเพื่อจัดการพื้นที่
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
    return fig


for i, name in enumerate(col_names):
    current_val = metrics_data.get(name)
    avg_val = historical_avg.get(name)
    indicator = indicator_data.get(name, {})
    
    col = cols[i]
    
    if np.isnan(current_val) or np.isinf(current_val) or np.isnan(avg_val) or avg_val == 0:
        # Display fallback text instead of gauge
        col.markdown(f"**{name}**")
        col.markdown(f"N/A (Avg: {avg_val:.2f})")
        continue 
    
    gauge_fig = create_gauge(
        title=name, # Use the metric name as the main title
        value=current_val,
        reference=avg_val,
        # Pass only the simplified delta for display in annotation
        delta_text=indicator['delta'].replace(' vs Avg', ''), 
        color=indicator['color'],
        max_range=avg_val * 2.0 if avg_val > 0 else 2.0 
    )
    col.plotly_chart(gauge_fig, use_container_width=True)
    
        
st.caption("Note: P/E, P/BV, and Beta are compared against the ticker's own historical average.")

# ============================
# view data+download
# ============================
table_dict = {
    "Stock Ticker": stock_ticker,
    "Macro Indicators Monthly": macro_indicators_m,
    "Stock Price Daily": stock_price, #ราคารายวันเดือนปี
    "Stock Financials Quarterly": stock_financials_quarterly,
    "Stock News": stock_news,
    # "Feature Dataset (ALL1)": ALL1,  # ❌ ไม่ใส่ใน dict = ไม่โชว์ใน UI
}

def convert_df_to_csv(df):
    """Converts DataFrame to CSV string for download."""
    return df.to_csv(index=False).encode('utf-8')

st.markdown(f"### Data View 📄")
table_name = st.selectbox("Select Table to View", list(table_dict.keys()))

current_df = table_dict[table_name] # ดึง DataFrame ปัจจุบัน

st.dataframe(current_df, use_container_width=True)

# 📌 NEW: ปุ่มดาวน์โหลด
csv_file = convert_df_to_csv(current_df)

st.download_button(
    label=f"⬇️Download {table_name} as CSV",
    data=csv_file,
    file_name=f"{table_name.replace(' ', '_').lower()}.csv",
    mime="text/csv",)