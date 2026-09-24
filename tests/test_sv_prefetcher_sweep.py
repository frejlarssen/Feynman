from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from sv_prefetcher_sweep.project import (
    _find_timing_file,
    build_command,
)
from sv_prefetcher_sweep.schema import ProjectPaths


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
    def test_cloud_task_runs_directly_without_batch_size_flag(self):
        paths = _paths("cloud_task.x")
        command = build_command(
            _Config(), paths, paths.circuit, _params(), Path("/tmp/output.hsv")
        )
        self.assertEqual(command[0], str(paths.binary))
        self.assertNotIn("mpirun", command)
        self.assertNotIn("-s", command)

    def test_mpi_binary_keeps_launcher_and_batch_size(self):
        paths = _paths("sv_prefetcher_subset_mpi.x")
        command = build_command(
            _Config(), paths, paths.circuit, _params(ranks=2), Path("/tmp/output.hsv")
        )
        self.assertEqual(command[:3], ["mpirun", "-n", "2"])
        self.assertEqual(command[command.index("-s") + 1], "1024")

    def test_direct_binary_rejects_multiple_ranks(self):
        paths = _paths("cloud_task.x")
        with self.assertRaisesRegex(ValueError, "requires ranks=1"):
            build_command(
                _Config(), paths, paths.circuit, _params(ranks=2), Path("/tmp/output.hsv")
            )

    def test_output_derived_timing_file_is_found(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            output_file = run_dir / "output.hsv"
            expected = run_dir / "output.timeBitstrings.csv"
            expected.write_text("bitstring_hex,elapsed_seconds,status\n", encoding="utf-8")
            self.assertEqual(_find_timing_file(run_dir, output_file), expected)


if __name__ == "__main__":
    unittest.main()
