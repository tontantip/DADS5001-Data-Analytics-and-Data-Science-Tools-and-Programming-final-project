import streamlit as st
import duckdb
import fin_index as fi 
import pandas as pd
import numpy as np
import warnings
import price_index as pi
import indicators_index as indi
import time
import json
from tqdm import tqdm
import ollama
import preparedata as pp 
DB_FILE = "my_stock_data.db"

# 1. สร้างฐานข้อมูล (ใช้ context manager)
print("Start downloading and saving data...")

files = {
    "stock_ticker": "1Bd-WwzSp3wTHq30DUtnZQkzBSMyeFZp0",
    "macro_indicators": "1zWEOdbO-dPf6C4iQHgYPXffBrbu_XjiT",
    "stock_price": "1Xg2UkYQVhBBOnZGxWM0bVUoFNy2gQp4K",
    "stock_financials": "1L3QlfcA3_y4XtR0RBXHsbdlfWO-WmRQe",
    "stock_news": "1s2qCI530GqZ1XC7fyWKZQSloX2HPgmj9"
}

with duckdb.connect(DB_FILE) as con:
    for table_name, file_id in files.items():
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        query = f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_parquet('{url}')"
        print(f"Processing {table_name}...")
        con.execute(query)

print(f"Done! Database created as '{DB_FILE}'")

con = duckdb.connect("my_stock_data.db", read_only=True)

## query ตัวอย่าง: ดึงข้อมูลจากตารางต่างๆ
# (โค้ดดึงข้อมูลเดิม)
df_financials = con.execute("SELECT * FROM stock_financials").df()
con.close() # ปิด Connection เมื่อดึงข้อมูลเสร็จ

## Feature engineering financial index
warnings.filterwarnings('ignore')

# 1. เตรียมข้อมูล
df = df_financials

# แปลงวันที่ และเรียงข้อมูล (สำคัญมากก่อนคำนวณ Growth/Streak)
df['start_date'] = pd.to_datetime(df['start_date'])
df['end_date'] = pd.to_datetime(df['end_date'])
df = df.sort_values(['ticker', 'start_date']).reset_index(drop=True) 
# Note: เรียงตาม start_date มักจะแม่นยำกว่า fiscal_year/period

# 2. รันคำนวณอัตราส่วน (เรียกใช้จาก Module)
# ต้องใช้ groupby ก่อนส่งเข้าฟังก์ชัน calculate_ratios ถ้ามีหลายหุ้น
df_ratio = df.groupby('ticker', group_keys=False).apply(fi.calculate_ratios)

# 3. รันคำนวณ streaks (เรียกใช้จาก Module)
streak_summary = df_ratio.groupby('ticker', group_keys=False).apply(fi.calculate_streaks)
streak_summary = streak_summary.sort_values('Consecutive_Positive_FCF_Years', ascending=False)

# 4. แสดงผล
pd.set_option('display.float_format', '{:,.2f}'.format)
pd.set_option('display.max_columns', None)

## show financial index summary
#print(streak_summary.head(10))

## show price index summary
#print(pi.price_summary.head(10))

## show indicators index summary
##print(indi.final_df.info())

## combine data
con = duckdb.connect("my_stock_data.db", read_only=True)

df_ticker = con.execute("SELECT * FROM stock_ticker").df()
con.close()
indi.final_df["indi"] = "y"
df_ticker["indi"] = "y"

### change column head of indicator index
thai_to_english_map = {
    'เงินเฟ้อ CPI': 'CPI',
    'Core CPI': 'Core_CPI',
    'Core PCE (สำคัญสุด)': 'Core_PCE', # สมมติว่ามีคอลัมน์นี้
    'อัตราการว่างงาน %': 'Unemployment_Rate',
    'การจ้างงานนอกภาคเกษตร (คน)': 'NFP', # Nonfarm Payrolls
    'GDP จริง (พันล้าน USD)': 'Real_GDP',
    'ความเชื่อมั่นผู้บริโภค': 'Consumer_Sentiment',
    'Growth Score': 'Growth_Score',
    'Inflation Score': 'Inflation_Score',
    'Labor Heat Score': 'Labor_Heat_Score',
    'US Macro Regime Score': 'Macro_Regime_Score',
    'สัญญาณการลงทุน': 'Investment_Signal',
    'ภาวะตลาด': 'Market_Regime',
    'date': 'Date'
}

# 2. ใช้เมธอด .rename()
# axis=1 หมายถึงการเปลี่ยนชื่อคอลัมน์ (ไม่ใช่แถว)
print("="*70)
final_df = indi.final_df.rename(columns=thai_to_english_map)
final_df = final_df.iloc[[2]]
print(final_df.info())

## change variable name
fin_index = streak_summary
price_summary = pi.price_summary

## combine data
con = duckdb.connect("my_stock_data.db", read_only=True)
index_stock = con.execute("""select
dt.symbol,
dt.security,
dt.gics_sector,
dt.marketcap,
fi.Consecutive_Revenue_Growth_Years,
fi.Consecutive_EPS_Growth_Years,
fi.Consecutive_Profitable_Years,
fi.Consecutive_Positive_FCF_Years,
fi.Consecutive_ROE_Above_15pct_Years,
fd.CPI,
fd.Core_CPI,
fd.Unemployment_Rate,
fd.NFP,
fd.Real_GDP,
fd.Consumer_Sentiment,
fd.Growth_Score,
fd.Inflation_Score,
fd.Labor_Heat_Score,
fd.Macro_Regime_Score,
fd.Investment_Signal,
fd.Market_Regime,
ps.latest_price,
ps.total_return_10y,
ps.cagr_10y,
ps.volatility,
ps.momentum_12m
from df_ticker as dt left join fin_index as fi on dt.symbol = fi.ticker
left join final_df as fd on dt.indi = fd.indi
left join price_summary as ps on dt.symbol = ps.ticker""").df()
con.close()

index_drop=index_stock[index_stock["symbol"]=="SOLS"].index

index_stock.drop(index_drop,axis=0,inplace=True)

with duckdb.connect("index_stock.db") as con:
    con.register('index_df', index_stock)
    con.execute("CREATE OR REPLACE TABLE index_stock_data AS SELECT * FROM index_df")



# --- ⚙️ ตั้งค่า Configuration ---

MODEL_NAME = 'gemma3:1b' 

df = index_stock.copy()

def format_market_cap(market_cap):
    if market_cap >= 1_000_000_000_000: return f"{market_cap/1_000_000_000_000:.2f}T"
    elif market_cap >= 1_000_000_000: return f"{market_cap/1_000_000_000:.2f}B"
    elif market_cap >= 1_000_000: return f"{market_cap/1_000_000:.2f}M"
    return f"{market_cap:.2f}"

def create_prompt(row):
    
    return f"""คุณเป็นนักวิเคราะห์หุ้นมืออาชีพ กรุณาวิเคราะห์ความน่าสนใจของหุ้นต่อไปนี้:

ข้อมูลบริษัท:
- Symbol: {row['symbol']}
- ชื่อเต็ม: {row['security']}
- Sector: {row['gics_sector']}
- Market Cap: ${row['marketcap']:,.2f} ({format_market_cap(row['marketcap'])})

ประสิทธิภาพทางการเงิน:
- รายได้เติบโตติดต่อกัน: {row['Consecutive_Revenue_Growth_Years']} ปี
- EPS เติบโตติดต่อกัน: {row['Consecutive_EPS_Growth_Years']} ปี
- ทำกำไรติดต่อกัน: {row['Consecutive_Profitable_Years']} ปี
- Free Cash Flow บวกติดต่อกัน: {row['Consecutive_Positive_FCF_Years']} ปี
- ROE > 15% ติดต่อกัน: {row['Consecutive_ROE_Above_15pct_Years']} ปี

สภาพแวดล้อมเศรษฐกิจมหภาค:
- CPI (เงินเฟ้อทั่วไป): {row['CPI']}%
- Core CPI (เงินเฟ้อหลัก): {row['Core_CPI']}%
- อัตราว่างงาน: {row['Unemployment_Rate']}%
- Real GDP: {row['Real_GDP']}%
- ความเชื่อมั่นผู้บริโภค: {row['Consumer_Sentiment']}

คะแนนและสัญญาณ:
- Growth Score: {row['Growth_Score']}
- Inflation Score: {row['Inflation_Score']}
- Labor Heat Score: {row['Labor_Heat_Score']}
- Macro Regime Score: {row['Macro_Regime_Score']}
- Investment Signal: {row['Investment_Signal']}
- Market Regime: {row['Market_Regime']}

ข้อมูลราคา:
- ราคาปัจจุบัน: ${row['latest_price']:.2f}
- ผลตอบแทน 10 ปี: {row['total_return_10y']*100:.1f}%
- CAGR 10 ปี: {row['cagr_10y']*100:.1f}%
- Volatility: {row['volatility']*100:.1f}%
- Momentum 12M: {row['momentum_12m']*100:.1f}%

กรุณาวิเคราะห์และให้คะแนนความน่าสนใจ โดยพิจารณาจาก:
1. คุณภาพทางการเงิน (Financial Quality)
2. แนวโน้มการเติบโต (Growth Trend)
3. สภาพตลาดและเศรษฐกิจมหภาค (Macro Environment)
4. ประสิทธิภาพราคา (Price Performance)

ตอบกลับเป็น JSON format เท่านั้น ไม่ต้องมี markdown หรือคำอธิบายอื่น:
{{
    "financial_quality_score": <คะแนน 0-10>,
    "growth_score": <คะแนน 0-10>,
    "macro_environment_score": <คะแนน 0-10>,
    "price_performance_score": <คะแนน 0-10>,
    "summary": "สรุปสั้นๆ 2-3 ประโยค"
}}"""

# --- เริ่ม Loop การทำงาน ---
print(f"🚀 Starting analysis using Ollama Model: {MODEL_NAME}")
print(f"Total stocks: {len(df)}")

results_list = [] 

for index, row in tqdm(df.iterrows(), total=df.shape[0]):
    try:
        prompt = create_prompt(row)


        response = ollama.chat(model=MODEL_NAME, messages=[
            {
                'role': 'system',
                'content': 'You are a helpful financial assistant that outputs strictly in JSON.'
            },
            {
                'role': 'user',
                'content': prompt
            },
        ], format='json', options={'temperature': 0.1}) # Temperature 0.1 สำหรับความแม่นยำสูง

        raw_text = response['message']['content']

        # Parsing JSON
        try:
            data = json.loads(raw_text)
            
            result_row = {
                "symbol": row['symbol'],
                "ai_fin_score": data.get("financial_quality_score"),
                "ai_price_score": data.get("price_performance_score"),
                "ai_envi_score": data.get("macro_environment_score"),
                "ai_comment": data.get("summary")
            }
        except json.JSONDecodeError:
            # Fallback cleaning
            clean_text = raw_text.replace("```json", "").replace("```", "").strip()
            try:
                data = json.loads(clean_text)
                result_row = {
                    "symbol": row['symbol'],
                    "ai_fin_score": data.get("financial_quality_score"),
                    "ai_price_score": data.get("price_performance_score"),
                    "ai_envi_score": data.get("macro_environment_score"),
                    "ai_comment": data.get("summary")
                }
            except:
                result_row = {
                    "symbol": row['symbol'],
                    "ai_fin_score": None, "ai_price_score": None, 
                    "ai_envi_score": None, "ai_comment": f"JSON Fail: {raw_text[:20]}..."
                }

        results_list.append(result_row)
        
        # ไม่จำเป็นต้อง sleep ถ้าเครื่องไหว แต่ถ้าเครื่องร้อนให้เปิดบรรทัดล่างนี้
        # time.sleep(0.2) 

    except Exception as e:
        # กรณีโมเดลหาไม่เจอ หรือ Ollama ยังไม่เปิด
        print(f"Error at {row['symbol']}: {e}")
        break # หยุดทันทีถ้า Error (เช่นหาโมเดลไม่เจอ) เพื่อให้คุณไปแก้ชื่อโมเดลก่อน

# --- สร้าง DataFrame ---
if results_list:
    result_AI = pd.DataFrame(results_list)
    result_AI = result_AI[['symbol', 'ai_fin_score', 'ai_price_score', 'ai_envi_score', 'ai_comment']]
    
    print("\n✅ Analysis Complete!")
    print(result_AI.head())
else:
    print("\n❌ No results generated. Please check your model name and Ollama connection.")

## import to database

with duckdb.connect("ai_result.db") as con:
    con.register('temp_df', result_AI)
    con.execute("CREATE OR REPLACE TABLE ai_result AS SELECT * FROM temp_df")