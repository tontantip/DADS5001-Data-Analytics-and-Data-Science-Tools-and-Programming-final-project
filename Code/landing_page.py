import streamlit as st

# ตั้งค่าหน้าเว็บ
st.set_page_config(
    page_title="QuantSense - AI Investment Copilot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS เพื่อตกแต่งหน้าตาให้สวยงามขึ้น
st.markdown("""
    <style>
    .main-header {
        font-size: 3.5rem;
        font-weight: 700;
        color: #1E3A8A; /* Dark Blue */
        text-align: center;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.8rem;
        font-weight: 600;
        color: #2563EB; /* Blue */
        margin-bottom: 1rem;
    }
    .text-content {
        font-size: 1.15rem;
        line-height: 1.6;
        text-align: justify;
        color: #333333;
    }
    .highlight {
        color: #2563EB;
        font-weight: bold;
    }
    .section-divider {
        margin-top: 3rem;
        margin-bottom: 3rem;
        border-top: 1px solid #ddd;
    }
    </style>
""", unsafe_allow_html=True)

# --- Hero Section ---
st.markdown('<div class="main-header">QuantSense</div>', unsafe_allow_html=True)
st.markdown('<p style="text-align: center; font-size: 1.5rem; color: #666;">AI Investment Copilot: Your Path to Smart Investing</p>', unsafe_allow_html=True)
st.write("---")

# --- Motivation Section ---
st.markdown('<div class="sub-header">Motivation (แรงบันดาลใจและวิสัยทัศน์)</div>', unsafe_allow_html=True)

# Row 1: Headline & Problem (Text Left, Image Right)
col1, col2 = st.columns([1.2, 1], gap="large")

with col1:
    st.markdown("### 💡 Headline: เปลี่ยน 'ข้อมูลมหาศาล' ให้เป็น 'คำตอบที่เรียบง่าย' ในการลงทุน")
    st.markdown("""
    <div class="text-content">
    ในโลกการลงทุนยุคปัจจุบัน เราไม่ได้ขาดแคลนข้อมูล แต่เรากำลังจมอยู่กับกองข้อมูลมหาศาล (Information Overload) 
    ความท้าทายที่แท้จริงคือการ <b>"สังเคราะห์" (Synthesize)</b> ข้อมูลเหล่านั้นเพื่อค้นหาเพชรเม็ดงามในตลาดหุ้น
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.image(
        "https://images.unsplash.com/photo-1642655358689-56b944d6f5f6?q=80&w=1170&auto=format&fit=crop&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
        caption="Information Overload in the Financial World",
        use_column_width=True
    )

st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

# Row 2: Solution & Vision (Image Left, Text Right)
col3, col4 = st.columns([1, 1.2], gap="large")

with col3:
    st.image(
        "https://images.unsplash.com/photo-1745674684468-b9fc392fda3f?q=80&w=1170&auto=format&fit=crop&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
        caption="AI Technology & Future Finance",
        use_column_width=True
    )

with col4:
    st.markdown("### 🚀 ปรัชญาของเรา")
    st.markdown("""
    <div class="text-content">
    แรงบันดาลใจของโปรเจกต์นี้ คือความเชื่อที่ว่า <b>"การลงทุนที่มีคุณภาพ ไม่ควรเป็นเรื่องซับซ้อน"</b> 
    โดยการนำเทคโนโลยี <b>AI (Large Language Model)</b> ที่มีความเข้าใจบริบททางเศรษฐกิจและการเงิน 
    มาผสานกับความแม่นยำของ <b>Machine Learning (Traditional)</b>
    <br><br>
    เราสร้าง Data Product นี้ขึ้นมาเพื่อเป็น <b>"AI Investment Copilot"</b> ที่จะเปลี่ยนกระบวนการวิเคราะห์หุ้นที่ต้องใช้เวลาหลายชั่วโมง 
    ให้ง่ายผ่านระบบ <b>Rating 5 ดาว</b> ที่กลั่นกรองมาจากศักยภาพทางธุรกิจที่แท้จริง เพื่อให้นักลงทุนสามารถทำกำไรได้อย่างยั่งยืน 
    มั่นใจ และมีเหตุผลรองรับในทุกการตัดสินใจ
    </div>
    """, unsafe_allow_html=True)

st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

# --- The Issue Section ---
st.markdown('<div class="sub-header">The Issue (ปัญหาและที่มาของโครงการ)</div>', unsafe_allow_html=True)

col5, col6 = st.columns([1.2, 1], gap="large")

with col5:
    st.markdown("### ❓ Headline: ทำไมการเลือกหุ้น 'ผู้ชนะ' ถึงเป็นเรื่องยากสำหรับนักลงทุนส่วนใหญ่?")
    st.markdown("""
    <div class="text-content">
    ในปัจจุบันข้อมูลการลงทุนจะหาได้ทั่วไป แต่กระบวนการเปลี่ยน <b>ข้อมูลดิบ (Raw Data)</b> ให้เป็น 
    <b>กลยุทธ์ที่ทำกำไรได้ (Actionable Insight)</b> กลับเต็มไปด้วยอุปสรรค ทำให้นักลงทุนจำนวนมากจึงจบลงด้วยการ "เดา" 
    หรือ "ซื้อตามกระแส" ซึ่งขาดความยั่งยืน
    <br><br>
    โปรเจกต์นี้จึงถูกพัฒนาขึ้นผ่าน <b>Web Application (Streamlit)</b> ที่ทำหน้าที่รวบรวม จัดการ และวิเคราะห์ข้อมูลทั้งหมดแทนคุณ 
    โดยใช้:
    <ul>
        <li><b>GenAI:</b> สวมบทบาทผู้เชี่ยวชาญวิเคราะห์ปัจจัยพื้นฐานให้คะแนน 0-5 ดาว</li>
        <li><b>Machine Learning:</b> คำนวณความน่าจะเป็นของราคา</li>
    </ul>
    เพื่อให้คุณเห็นภาพรวมของ <b>"โอกาส"</b> และ <b>"ความเสี่ยง"</b> ได้ชัดเจนที่สุด
    </div>
    """, unsafe_allow_html=True)

with col6:
    st.image(
        "https://github.com/tontantip/Archive/blob/main/Image_dads5001_project/Gemini_Generated_Image_q62ddnq62ddnq62d.png?raw=true",
        caption="The Complexity of Finding Winners",
        use_column_width=True
    )

# --- Footer ---
st.write("---")
st.markdown(
    """
    <div style='text-align: center; color: grey; padding: 20px;'>
        <p>© 2025 QuantSense Project. Powered by Streamlit & GenAI.</p>
    </div>
    """, 
    unsafe_allow_html=True
)