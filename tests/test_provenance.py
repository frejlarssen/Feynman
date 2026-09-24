from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sweeplib.provenance import _hardware_metadata, _system_command_metadata


class SystemMetadataTests(unittest.TestCase):
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
