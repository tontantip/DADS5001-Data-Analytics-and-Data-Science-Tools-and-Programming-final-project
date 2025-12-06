import pandas as pd
import duckdb

## import ai result from database
con = duckdb.connect("ai_result.db")
ai_result = con.execute("select * from ai_result").df()
con.close

## import index stock
con = duckdb.connect("index_stock.db")
index_stock = con.execute("select * from index_stock_data").df()
con.close

ai_result["final_score"] = (((ai_result["ai_fin_score"]*0.5)+(ai_result["ai_price_score"]*0.35)+(ai_result["ai_envi_score"]*0.15))/2)

comb = duckdb.sql("""select * 
                  from index_stock as id left join ai_result as ar
                  on  id.symbol = ar.symbol
                  """).df()
#comb.to_csv("final_score.csv",index=False)
print(comb.info())