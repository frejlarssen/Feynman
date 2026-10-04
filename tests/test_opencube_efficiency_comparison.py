import csv
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.plot_opencube_efficiency_comparison import load_efficiency, render_comparison


class OpenCubeEfficiencyComparisonTests(unittest.TestCase):
    def _write_summary(self, path: Path, timings: dict[int, list[float]]) -> None:
        rows = []
        for threads, samples in timings.items():
            for timing in samples:
                rows.append({
                    "case_name": "thirds",
                    "varied_param": "omp_threads",
                    "varied_value": str(threads),
                    "total_full_s": str(timing),
                    "returncode": "0",
                    "ranks": "1",
                    "feynman_env": f'{{"OMP_NUM_THREADS":"{threads}"}}',
                })
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0])
            writer.writeheader()
            writer.writerows(rows)

    def test_efficiency_uses_each_systems_own_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.csv"
            self._write_summary(summary, {4: [20, 20], 8: [12, 8]})
            threads, means, stds, efficiencies = load_efficiency(
                summary,
                y_column="total_full_s",
            )
            self.assertEqual(threads, [4, 8])
            self.assertEqual(means, [20, 10])
            self.assertEqual(stds, [0, 2**0.5 * 2])
            self.assertEqual(efficiencies, [100, 100])

    def test_render_writes_pdf_and_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name, scale in (("summary_merged_cn07.csv", 1), ("summary_merged_cn09.csv", 2)):
                self._write_summary(directory / name, {4: [20 * scale], 8: [10 * scale]})
            output = directory / "comparison.pdf"
            speedup_output, plotted_data = render_comparison(
                directory=directory,
                output_path=output,
                y_column="total_full_s",
            )
            self.assertGreater(output.stat().st_size, 1000)
            self.assertGreater(speedup_output.stat().st_size, 1000)
            with plotted_data.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 4)
            self.assertEqual({row["system"] for row in rows}, {"cn07 (AmpereOne)", "cn09 (Rhea)"})
            self.assertEqual({row["speedup"] for row in rows}, {"1.0", "2.0"})
            self.assertEqual({row["relative_parallel_efficiency_percent"] for row in rows}, {"100.0"})


if __name__ == "__main__":
    unittest.main()
