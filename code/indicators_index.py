import pandas as pd
import numpy as np
import duckdb
con = duckdb.connect("my_stock_data.db", read_only=True)
df_indicators = con.execute("SELECT * FROM macro_indicators").df()

con.close()
# 1. อ่านไฟล์
df = df_indicators
df['date'] = pd.to_datetime(df['date'])
df = df.set_index('date').sort_index()

# ลบคอลัมน์ว่าง
df = df.dropna(how='all', axis=1)

# =================================================================
# 2. สร้าง Macro Index ทั้งหมด (เหมือนก่อนหน้า แต่ปรับให้สวยและแม่นยำขึ้น)
# =================================================================

# --- Growth Components ---
df['gdp_qoq_annualized'] = df['gdp_real'].pct_change(3) * 400  # แปลงเป็น % annualized
df['nfp_mom'] = df['nfp'].pct_change() * 100
df['unemployment_change'] = df['unemployment'].diff()
df['sentiment_z'] = (df['consumer_sentiment'] - df['consumer_sentiment'].rolling(36).mean()) / df['consumer_sentiment'].rolling(36).std()

# Growth Score (0–100)
growth = (
    df['gdp_qoq_annualized'].clip(-5, 10) / 15 * 30 +
    df['nfp_mom'].clip(-1, 2) / 3 * 20 +
    (-df['unemployment_change'].clip(-1, 1)) * 20 +
    df['sentiment_z'].clip(-2, 2) / 4 * 30
)
df['Growth_Score'] = growth.clip(0, 100).rolling(3).mean()

# --- Inflation Pressure ---
df['core_pce_yoy'] = df['core_pce'].pct_change(12) * 100
df['core_cpi_yoy'] = df['core_cpi'].pct_change(12) * 100

inflation = (
    (df['core_pce_yoy'] - 2).clip(0, 5) / 5 * 50 +
    (df['core_cpi_yoy'] - 2).clip(0, 6) / 6 * 50
)
df['Inflation_Score'] = inflation.clip(0, 100).rolling(3).mean()

# --- Labor Market Heat ---
labor_heat = (
    (5.5 - df['unemployment']).clip(0, 2) / 2 * 60 +
    df['nfp'].clip(0, 400000) / 400000 * 40
)
df['Labor_Heat_Score'] = labor_heat.clip(0, 100)

# --- สุดยอดดัชนีรวม: US Macro Regime Score ---
df['US_Macro_Regime_Score'] = (
    df['Growth_Score'].fillna(50) * 0.5 +
    (100 - df['Inflation_Score'].fillna(50)) * 0.3 +
    (100 - df['Labor_Heat_Score']) * 0.2
)
df['US_Macro_Regime_Score'] = df['US_Macro_Regime_Score'].rolling(3).mean()

# --- สัญญาณการลงทุน ---
def get_signal(score):
    if score > 70:  return "STRONG BUY - Risk-On เต็มตัว"
    if score > 60:  return "BUY - เศรษฐกิจดี"
    if score > 45:  return "NEUTRAL - รอจังหวะ"
    if score > 30:  return "SELL - ระวังตัว"
    return "STRONG SELL - Risk-Off"

df['Investment_Signal'] = df['US_Macro_Regime_Score'].apply(get_signal)
df['Regime'] = np.where(df['US_Macro_Regime_Score'] > 60, 'Bull Market',
               np.where(df['US_Macro_Regime_Score'] < 40, 'Bear Market', 'Sideways'))

# =================================================================
# 3. สร้าง DataFrame สุดสวย พร้อมแสดงผลทันที
# =================================================================

# เลือกคอลัมน์ที่สำคัญที่สุด
final_df = df[[
    'cpi', 'core_cpi', 'core_pce', 'unemployment', 'nfp',
    'gdp_real', 'consumer_sentiment',
    'Growth_Score', 'Inflation_Score', 'Labor_Heat_Score',
    'US_Macro_Regime_Score', 'Investment_Signal', 'Regime'
]].copy()

# ปัดทศนิยมให้อ่านง่าย
final_df = final_df.round(2)

# เรียงจากใหม่ → เก่า
final_df = final_df.sort_index(ascending=False)

# ตั้งชื่อคอลัมน์ให้เป็นภาษาไทย + อังกฤษ (สลับกันได้)
final_df.columns = [
    'เงินเฟ้อ CPI', 'Core CPI', 'Core PCE (สำคัญสุด)', 'อัตราการว่างงาน %',
    'การจ้างงานนอกภาคเกษตร (คน)', 'GDP จริง (พันล้าน USD)', 'ความเชื่อมั่นผู้บริโภค',
    'Growth Score', 'Inflation Score', 'Labor Heat Score',
    'US Macro Regime Score', 'สัญญาณการลงทุน', 'ภาวะตลาด'
]