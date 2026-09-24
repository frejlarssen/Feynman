from __future__ import annotations

import unittest

from scripts.summarize_cloud_strong_scaling import summarize


def _row(run_id: str, slots: int, elapsed: int, *, num_batches: int = 64) -> dict[str, str]:
    return {
        "run_id": run_id,
        "label_kind": "pool_slots",
        "target_label_value": str(slots),
        "state": "success",
        "elapsed_seconds": str(elapsed),
        "num_batches": str(num_batches),
    }


class StrongScalingSummaryTests(unittest.TestCase):
    def test_computes_speedup_efficiency_and_exclusions(self) -> None:
        included = [
            _row("one-a", 1, 407),
            _row("one-b", 1, 403),
            _row("one-c", 1, 402),
            _row("four-a", 4, 120),
            _row("four-b", 4, 121),
        ]
        all_rows = included + [_row("four-outlier", 4, 7973)]

        rows = summarize(included_rows=included, all_rows=all_rows, fixed_batches=64)

        self.assertEqual(rows[0]["mean_elapsed_seconds"], "404.000000")
        self.assertEqual(rows[1]["included_elapsed_seconds"], "120;121")
        self.assertEqual(rows[1]["speedup_vs_baseline"], "3.352697")
        self.assertEqual(rows[1]["strong_scaling_efficiency_percent"], "83.817427")
        self.assertEqual(rows[1]["num_excluded_runs"], 1)
        self.assertEqual(rows[1]["excluded_elapsed_seconds"], "7973")
        self.assertEqual(rows[1]["fixed_batches"], 64)

    def test_rejects_non_pool_slot_input(self) -> None:
        row = _row("run", 1, 10)
        row["label_kind"] = "target_num_batches"
        with self.assertRaisesRegex(ValueError, "must use pool_slots"):
            summarize(included_rows=[row], all_rows=None, fixed_batches=None)


if __name__ == "__main__":
    unittest.main()
