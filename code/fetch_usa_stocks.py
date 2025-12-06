"""
Script to fetch historical stock data for top 500 US stocks (S&P 500)
Data period: Last 1 month
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import time

def get_sp500_tickers():
    """
    Get S&P 500 ticker symbols from Wikipedia
    """
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    tables = pd.read_html(url)
    sp500_table = tables[0]
    tickers = sp500_table['Symbol'].tolist()
    # Clean tickers (replace . with -)
    tickers = [ticker.replace('.', '-') for ticker in tickers]
    return tickers[:500]  # Get first 500

def fetch_stock_data(tickers, period='1mo'):
    """
    Fetch historical stock data for given tickers
    
    Parameters:
    - tickers: list of stock ticker symbols
    - period: time period ('1mo' = 1 month)
    
    Returns:
    - DataFrame with stock data
    """
    all_data = []
    failed_tickers = []
    
    print(f"Starting to fetch data for {len(tickers)} stocks...")
    
    for i, ticker in enumerate(tickers):
        try:
            print(f"Fetching {i+1}/{len(tickers)}: {ticker}")
            stock = yf.Ticker(ticker)
            hist = stock.history(period=period)
            
            if not hist.empty:
                hist['Ticker'] = ticker
                hist['Date'] = hist.index
                all_data.append(hist)
            else:
                failed_tickers.append(ticker)
                
            # Add delay to avoid rate limiting
            if (i + 1) % 10 == 0:
                time.sleep(1)
                
        except Exception as e:
            print(f"Error fetching {ticker}: {str(e)}")
            failed_tickers.append(ticker)
            continue
    
    if all_data:
        combined_df = pd.concat(all_data, ignore_index=True)
        print(f"\nSuccessfully fetched data for {len(tickers) - len(failed_tickers)} stocks")
        if failed_tickers:
            print(f"Failed tickers: {failed_tickers}")
        return combined_df
    else:
        print("No data was fetched")
        return pd.DataFrame()

def save_data(df, filename='usa_stocks_1month.csv'):
    """
    Save data to CSV file
    """
    if not df.empty:
        df.to_csv(filename, index=False)
        print(f"\nData saved to {filename}")
        print(f"Total records: {len(df)}")
        print(f"Date range: {df['Date'].min()} to {df['Date'].max()}")
        print(f"\nColumns: {list(df.columns)}")
        print(f"\nSample data:")
        print(df.head(10))
    else:
        print("No data to save")

if __name__ == "__main__":
    # Get S&P 500 tickers
    print("Fetching S&P 500 ticker list...")
    tickers = get_sp500_tickers()
    print(f"Found {len(tickers)} tickers")
    
    # Fetch historical data (1 month)
    stock_data = fetch_stock_data(tickers, period='1mo')
    
    # Save to CSV
    save_data(stock_data)
    
    print("\n=== Summary ===")
    if not stock_data.empty:
        print(f"Unique stocks: {stock_data['Ticker'].nunique()}")
        print(f"Total data points: {len(stock_data)}")
        print(f"Columns: {list(stock_data.columns)}")
