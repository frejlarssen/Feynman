#!/usr/bin/env python3
"""Thin CLI wrapper for QAOA pruning sweep runner."""

from pathlib import Path

from qaoa_pruning_sweep.main import main


if __name__ == "__main__":
    raise SystemExit(main(entry_script=Path(__file__).resolve()))
