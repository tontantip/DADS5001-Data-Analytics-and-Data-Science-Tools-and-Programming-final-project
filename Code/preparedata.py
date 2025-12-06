# setup_database.py
import duckdb

# 1. ห่อหุ้มตรรกะทั้งหมดไว้ในฟังก์ชัน
def setup_duckdb_database():
    DB_FILE = "my_stock_data.db"
    
    # 1. สร้างการเชื่อมต่อแบบ Persistent (ระบุชื่อไฟล์ .db)
    con = duckdb.connect(DB_FILE)

    print("Start downloading and saving data...")

    # URL List
    files = {
        "stock_ticker": "1Bd-WwzSp3wTHq30DUtnZQkzBSMyeFZp0",
        "macro_indicators": "1zWEOdbO-dPf6C4iQHgYPXffBrbu_XjiT",
        "stock_price": "1Xg2UkYQVhBBOnZGxWM0bVUoFNy2gQp4K",
        "stock_financials": "1L3QlfcA3_y4XtR0RBXHsbdlfWO-WmRQe",
        "stock_news": "1s2qCI530GqZ1XC7fyWKZQSloX2HPgmj9"
    }

    # Loop เพื่อดึงข้อมูลและสร้าง Table ใน Database
    for table_name, file_id in files.items():
        url = f"https://drive.google.com/uc?export=download&id={file_id}"

        # คำสั่ง SQL: สร้าง Table ชื่อตาม key เก็บข้อมูลจาก Parquet
        query = f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_parquet('{url}')"

        print(f"Processing {table_name}...")
        con.execute(query)

    # ปิดการเชื่อมต่อเพื่อบันทึกข้อมูลลงไฟล์ให้สมบูรณ์
    con.close()
    print(f"Done! Database created as '{DB_FILE}'")
