(import os)
from pathlib import Path
import yfinance as yf


def download_and_save_csv(symbol: str,
						  period: str = "1y",
						  interval: str = "1d",
						  save_dir: str = "Data/processed",
						  filename: str | None = None) -> str:
	"""Download historical data for `symbol` via yfinance and save as CSV.

	Returns the path to the written CSV file.
	"""
	Path(save_dir).mkdir(parents=True, exist_ok=True)

	ticker = yf.Ticker(symbol)
	df = ticker.history(period=period, interval=interval)

	if df.empty:
		raise ValueError(f"Keine Daten für Symbol: {symbol} (period={period}, interval={interval})")

	if filename is None:
		filename = f"{symbol}_history.csv"

	save_path = Path(save_dir) / filename
	df.to_csv(save_path)
	return str(save_path)


if __name__ == "__main__":
	import argparse

	parser = argparse.ArgumentParser(description="Download historical stock data and save as CSV")
	parser.add_argument("symbol", help="Ticker symbol, e.g. AAPL")
	parser.add_argument("--period", default="1y", help="yfinance period (default: 1y)")
	parser.add_argument("--interval", default="1d", help="yfinance interval (default: 1d)")
	parser.add_argument("--out", default="Data/processed", help="Output directory (default: Data/processed)")
	parser.add_argument("--filename", default=None, help="Output filename (optional)")

	args = parser.parse_args()
	path = download_and_save_csv(args.symbol, period=args.period, interval=args.interval, save_dir=args.out, filename=args.filename)
	print(f"Saved historical data for {args.symbol} to {path}")

