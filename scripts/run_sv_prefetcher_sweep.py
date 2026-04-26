#!/usr/bin/env python3
"""Thin CLI wrapper for sv_prefetcher sweep runner."""

from pathlib import Path

from sv_prefetcher_sweep.main import main


if __name__ == "__main__":
    raise SystemExit(main(entry_script=Path(__file__).resolve()))
