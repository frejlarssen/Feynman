from __future__ import annotations

import unittest
from pathlib import Path

from scripts.plot_timebitstrings_hist import TimingSeries
from scripts.summarize_timebitstrings import linear_percentile, summarize_series


class TimeBitstringsSummaryTests(unittest.TestCase):
    def test_linear_percentile_and_summary(self) -> None:
        series = TimingSeries(
            label="example",
            paths=(Path("run/hexstrings/batch_0.timeBitstrings.csv"),),
            times=[1.0, 2.0, 3.0, 4.0, 5.0],
            statuses=["supported"] * 5,
        )

        row = summarize_series(series, status_filter="all")

        self.assertEqual(linear_percentile(series.times, 95.0), 4.8)
        self.assertEqual(row["median_seconds"], "3")
        self.assertEqual(row["percentile_95_seconds"], "4.8")
        self.assertEqual(row["num_supported"], 5)
        self.assertEqual(row["num_timings"], 5)

    def test_rejects_empty_series(self) -> None:
        series = TimingSeries(label="empty", paths=(), times=[], statuses=[])
        with self.assertRaisesRegex(ValueError, "empty timing series"):
            summarize_series(series, status_filter="all")


if __name__ == "__main__":
    unittest.main()
