import duckdb
import pandas as pd
con = duckdb.connect("ai_result.db")
#data = con.execute("select * from ai_result")
data = con.execute("select * from ai_result").df()
con.close
print(data)

