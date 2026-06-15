from pathlib import Path
from contextlib import redirect_stdout
import yfinance as yf
import pandas as pd

ticker_symbol = "AAPL"
ticker = yf.Ticker(ticker_symbol)

# Projekt-Hauptordner ermitteln
project_root = Path(__file__).resolve().parents[1]

# Speicherpfad im Projekt
save_dir = project_root / "Data" / "processed"
save_dir.mkdir(parents=True, exist_ok=True)

save_path = save_dir / "apple_info.txt"

with open(save_path, "w", encoding="utf-8") as file:
    with redirect_stdout(file):

        history = ticker.history(period="1y")

        print("=" * 80)
        print("1. HISTORISCHE KURSDATEN - SPALTEN")
        print("=" * 80)
        print(history.columns.tolist())
        print(history.head())

        info = ticker.info

        print("\n" + "=" * 80)
        print("2. ALLE INFO-ATTRIBUTE")
        print("=" * 80)

        for key, value in info.items():
            print(f"{key}: {value}")

        print("\n" + "=" * 80)
        print("3. ALLE INFO-KEYS ALS LISTE")
        print("=" * 80)

        for key in sorted(info.keys()):
            print(key)

        print("\n" + "=" * 80)
        print("4. DIVIDENDEN")
        print("=" * 80)
        print(ticker.dividends.tail())

        print("\n" + "=" * 80)
        print("5. SPLITS")
        print("=" * 80)
        print(ticker.splits.tail())

        print("\n" + "=" * 80)
        print("6. ACTIONS")
        print("=" * 80)
        print(ticker.actions.tail())

        print("\n" + "=" * 80)
        print("7. FINANCIALS")
        print("=" * 80)
        print(ticker.financials)

        print("\n" + "=" * 80)
        print("8. BALANCE SHEET")
        print("=" * 80)
        print(ticker.balance_sheet)

        print("\n" + "=" * 80)
        print("9. CASHFLOW")
        print("=" * 80)
        print(ticker.cashflow)

        print("\n" + "=" * 80)
        print("10. NEWS")
        print("=" * 80)

        news = ticker.news
        for article in news[:5]:
            print(article)

        print("\n" + "=" * 80)
        print("11. OPTIONS")
        print("=" * 80)
        print(ticker.options)

print(f"Apple information saved to: {save_path}")