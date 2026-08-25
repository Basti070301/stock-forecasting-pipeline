from __future__ import annotations

import unittest

import pandas as pd

from src.feature_engineering import calculate_features


class FeatureEngineeringTests(unittest.TestCase):
    def test_features_and_targets_are_calculated_per_ticker(self) -> None:
        dates = pd.bdate_range("2026-01-01", periods=35)
        frames = []
        for ticker, offset in (("AAA", 0), ("BBB", 100)):
            frames.append(
                pd.DataFrame(
                    {
                        "ticker": ticker,
                        "trade_date": dates,
                        "close_price": [offset + 100 + index for index in range(35)],
                        "volume": [1_000 + index for index in range(35)],
                    }
                )
            )
        prices = pd.concat(frames, ignore_index=True)

        features = calculate_features(prices)

        for ticker in ("AAA", "BBB"):
            ticker_features = features.loc[features["ticker"] == ticker].reset_index(
                drop=True
            )
            self.assertTrue(pd.isna(ticker_features.loc[0, "daily_return"]))
            self.assertTrue(pd.isna(ticker_features.loc[28, "moving_average_30"]))
            self.assertFalse(pd.isna(ticker_features.loc[29, "moving_average_30"]))
            self.assertTrue(bool(ticker_features.loc[0, "target_next_day_up"]))
            self.assertTrue(pd.isna(ticker_features.loc[34, "target_next_day_up"]))


if __name__ == "__main__":
    unittest.main()
