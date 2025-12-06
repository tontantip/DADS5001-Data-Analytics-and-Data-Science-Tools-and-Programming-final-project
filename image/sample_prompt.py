## create prompt
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

## set ai
response = ollama.chat(model=MODEL_NAME, messages=[
            {
                'role': 'system',
                'content': 'You are a helpful financial assistant that outputs strictly in JSON.'
            },
            {
                'role': 'user',
                'content': prompt
            },
        ], format='json', options={'temperature': 0.1})
