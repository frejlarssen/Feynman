import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout
import io

from scripts.airflow_pool_autoscaler import (
    AutoscalerConfig,
    Progress,
    decide_scale,
    load_autoscaler_config,
    run_controller,
    summarize_progress,
)
from scripts.plot_airflow_pool_autoscaler import plot_events


def config(**overrides):
    values = dict(
        enabled=True,
        pool_name="simulate_pool",
        initial_pool_slots=2,
        max_pool_slots=16,
        target_completion_seconds=3600,
        check_interval_seconds=300,
        warmup_seconds=1200,
        cooldown_seconds=300,
        scale_factor=2,
    )
    values.update(overrides)
    return AutoscalerConfig(**values)


class AirflowPoolAutoscalerTests(unittest.TestCase):
    def test_config_reader_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"autoscaler": {
                "enabled": True,
                "pool_name": "simulate_pool",
                "initial_pool_slots": 2,
                "max_pool_slots": 16,
                "target_completion_seconds": 3600,
                "check_interval_seconds": 300,
                "warmup_seconds": 1200,
                "cooldown_seconds": 300,
                "scale_factor": 2,
            }}))
            parsed = load_autoscaler_config(path)
            self.assertEqual(parsed.max_pool_slots, 16)
            self.assertTrue(parsed.restore_pool_on_exit)

            payload = json.loads(path.read_text())
            payload["autoscaler"]["max_pool_slots"] = 1
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "max_pool_slots"):
                load_autoscaler_config(path)

    def test_progress_counts_only_mapped_task(self):
        rows = [
            {"task_id": "simulate_batch", "state": "success"},
            {"task_id": "simulate_batch", "state": "running"},
            {"task_id": "simulate_batch", "state": "queued"},
            {"task_id": "simulate_batch", "state": None, "map_index": -1},
            {"task_id": "split_hexstrings", "state": "success"},
        ]
        progress = summarize_progress(rows, "simulate_batch")
        self.assertEqual(progress, Progress(3, 1, 1, 1, 1))

    def test_scales_when_projected_to_miss_target(self):
        decision = decide_scale(
            config=config(),
            progress=Progress(100, 10, 10, 2, 88),
            current_pool_slots=2,
            elapsed_seconds=1200,
            window_elapsed_seconds=1200,
            window_completed_batches=10,
            cooldown_remaining_seconds=0,
        )
        self.assertTrue(decision.should_scale)
        self.assertEqual(decision.next_pool_slots, 4)
        self.assertGreater(decision.projected_remaining_seconds, decision.target_remaining_seconds)

    def test_holds_during_warmup_and_at_capacity(self):
        progress = Progress(100, 0, 0, 2, 98)
        warmup = decide_scale(
            config=config(), progress=progress, current_pool_slots=2,
            elapsed_seconds=600, window_elapsed_seconds=600,
            window_completed_batches=0, cooldown_remaining_seconds=0,
        )
        self.assertEqual(warmup.reason, "warmup")
        capped = decide_scale(
            config=config(), progress=progress, current_pool_slots=16,
            elapsed_seconds=1800, window_elapsed_seconds=600,
            window_completed_batches=0, cooldown_remaining_seconds=0,
        )
        self.assertEqual(capped.reason, "at_max_pool_slots")

    def test_holds_when_target_is_achievable(self):
        decision = decide_scale(
            config=config(),
            progress=Progress(100, 50, 50, 2, 48),
            current_pool_slots=2,
            elapsed_seconds=1200,
            window_elapsed_seconds=1200,
            window_completed_batches=50,
            cooldown_remaining_seconds=0,
        )
        self.assertFalse(decision.should_scale)
        self.assertEqual(decision.reason, "projected_to_meet_target")

    @mock.patch("scripts.airflow_pool_autoscaler._dag_state", return_value="success")
    @mock.patch("scripts.airflow_pool_autoscaler._task_states", return_value=[])
    @mock.patch("scripts.airflow_pool_autoscaler._set_pool")
    def test_controller_writes_auditable_artifacts(self, set_pool, _states, _dag):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = root / "events.jsonl"
            summary = root / "summary.json"
            with redirect_stdout(io.StringIO()):
                rc = run_controller(
                    config=config(check_interval_seconds=0.01),
                    dag_id="feynman",
                    run_id="test-run",
                    events_path=events,
                    summary_path=summary,
                    stop_file=None,
                )
            self.assertEqual(rc, 0)
            set_pool.assert_called_once_with(config(check_interval_seconds=0.01), 2)
            self.assertEqual(json.loads(summary.read_text())["final_reason"], "dag_terminal")
            self.assertEqual(len(events.read_text().splitlines()), 1)

    @mock.patch("scripts.airflow_pool_autoscaler._dag_state", return_value="running")
    @mock.patch(
        "scripts.airflow_pool_autoscaler._task_states",
        side_effect=[
            [
                {"task_id": "simulate_batch", "state": "running", "map_index": 0},
                {"task_id": "simulate_batch", "state": "queued", "map_index": 1},
            ],
            [
                {"task_id": "simulate_batch", "state": "success", "map_index": 0},
                {"task_id": "simulate_batch", "state": "success", "map_index": 1},
            ],
        ],
    )
    @mock.patch("scripts.airflow_pool_autoscaler._set_pool")
    def test_controller_scales_and_restores_pool(self, set_pool, _states, _dag):
        autoscale_config = config(
            warmup_seconds=0,
            cooldown_seconds=0,
            check_interval_seconds=0.01,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with redirect_stdout(io.StringIO()):
                run_controller(
                    config=autoscale_config,
                    dag_id="feynman",
                    run_id="test-run",
                    events_path=root / "events.jsonl",
                    summary_path=root / "summary.json",
                    stop_file=None,
                )
            self.assertEqual(
                set_pool.call_args_list,
                [
                    mock.call(autoscale_config, 2),
                    mock.call(autoscale_config, 4),
                    mock.call(autoscale_config, 2),
                ],
            )
            summary = json.loads((root / "summary.json").read_text())
            self.assertEqual(summary["scale_event_count"], 1)
            self.assertEqual(summary["final_pool_slots"], 4)
            self.assertEqual(summary["restored_pool_slots"], 2)

    def test_timeline_plot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = root / "events.jsonl"
            events.write_text(
                "\n".join(json.dumps(row) for row in [
                    {"elapsed_seconds": 0, "pool_slots": 1, "total_batches": 10,
                     "succeeded_batches": 0, "decision": "hold"},
                    {"elapsed_seconds": 300, "pool_slots": 1, "total_batches": 10,
                     "succeeded_batches": 1, "decision": "scale"},
                    {"elapsed_seconds": 600, "pool_slots": 2, "total_batches": 10,
                     "succeeded_batches": 4, "decision": "hold"},
                ]) + "\n"
            )
            output = plot_events(events, root / "timeline.pdf")
            self.assertTrue(output.read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
