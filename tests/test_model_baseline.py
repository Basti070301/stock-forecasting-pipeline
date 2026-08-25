from __future__ import annotations

import unittest

import pandas as pd

from src.model_baseline import chronological_split


class ModelBaselineTests(unittest.TestCase):
    def test_chronological_split_keeps_future_out_of_training(self) -> None:
        dates = pd.bdate_range("2026-01-01", periods=10)
        frame = pd.DataFrame(
            {
                "trade_date": list(dates) * 2,
                "ticker": ["AAA"] * 10 + ["BBB"] * 10,
            }
        )

        train, test, cutoff = chronological_split(frame, train_fraction=0.8)

        self.assertEqual(train["trade_date"].max(), cutoff)
        self.assertLess(train["trade_date"].max(), test["trade_date"].min())
        self.assertEqual(len(train), 16)
        self.assertEqual(len(test), 4)


if __name__ == "__main__":
    unittest.main()
