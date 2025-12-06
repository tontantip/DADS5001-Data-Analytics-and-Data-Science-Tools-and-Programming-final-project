# fin_index.py (ไฟล์ Module)
import pandas as pd
import numpy as np

# ถ้ามีหลายหุ้น ใช้ groupby ได้เลย โค้ดนี้รองรับอัตโนมัติ
def calculate_ratios(df):
    data = df.copy()

    # ------------------------------------------------------------------
    # 1. Profitability Ratios
    # ------------------------------------------------------------------
    data['Gross_Margin_%']      = (data['gross_profit'] / data['revenue']) * 100
    data['Operating_Margin_%']  = (data['operating_income'] / data['revenue']) * 100
    data['Net_Margin_%']        = (data['net_income'] / data['revenue']) * 100
    data['ROA_%']               = (data['net_income'] / data['assets']) * 100
    data['ROE_%']               = (data['net_income'] / data['equity']) * 100

    # คำนวณ NOPAT และ Invested Capital เพื่อ ROIC (ประมาณ)
    data['NOPAT'] = data['operating_income'] * (1 - 0.25)   # สมมติ tax rate 25%
    data['Invested_Capital'] = data['assets'] - data['current_liabilities']
    data['ROIC_%'] = (data['NOPAT'] / data['Invested_Capital']).replace([np.inf, -np.inf], np.nan) * 100 # แก้ปัญหาหารด้วย 0

    # ------------------------------------------------------------------
    # 2. Efficiency Ratios (ต้องมีข้อมูลเพิ่มในอนาคต แต่คำนวณเท่าที่มี)
    # ------------------------------------------------------------------
    data['Asset_Turnover'] = data['revenue'] / data['assets']

    # ------------------------------------------------------------------
    # 3. Liquidity Ratios
    # ------------------------------------------------------------------
    data['Current_Ratio']      = (data['current_assets'] / data['current_liabilities']).replace([np.inf, -np.inf], np.nan)
    data['Quick_Ratio']        = ((data['current_assets'] - (data['cost_of_revenue'] * 0.1)) / data['current_liabilities']).replace([np.inf, -np.inf], np.nan)
    data['Cash_Ratio']         = ((data['current_assets'] - data['current_liabilities'] + data['liabilities']) / data['current_liabilities']).replace([np.inf, -np.inf], np.nan)

    # ------------------------------------------------------------------
    # 4. Leverage / Solvency Ratios
    # ------------------------------------------------------------------
    data['Total_Debt'] = data['liabilities'] - data['current_liabilities']   # ประมาณ long-term debt
    data['Debt_to_Equity'] = (data['Total_Debt'] / data['equity']).replace([np.inf, -np.inf], np.nan)

    # สมมติ EBITDA ≈ Operating Income + 100M (เพื่อตัวอย่าง)
    data['EBITDA_est'] = data['operating_income'] + 100_000_000
    data['Debt_to_EBITDA'] = (data['Total_Debt'] / data['EBITDA_est']).replace([np.inf, -np.inf], np.nan)
    data['Net_Debt'] = data['Total_Debt'] - (data['current_assets'] * 0.2)   # ประมาณ cash
    data['Net_Debt_to_EBITDA'] = (data['Net_Debt'] / data['EBITDA_est']).replace([np.inf, -np.inf], np.nan)

    # ------------------------------------------------------------------
    # 5. Cash Flow Ratios
    # ------------------------------------------------------------------
    data['Free_Cash_Flow'] = data['operating_cashflow'] + data['cf_investing']
    # ประมาณ shares
    shares_outstanding = (data['equity'] / data['eps_basic']).replace([0, np.inf, -np.inf], np.nan)
    data['FCF_per_Share'] = (data['Free_Cash_Flow'] / shares_outstanding).replace([np.inf, -np.inf], np.nan) 
    data['FCF_Margin_%'] = (data['Free_Cash_Flow'] / data['revenue']).replace([np.inf, -np.inf], np.nan) * 100
    data['FCF_Conversion_%'] = (data['Free_Cash_Flow'] / data['net_income']).replace([np.inf, -np.inf], np.nan) * 100

    # ------------------------------------------------------------------
    # 6. Growth Rates (QoQ และ YoY)
    # ------------------------------------------------------------------
    # เนื่องจากโค้ดนี้รันใน groupby (ตาม ticker) จึงต้องใช้ shift/pct_change ธรรมดา
    # แต่ต้องเรียงตามเวลาแล้ว!
    data['Revenue_Growth_QoQ_%'] = data['revenue'].pct_change() * 100
    data['Net_Income_Growth_QoQ_%'] = data['net_income'].pct_change() * 100
    data['EPS_Growth_QoQ_%'] = data['eps_basic'].pct_change() * 100

    # YoY Growth (เทียบไตรมาสเดียวกันปีก่อน) - ต้องใช้ periods=4 ใน groupby/apply
    # เนื่องจากเราอยู่ในฟังก์ชันที่รันใน groupby อยู่แล้ว ใช้แค่ periods=4 ก็ได้
    data['Revenue_Growth_YoY_%'] = data['revenue'].pct_change(periods=4) * 100
    data['EPS_Growth_YoY_%'] = data['eps_basic'].pct_change(periods=4) * 100
    
    # เพิ่มคอลัมน์ช่วงเวลาเพื่อแสดงผลสวย
    data['Period'] = data['fiscal_year'].astype(str) + ' ' + data['fiscal_period']

    return data


# =================================================================
# ส่วนเสริม: คำนวณ "ความต่อเนื่อง" (Consecutive Streaks)
# =================================================================
def calculate_streaks(group):
    # ไม่ต้อง sort อีก เพราะมีการ sort ในไฟล์หลักแล้ว
    g = group.copy() 

    # 1. รายได้เติบโตต่อเนื่องกี่ไตรมาส (ใช้ QoQ growth)
    revenue_growth = (g['Revenue_Growth_QoQ_%'] > 0)
    g['rev_growth_streak'] = revenue_growth.cumsum()
    g['rev_growth_streak'] = g['rev_growth_streak'].where(revenue_growth, 0)
    current_rev_streak_q = g['rev_growth_streak'].iloc[-1] if revenue_growth.iloc[-1] else 0
    current_rev_streak_y = current_rev_streak_q // 4

    # 2. EPS เติบโตต่อเนื่องกี่ไตรมาส (ใช้ QoQ growth)
    eps_growth = (g['EPS_Growth_QoQ_%'] > 0)
    g['eps_growth_streak'] = eps_growth.cumsum()
    g['eps_growth_streak'] = g['eps_growth_streak'].where(eps_growth, 0)
    current_eps_streak_q = g['eps_growth_streak'].iloc[-1] if eps_growth.iloc[-1] else 0
    current_eps_streak_y = current_eps_streak_q // 4

    # 3. กำไรสุทธิเป็นบวกต่อเนื่อง
    positive_ni = g['net_income'] > 0
    g['positive_ni_streak'] = positive_ni.cumsum()
    g['positive_ni_streak'] = g['positive_ni_streak'].where(positive_ni, 0)
    ni_streak_q = g['positive_ni_streak'].iloc[-1] if positive_ni.iloc[-1] else 0
    ni_streak_y = ni_streak_q // 4

    # 4. Free Cash Flow เป็นบวกต่อเนื่อง
    positive_fcf = g['Free_Cash_Flow'] > 0
    g['positive_fcf_streak'] = positive_fcf.cumsum()
    g['positive_fcf_streak'] = g['positive_fcf_streak'].where(positive_fcf, 0)
    fcf_streak_q = g['positive_fcf_streak'].iloc[-1] if positive_fcf.iloc[-1] else 0
    fcf_streak_y = fcf_streak_q // 4

    # 5. ROE > 15% ต่อเนื่อง
    high_roe = g['ROE_%'] > 15
    g['high_roe_streak'] = high_roe.cumsum()
    g['high_roe_streak'] = g['high_roe_streak'].where(high_roe, 0)
    roe_streak_q = g['high_roe_streak'].iloc[-1] if high_roe.iloc[-1] else 0
    roe_streak_y = roe_streak_q // 4

    # สรุปผล
    summary = {
        'Ticker': g['ticker'].iloc[0],
        'Latest_Period': g['Period'].iloc[-1],
        'Consecutive_Revenue_Growth_Years': int(current_rev_streak_y),
        'Consecutive_EPS_Growth_Years': int(current_eps_streak_y),
        'Consecutive_Profitable_Years': int(ni_streak_y),
        'Consecutive_Positive_FCF_Years': int(fcf_streak_y),
        'Consecutive_ROE_Above_15pct_Years': int(roe_streak_y),
        'Total_Quarters': len(g)
    }
    return pd.Series(summary)