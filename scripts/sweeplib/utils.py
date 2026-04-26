from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(ts: dt.datetime) -> str:
    return ts.isoformat(timespec="seconds")


def sanitize(text: str) -> str:
    out = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_") or "value"


def resolve_path(path_str: str, root: Path, must_exist: bool = False) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if must_exist and not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    return path


def run_capture(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def ensure_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    assert isinstance(value, str)
    return value
