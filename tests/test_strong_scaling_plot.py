import csv
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sweeplib.plotting import strong_scaling_series, render_perf_sweep_plot


def row(p, t, case='default', **extra):
    return dict(varied_param='ranks', varied_value=str(p), total_full_s=str(t),
                case_name=case, returncode='0', **extra)


class StrongScalingTests(unittest.TestCase):
    def test_relative_baseline_repeats_cases_and_failures(self):
        rows = [row(4, 12), row(4, 8), row(8, 5), row(4, 20, 'arm'), row(8, 20, 'arm')]
        rows.append(dict(row(2, 100), returncode='1'))
        series = strong_scaling_series(rows, 'total_full_s')
        self.assertEqual(series['default'][0], [4, 8])
        self.assertEqual(series['default'][1], [10, 5])
        self.assertEqual(series['default'][3], [100, 100])
        self.assertEqual(series['arm'][3], [100, 50])

    def test_changed_settings_rejected(self):
        with self.assertRaisesRegex(ValueError, 'fixed workload'):
            strong_scaling_series([row(1, 10, batch_size='1'), row(2, 5, batch_size='2')], 'total_full_s')

    def test_invalid_timings_excluded(self):
        with self.assertRaisesRegex(RuntimeError, 'positive timings'):
            strong_scaling_series([row(1, 0), row(2, 'nan')], 'total_full_s')

    def test_dispatch_and_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary.csv'
            rows = [row(4, 10), row(8, 5)]
            def write():
                with summary.open('w') as handle:
                    writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
            write()
            kwargs = dict(summary_path=summary, y_column='total_full_s', include_failures=False,
                          mode='meanstd', x_label='ranks', title='', output_path=Path(tmp) / 'plot.pdf')
            render_perf_sweep_plot(**kwargs)
            self.assertGreater(kwargs['output_path'].stat().st_size, 1000)
            for item in rows:
                item['varied_param'] = 'batch_size'
            write()
            with patch('sweeplib.plotting.render_sweep_plot') as generic:
                render_perf_sweep_plot(**kwargs)
                generic.assert_called_once()


if __name__ == '__main__':
    unittest.main()
