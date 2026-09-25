from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sweeplib.provenance import (
    _compile_command_metadata,
    _hardware_metadata,
    _system_command_metadata,
    _toolchain_metadata,
)


class SystemMetadataTests(unittest.TestCase):
    def test_compile_command_reports_effective_optimization(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / 'build'
            source = root / 'apps' / 'feynman.cpp'
            build.mkdir()
            source.parent.mkdir()
            source.write_text('// test\n', encoding='utf-8')
            cache = build / 'CMakeCache.txt'
            cache.write_text('', encoding='utf-8')
            database = [{
                'directory': str(build),
                'arguments': ['/usr/bin/g++', '-O0', '-O3', '-DNDEBUG', '-c', str(source)],
                'file': str(source),
            }]
            (build / 'compile_commands.json').write_text(
                json.dumps(database), encoding='utf-8'
            )

            result = _compile_command_metadata(build / 'feynman.x', cache, root)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['optimization_flags'], ['-O0', '-O3'])
            self.assertEqual(result['effective_optimization'], '-O3')
            self.assertIn('-DNDEBUG', result['arguments'])

    @patch('sweeplib.provenance._system_command_metadata')
    def test_toolchain_metadata_reports_compiler_and_openmp_spec_date(self, probe):
        probe.return_value = dict(stdout='version output\n', stderr='', returncode=0, status='ok')
        cache = {
            'CMAKE_CXX_COMPILER': '/usr/bin/g++',
            'CMAKE_CXX_COMPILER_ID': 'GNU',
            'CMAKE_CXX_COMPILER_VERSION': '14.2.0',
            'OpenMP_CXX_SPEC_DATE': '202011',
            'OpenMP_CXX_FLAGS': '-fopenmp',
            'OpenMP_CXX_LIB_NAMES': 'gomp;pthread',
            'OpenMP_gomp_LIBRARY': '/usr/lib/libgomp.so',
        }
        result = _toolchain_metadata(cache, Path.cwd())
        self.assertEqual(result['compiler']['path'], '/usr/bin/g++')
        self.assertEqual(result['compiler']['cmake_reported_version'], '14.2.0')
        self.assertEqual(result['openmp']['spec_date'], '202011')
        self.assertNotIn('version', result['openmp'])
        self.assertEqual(result['openmp']['libraries']['OpenMP_gomp_LIBRARY'], '/usr/lib/libgomp.so')
        probe.assert_any_call(['/usr/bin/g++', '--version'], Path.cwd())

    @patch('sweeplib.provenance.subprocess.run')
    def test_capture_success_and_nonzero(self, run):
        for code, status in [(0, 'ok'), (1, 'failed')]:
            run.return_value = subprocess.CompletedProcess(['df', '-h'], code, 'disks\n', 'diagnostic\n')
            result = _system_command_metadata(['df', '-h'], Path.cwd())
            self.assertEqual(result['status'], status)
            self.assertEqual(result['stdout'], 'disks\n')
            self.assertEqual(result['stderr'], 'diagnostic\n')
            self.assertEqual(result['returncode'], code)
        self.assertEqual(run.call_args.kwargs['timeout'], 10)

    @patch('sweeplib.provenance.subprocess.run')
    def test_missing_and_timeout(self, run):
        run.side_effect = FileNotFoundError('missing')
        self.assertEqual(_system_command_metadata(['missing'], Path.cwd())['status'], 'unavailable')
        run.side_effect = subprocess.TimeoutExpired(['df'], 10, output=b'partial\n', stderr=b'busy\n')
        result = _system_command_metadata(['df'], Path.cwd())
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(result['stdout'], 'partial\n')
        self.assertEqual(result['stderr'], 'busy\n')

    @patch('sweeplib.provenance._system_command_metadata')
    def test_platform_probes_and_compatible_core_count(self, probe):
        probe.return_value = dict(stdout='8\n', stderr='', returncode=0, status='ok')
        for system, required, absent in [
            ('Linux', {'lscpu', 'free', 'lsblk', 'nproc', 'os_release'}, {'sw_vers', 'vm_stat'}),
            ('Darwin', {'sw_vers', 'sysctl_hardware', 'sysctl_cpu', 'vm_stat'}, {'lscpu', 'free', 'nproc'}),
        ]:
            with patch('sweeplib.provenance.platform.system', return_value=system):
                result = _hardware_metadata(Path.cwd())
            names = set(result['system_commands'])
            self.assertTrue((required | {'df', 'uname', 'uptime'}) <= names)
            self.assertFalse(names & absent)
            self.assertEqual(result['logical_cores_nproc'], 8 if system == 'Linux' else None)


if __name__ == '__main__':
    unittest.main()
