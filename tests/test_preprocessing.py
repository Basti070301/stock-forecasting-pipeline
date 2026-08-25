from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.preprocessing import clean_price_frame


class PreprocessingTests(unittest.TestCase):
    def test_exchange_local_date_is_not_shifted_to_previous_day(self) -> None:
        raw = pd.DataFrame(
            {
                "Date": ["2026-06-19 00:00:00+02:00"],
                "Open": [100.0],
                "High": [105.0],
                "Low": [99.0],
                "Close": [104.0],
                "Volume": [1_000],
            }
        )

        cleaned = clean_price_frame(raw, "SAP.DE")

        self.assertEqual(cleaned.loc[0, "trade_date"], date(2026, 6, 19))
        self.assertEqual(cleaned.loc[0, "ticker"], "SAP.DE")
        self.assertEqual(cleaned.loc[0, "dividends"], 0.0)

    def test_invalid_ohlc_row_is_removed(self) -> None:
        raw = pd.DataFrame(
            {
                "Date": ["2026-06-18", "2026-06-19"],
                "Open": [100.0, 100.0],
                "High": [105.0, 102.0],
                "Low": [99.0, 99.0],
                "Close": [104.0, 103.0],
                "Volume": [1_000, 1_000],
            }
        )

        cleaned = clean_price_frame(raw, "AAPL")

        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned.loc[0, "trade_date"], date(2026, 6, 18))


if __name__ == "__main__":
    unittest.main()
