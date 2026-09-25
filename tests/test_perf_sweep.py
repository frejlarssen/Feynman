from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from perf_sweep.project import (
    _find_timing_file,
    build_command,
    parse_metrics,
)
from perf_sweep.schema import ProjectPaths


class _Config:
    mpirun = "mpirun"


def _paths(binary_name: str) -> ProjectPaths:
    root = Path("/repo")
    return ProjectPaths(
        repo_root=root,
        binary=root / "build" / binary_name,
        circuit=root / "circuit.qasm",
        input_statevector=root / "input.hsv",
        output_bitstrings=root / "outputs.hs",
        output_root=root / "results",
    )


def _params(**overrides):
    params = {
        "ranks": 1,
        "schedule": "prefetch",
        "batch_size": 1024,
        "fraction": 1.0,
        "threshold": 0.0,
        "p": None,
        "r": None,
        "verbosity": 1,
        "dense": False,
    }
    params.update(overrides)
    return params


class PerfSweepCommandTests(unittest.TestCase):
    def test_phase_timings_are_summed_across_simulate_calls(self):
        stdout = """\
Total clocktime sampling: 0.100000000 seconds
Total clocktime seconds_parallel_for: 1.250000000 seconds
Total clocktime sum of parallel_for iterations: 2.500000000 seconds
Total clocktime sampling: 0.200000000 seconds
Total clocktime seconds_parallel_for: 1.750000000 seconds
Total clocktime sum of parallel_for iterations: 3.500000000 seconds
"""
        metrics = parse_metrics(stdout)
        self.assertAlmostEqual(metrics["total_sampling_s"], 0.3)
        self.assertAlmostEqual(metrics["total_parallel_for_s"], 3.0)
        self.assertAlmostEqual(metrics["total_parallel_for_iterations_s"], 6.0)

    def test_feynman_runs_directly_without_batch_size_flag(self):
        paths = _paths("feynman.x")
        command = build_command(
            _Config(), paths, paths.circuit, _params(), Path("/tmp/output.hsv")
        )
        self.assertEqual(command[0], str(paths.binary))
        self.assertNotIn("mpirun", command)
        self.assertNotIn("-s", command)

    def test_mpi_binary_keeps_launcher_and_batch_size(self):
        paths = _paths("feynman_mpi.x")
        command = build_command(
            _Config(), paths, paths.circuit, _params(ranks=2), Path("/tmp/output.hsv")
        )
        self.assertEqual(command[:3], ["mpirun", "-n", "2"])
        self.assertEqual(command[command.index("--batch-size") + 1], "1024")
        self.assertEqual(command[command.index("--schedule") + 1], "prefetch")

    def test_direct_binary_rejects_multiple_ranks(self):
        paths = _paths("feynman.x")
        with self.assertRaisesRegex(ValueError, "requires ranks=1"):
            build_command(
                _Config(), paths, paths.circuit, _params(ranks=2), Path("/tmp/output.hsv")
            )

    def test_static_schedule_is_explicit(self):
        paths = _paths("feynman_mpi.x")
        command = build_command(
            _Config(), paths, paths.circuit,
            _params(ranks=3, schedule="static-cyclic", batch_size=7),
            Path("/tmp/output.hsv"),
        )
        self.assertEqual(command[command.index("--schedule") + 1], "static-cyclic")
        self.assertEqual(command[command.index("--batch-size") + 1], "7")

    def test_output_derived_timing_file_is_found(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            output_file = run_dir / "output.hsv"
            expected = run_dir / "output.timeBitstrings.csv"
            expected.write_text("bitstring_hex,elapsed_seconds,status\n", encoding="utf-8")
            self.assertEqual(_find_timing_file(run_dir, output_file), expected)


if __name__ == "__main__":
    unittest.main()
