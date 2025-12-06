import streamlit as st
st.set_page_config(page_title="Top 9 Stock Dashboard", layout="wide")

import duckdb
import pandas as pd
import numpy as np
import textwrap
import plotly.express as px

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
         📟 Stock Market Overview
    </h1>
    """,
    unsafe_allow_html=True
)




# =================================================================================================
# 📊 ฟังก์ชันสร้าง Market Heatmap แบบ Finviz ใน Streamlit
#   ใช้ร่วมกับตัวแปร stock_price และ stock_ticker ที่มีอยู่แล้ว
# =================================================================================================


def render_market_heatmap(stock_price: pd.DataFrame,
                          stock_ticker: pd.DataFrame,
                          key_prefix: str = "hm"):

    # ============================
    # 1) เตรียมข้อมูล + คำนวณ % เปลี่ยนเทียบ "ปิดเมื่อวาน"
    # ============================
    sp = stock_price.copy()
    sp["Date"] = pd.to_datetime(sp["Date"])
    sp = sp.sort_values(["tickers", "Date"])

    # ret_1d = (Close วันนี้ - Close เมื่อวาน) / Close เมื่อวาน
    sp["ret_1d"] = sp.groupby("tickers")["Price_Close"].pct_change()

    # เลือก "วันล่าสุด"
    selected_date = sp["Date"].max().date()
    sp_day = sp[sp["Date"].dt.date == selected_date]

    if sp_day.empty:
        st.warning("ไม่มีข้อมูลสำหรับวันที่ล่าสุด")
        return

    sp_day = sp_day.copy()

    # ============================
    # 2) เตรียม meta (ticker info)
    # ============================
    meta = stock_ticker.copy()

    if "symbol" in meta.columns:
        meta = meta.rename(columns={"symbol": "tickers"})
    if "marketcap" in meta.columns:
        meta = meta.rename(columns={"marketcap": "market_cap"})

    required_cols = ["tickers", "security", "gics_sector", "gics_sub-industry", "market_cap"]
    missing = [c for c in required_cols if c not in meta.columns]
    if missing:
        st.error(f"stock_ticker ขาด column: {missing}")
        st.write(list(meta.columns))
        return

    df = sp_day.merge(
        meta[["tickers", "security", "gics_sector", "gics_sub-industry", "market_cap"]],
        on="tickers",
        how="left"
    )

    df = df.dropna(subset=["gics_sector", "market_cap"])
    df = df[df["market_cap"] > 0].copy()
    if df.empty:
        st.warning("ไม่มีข้อมูล heatmap")
        return

    # ============================
    # 3) เตรียมค่าไว้ย้อมสีแบบ Finviz
    # ============================
    df["ret_clip"] = df["ret_1d"].clip(-0.03, 0.03)

    # สี discrete finviz
    color_minus3 = "#ff4b4b"
    color_minus2 = "#b44b4b"
    color_minus1 = "#6c707d"
    color_0      = "#4b5563"
    color_plus1  = "#4a7f70"
    color_plus2  = "#53c06b"
    color_plus3  = "#4ade80"

    step_scale = [
        [0.00, color_minus3], [0.16, color_minus3],
        [0.16, color_minus2], [0.32, color_minus2],
        [0.32, color_minus1], [0.48, color_minus1],
        [0.48, color_0],      [0.52, color_0],
        [0.52, color_plus1],  [0.68, color_plus1],
        [0.68, color_plus2],  [0.84, color_plus2],
        [0.84, color_plus3],  [1.00, color_plus3],
    ]

    # ============================
    # 4) Treemap
    # ============================
    df["label"] = df["tickers"]

    fig = px.treemap(
        df,
        path=["gics_sector", "gics_sub-industry", "label"],
        values="market_cap",
        color="ret_clip",                 # สี = ค่าที่ clip
        range_color=(-0.03, 0.03),
        color_continuous_scale=step_scale,
        custom_data=[
            "tickers",           # 0
            "security",          # 1
            "gics_sector",       # 2
            "gics_sub-industry", # 3
            "ret_clip",          # 4
            "ret_1d",            # 5 <- ค่าจริง (real)
            "Price_Open",        # 6
            "Price_Close",       # 7
            "market_cap",        # 8
        ],
    )

    fig.update_coloraxes(showscale=False)

    # ============================
    # ★★ แสดง Return 1D (real) ★★
    # ใช้ customdata[5]
    # ============================
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{customdata[5]:+.2%}",  # real %
        textposition="middle center",
        insidetextfont=dict(color="white", size=18),
        marker=dict(line=dict(width=0.4, color="#202124")),
        hovertemplate=(
            "<b>%{customdata[0]}</b> — %{customdata[1]}<br>"
            "Sector: %{customdata[2]}<br>"
            "Industry: %{customdata[3]}<br>"
            "Return 1D (real): %{customdata[5]:+.2%}<br>"
            "Return 1D (clip): %{customdata[4]:+.2%}<br>"
            "Open: %{customdata[6]:.2f}<br>"
            "Close: %{customdata[7]:.2f}<br>"
            "MktCap: %{customdata[8]:,.0f}<br>"
            "<extra></extra>"
        ),
    )

    fig.update_layout(
        margin=dict(t=30, l=0, r=0, b=40),  # ลด bottom นิดหน่อย เพราะไม่มี legend แล้ว
        height=770,
        paper_bgcolor="#202124",
        plot_bgcolor="#202124",
    )

    st.subheader("Market Heatmap")
    st.plotly_chart(fig, use_container_width=True)

    # ============================
    # 5) 🔒 CSS ปิด legend กล่องสีเก่า (ถ้ามีโค้ดส่วนอื่นยังสร้างอยู่)
    # ============================
    st.markdown("""
    <style>
        /* ซ่อน flex legend เดิมที่เป็นกล่อง -3% ถึง +3% */
        div[style*='display:flex'][style*='margin-top:6px'][style*='font-size:13px'] {
            display: none !important;
        }
        /* กันไว้เผื่อ child div ของ legend */
        div[style*='padding:4px 14px'][style*='border-radius:3px'] {
            display: none !important;
        }
    </style>
    """, unsafe_allow_html=True)


# เรียกใช้ Heatmap ในหน้า
render_market_heatmap(stock_price, stock_ticker, key_prefix="main")



# ==================================================================================================
# CARD ราคาหุ้น (Return 1D จากราคาปิดล่าสุดเทียบเมื่อวาน)
# ==================================================================================================
price = stock_price.copy()
price["Date"] = pd.to_datetime(price["Date"])
price = price.sort_values(["tickers", "Date"])

# คำนวณ % การเปลี่ยนแปลงของราคาปิดล่าสุดเทียบกับวันก่อนหน้า
price["pct_change"] = (
    price.groupby("tickers")["Price_Close"]
         .pct_change() * 100
)

# ดึงข้อมูลล่าสุดของแต่ละหุ้น
latest = (
    price.groupby("tickers", sort=False)
         .tail(1)
         .reset_index(drop=True)
)

# join ข้อมูลบริษัท
latest = latest.merge(
    stock_ticker[["symbol", "security", "gics_sector", "gics_sub-industry"]],
    left_on="tickers",
    right_on="symbol",
    how="left"
)

# =========================================================
# Top 15
# =========================================================
top15_gain   = latest.nlargest(15, "pct_change")
top15_loss   = latest.nsmallest(15, "pct_change")
top15_volume = latest.nlargest(15, "Volume")


# =========================================================
# ฟังก์ชันสร้าง HTML การ์ด 1 ใบ (ไม่เรียก markdown ที่นี่)
# =========================================================
def card_html(row):
    ticker = row["tickers"]
    price  = row["Price_Close"]
    pct    = row["pct_change"]

    name     = row["security"] or ""
    sector   = row["gics_sector"] or ""
    industry = row["gics_sub-industry"] or ""

    color = "#28ff8a" if pct >= 0 else "#ff5c5c"
    arrow = "↑" if pct >= 0 else "↓"

    return f"""
<div class="stock-card">
  <div style="display:flex; justify-content:space-between; align-items:center;">
    <div style="font-size:20px; font-weight:700;">{ticker}</div>
    <div style="font-size:22px; font-weight:700;">{price:,.2f}</div>
  </div>

  <div style="font-size:16px; opacity:0.9; margin-top:4px;">
    {name}
  </div>

  <div style="font-size:13px; opacity:0.7; margin-top:2px;">
    {sector} — {industry}
  </div>

  <div style="font-size:18px; font-weight:700; color:{color}; margin-top:10px;">
    {arrow} {pct:.2f}%
  </div>
</div>
"""


# ============================
# CSS – Flex Layout ให้เรียงหลายคอลัมน์จริง
# ============================
st.markdown("""
<style>
.card-container {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;   /* <<< เปลี่ยนเป็น center */
}

/* การ์ดเดี่ยว */
.stock-card {
    background-color:#001a27;
    padding:18px;
    border-radius:12px;

    width:280px;
    min-height:170px;

    box-sizing:border-box;

    display:flex;
    flex-direction:column;
    justify-content:space-between;

    color:white;
    font-family:'Segoe UI', sans-serif;

    margin:10px;
}

@media (max-width: 768px) {
    .card-container {
        justify-content: center;  /* <<< มือถือก็ให้กลางเหมือนกัน */
    }
    .stock-card {
        width:100%;
        min-width:100%;
    }
}
</style>
""", unsafe_allow_html=True)



# =========================================================
# ฟังก์ชันสร้าง Section + รวมการ์ดทั้งหมดทีเดียว
# =========================================================
def render_section_cards(title, data):
    st.markdown(f"## {title}")

    cards_html = ""
    for _, r in data.iterrows():
        cards_html += card_html(r)

    full_html = f'<div class="card-container">{cards_html}</div>'
    st.markdown(full_html, unsafe_allow_html=True)


# =========================================================
# ใช้งาน
# =========================================================
render_section_cards("Top 15 Gain 🚀", top15_gain)
st.write("")
render_section_cards("Top 15 Loss 📉", top15_loss)
st.write("")
render_section_cards("Top 15 Volume 🔥", top15_volume)



#===========================================================================================================================================================================
# จบ CARD ราคาหุ้น
#===========================================================================================================================================================================


# ==============================
# 📉➡️📈 Reversal Rebound Scanner 
# ==============================

st.markdown(
    """
    <h1 style='text-align: center; font-size: 38px; font-weight: 700;'>
        Reversal Rebound Strategy Scanner
    </h1>
    """,
    unsafe_allow_html=True
)

st.caption("เป็นการคัดเลือกหุ้นที่เผชิญการปรับตัวลงอย่างต่อเนื่องตลอดหลายไตรมาส ซึ่งสะท้อนแรงกดดันเชิงพื้นฐานและภาวะตลาดในช่วงที่ผ่านมา พร้อมกันนั้นข้อมูลราคาล่าสุดเริ่มปรากฏสัญญาณรีบาวด์ในเชิงเทคนิค ทั้งในมิติของโมเมนตัม การชะลอแรงขาย และโครงสร้างเทรนด์ที่เริ่มเปลี่ยนทิศ ในเวลาเดียวกันทิศทางของผลประกอบการกลับมาเติบโตสอดคล้องกับภาพรวมของกลุ่มอุตสาหกรรม ทำให้หุ้นชุดนี้มีลักษณะของสินทรัพย์ที่กำลังเปลี่ยนผ่านจากภาวะอ่อนตัวสู่ระยะฟื้นตัวตามวงจรของ sector ที่สังกัดอยู่")

# ---- Top N control ให้เลือกได้เหมือน Ultra ----
TOP_N_REV = st.slider("Stock Limit", 5, 50, 20, 5)

# ใช้ ALL1 ที่มีอยู่แล้วในแอป
df = ALL1.copy()

# ---------------------------------
# 0) เคลียร์ค่า inf / -inf
# ---------------------------------
num_cols = df.select_dtypes(include=[np.number]).columns
df[num_cols] = df[num_cols].replace([np.inf, -np.inf], np.nan)

# เรียงตาม tickers, year, q
df = df.sort_values(["tickers", "year", "q"]).reset_index(drop=True)

# ---------------------------------
# 1) เลือก "ไตรมาสล่าสุด" ของแต่ละหุ้น
# ---------------------------------
latest = (
    df.groupby("tickers", sort=False)   # ไม่ให้ groupby ไป sort เอง
      .tail(1)
      .reset_index(drop=True)
)

latest = latest.sort_values(
    ["gics_sector", "year", "q", "tickers"]
).reset_index(drop=True)

# ---------------------------------
# 2) วัดว่า "ลงมานาน" แค่ไหน (3 ไตรมาสล่าสุด)
# ---------------------------------
for c in ["ret_q", "ret_last_1q", "ret_last_2q"]:
    if c not in latest.columns:
        latest[c] = 0
    latest[c] = latest[c].fillna(0)

latest["down_3q_sum"] = (
    latest["ret_q"] +
    latest["ret_last_1q"] +
    latest["ret_last_2q"]
)

mask_downtrend = (
    (latest["ret_last_1q"] < 0) &
    (latest["ret_last_2q"] < 0) &
    (latest["down_3q_sum"] < -0.15)
)

# ---------------------------------
# 3) BLOCK: Trend (Oversold + Volatility)
# ---------------------------------
latest["r_down_depth"] = (-latest["down_3q_sum"]).rank(pct=True)

if "volatility_q" in latest.columns:
    v = latest["volatility_q"].fillna(latest["volatility_q"].median())
    r_v = v.rank(pct=True)
    latest["r_volatility_mid"] = 1 - (2 * (r_v - 0.5).abs())
else:
    latest["r_volatility_mid"] = 0.5

latest["score_trend"] = (
    0.7 * latest["r_down_depth"] +
    0.3 * latest["r_volatility_mid"]
)

# ---------------------------------
# 4) BLOCK: Price Action
# ---------------------------------
if "close_to_high_q" not in latest.columns:
    latest["close_to_high_q"] = 0
latest["close_to_high_q"] = latest["close_to_high_q"].fillna(0)
latest["r_close_to_high"] = latest["close_to_high_q"].rank(pct=True)

latest["r_ret_q"] = latest["ret_q"].rank(pct=True)

if "momentum_accel" not in latest.columns:
    latest["momentum_accel"] = 0
latest["momentum_accel_clip"] = latest["momentum_accel"].clip(-0.5, 0.5)
latest["r_mom_accel"] = latest["momentum_accel_clip"].rank(pct=True)

latest["score_price"] = (
    0.5 * latest["r_close_to_high"] +
    0.3 * latest["r_ret_q"] +
    0.2 * latest["r_mom_accel"]
)

# ---------------------------------
# 5) BLOCK: Volume
# ---------------------------------
if "vol_mom_q" not in latest.columns:
    latest["vol_mom_q"] = 0

latest["vol_mom_q"] = latest["vol_mom_q"].fillna(0)
latest["vol_mom_clip"] = latest["vol_mom_q"].clip(0, 3)
latest["r_vol_mom"] = latest["vol_mom_clip"].rank(pct=True)

if "vol_pressure_q" in latest.columns:
    latest["vol_pressure_q"] = latest["vol_pressure_q"].fillna(0)
    latest["vol_pressure_clip"] = latest["vol_pressure_q"].clip(-3, 3)
    latest["r_vol_pressure"] = latest["vol_pressure_clip"].rank(pct=True)
else:
    latest["r_vol_pressure"] = 0.5

latest["score_volume"] = (
    0.7 * latest["r_vol_mom"] +
    0.3 * latest["r_vol_pressure"]
)

# ---------------------------------
# 6) BLOCK: Fundamental
# ---------------------------------
fin_base_cols = ["revenue", "net_income", "eps_diluted", "operating_cashflow"]
fin_qoq_cols  = [f"{c}_qoq" for c in fin_base_cols]

for c in fin_qoq_cols:
    if c not in latest.columns:
        latest[c] = 0
    latest[c] = latest[c].fillna(0)

for c in fin_qoq_cols:
    latest[c + "_cap"] = latest[c].clip(-5, 5)

for c in fin_qoq_cols:
    latest[c + "_w"] = latest.groupby("gics_sector")[c + "_cap"].transform(
        lambda s: s.clip(
            s.quantile(0.05),
            s.quantile(0.95)
        )
    )

latest["fund_raw"] = (
    0.20 * latest["revenue_qoq_w"] +
    0.35 * latest["net_income_qoq_w"] +
    0.35 * latest["eps_diluted_qoq_w"] +
    0.10 * latest["operating_cashflow_qoq_w"]
)

latest["fund_clip"] = latest["fund_raw"].clip(-0.3, 0.3)
latest["score_fund"] = latest.groupby("gics_sector")["fund_clip"].rank(pct=True)

# ---------------------------------
# 7) Reversal Super Score
# ---------------------------------
latest["reversal_super_score"] = (
    0.30 * latest["score_trend"] +
    0.30 * latest["score_price"] +
    0.20 * latest["score_volume"] +
    0.20 * latest["score_fund"]
)

st.markdown("### Reversal Filter Sensitivity")

col1, col2, col3, col4 = st.columns(4)

with col1:
    th_trend = st.slider("Trend", 0.0, 1.0, 0.25, 0.05)
with col2:
    th_price = st.slider("Price", 0.0, 1.0, 0.25, 0.05)
with col3:
    th_volume = st.slider("Volume", 0.0, 1.0, 0.25, 0.05)
with col4:
    th_fund = st.slider("Fund", 0.0, 1.0, 0.25, 0.05)

# ---------------------------------
# 8) ฟิลเตอร์ + เรียงผลลัพธ์
# ---------------------------------
candidates = latest.loc[mask_downtrend].copy()
candidates = candidates[candidates["ret_q"] > -0.15]

candidates = candidates[
    (candidates["score_trend"]  >= th_trend) &
    (candidates["score_price"]  >= th_price) &
    (candidates["score_volume"] >= th_volume) &
    (candidates["score_fund"]   >= th_fund)
]


candidates = candidates.sort_values(
    ["gics_sector", "reversal_super_score"],
    ascending=[True, False]
).reset_index(drop=True)

# ==============================
# 9) Columns + stars
# ==============================
cols_show = [
    "tickers", "gics_sector",
    "reversal_super_score",
    "score_trend", "score_price", "score_volume", "score_fund",
]

candidates_view = candidates[cols_show].rename(columns={
    "tickers": "Ticker",
    "gics_sector": "Sector",
    "reversal_super_score": "Reversal Score",
    "score_trend": "Trend (Oversold)",
    "score_price": "Price Action",
    "score_volume": "Volume Signal",
    "score_fund": "Fundamental Strength",
})

def to_yellow_stars(x):
    full = int(round(x * 5))
    return "⭐" * full if full > 0 else ""

star_cols = [
    "Reversal Score",
    "Trend (Oversold)",
    "Price Action",
    "Volume Signal",
    "Fundamental Strength",
]

for col in star_cols:
    candidates_view[col] = candidates_view[col].apply(to_yellow_stars)

# ==========================================
# 10) Sparkline 30 วัน
# ==========================================
sp = stock_price[["tickers", "Date", "Price_Close"]].copy()
sp["Date"] = pd.to_datetime(sp["Date"])
sp = sp.sort_values(["tickers", "Date"])
g_price = sp.groupby("tickers")

def get_last_30_prices(ticker):
    if ticker not in g_price.groups:
        return []
    g = g_price.get_group(ticker)
    return g["Price_Close"].tail(30).tolist()

candidates_view["Trend 30D"] = candidates_view["Ticker"].map(get_last_30_prices)

# ==========================================
# 11) UI: filter + Top N + 🥇🥈🥉 (Top 3 รวมทั้งตาราง) + ตาราง
# ==========================================
if candidates_view.empty:
    st.warning("ยังไม่มีตัวไหนผ่านเงื่อนไข downtrend + รีบาวด์ ตามเกณฑ์นี้เลย")
else:
    # กันกรณี Sector เป็น int/str ปนกัน → บังคับเป็น string ก่อน
    candidates_view["Sector"] = candidates_view["Sector"].astype(str)

    sectors = sorted(candidates_view["Sector"].dropna().unique())
    selected_sectors = st.multiselect(
        "Choose Sectors",
        options=sectors,
        default=sectors,
    )

    filtered = candidates_view[candidates_view["Sector"].isin(selected_sectors)]

    filtered = (
        filtered
        .sort_values(["Sector", "Reversal Score"], ascending=[True, False])
        .groupby("Sector", group_keys=False)
        .head(TOP_N_REV)
        .reset_index(drop=True)
    )

    # --------------------------------------
    # 🏅 ติดเหรียญเฉพาะ Top 3 รวมทั้งตาราง
    # ใช้ความยาว string ของ Reversal Score (จำนวนดาว) เป็น proxy
    # --------------------------------------
    filtered = filtered.assign(
        _rev_len = filtered["Reversal Score"].str.len()
    )

    medals = ["🥇", "🥈", "🥉"]
    top_idx = (
        filtered.sort_values("_rev_len", ascending=False)
                .index[:3]          # 3 อันดับสูงสุด
    )

    for i, idx in enumerate(top_idx):
        filtered.loc[idx, "Ticker"] = f"{filtered.loc[idx, 'Ticker']} {medals[i]}"

    filtered = filtered.drop(columns=["_rev_len"])

    # --------------------------------------
    # จัดลำดับคอลัมน์
    # --------------------------------------
    cols_order = [
        "Ticker",
        "Sector",
        "Trend 30D",
        "Reversal Score",
        "Trend (Oversold)",
        "Price Action",
        "Volume Signal",
        "Fundamental Strength",
    ]
    cols_order = [c for c in cols_order if c in filtered.columns]
    filtered = filtered[cols_order]

    st.dataframe(
        filtered,
        use_container_width=True,
        height=600,
        column_config={
            "Trend 30D": st.column_config.LineChartColumn(
                "Trend 30D",
                width="small",
                y_min=None,
                y_max=None,
            ),
        },
    )

    csv_bytes = filtered.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ ดาวน์โหลด Reversal Candidates เป็น CSV",
        data=csv_bytes,
        file_name="reversal_candidates.csv",
        mime="text/csv",
    )


# ==============================================================================================================================================================================
# จบ 📉➡️📈 Reversal Rebound Scanner 
# ==============================================================================================================================================================================

# ==============================
# 🧠 Ultra Factor Ranker (Multi-Block Style Model) + Weights on page
# ==============================

# 👇 ต้องประกาศ df_ultra ก่อนใช้เสมอ
df_ultra = ALL1.copy()

# ==========================================
# 0) helper: winsorize + cross-sectional z-score
# ==========================================
def winsorize_ultra(s, lower=0.01, upper=0.99):
    lo = s.quantile(lower)
    hi = s.quantile(upper)
    return s.clip(lo, hi)

def cs_zscore_ultra(df, values, by=["year", "q", "gics_sector"]):
    if isinstance(values, str):
        s = df[values]
    else:
        s = values

    def _z(g):
        x = s.loc[g.index]
        return (x - x.mean()) / (x.std(ddof=0) + 1e-9)

    out = df.groupby(by, group_keys=False).apply(_z)
    return out.reindex(df.index)

# sort ให้ rolling ตามเวลาได้ถูก
df_ultra = df_ultra.sort_values(["tickers", "year", "q"]).reset_index(drop=True)

# เตรียมคอลัมน์ที่ใช้ให้ไม่เป็น NaN
df_ultra["ret_last_2q"]       = df_ultra.get("ret_last_2q", 0).fillna(0)
df_ultra["gross_profit_qoq"]  = df_ultra.get("gross_profit_qoq", 0).fillna(0)
df_ultra["volatility_q"]      = df_ultra.get("volatility_q", 0).fillna(0)
df_ultra["body_vol_q"]        = df_ultra.get("body_vol_q", 0).fillna(0)

for c in [
    "revenue_qoq", "net_income_qoq", "eps_diluted_qoq",
    "operating_cashflow_qoq", "ret_q", "momentum_accel",
    "close_to_high_q", "vol_mom_q", "ret_last_1q"
]:
    df_ultra[c] = df_ultra.get(c, 0).fillna(0)

# ==========================================
# 1) raw signals
# ==========================================
df_ultra["raw_growth"] = (
      0.4 * df_ultra["revenue_qoq"]
    + 0.4 * df_ultra["net_income_qoq"]
    + 0.2 * df_ultra["eps_diluted_qoq"]
)

df_ultra["raw_profit_quality"] = (
      0.4 * df_ultra["operating_cashflow_qoq"]
    + 0.3 * (df_ultra["operating_cashflow_qoq"] - df_ultra["net_income_qoq"])
    + 0.3 * df_ultra["gross_profit_qoq"].clip(-1, 3)
)

df_ultra["raw_mom"] = (
      0.5 * df_ultra["ret_q"]
    + 0.3 * df_ultra["momentum_accel"]
    + 0.2 * df_ultra["close_to_high_q"]
)

df_ultra["raw_mr"] = (
      -0.7 * df_ultra["ret_last_1q"]
    - 0.3 * df_ultra["ret_last_2q"]
    + 0.4 * df_ultra["vol_mom_q"]
)

df_ultra["raw_vol_struct"] = (
      -0.6 * df_ultra["volatility_q"]
    + 0.4 * (1 - df_ultra["body_vol_q"])
)

df_ultra["raw_fin_mom"] = (
      0.5 * df_ultra["net_income_qoq"]
    + 0.3 * df_ultra["operating_cashflow_qoq"]
    + 0.2 * df_ultra["eps_diluted_qoq"]
)

df_ultra["raw_timing"] = (
      0.5 * df_ultra["close_to_high_q"]
    + 0.5 * df_ultra["vol_mom_q"]
)

# ==========================================
# 2) winsorize
# ==========================================
raw_cols_ultra = [
    "raw_growth", "raw_profit_quality", "raw_mom",
    "raw_mr", "raw_vol_struct", "raw_fin_mom", "raw_timing"
]
for c in raw_cols_ultra:
    df_ultra[c] = winsorize_ultra(df_ultra[c])

# ==========================================
# 3) cross-sectional z-score (ต่อ year×q×sector)
# ==========================================
for c in raw_cols_ultra:
    z_col = c.replace("raw_", "z_")
    df_ultra[z_col] = cs_zscore_ultra(df_ultra, c)

z_cols_ultra = [c.replace("raw_", "z_") for c in raw_cols_ultra]

# ==========================================
# 4) rolling 3Q persistence ต่อ ticker
# ==========================================
for c in z_cols_ultra:
    df_ultra[c + "_roll3"] = (
        df_ultra.groupby("tickers")[c]
        .transform(lambda x: x.rolling(3, min_periods=1).mean())
    )

# ==========================================
# 5) Style factors (G_xxx)
# ==========================================
def mix_ultra(z, z_roll, w_persist=0.4):
    return (1 - w_persist) * z + w_persist * z_roll

df_ultra["G_growth"]   = mix_ultra(df_ultra["z_growth"],        df_ultra["z_growth_roll3"])
df_ultra["G_quality"]  = mix_ultra(df_ultra["z_profit_quality"],df_ultra["z_profit_quality_roll3"])
df_ultra["G_mom"]      = mix_ultra(df_ultra["z_mom"],           df_ultra["z_mom_roll3"])
df_ultra["G_mr"]       = mix_ultra(df_ultra["z_mr"],            df_ultra["z_mr_roll3"])
df_ultra["G_vol"]      = mix_ultra(df_ultra["z_vol_struct"],    df_ultra["z_vol_struct_roll3"])
df_ultra["G_fin_mom"]  = mix_ultra(df_ultra["z_fin_mom"],       df_ultra["z_fin_mom_roll3"])
df_ultra["G_timing"]   = mix_ultra(df_ultra["z_timing"],        df_ultra["z_timing_roll3"])

# ==========================================
# 6) Interaction / conviction factors
# ==========================================
df_ultra["F_growth_quality"] = cs_zscore_ultra(
    df_ultra, (df_ultra["G_growth"] + df_ultra["G_quality"]) / 2
)
df_ultra["F_mom_lowvol"] = cs_zscore_ultra(
    df_ultra, df_ultra["G_mom"] - 0.5 * df_ultra["G_vol"]
)
df_ultra["F_fin_timing"] = cs_zscore_ultra(
    df_ultra, 0.6 * df_ultra["G_fin_mom"] + 0.4 * df_ultra["G_timing"]
)

# ==========================================
# 7) Block scores
# ==========================================
df_ultra["fundamental_block"] = (
      0.40 * df_ultra["G_growth"]
    + 0.30 * df_ultra["G_quality"]
    + 0.30 * df_ultra["G_fin_mom"]
)
df_ultra["price_mom_block"] = (
      0.45 * df_ultra["G_mom"]
    + 0.25 * df_ultra["F_mom_lowvol"]
    + 0.30 * df_ultra["F_fin_timing"]
)
df_ultra["risk_structure_block"] = (
      0.50 * df_ultra["G_vol"]
    + 0.30 * df_ultra["G_mr"]
    + 0.20 * df_ultra["F_growth_quality"]
)

df_ultra["fundamental_block_z"]     = cs_zscore_ultra(df_ultra, "fundamental_block")
df_ultra["price_mom_block_z"]       = cs_zscore_ultra(df_ultra, "price_mom_block")
df_ultra["risk_structure_block_z"]  = cs_zscore_ultra(df_ultra, "risk_structure_block")

# ==========================================
# 8) Header + Weights + Top N (อยู่ใต้หัวข้อ Ultra Factor)
# ==========================================
st.markdown(
    "<h2 style='text-align:center;'>Growth Momentum Scanner</h2>",
    unsafe_allow_html=True
)
st.caption("Growth Momentum Scanner เป็นระบบจัดอันดับหุ้นเชิงปริมาณที่ผสานข้อมูลปัจจัยพื้นฐาน (Fundamentals), โมเมนตัมราคา (Price-Momentum), และโครงสร้างความเสี่ยง (Risk Structure) เข้าไว้ด้วยกันในรูปแบบ Growth Momentum Scanner โดยใช้ Z-score เชิงกลุ่มอุตสาหกรรม–ไตรมาส และ Rolling Persistence 3 ไตรมาส เพื่อเน้นความเสถียรของสัญญาณมากกว่าค่าฉาบฉวยในระยะสั้นง")

st.markdown("### Growth Momentum Scanner")


col_fund, col_mom, col_risk, col_n = st.columns(4)
with col_fund:
    w_fund_raw = st.slider("Fundamental", 0.0, 1.0, 0.40, 0.05)
with col_mom:
    w_mom_raw  = st.slider("Momentum",    0.0, 1.0, 0.40, 0.05)
with col_risk:
    w_risk_raw = st.slider("Risk/Structure", 0.0, 1.0, 0.20, 0.05)
with col_n:
    TOP_N_ULTRA = st.slider("Top N", 5, 50, 20, 5)

w_sum = w_fund_raw + w_mom_raw + w_risk_raw
if w_sum == 0:
    w_fund, w_mom, w_risk = 1/3, 1/3, 1/3
else:
    w_fund = w_fund_raw / w_sum
    w_mom  = w_mom_raw  / w_sum
    w_risk = w_risk_raw / w_sum


# ใช้น้ำหนักที่ normalize แล้วมาคิด ultra_score_v2
df_ultra["ultra_score_v2"] = (
      w_fund * df_ultra["fundamental_block_z"]
    + w_mom  * df_ultra["price_mom_block_z"]
    + w_risk * df_ultra["risk_structure_block_z"]
)

# ==========================================
# 9) เลือกไตรมาสล่าสุดของแต่ละ ticker
# ==========================================
df_ultra_sorted = df_ultra.sort_values(["tickers", "year", "q"])
latest_ultra = df_ultra_sorted.groupby("tickers", as_index=False).tail(1)

# ==========================================
# 10) เตรียมตารางสำหรับ UI
# ==========================================
ultra_view = latest_ultra[[
    "tickers", "gics_sector",
    "ultra_score_v2",
    "fundamental_block_z",
    "price_mom_block_z",
    "risk_structure_block_z",
]]

ultra_view = ultra_view.rename(columns={
    "tickers": "Ticker",
    "gics_sector": "Sector",
    "ultra_score_v2": "Ultra Score",
    "fundamental_block_z": "Fundamental",
    "price_mom_block_z": "Momentum",
    "risk_structure_block_z": "Risk Structure",
})

# ==========================================
# 11) เพิ่ม Sparkline 30 วัน จาก stock_price
# ==========================================
sp = stock_price[["tickers", "Date", "Price_Close"]].copy()
sp["Date"] = pd.to_datetime(sp["Date"])
sp = sp.sort_values(["tickers", "Date"])
g_price_ultra = sp.groupby("tickers")

def get_last_30_prices_ultra(ticker):
    if ticker not in g_price_ultra.groups:
        return []
    g = g_price_ultra.get_group(ticker)
    return g["Price_Close"].tail(30).tolist()

ultra_view["Trend 30D"] = ultra_view["Ticker"].map(get_last_30_prices_ultra)

# ==========================================
# 12) แปลง block scores เป็น "ดาวสีเหลือง" ตาม percentile
# ==========================================
def z_to_yellow_stars_series(s):
    pct = s.rank(pct=True)
    num = (pct * 5).round().astype(int).clip(0, 5)
    return num.apply(lambda n: "⭐" * n if n > 0 else "")

for col in ["Ultra Score", "Fundamental", "Momentum", "Risk Structure"]:
    ultra_view[col] = z_to_yellow_stars_series(ultra_view[col])

# ==========================================
# 13) ตาราง Ultra Factor + 🥇🥈🥉
# ==========================================
if ultra_view.empty:
    st.warning("ยังไม่มีข้อมูล Ultra Factor ให้แสดง")
else:
    ultra_view["Sector"] = ultra_view["Sector"].astype(str)

    sectors_ultra = sorted(ultra_view["Sector"].unique())
    selected_sectors_ultra = st.multiselect(
        "Choose Sectors",
        options=sectors_ultra,
        default=sectors_ultra,
    )

    filtered_ultra = ultra_view[ultra_view["Sector"].isin(selected_sectors_ultra)]

    filtered_ultra = (
        filtered_ultra
        .assign(_ultra_len = filtered_ultra["Ultra Score"].str.len())
        .sort_values("_ultra_len", ascending=False)
        .drop(columns=["_ultra_len"])
    )

    filtered_ultra = filtered_ultra.head(TOP_N_ULTRA)

    # 🏆 เพิ่มเหรียญ podium ต่อท้ายชื่อหุ้นในคอลัมน์ Ticker
    def add_medals(df):
        medals = ["🥇", "🥈", "🥉"]
        df = df.copy().reset_index(drop=True)
        for i in range(min(3, len(df))):   # กันกรณีหุ้นน้อยกว่า 3 ตัว
            df.loc[i, "Ticker"] = f"{df.loc[i, 'Ticker']} {medals[i]}"
        return df

    filtered_ultra = add_medals(filtered_ultra)

    cols_ultra = [
        "Ticker", "Sector", "Trend 30D",
        "Ultra Score", "Fundamental", "Momentum", "Risk Structure",
    ]
    cols_ultra = [c for c in cols_ultra if c in filtered_ultra.columns]
    filtered_ultra = filtered_ultra[cols_ultra]

    st.dataframe(
        filtered_ultra,
        use_container_width=True,
        column_config={
            "Trend 30D": st.column_config.LineChartColumn(
                "Trend 30D",
                width="small",
                y_min=None,
                y_max=None,
            ),
        },
    )

    csv_ultra = filtered_ultra.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ ดาวน์โหลด Ultra Factor CSV",
        data=csv_ultra,
        file_name="ultra_factor_ranker.csv",
        mime="text/csv",
    )


# ====================================================================================================================================================================================
# 🧠 Ultra Factor Ranker (Multi-Block Style Model) + Weights on page
# ====================================================================================================================================================================================


# ==============================
# 🔻 Sell Pressure Scanner (Take-Profit / Risk Alert)
# ==============================

st.markdown(
    """
    <h2 style='text-align:center; font-weight:700;'>
        Sell Pressure Scanner
    </h2>
    """,
    unsafe_allow_html=True
)

st.caption("สแกนคัดหุ้นที่มีภาวะร้อนแรงเกิน โมเมนตัมชะลอตัว ผลประกอบการอ่อนแรง และความเสี่ยงด้านหนี้สินเพิ่มขึ้น เพื่อเป็นสัญญาณประกอบการลดสัดส่วนหรือทำกำไร")

TOP_N_SELL = st.slider("# Stock Limit", 5, 50, 20, 5)

# -------------------------------------------------------------------
# 0) เตรียม df + helper
# -------------------------------------------------------------------
df_sell = ALL1.copy()

num_cols = df_sell.select_dtypes(include=[np.number]).columns
df_sell[num_cols] = df_sell[num_cols].replace([np.inf, -np.inf], np.nan)

def winsorize_series(s, lower=0.01, upper=0.99):
    lo = s.quantile(lower)
    hi = s.quantile(upper)
    return s.clip(lo, hi)

def cs_zscore(df, col, by=["year", "q", "gics_sector"]):
    def _z(g):
        x = g[col].astype(float)
        x = winsorize_series(x)
        mu = x.mean()
        std = x.std(ddof=0)
        return (x - mu) / (std + 1e-9)

    return df.groupby(by, group_keys=False).apply(_z)

# -------------------------------------------------------------------
# 1) Overheat block
# -------------------------------------------------------------------
for c in ["ret_q", "close_to_high_q", "vol_mom_q", "body_vol_q"]:
    df_sell[c] = df_sell.get(c, 0).fillna(0)

df_sell["z_ret_q"]           = cs_zscore(df_sell, "ret_q")
df_sell["z_close_to_high_q"] = cs_zscore(df_sell, "close_to_high_q")
df_sell["z_vol_mom_q"]       = cs_zscore(df_sell, "vol_mom_q")
df_sell["z_body_vol_q"]      = cs_zscore(df_sell, "body_vol_q")

df_sell["score_overheat"] = (
    0.3 * df_sell["z_ret_q"] +
    0.3 * df_sell["z_close_to_high_q"] +
    0.2 * df_sell["z_vol_mom_q"] +
    0.2 * df_sell["z_body_vol_q"]
)

# -------------------------------------------------------------------
# 2) Momentum breakdown block
# -------------------------------------------------------------------
for c in ["ret_last_1q", "ret_last_2q", "momentum_accel", "range_q", "volatility_q"]:
    df_sell[c] = df_sell.get(c, 0).fillna(0)

df_sell["z_ret_last_1q"]    = cs_zscore(df_sell, "ret_last_1q")
df_sell["z_ret_last_2q"]    = cs_zscore(df_sell, "ret_last_2q")
df_sell["z_momentum_accel"] = cs_zscore(df_sell, "momentum_accel")
df_sell["z_range_q"]        = cs_zscore(df_sell, "range_q")
df_sell["z_volatility_q"]   = cs_zscore(df_sell, "volatility_q")

df_sell["score_breakdown"] = (
    -0.4 * df_sell["z_ret_last_1q"] +
    -0.2 * df_sell["z_ret_last_2q"] +
    -0.4 * df_sell["z_momentum_accel"] +
     0.3 * df_sell["z_range_q"] +
     0.3 * df_sell["z_volatility_q"]
)

# -------------------------------------------------------------------
# 3) Fundamental deterioration block
# -------------------------------------------------------------------
for col in ["revenue_qoq", "net_income_qoq", "eps_diluted_qoq", "operating_cashflow_qoq"]:
    df_sell[col] = df_sell.get(col, np.nan)

df_sell["z_rev_qoq"]  = cs_zscore(df_sell, "revenue_qoq")
df_sell["z_ni_qoq"]   = cs_zscore(df_sell, "net_income_qoq")
df_sell["z_epsd_qoq"] = cs_zscore(df_sell, "eps_diluted_qoq")
df_sell["z_ocf_qoq"]  = cs_zscore(df_sell, "operating_cashflow_qoq")

df_sell["score_fundamental"] = (
    -0.3 * df_sell["z_rev_qoq"] +
    -0.4 * df_sell["z_ni_qoq"] +
    -0.4 * df_sell["z_epsd_qoq"] +
    -0.3 * df_sell["z_ocf_qoq"]
)

# -------------------------------------------------------------------
# 4) Balance sheet risk block
# -------------------------------------------------------------------
df_sell["de_ratio"] = df_sell["liabilities"] / (df_sell["equity"].replace(0, np.nan))
df_sell["de_ratio"] = df_sell["de_ratio"].replace([np.inf, -np.inf], np.nan)

g_t = df_sell.groupby("tickers")
df_sell["de_ratio_last_1q"] = g_t["de_ratio"].shift(1)
df_sell["de_ratio_change"]  = df_sell["de_ratio"] - df_sell["de_ratio_last_1q"]

df_sell["z_de_ratio"]     = cs_zscore(df_sell, "de_ratio")
df_sell["z_de_ratio_chg"] = cs_zscore(df_sell, "de_ratio_change")

df_sell["score_balance"] = (
    0.6 * df_sell["z_de_ratio"] +
    0.4 * df_sell["z_de_ratio_chg"]
)

# -------------------------------------------------------------------
# 5) รวมเป็น sell_score
# -------------------------------------------------------------------
df_sell["sell_score"] = (
    df_sell["score_overheat"] +
    df_sell["score_breakdown"] +
    df_sell["score_fundamental"] +
    df_sell["score_balance"]
)

df_sell = df_sell.replace([np.inf, -np.inf], np.nan)
df_sell = df_sell.dropna(subset=["sell_score"]).copy()

# -------------------------------------------------------------------
# 6) เอาเฉพาะไตรมาสล่าสุดของแต่ละหุ้น
# -------------------------------------------------------------------
df_sell = df_sell.sort_values(["tickers", "year", "q"])
latest_sell = (
    df_sell.groupby("tickers", sort=False)
           .tail(1)
           .reset_index(drop=True)
)

# ---------------------------------------------------------
# ✨ Sell Filter Sensitivity (0–1 scale, แบบ Reversal)
# ---------------------------------------------------------
st.markdown("### Sell Filter Sensitivity")

col1, col2, col3, col4 = st.columns(4)
with col1:
    th_over = st.slider("Overheat", 0.0, 1.0, 0.25, 0.05)
with col2:
    th_break = st.slider("Breakdown", 0.0, 1.0, 0.25, 0.05)
with col3:
    th_fund = st.slider("Fundamental", 0.0, 1.0, 0.25, 0.05)
with col4:
    th_bal = st.slider("Balance Risk", 0.0, 1.0, 0.25, 0.05)

# rank เป็น percentile 0–1 ของแต่ละ block
latest_sell["p_overheat"]      = latest_sell["score_overheat"].rank(pct=True)
latest_sell["p_breakdown"]     = latest_sell["score_breakdown"].rank(pct=True)
latest_sell["p_fundweak"]      = latest_sell["score_fundamental"].rank(pct=True)
latest_sell["p_balance_risk"]  = latest_sell["score_balance"].rank(pct=True)

mask_sell_filter = (
    (latest_sell["p_overheat"]     >= th_over)  &
    (latest_sell["p_breakdown"]    >= th_break) &
    (latest_sell["p_fundweak"]     >= th_fund)  &
    (latest_sell["p_balance_risk"] >= th_bal)
)

filtered_latest_sell = latest_sell.loc[mask_sell_filter].copy()

# -------------------------------------------------------------------
# 7) เตรียมตาราง view + ดาว  (ใช้ filtered_latest_sell แทน latest_sell)
# -------------------------------------------------------------------
sell_view = filtered_latest_sell[[
    "tickers", "gics_sector",
    "sell_score",
    "score_overheat",
    "score_breakdown",
    "score_fundamental",
    "score_balance",
]].rename(columns={
    "tickers": "Ticker",
    "gics_sector": "Sector",
    "sell_score": "Sell Score",
    "score_overheat": "Overheat",
    "score_breakdown": "Momentum Breakdown",
    "score_fundamental": "Fundamental Weak",
    "score_balance": "Balance Sheet Risk",
})

def z_to_yellow_stars_series(s):
    pct = s.rank(pct=True)                          # 0–1
    num = (pct * 5).round().astype(int).clip(0, 5) # 0–5 ดาว
    return num.apply(lambda n: "⭐" * n if n > 0 else "")

# ⭐ คอลัมน์ดาว (คนละชื่อกับคอลัมน์ score)
sell_view["Sell"]        = z_to_yellow_stars_series(sell_view["Sell Score"])
sell_view["Overheat"]    = z_to_yellow_stars_series(sell_view["Overheat"])
sell_view["Breakdown"]   = z_to_yellow_stars_series(sell_view["Momentum Breakdown"])
sell_view["Fundamental"] = z_to_yellow_stars_series(sell_view["Fundamental Weak"])
sell_view["Balance"]     = z_to_yellow_stars_series(sell_view["Balance Sheet Risk"])

# -------------------------------------------------------------------
# 8) Sparkline 30 วันล่าสุดจาก stock_price
# -------------------------------------------------------------------
sp_sell = stock_price[["tickers", "Date", "Price_Close"]].copy()
sp_sell["Date"] = pd.to_datetime(sp_sell["Date"])
sp_sell = sp_sell.sort_values(["tickers", "Date"])
g_price_sell = sp_sell.groupby("tickers")

def get_last_30_prices_sell(ticker):
    if ticker not in g_price_sell.groups:
        return []
    g = g_price_sell.get_group(ticker)
    return g["Price_Close"].tail(30).tolist()

sell_view["Trend 30D"] = sell_view["Ticker"].map(get_last_30_prices_sell)

# -------------------------------------------------------------------
# 9) UI: filter sector + Global Top N + 😡🙁😐 + ตาราง
# -------------------------------------------------------------------
if sell_view.empty:
    st.warning("ยังไม่มีข้อมูล Sell Scanner ให้แสดงหลังใช้ Filter แล้ว")
else:
    sell_view["Sector"] = sell_view["Sector"].astype(str)

    sectors_sell = sorted(sell_view["Sector"].dropna().unique())
    selected_sectors_sell = st.multiselect(
        "Choose Sectors",
        options=sectors_sell,
        default=sectors_sell,
    )

    filtered_sell = sell_view[sell_view["Sector"].isin(selected_sectors_sell)].copy()

    filtered_sell = (
        filtered_sell
        .sort_values("Sell Score", ascending=False)
        .head(TOP_N_SELL)
        .reset_index(drop=True)
    )

    # 🏅 เพิ่มเหรียญให้ Top 3
    medals = ["😡", "🙁", "😐"]
    top_idx = filtered_sell.sort_values("Sell Score", ascending=False).index[:3]
    for i, idx in enumerate(top_idx):
        filtered_sell.loc[idx, "Ticker"] = f"{filtered_sell.loc[idx, 'Ticker']} {medals[i]}"

    # ลบคะแนนดิบที่ไม่ใช้โชว์ กัน column name ซ้ำ
    drop_score_cols = [
        "Sell Score",
        "Momentum Breakdown",     # ตัวเลข
        "Fundamental Weak",       # ตัวเลข
        "Balance Sheet Risk",     # ตัวเลข
    ]
    filtered_sell = filtered_sell.drop(
        columns=[c for c in drop_score_cols if c in filtered_sell.columns]
    )

    # ตั้งชื่อคอลัมน์ดาวให้สื่อความ
    filtered_sell = filtered_sell.rename(columns={
        "Trend 30D": "Price Trend (30D)",
        "Sell": "Sell Pressure",
        "Overheat": "Overheat Signal",
        "Breakdown": "Momentum Breakdown",
        "Fundamental": "Fundamental Weakness",
        "Balance": "Balance Sheet Risk",
    })

    cols_sell = [
        "Ticker",
        "Sector",
        "Price Trend (30D)",
        "Sell Pressure",
        "Overheat Signal",
        "Momentum Breakdown",
        "Fundamental Weakness",
        "Balance Sheet Risk",
    ]
    cols_sell = [c for c in cols_sell if c in filtered_sell.columns]
    filtered_sell_display = filtered_sell[cols_sell]


    st.dataframe(
        filtered_sell_display,
        use_container_width=True,
        height=600,
        column_config={
            "Price Trend (30D)": st.column_config.LineChartColumn(
                "Price Trend (30D)",
                width="small",
                y_min=None,
                y_max=None,
            ),
        },
    )

    csv_sell = filtered_sell_display.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ ดาวน์โหลด Sell Scanner CSV",
        data=csv_sell,
        file_name="sell_scanner.csv",
        mime="text/csv",
    )
