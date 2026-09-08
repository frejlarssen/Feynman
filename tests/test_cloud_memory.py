import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.cloud_memory import PLOT_METRICS, SUMMARY_FIELDS, collect_profiles, summarize_profiles
from scripts.plot_cloud_benchmark import _metric_value, _should_plot_efficiency, _to_groups

ROOT = Path(__file__).resolve().parents[1]


def worker(rss=64, faults=2, some=10, full=5):
    return {
        "schema_version": 1,
        "process_status": "available",
        "peak_rss_mib": rss,
        "major_faults": faults,
        "memory_psi_scope": "cgroup",
        "memory_psi_status": "available",
        "profile_seconds": 10,
        "memory_psi_some_seconds": some / 10,
        "memory_psi_full_seconds": full / 10,
        "memory_psi_some_percent": some,
        "memory_psi_full_percent": full,
    }


class CloudMemoryTests(unittest.TestCase):
    def test_aggregates_and_missing_coverage(self):
        rows = [worker(), worker(rss=128, faults=6, some=30, full=15)]
        summary = summarize_profiles(rows, 2)
        self.assertEqual(summary["simulate_worker_peak_rss_mib_mean"], 96)
        self.assertEqual(summary["simulate_worker_peak_rss_mib_max"], 128)
        self.assertEqual(summary["simulate_worker_major_faults_sum"], 8)
        self.assertEqual(summary["simulate_worker_memory_psi_some_percent_mean"], 20)
        self.assertNotIn("simulate_worker_peak_rss_mib_sum", summary)
        self.assertTrue(all(summarize_profiles(rows[:1], 2)[key] is None for key in PLOT_METRICS))
        self.assertTrue(all(summarize_profiles([], 0)[key] is None for key in PLOT_METRICS))
        rows[1]["memory_psi_status"] = "cgroup_v2_psi_unavailable"
        rows[1]["memory_psi_some_percent"] = None
        partial = summarize_profiles(rows, 2)
        self.assertEqual(partial["simulate_memory_psi_count"], 1)
        self.assertIsNone(partial["simulate_worker_memory_psi_some_percent_mean"])
        self.assertEqual(partial["simulate_worker_peak_rss_mib_max"], 128)

    def test_cpp_capture_and_namespace_resolution(self):
        with tempfile.TemporaryDirectory(prefix="feynman-memory-test-") as directory:
            directory = Path(directory)
            binary = directory / "memory_test"
            subprocess.run(["c++", "-std=c++17", "-I", str(ROOT),
                            str(ROOT / "tests/memory_profile_test.cpp"), "-o", str(binary)], check=True)
            subprocess.run([str(binary), str(directory)], check=True, capture_output=True)
            profile = json.loads((directory / "available.json").read_text())
            self.assertGreater(profile["peak_rss_mib"], 0)
            self.assertGreaterEqual(profile["major_faults"], 0)
            self.assertEqual(profile["memory_psi_some_start_us"], 100000)
            self.assertEqual(profile["memory_psi_some_end_us"], 105000)
            self.assertAlmostEqual(profile["memory_psi_some_seconds"], 0.005)
            self.assertAlmostEqual(profile["memory_psi_full_seconds"], 0.002)
            self.assertAlmostEqual(profile["memory_psi_some_percent"],
                                   0.5 / profile["profile_seconds"], places=7)
            for filename, status in [("reset", "psi_counter_reset"),
                                     ("end_missing", "psi_end_read_failed"),
                                     ("unavailable", "cgroup_v2_psi_unavailable")]:
                profile = json.loads((directory / f"{filename}.json").read_text())
                self.assertEqual(profile["memory_psi_status"], status)
                self.assertIsNone(profile["memory_psi_some_percent"])
                self.assertGreater(profile["peak_rss_mib"], 0)

    def test_artifacts_csv_and_all_plots(self):
        with tempfile.TemporaryDirectory(prefix="feynman-memory-plots-") as directory:
            directory = Path(directory)
            source = directory / "worker_outputs"
            run_dir = directory / "run"
            source.mkdir()
            run_dir.mkdir()
            (run_dir / "dag_run_conf.json").write_text(json.dumps({
                "benchmark_case": {"run_output_dir": str(source)}}))
            for i, record in enumerate([worker(), worker(rss=128, faults=6, some=30, full=15)]):
                (source / f"test_batch_{i}.memory.json").write_text(json.dumps(record))
            summary = collect_profiles(run_dir, 2)
            payload = json.loads((run_dir / "memory_summary.json").read_text())
            self.assertEqual(len(payload["workers"]), 2)
            self.assertEqual(payload["summary"], summary)
            csv_path = directory / "summary.csv"
            with csv_path.open("w") as f:
                writer = csv.DictWriter(f, fieldnames=["state", "label_kind", "target_label_value", *SUMMARY_FIELDS])
                writer.writeheader()
                for slots in [1, 2]:
                    writer.writerow(dict(state="success", label_kind="pool_slots", target_label_value=slots, **summary))
            result = subprocess.run([sys.executable, str(ROOT / "scripts/plot_cloud_benchmark.py"),
                                     "--summary-csv", str(csv_path), "--memory-all"],
                                    check=True, capture_output=True, text=True)
            self.assertNotIn("WARNING", result.stderr)
            for metric in PLOT_METRICS:
                stem = f"cloud_benchmark_{metric}_vs_pool_slots"
                self.assertTrue((directory / f"{stem}.pdf").read_bytes().startswith(b"%PDF"))
                with (directory / f"{stem}.csv").open() as f:
                    aggregates = list(csv.DictReader(f))
                self.assertEqual(float(aggregates[0]["mean"]), summary[metric])
                self.assertEqual(aggregates[0]["strong_scaling_efficiency_percent"], "")

    def test_zero_metrics_are_plottable_missing_are_not(self):
        key = "simulate_worker_major_faults_sum"
        row = {"state": "success", "target_label_value": "4", key: "0"}
        self.assertEqual(_to_groups([row], metric=key), {4: [0.0]})
        self.assertFalse(_should_plot_efficiency(metric=key, no_efficiency=False))
        row[key] = ""
        self.assertIsNone(_metric_value(row, metric=key))


if __name__ == "__main__":
    unittest.main()
