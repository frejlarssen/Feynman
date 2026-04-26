from __future__ import annotations

import shlex
import sys
from pathlib import Path

from sweeplib.provenance import get_git_info
from sweeplib.sweep import run_sweep

from .cli import build_config
from .project import build_metadata, make_run_one, resolve_paths
from .schema import SUMMARY_FIELDS


def main(entry_script: Path | None = None) -> int:
    config = build_config()
    repo_root = Path(__file__).resolve().parents[2]
    paths = resolve_paths(config, repo_root)
    git_info = get_git_info(paths.repo_root)
    run_one = make_run_one(config=config, paths=paths, git_info=git_info)
    runner_script_path = entry_script or Path(__file__).resolve()
    invocation = shlex.join(sys.argv)

    return run_sweep(
        output_root=paths.output_root,
        experiment_name=config.experiment_name,
        summary_fields=SUMMARY_FIELDS,
        values=config.values,
        repeat=config.repeat,
        continue_on_error=config.continue_on_error,
        run_one=run_one,
        build_metadata=lambda sweep_dir, created_at: build_metadata(
            config=config,
            paths=paths,
            git_info=git_info,
            sweep_dir=sweep_dir,
            created_at=created_at,
            runner_script_path=runner_script_path,
            invocation=invocation,
        ),
    )
