"""Numerical/CLI integration checks. Set FEYNMAN_TEST_BINARY and optionally
FEYNMAN_TEST_MPI_BINARY to built executables; uses the site mpirun in PATH.
"""
import csv
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('FEYNMAN_TEST_BINARY'), 'Set FEYNMAN_TEST_BINARY')
class SimulatorBackends(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.circuit = self.root / 'ghz.qasm'
        self.circuit.write_text('OPENQASM 3.0;\ninclude "stdgates.inc";\nqreg q[3];\nh q[0];\ncx q[0],q[1];\ncx q[1],q[2];\n')
        self.input = self.root / 'input.hsv'
        self.input.write_text(f'0x00:{1 / math.sqrt(2)}+0i\n0x07:0+{1 / math.sqrt(2)}i\n')
        self.outputs = self.root / 'outputs.hs'
        self.outputs.write_text('8\n1\n' + ''.join(f'0x{i:02X}\n' for i in range(8)))
        self.binary = os.environ['FEYNMAN_TEST_BINARY']
        self.mpi = os.environ.get('FEYNMAN_TEST_MPI_BINARY')

    def invoke(self, args, ranks=None, success=True):
        cmd = [self.binary] if ranks is None else [os.environ.get('MPIRUN', 'mpirun'), '-n', str(ranks), self.mpi]
        proc = subprocess.run(cmd + args, capture_output=True, text=True, timeout=30,
                              env={**os.environ, 'OMP_NUM_THREADS': '2', 'OMP_DYNAMIC': 'FALSE'})
        if success:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        else:
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def file_run(self, ranks=None, schedule=None, count=8):
        self.outputs.write_text(f'{count}\n1\n' + ''.join(f'0x{i:02X}\n' for i in range(count)))
        output = self.root / 'result.hsv'
        args = ['-c', str(self.circuit), '-i', str(self.input), '-b', str(self.outputs),
                '-o', str(output), '-p', '1', '-r', '1', '-t', '0', '-D']
        if schedule:
            args += ['--schedule', schedule, '--batch-size', '1']
        proc = self.invoke(args, ranks)
        values = {}
        for line in output.read_text().splitlines():
            key, value = line.split(':')
            self.assertNotIn(int(key, 16), values)
            values[int(key, 16)] = complex(value.replace('+-', '-').replace('i', 'j'))
        expected = {0: .5, 7: .5, 2: .5j, 5: -.5j}
        self.assertEqual(len(values), count)
        for index in range(count):
            self.assertAlmostEqual(abs(values[index] - expected.get(index, 0)), 0, places=12)
        with output.with_suffix('.timeBitstrings.csv').open() as f:
            self.assertEqual(len(list(csv.DictReader(f))), count)
        self.assertIn(f'Number of simulate calls: {count * 2}', proc.stdout)
        total = float(re.search(r'Total clocktime for all simulate calls: ([\d.e+-]+)', proc.stdout)[1])
        avg = float(re.search(r'Average clocktime per simulate call: ([\d.e+-]+)', proc.stdout)[1])
        self.assertGreater(total, 0)
        self.assertAlmostEqual(total / (count * 2), avg, places=8)

    def test_standalone_sparse_input(self):
        self.file_run()

    def test_split_simulate_concat(self):
        self.file_run()
        expected = (self.root / 'result.hsv').read_text()
        binaries = Path(self.binary).parent
        split = binaries / 'feynman_split_batches.x'
        concat = binaries / 'feynman_concat_batches.x'
        batches = self.root / 'batches'
        subprocess.run([str(split), '-h', str(self.outputs), '-o', str(batches),
                        '-n', '3', '-v', '0'], check=True, timeout=10)
        for request in sorted(batches.glob('*.hs')):
            self.invoke(['-c', str(self.circuit), '-i', str(self.input),
                         '-b', str(request), '-o', str(request.with_suffix('.hsv')),
                         '-p', '1', '-r', '1', '-t', '0', '-D'])
        combined = self.root / 'combined.hsv'
        subprocess.run([str(concat), '-i', str(batches), '-o', str(combined),
                        '-p', 'batch_', '-n', '3', '-v', '0'], check=True, timeout=10)
        self.assertEqual(combined.read_text(), expected)

    def test_mpi_schedules(self):
        if not self.mpi:
            self.skipTest('Set FEYNMAN_TEST_MPI_BINARY')
        for schedule in ['static-block', 'static-cyclic', 'dynamic', 'prefetch']:
            for ranks, count in [(1, 8), (3, 8), (4, 2)]:
                with self.subTest(schedule=schedule, ranks=ranks, count=count):
                    self.file_run(ranks, schedule, count)

    def test_amplitude_and_build_only(self):
        for ranks in [None] + ([3] if self.mpi else []):
            proc = self.invoke(['-c', str(self.circuit), '--input-bits', '000',
                                '--output-bits', '111', '-v', '0', '-t', '0'], ranks)
            value = proc.stdout.split('Total amplitude: ')[1].splitlines()[0]
            self.assertAlmostEqual(complex(value.replace('i', 'j')).real, 1 / math.sqrt(2), places=12)
            proc = self.invoke(['-c', str(self.circuit), '--build-only'], ranks)
            self.assertIn('Circuit has 3 gates', proc.stdout)
            self.assertNotIn('Number of simulate calls:', proc.stdout)

    def test_failure_exit_and_no_mpi_hang(self):
        for ranks in [None] + ([3] if self.mpi else []):
            self.invoke(['-c', str(self.circuit), '-i', str(self.root / 'missing.hsv'),
                         '-b', str(self.outputs), '-o', str(self.root / 'out.hsv')], ranks, success=False)
        if self.mpi:
            self.invoke(['-c', str(self.circuit), '--build-only', '--batch-size', '0'], 3, success=False)
            self.invoke(['-c', str(self.circuit), '--build-only', '--schedule', 'invalid'], 3, success=False)


if __name__ == '__main__':
    unittest.main()
